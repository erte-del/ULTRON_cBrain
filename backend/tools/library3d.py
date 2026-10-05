"""The 3D library: ready-made models Ultron shows before it builds anything itself.

    library3d/
        office_chair.glb      a finished model: drop the file in and it's found
        office_chair.json     optional: {"title", "aliases", "tags", "category", "spec"}
        mug.json              a model with only a "spec": built with Ultron's own shapes when shown

Flow:
  search_3d_library        -> what the library has for a request (empty query = everything)
  show_from_3d_library     -> puts the model in the 3D panel, exactly like a preview
Only when nothing in the library is the thing asked for, or the user wants it changed,
does Ultron use preview_3d. A model with a "spec" can be changed in small steps; a
plain .glb can't, so a change to one means Ultron rebuilds it as its own new version.
"""

import asyncio
import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import trimesh
from claude_agent_sdk import tool

import config
from storage import model_store

from . import shapes
from .models3d import LIBRARY_SPEC_KEY, _show, _text, render_views

log = logging.getLogger("ultron.3d.library")

ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")
# Words that say "show me" but not what; ignored when matching.
FILLER = {"a", "an", "the", "of", "me", "my", "show", "make", "build", "create", "give", "get", "model",
          "models", "3d", "object", "please", "i", "want", "need", "to", "for", "some", "your", "from",
          "library", "can", "you", "see", "and"}


@dataclass
class Item:
    id: str
    title: str
    category: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    spec: dict[str, Any] | None = None
    has_glb: bool = False


def _words(text: str) -> list[str]:
    """Lowercase words, plurals folded ('chairs' -> 'chair'), filler dropped."""
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def _meaningful(text: str) -> list[str]:
    return [w for w in _words(text) if w not in FILLER]


