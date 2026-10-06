"""3D objects: fast previews, changes through chat, final file only after approval. (Phase 4d)

Flow (JARVIS_BUILD_PROMPT.md, section 7b). Ready-made models come first: see library3d.py.
  preview_3d  -> low-detail preview in the big 3D panel (new version every change).
                 Claude also gets 4 rendered views and a list of floating parts, so it
                 can check its own work and fix mistakes before replying.
  revert_3d  -> back to an earlier version
  get_3d_spec -> read back the spec of a version (e.g. after a restart)
  export_3d   -> 'act' tool: goes through the confirmation gate, then Blender builds
                 the detailed final file (.blend, .fbx, .obj, .stl, .gltf, .glb)
"""

import asyncio
import base64
import io
import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool
from PIL import Image, ImageDraw

import config
import events
import hub
from storage import model_store

from . import shapes

log = logging.getLogger("ultron.3d")

EXPORT_SCRIPT = Path(__file__).with_name("blender_export_script.py")
RENDER_SCRIPT = Path(__file__).with_name("blender_render_script.py")
BLENDER_TIMEOUT_S = 180
# A fixed (.glb only) model from the 3D library has no parts, just this marker in its spec.
LIBRARY_SPEC_KEY = "library"
RENDER_TIMEOUT_S = 60
VIEWS = [("three_quarter", "3/4 front"), ("side", "side (front is right)"),
         ("front", "front"), ("top", "top (front is right)")]

SPEC_DESCRIPTION = (
    "The object as a list of parts. Units are meters, Y is up, the ground is y=0, sizes realistic. "
    "Vehicles, furniture and long objects: length along X with the FRONT toward +X, width along Z, "
    "centered on z=0. Each part: {name, shape, position [x,y,z] (the part's center), rotation [x,y,z] "
    "degrees, scale [x,y,z] (optional), color (name or #hex), material: matte|glossy|metal|glass, "
    "mirror: true (also adds a copy on the other side, z -> -z; write symmetric parts ONCE with mirror)} "
    "plus its shape's fields: "
    "box {size [w,h,d], round 0–0.5 (rounded corners, as a fraction of the smallest side)}; "
    "sphere {radius}; cylinder {radius} or {radius_top, radius_bottom}, {height}; cone {radius, height}; "
    "torus {radius, tube} (a ring lying flat); capsule {radius, height (total)}; "
    "lathe {points [[radius, y], ...]} spun around the vertical axis (vases, bottles, lamps); "
    "extrude {outline [[x, y], ...] in the X-Y plane, depth along Z} (flat shapes, signs, profiles); "
    "loft {sections [{x, y, width, height, roundness, bottom_roundness}, ...]}: a SMOOTH body through "
    "cross-sections placed along X (x increasing; y = the section's center height; width along Z; "
    "roundness 0 = square, 1 = oval; bottom_roundness defaults to roundness). Use loft for car bodies, "
    "cabins, boat hulls, fuselages, sofas: anything curved in more than one direction. "
    "Round shapes stand upright (axis along Y); rotate [90,0,0] to make a wheel. "
    "asset {model: a model id (e.g. one shown from 3DAssets.dev or the library), version (optional), "
    "colors {material name: color}}: places that whole model, its bottom center at 'position', "
    "turned with 'rotation' and sized with 'scale'. Use asset parts to COMBINE models into one scene "
    "(a house on a garden) and to recolor a finished model by material name (e.g. 'plaster' = walls). "
    "Parts must touch or overlap slightly: nothing should float."
)


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


async def _show(rec: model_store.ModelRecord) -> None:
    await hub.emit(events.canvas_card(rec.id, "model3d", rec.title, model_store.card_data(rec)))


def _load(model_id: Any) -> model_store.ModelRecord:
    return model_store.load(str(model_id))


# ---- Preview ------------------------------------------------------------------------