def _strings(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def items() -> list[Item]:
    """Everything in the library folder. A broken file is skipped and logged, never fatal."""
    folder = config.LIBRARY_3D_DIR
    if not folder.is_dir():
        return []
    found: dict[str, Item] = {}
    for path in sorted(folder.iterdir()):
        if path.suffix not in (".glb", ".json") or not ITEM_ID.match(path.stem):
            continue
        item = found.setdefault(path.stem, Item(id=path.stem, title=path.stem.replace("_", " ").replace("-", " ").title()))
        if path.suffix == ".glb":
            item.has_glb = True
            continue
        try:
            meta = json.loads(path.read_text())
            item.title = str(meta.get("title") or item.title)[:80]
            item.category = str(meta.get("category") or "")
            item.aliases = _strings(meta.get("aliases"))
            item.tags = _strings(meta.get("tags"))
            item.spec = meta.get("spec")
        except (OSError, ValueError, AttributeError):
            log.warning("Skipping unreadable library file %s", path.name, exc_info=True)
            found.pop(path.stem)
    return [i for i in found.values() if i.has_glb or i.spec]


def search(query: str) -> list[tuple[Item, str]]:
    """Library items for a request, best first, each marked 'exact' or 'partial'.

    exact   = every meaningful word of the request is in the item's name, aliases or tags
    partial = only some are (e.g. asked for a 'sports car', the library has a 'chair' tagged 'seat')
    """
    wanted = _meaningful(query)
    if not wanted:
        return []
    ranked = []
    for item in items():
        names = {w for text in [item.title, item.id, *item.aliases] for w in _meaningful(text)}
        context = {w for text in [item.category, *item.tags] for w in _meaningful(text)}
        hits_name = sum(w in names for w in wanted)
        hits_any = sum(w in names or w in context for w in wanted)
        if not hits_any:
            continue
        phrase = " ".join(wanted) in {" ".join(_meaningful(t)) for t in [item.title, item.id, *item.aliases]}
        score = hits_name * 3 + (hits_any - hits_name) + (10 if phrase else 0)
        ranked.append((score, item, "exact" if hits_any == len(wanted) else "partial"))
    ranked.sort(key=lambda r: (-r[0], r[1].id))
    return [(item, quality) for _, item, quality in ranked]


def _describe(item: Item) -> str:
    extra = f" ({', '.join(item.aliases)})" if item.aliases else ""
    kind = "editable parts" if item.spec else "fixed model"
    return f"{item.id}: {item.title}{extra}" + (f" [{item.category}]" if item.category else "") + f", {kind}"


@tool(
    "search_3d_library",
    "Look in the 3D LIBRARY of ready-made models. Do this FIRST whenever the user asks for a 3D "
    "object, before preview_3d. Pass what they asked for in a few words ('chair', 'coffee mug'). "
    "An empty query lists everything in the library.",
    {"type": "object", "properties": {"query": {"type": "string"}}},
)
async def search_3d_library(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        everything = items()
        if not everything:
            return _text("The 3D library is empty. Build the object yourself with preview_3d.")
        return _text("The 3D library has:\n" + "\n".join(_describe(i) for i in everything))
    results = search(query)
    exact = [i for i, quality in results if quality == "exact"]
    if not exact:
        near = "".join(f"\nNot the same thing, don't use unless the user agrees: {_describe(i)}" for i, _ in results[:3])
        return _text(f"Nothing in the 3D library is {query!r}. Tell the user it isn't there and build it "
                     f"yourself with preview_3d.{near}")
    lines = "\n".join(_describe(i) for i in exact[:5])
    return _text(f"In the 3D library:\n{lines}\n"
                 "If one of these is really the object the user asked for, show it with show_from_3d_library. "
                 "If it's only similar (a different kind, brand or model), it isn't in the library: build it yourself.")


def _import_glb(item: Item) -> tuple[bytes, int, list[float]]:
    glb = (config.LIBRARY_3D_DIR / f"{item.id}.glb").read_bytes()
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    size, _ = shapes.summary(scene)
    return glb, len(scene.geometry), size


def _import_spec(item: Item) -> tuple[dict[str, Any], bytes, int, list[float]]:
    parts = shapes.validate(item.spec)
    scene = shapes.build_scene(parts, "preview")
    size, _ = shapes.summary(scene)
    return item.spec, shapes.to_glb(scene), len(parts), size


@tool(
    "show_from_3d_library",
    "Show a ready-made model from the 3D library in the big 3D panel. Use the id from "
    "search_3d_library. This is the answer to the request; don't also call preview_3d unless the "
    "user then asks for a change.",
    {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]},
)
async def show_from_3d_library(args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id", ""))
    item = next((i for i in items() if i.id == item_id), None)
    if item is None:
        return _text(f"No model called {item_id!r} in the 3D library. Search it first.", is_error=True)
    try:
        if item.has_glb:
            glb, parts, size = await asyncio.to_thread(_import_glb, item)
            spec = item.spec or {"parts": [], LIBRARY_SPEC_KEY: item.id}
            source = "library"
        else:
            spec, glb, parts, size = await asyncio.to_thread(_import_spec, item)
            source = ""
    except Exception as e:  # unreadable .glb, bad spec
        log.exception("Could not load library model %s", item.id)
        return _text(f"Could not open {item.id} from the library ({e}). Build it yourself with preview_3d.", is_error=True)

    rec = model_store.create(item.title)
    await asyncio.to_thread(model_store.add_version, rec, spec, glb, "from the 3D library", parts, size, source)
    await _show(rec)
    w, h, d = size
    lines = [f"{rec.id} '{item.title}' from the 3D library is showing in the 3D panel: {w} × {h} × {d} m."]
    content: list[dict[str, Any]] = []
    if item.has_glb and not item.spec:
        lines.append(
            "It's a finished model, so its parts can't be edited. If the user wants a change, rebuild it "
            f"as your own version: preview_3d with model_id {rec.id} and a full 'spec' (the views attached "
            "show what it looks like now), and say that you rebuilt it from simple shapes."
        )
        sheet = await render_views(glb)
        if sheet:
            content.append({"type": "image", "data": base64.b64encode(sheet).decode(), "mimeType": "image/jpeg"})
    else:
        lines.append(f"A change is a small edit: preview_3d with model_id {rec.id} and update_parts / add_parts / "
                     "remove_parts (get_3d_spec shows the part names).")
    lines.append("Tell the user briefly it came from the library, and ask if they want anything changed. "
                 "No need to check views: it's already finished. When they're happy, offer the file types "
                 f"({', '.join('.' + f for f in model_store.FORMATS)}); export_3d makes the file.")
    return {"content": [{"type": "text", "text": "\n".join(lines)}, *content]}