def _build_preview(spec: dict[str, Any]) -> tuple[bytes, int, list[float], int, list[tuple[str, float]]]:
    parts = shapes.validate(spec)
    scene = shapes.build_scene(parts, "preview")
    size, triangles = shapes.summary(scene)
    return shapes.to_glb(scene), len(parts), size, triangles, shapes.floating_parts(scene)


async def _blender(script: Path, *args: str, ok_marker: str, timeout: float) -> str:
    """Run one of Ultron's fixed Blender scripts in the background. Returns Blender's output."""
    blender = config.BLENDER_PATH
    if not Path(blender).exists():
        raise RuntimeError(f"Blender not found at {blender} (set BLENDER_PATH in .env)")
    proc = await asyncio.create_subprocess_exec(
        blender, "--background", "--factory-startup", "--python-exit-code", "1",
        "--python", str(script), "--", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError("Blender took too long") from None
    text = out.decode(errors="replace")
    if proc.returncode != 0 or ok_marker not in text:
        log.error("Blender (%s) failed:\n%s", script.name, text[-3000:])
        raise RuntimeError("Blender failed (details in the backend log)")
    return text


def _contact_sheet(folder: Path) -> bytes:
    """The four views in a 2×2 grid with labels, as a JPEG for Claude."""
    tiles = [(Image.open(folder / f"{name}.png").convert("RGB"), label) for name, label in VIEWS]
    w, h = tiles[0][0].size
    sheet = Image.new("RGB", (w * 2, h * 2), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(tiles):
        x, y = (i % 2) * w, (i // 2) * h
        sheet.paste(tile, (x, y))
        draw.rectangle([x, y, x + 8 + 7 * len(label), y + 18], fill="white")
        draw.text((x + 5, y + 4), label, fill="black")
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=82)
    return buf.getvalue()


async def render_views(glb: bytes) -> bytes | None:
    """Four quick views of a preview for Claude to look at, or None if Blender isn't available."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "preview.glb").write_bytes(glb)
            await _blender(RENDER_SCRIPT, str(folder / "preview.glb"), str(folder),
                           ok_marker="JARVIS_RENDER_OK", timeout=RENDER_TIMEOUT_S)
            return await asyncio.to_thread(_contact_sheet, folder)
    except Exception:
        log.warning("Could not render preview views", exc_info=True)
        return None


@tool(
    "preview_3d",
    "Make or update a fast, low-detail 3D PREVIEW and show it in the big 3D panel. Use this "
    "whenever the user asks for a 3D object, model, shape or scene. For a real, recognisable "
    "object (a specific car, plane, building, product), look at a reference photo first "
    "(image_search, ideally a side view) and match its silhouette and proportions. "
    "Each call makes a new version. For a SMALL change to an existing model, pass model_id "
    "with update_parts / add_parts / remove_parts instead of the whole spec (much faster); "
    "send a full spec only for a new object or a big rebuild. To put models that are already "
    "showing together (e.g. a house and a garden from 3DAssets.dev), make a NEW model whose spec "
    "has one 'asset' part per model, placed next to / on each other. "
    "This never makes the final file (that's export_3d, only after the user approves). "
    "You get back 4 rendered views and a list of any floating parts: check them and fix "
    "mistakes before replying. Keep previews fast: as few parts as show the shape, loft for "
    "smooth bodies, and mirror for symmetric parts.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short name, e.g. 'Wooden chair'."},
            "model_id": {"type": "string", "description": "To update an existing model (e.g. mdl_002)."},
            "note": {"type": "string", "description": "What changed, e.g. 'wider base'."},
            "spec": {
                "type": "object",
                "description": SPEC_DESCRIPTION,
                "properties": {"parts": {"type": "array", "items": {"type": "object"}}},
                "required": ["parts"],
            },
            "update_parts": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Small change: [{name, ...only the fields to change}] for parts of the "
                "current version, e.g. [{\"name\": \"body\", \"color\": \"red\"}]. null removes a field.",
            },
            "add_parts": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Small change: new parts to add (same format as spec parts).",
            },
            "remove_parts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Small change: names of parts to delete.",
            },
        },
    },
)
async def preview_3d(args: dict[str, Any]) -> dict[str, Any]:
    changes = {k: args.get(k) for k in ("update_parts", "add_parts", "remove_parts") if args.get(k)}
    try:
        rec = _load(args["model_id"]) if args.get("model_id") else None
        if args.get("spec") is not None:
            spec = args["spec"]
        elif changes and rec is not None:
            current = model_store.spec(rec)
            if not current.get("parts") and LIBRARY_SPEC_KEY in current:
                # A finished model: edit it as one 'asset' part called 'model' (recolor, add parts next to it).
                current = {"parts": [{"name": "model", "shape": "asset", "model": rec.id, "version": rec.current}]}
            spec = shapes.apply_changes(current, **changes)
        else:
            return _text("Preview not made: pass a full 'spec', or a model_id with "
                         "update_parts / add_parts / remove_parts.", is_error=True)
        glb, parts, size, triangles, floating = await asyncio.to_thread(_build_preview, spec)
    except (KeyError, shapes.SpecError) as e:
        return _text(f"Preview not made: {str(e).strip(chr(39))}", is_error=True)
    except Exception as e:  # geometry library errors
        log.exception("3D preview failed")
        return _text(f"Preview not made (geometry error: {e}). Simplify the part that caused it.", is_error=True)

    if rec is None:
        rec = model_store.create(str(args.get("title") or "3D object"))
    if args.get("title"):
        rec.title = str(args["title"])[:80]
    note = str(args.get("note") or ("first version" if not rec.versions else "changed"))
    v = await asyncio.to_thread(model_store.add_version, rec, spec, glb, note, parts, size)
    await _show(rec)  # the user sees it right away; the check below runs after
    log.info("3D preview %s v%s: %s parts, %s triangles, size %s, floating %s",
             rec.id, v.version, parts, triangles, size, floating)

    sheet = await render_views(glb)
    w, h, d = size
    lines = [
        f"{rec.id} v{v.version} is showing in the 3D preview panel: {parts} parts, "
        f"{w} × {h} × {d} m (along X × Y × Z).",
    ]
    if floating:
        lines.append("PROBLEM: these parts don't touch the rest of the object (floating): "
                     + "; ".join(f"{name} ({gap * 100:.0f} cm gap)" for name, gap in floating) + ".")
    if sheet:
        lines.append(
            "Attached: 4 views of the preview (3/4 front, side, front, top). CHECK THEM before replying: "
            "floating or misplaced parts, parts facing the wrong way, wrong proportions, anything that "
            "doesn't look like what the user asked for. If you looked at a reference photo, compare "
            "the side view with it: silhouette, roofline, where the wheels and lights sit."
        )
    lines.append(
        "If something is clearly wrong, fix it now with ONE more preview_3d call (same model_id; "
        "use update_parts etc. for small fixes), then reply. Mention anything still off. Otherwise tell the user briefly and ask what to change. "
        "When they say it's good, ask which file type they want "
        f"({', '.join('.' + f for f in model_store.FORMATS)}) and then call export_3d."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": "\n".join(lines)}]
    if sheet:
        content.append({"type": "image", "data": base64.b64encode(sheet).decode(), "mimeType": "image/jpeg"})
    return {"content": content}


@tool(
    "revert_3d",
    "Go back to an earlier version of a 3D model (default: the previous one). Nothing is deleted.",
    {
        "type": "object",
        "properties": {"model_id": {"type": "string"}, "version": {"type": "integer"}},
        "required": ["model_id"],
    },
)
async def revert_3d(args: dict[str, Any]) -> dict[str, Any]:
    try:
        rec = _load(args["model_id"])
        target = args.get("version") or max(rec.current - 1, 1)
        model_store.set_current(rec, int(target))
    except (KeyError, ValueError) as e:
        return _text(f"Not reverted: {e}", is_error=True)
    await _show(rec)
    return _text(f"{rec.id} is back to v{rec.current} in the preview. Its spec: "
                 + json.dumps(model_store.spec(rec)))


@tool(
    "get_3d_spec",
    "Read back the spec of a 3D model version (default: current), e.g. before changing it "
    "if you no longer have it.",
    {
        "type": "object",
        "properties": {"model_id": {"type": "string"}, "version": {"type": "integer"}},
        "required": ["model_id"],
    },
)
async def get_3d_spec(args: dict[str, Any]) -> dict[str, Any]:
    try:
        rec = _load(args["model_id"])
        v = rec.get(args.get("version"))
    except KeyError as e:
        return _text(str(e), is_error=True)
    return _text(f"{rec.id} '{rec.title}' v{v.version}: " + json.dumps(model_store.spec(rec, v.version)))


# ---- Final export -------------------------------------------------------------------

async def build_final(rec: model_store.ModelRecord, version: int, fmt: str) -> str:
    """Build the detailed model and export it. Returns the stored file name."""
    spec = model_store.spec(rec, version)
    folder = model_store.folder(rec.id)
    if not spec.get("parts") and LIBRARY_SPEC_KEY in spec:  # a finished library model: convert its file as it is
        glb = (folder / f"v{version}_preview.glb").read_bytes()
    else:
        parts = shapes.validate(spec)
        scene = await asyncio.to_thread(shapes.build_scene, parts, "final")
        glb = await asyncio.to_thread(shapes.to_glb, scene)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        src = tmp_dir / "model.glb"
        src.write_bytes(glb)
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        await _blender(EXPORT_SCRIPT, str(src), str(out_dir / f"model.{fmt}"), fmt,
                       ok_marker="JARVIS_EXPORT_OK", timeout=BLENDER_TIMEOUT_S)
        produced = sorted(out_dir.iterdir())
        if len(produced) == 1:  # a single file (.blend, .fbx, .stl, .glb)
            name = f"final_v{version}.{fmt}"
            shutil.move(produced[0], folder / name)
        else:  # several files (.obj + .mtl, .gltf + .bin): zip them
            name = f"final_v{version}.zip"
            with zipfile.ZipFile(folder / name, "w", zipfile.ZIP_DEFLATED) as z:
                for p in produced:
                    z.write(p, p.name)
    model_store.add_export(rec, version, fmt, name)
    return name


@tool(
    "export_3d",
    "Build the FINAL, detailed 3D file from an approved preview and give it to the user. "
    "Only call this after the user has said the preview is good AND told you the file type. "
    "The user confirms it once more before it runs. Formats: blend, fbx, obj, stl "
    "(millimeters, for 3D printing), gltf, glb.",
    {
        "type": "object",
        "properties": {
            "model_id": {"type": "string"},
            "format": {"type": "string", "enum": model_store.FORMATS},
            "version": {"type": "integer", "description": "Default: the version showing now."},
        },
        "required": ["model_id", "format"],
    },
)
async def export_3d(args: dict[str, Any]) -> dict[str, Any]:
    fmt = str(args.get("format", "")).lower().lstrip(".")
    if fmt not in model_store.FORMATS:
        return _text(f"Unknown format; use one of {model_store.FORMATS}", is_error=True)
    try:
        rec = _load(args["model_id"])
        version = rec.get(args.get("version")).version
    except KeyError as e:
        return _text(str(e), is_error=True)

    log.info("Exporting %s v%s as %s", rec.id, version, fmt)
    try:
        name = await build_final(rec, version, fmt)
    except (RuntimeError, shapes.SpecError) as e:
        return _text(f"Export failed: {e}", is_error=True)
    await _show(rec)
    download = model_store.download_name(rec, name)
    return _text(
        f"Done: {download} is ready. There's a download button in the 3D panel."
        + (" It's a .zip because this format has more than one file." if name.endswith(".zip") else "")
        + (" The STL is in millimeters." if fmt == "stl" else "")
    )
