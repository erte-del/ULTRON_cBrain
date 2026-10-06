"""3D scene spec -> geometry (trimesh).

Claude describes an object as JSON parts; this module checks the JSON and builds
the meshes. The preview and the final file both come from here, so the final is
exactly the shape you approved, just with more detail.

Conventions (also explained to Claude in the tool description):
  - units are meters; Y is up; the ground is y = 0
  - `position` is the center of the part; `rotation` is degrees around X, Y, Z
  - round shapes (cylinder, cone, capsule, lathe, torus) have their axis along Y
  - a loft runs along X (vehicles: front toward +X, width along Z)
  - `mirror` adds a copy reflected across the middle (default: left/right, the Z axis)
  - an `asset` part is another stored model (e.g. one pulled from 3DAssets.dev) placed in
    this one, with its bottom center at `position`; `colors` recolors its materials by name
"""

import io
import json
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh
from PIL import ImageColor
from shapely.geometry import Polygon
from trimesh import creation, transformations
from trimesh.visual.material import PBRMaterial

from storage import model_store

SHAPES = ["box", "sphere", "cylinder", "cone", "torus", "capsule", "lathe", "extrude", "loft", "asset"]

# name -> (metallic, roughness, alpha)
MATERIALS = {
    "matte": (0.0, 0.9, 1.0),
    "glossy": (0.0, 0.25, 1.0),
    "metal": (1.0, 0.3, 1.0),
    "glass": (0.0, 0.05, 0.35),
}

# Segments for round shapes. Preview = fast and chunky; final = smooth.
DETAIL = {"preview": 16, "final": 96}
# Lofts: extra sections added between each pair you give, and points around each section.
LOFT_DETAIL = {"preview": (2, 20), "final": (8, 72)}
MAX_LOFT_SECTIONS = 100

MAX_PARTS = 200
MIN_SIZE, MAX_SIZE = 0.0005, 1000.0  # meters


class SpecError(ValueError):
    """A problem in the spec; the message goes back to Claude."""


@dataclass
class Part:
    name: str
    shape: str
    params: dict[str, Any]
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    color: tuple[int, int, int] = (200, 200, 200)
    material: str = "matte"
    mirror: str | None = None  # "x", "y" or "z": also add a copy reflected across that axis
    extra: dict[str, Any] = field(default_factory=dict)


# ---- Validation ---------------------------------------------------------------------

def _size(part: dict, key: str, where: str, default: float | None = None) -> float:
    value = part.get(key, default)
    if value is None:
        raise SpecError(f"{where}: '{key}' is required")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise SpecError(f"{where}: '{key}' must be a number") from None
    if not MIN_SIZE <= value <= MAX_SIZE:
        raise SpecError(f"{where}: '{key}' must be between {MIN_SIZE} and {MAX_SIZE} meters")
    return value


def _vec3(part: dict, key: str, where: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
    value = part.get(key, default)
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise SpecError(f"{where}: '{key}' must be [x, y, z]")
    try:
        out = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        raise SpecError(f"{where}: '{key}' must contain numbers") from None
    if any(math.isnan(v) or abs(v) > 100_000 for v in out):
        raise SpecError(f"{where}: '{key}' is out of range")
    return out  # type: ignore[return-value]


def _points(part: dict, key: str, where: str, minimum: int) -> list[tuple[float, float]]:
    raw = part.get(key)
    if not isinstance(raw, list) or len(raw) < minimum or len(raw) > 500:
        raise SpecError(f"{where}: '{key}' needs {minimum}–500 [a, b] points")
    try:
        pts = [(float(a), float(b)) for a, b in raw]
    except (TypeError, ValueError):
        raise SpecError(f"{where}: '{key}' must be a list of [a, b] number pairs") from None
    if any(abs(v) > MAX_SIZE for p in pts for v in p):
        raise SpecError(f"{where}: '{key}' has a point that is too far out")
    return pts


def _loft_sections(raw: dict, where: str) -> list[list[float]]:
    """[[x, y, width, height, roundness_top, roundness_bottom], ...] sorted by x."""
    sections = raw.get("sections")
    if not isinstance(sections, list) or not 2 <= len(sections) <= MAX_LOFT_SECTIONS:
        raise SpecError(f"{where}: loft needs 'sections': 2–{MAX_LOFT_SECTIONS} objects "
                        "like {x, y, width, height, roundness}")
    out = []
    for k, sec in enumerate(sections, 1):
        w = f"{where} section {k}"
        if not isinstance(sec, dict):
            raise SpecError(f"{w}: must be an object like {{x, y, width, height, roundness}}")
        try:
            x, y = float(sec.get("x", 0)), float(sec.get("y", 0))
            width, height = float(sec["width"]), float(sec["height"])
            top = float(sec.get("roundness", 0.5))
            bottom = float(sec.get("bottom_roundness", top))
        except (KeyError, TypeError, ValueError):
            raise SpecError(f"{w}: needs numbers x, y, width, height (and optional roundness 0–1)") from None
        if not (0 <= width <= MAX_SIZE and 0 <= height <= MAX_SIZE):
            raise SpecError(f"{w}: width and height must be 0–{MAX_SIZE} meters")
        if not (0 <= top <= 1 and 0 <= bottom <= 1):
            raise SpecError(f"{w}: roundness must be from 0 (square) to 1 (oval)")
        if out and x <= out[-1][0]:
            raise SpecError(f"{w}: sections must go in order of increasing x")
        out.append([x, y, width, height, top, bottom])
    if max(s[2] for s in out) < MIN_SIZE or max(s[3] for s in out) < MIN_SIZE:
        raise SpecError(f"{where}: the loft has no size")
    return out


def _color(value: Any, where: str) -> tuple[int, int, int]:
    try:
        return ImageColor.getrgb(str(value))[:3]  # type: ignore[return-value]
    except ValueError:
        raise SpecError(f"{where}: unknown color {value!r}") from None


def _asset_params(raw: dict, where: str) -> dict[str, Any]:
    try:
        rec = model_store.load(str(raw.get("model")))
        version = rec.get(raw.get("version")).version
    except (KeyError, TypeError, ValueError):
        raise SpecError(f"{where}: 'model' must be an existing model id (e.g. mdl_004), "
                        "and 'version' one of its versions") from None
    # Pin the version into the spec, so later changes to that model don't change this one.
    raw["version"] = version
    colors = raw.get("colors") or {}
    if not isinstance(colors, dict):
        raise SpecError(f"{where}: 'colors' must be {{material name: color}}")
    return {"model": rec.id, "version": version,
            "colors": {str(k): _color(c, f"{where} colors") for k, c in colors.items()}}


def validate(spec: Any) -> list[Part]:
    """Check a spec from Claude and turn it into Parts. Raises SpecError with a clear message."""
    if not isinstance(spec, dict) or not isinstance(spec.get("parts"), list):
        raise SpecError("The spec must be an object with a 'parts' list")
    raw_parts = spec["parts"]
    if not 1 <= len(raw_parts) <= MAX_PARTS:
        raise SpecError(f"Use 1–{MAX_PARTS} parts")

    parts = []
    for i, raw in enumerate(raw_parts, 1):
        if not isinstance(raw, dict):
            raise SpecError(f"Part {i} must be an object")
        name = str(raw.get("name") or f"part_{i}")[:40]
        where = f"Part {i} ({name})"
        shape = raw.get("shape")
        if shape not in SHAPES:
            raise SpecError(f"{where}: 'shape' must be one of {SHAPES}")

        if shape == "box":
            size = raw.get("size")
            if not (isinstance(size, list) and len(size) == 3):
                raise SpecError(f"{where}: box needs 'size': [width, height, depth]")
            params = {"size": [_size({"s": s}, "s", f"{where} size") for s in size]}
            if "round" in raw:  # rounded corners: fraction of the smallest side
                try:
                    params["round"] = float(raw["round"])
                except (TypeError, ValueError):
                    raise SpecError(f"{where}: 'round' must be a number from 0 to 0.5") from None
                if not 0 <= params["round"] <= 0.5:
                    raise SpecError(f"{where}: 'round' must be from 0 to 0.5")
        elif shape == "sphere":
            params = {"radius": _size(raw, "radius", where)}
        elif shape == "cylinder":
            r = raw.get("radius")
            params = {
                "radius_top": _size(raw, "radius_top", where, r),
                "radius_bottom": _size(raw, "radius_bottom", where, r),
                "height": _size(raw, "height", where),
            }
        elif shape == "cone":
            params = {"radius": _size(raw, "radius", where), "height": _size(raw, "height", where)}
        elif shape == "torus":
            params = {"radius": _size(raw, "radius", where), "tube": _size(raw, "tube", where)}
            if params["tube"] >= params["radius"]:
                raise SpecError(f"{where}: torus 'tube' must be smaller than 'radius'")
        elif shape == "capsule":
            params = {"radius": _size(raw, "radius", where), "height": _size(raw, "height", where)}
        elif shape == "lathe":
            pts = _points(raw, "points", where, 2)
            if any(r < 0 for r, _ in pts):
                raise SpecError(f"{where}: lathe points are [radius, y]; radius can't be negative")
            params = {"points": pts}
        elif shape == "extrude":
            outline = _points(raw, "outline", where, 3)
            poly = Polygon(outline)
            if not poly.is_valid or poly.area < MIN_SIZE**2:
                raise SpecError(f"{where}: 'outline' must be a simple shape that doesn't cross itself")
            params = {"outline": outline, "depth": _size(raw, "depth", where)}
        elif shape == "loft":
            params = {"sections": _loft_sections(raw, where)}
        elif shape == "asset":
            params = _asset_params(raw, where)

        color = _color(raw.get("color", "#c8c8c8"), where)
        material = raw.get("material", "matte")
        if material not in MATERIALS:
            raise SpecError(f"{where}: 'material' must be one of {list(MATERIALS)}")

        mirror = raw.get("mirror")
        if mirror is True:
            mirror = "z"
        if mirror in (None, False):
            mirror = None
        elif mirror not in ("x", "y", "z"):
            raise SpecError(f"{where}: 'mirror' must be true (left/right) or one of 'x', 'y', 'z'")

        scale = _vec3(raw, "scale", where, (1.0, 1.0, 1.0))
        if any(s <= 0 for s in scale):
            raise SpecError(f"{where}: 'scale' values must be positive")
        parts.append(Part(
            name=name,
            shape=shape,
            params=params,
            position=_vec3(raw, "position", where, (0.0, 0.0, 0.0)),
            rotation=_vec3(raw, "rotation", where, (0.0, 0.0, 0.0)),
            scale=scale,
            color=color,  # type: ignore[arg-type]
            material=material,
            mirror=mirror,
        ))
    return parts


# ---- Geometry -----------------------------------------------------------------------

# trimesh builds round shapes around the Z axis; our convention is Y up.
_Z_TO_Y = transformations.rotation_matrix(-math.pi / 2, [1, 0, 0])


def _revolve(profile: list[tuple[float, float]], segments: int) -> trimesh.Trimesh:
    """Spin a [radius, height] profile around the vertical axis."""
    mesh = creation.revolve(np.array(profile, dtype=float), sections=segments)
    mesh.apply_transform(_Z_TO_Y)
    return mesh


def _rounded_box(size: list[float], round_: float, segments: int) -> trimesh.Trimesh:
    """A box with rounded corners: the hull of a small sphere in each corner."""
    r = round_ * min(size)
    if r <= 0:
        return creation.box(extents=size)
    ball = creation.uv_sphere(radius=r, count=[max(6, segments // 2), segments])
    inner = [max(s / 2 - r, 0.0) for s in size]
    corners = [(sx * inner[0], sy * inner[1], sz * inner[2]) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    return trimesh.convex.convex_hull(np.vstack([ball.vertices + c for c in corners]))


def _superellipse(width: float, height: float, top: float, bottom: float, count: int) -> np.ndarray:
    """Points around a cross-section, from a rectangle (roundness 0) to an oval (1).
    Returns (count, 2) of [z, y]."""
    t = np.linspace(0, 2 * np.pi, count, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    roundness = np.where(s >= 0, top, bottom)
    n = 2 + 10 * (1 - roundness) ** 1.5  # exponent: 2 = ellipse, 12 = almost a rectangle
    z = (width / 2) * np.sign(c) * np.abs(c) ** (2 / n)
    y = (height / 2) * np.sign(s) * np.abs(s) ** (2 / n)
    return np.column_stack([z, y])


def _smooth_sections(sections: list[list[float]], steps: int) -> np.ndarray:
    """Add `steps - 1` in-between sections: x linear (keeps order), the rest on a smooth curve."""
    pts = np.array(sections, dtype=float)
    if steps <= 1 or len(pts) < 2:
        return pts
    padded = np.vstack([pts[0], pts, pts[-1]])
    out = []
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = padded[i : i + 4]
        for k in range(steps):
            t = k / steps
            curve = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2
                           + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3)  # Catmull-Rom
            curve[0] = p1[0] + (p2[0] - p1[0]) * t
            out.append(curve)
    out.append(pts[-1])
    result = np.array(out)
    result[:, 2:4] = np.clip(result[:, 2:4], 0, None)
    result[:, 4:6] = np.clip(result[:, 4:6], 0, 1)
    return result


def _loft(sections: list[list[float]], detail: str) -> trimesh.Trimesh:
    """A smooth body through cross-sections placed along X (car bodies, hulls, fuselages)."""
    steps, count = LOFT_DETAIL[detail]
    rows = _smooth_sections(sections, steps)
    rings = []
    for x, y, width, height, top, bottom in rows:
        zy = _superellipse(width, height, top, bottom, count)
        rings.append(np.column_stack([np.full(count, x), zy[:, 1] + y, zy[:, 0]]))
    vertices = np.vstack(rings + [[rows[0][0], rows[0][1], 0], [rows[-1][0], rows[-1][1], 0]])
    first_cap, last_cap = len(vertices) - 2, len(vertices) - 1
    faces = []
    for i in range(len(rings) - 1):
        a, b = i * count, (i + 1) * count
        for j in range(count):
            j2 = (j + 1) % count
            faces += [[a + j, b + j, b + j2], [a + j, b + j2, a + j2]]
    last = (len(rings) - 1) * count
    for j in range(count):
        j2 = (j + 1) % count
        faces += [[first_cap, j2, j], [last_cap, last + j, last + j2]]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if mesh.volume < 0:  # faces are built in a consistent order; flip if they point inward
        mesh.invert()
    return mesh


def _mesh(part: Part, segments: int, detail: str = "preview") -> trimesh.Trimesh:
    p = part.params
    if part.shape == "box":
        return _rounded_box(p["size"], p.get("round", 0.0), segments)
    if part.shape == "loft":
        return _loft(p["sections"], detail)
    if part.shape == "sphere":
        return creation.uv_sphere(radius=p["radius"], count=[max(8, segments // 2), segments])
    if part.shape == "cylinder":
        h, rt, rb = p["height"], p["radius_top"], p["radius_bottom"]
        return _revolve([(0, -h / 2), (rb, -h / 2), (rt, h / 2), (0, h / 2)], segments)
    if part.shape == "cone":
        h, r = p["height"], p["radius"]
        return _revolve([(0, -h / 2), (r, -h / 2), (0, h / 2)], segments)
    if part.shape == "torus":
        mesh = creation.torus(major_radius=p["radius"], minor_radius=p["tube"],
                              major_sections=segments, minor_sections=max(8, segments // 2))
        mesh.apply_transform(_Z_TO_Y)
        return mesh
    if part.shape == "capsule":
        r = p["radius"]
        mesh = creation.capsule(height=max(p["height"] - 2 * r, 0.0), radius=r,
                                count=[segments, max(8, segments // 2)])
        mesh.apply_transform(_Z_TO_Y)
        return mesh
    if part.shape == "lathe":
        return _revolve(p["points"], segments)
    # extrude: outline in the X-Y plane, pushed out along Z, centered
    mesh = creation.extrude_polygon(Polygon(p["outline"]), p["depth"])
    mesh.apply_translation([0, 0, -p["depth"] / 2])
    return mesh


def _transform(part: Part) -> np.ndarray:
    rx, ry, rz = (math.radians(a) for a in part.rotation)
    m = transformations.euler_matrix(rx, ry, rz, "rxyz")
    m[:3, :3] = m[:3, :3] @ np.diag(part.scale)
    m[:3, 3] = part.position
    return m


def _linear(channel: int) -> float:
    """Screen color (sRGB, 0–255) -> the linear value glTF and Blender expect.
    Without this, every color comes out too light ("dark blue" looks bright blue)."""
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _material(part: Part) -> PBRMaterial:
    metallic, roughness, alpha = MATERIALS[part.material]
    return PBRMaterial(
        name=part.material,
        baseColorFactor=[*(_linear(c) for c in part.color), alpha],
        metallicFactor=metallic,
        roughnessFactor=roughness,
        alphaMode="BLEND" if alpha < 1 else "OPAQUE",
        doubleSided=part.shape == "lathe",  # an open lathe profile shows its inside
    )


# Largest value of each integer component type (glTF componentType -> max).
_NORMALIZED_MAX = {5120: 127, 5121: 255, 5122: 32767, 5123: 65535}


def _position_divisor(glb: bytes) -> int:
    """How much trimesh over-scales a KHR_mesh_quantization file (1 = not quantized).

    3DAssets.dev stores positions as normalized int16; trimesh reads them raw, so a 2 m tree
    comes out 65 km tall. Blender and the 3D panel read them correctly, only trimesh needs this.
    """
    gltf = json.loads(glb[20:20 + int.from_bytes(glb[12:16], "little")])
    accessors = gltf.get("accessors", [])
    found = {_NORMALIZED_MAX.get(accessors[p["attributes"]["POSITION"]]["componentType"], 1)
             if accessors[p["attributes"]["POSITION"]].get("normalized") else 1
             for m in gltf.get("meshes", []) for p in m.get("primitives", []) if "POSITION" in p.get("attributes", {})}
    # ponytail: assumes one quantization for the whole file (true for 3DAssets); mixed files keep raw sizes
    return found.pop() if len(found) == 1 else 1


def load_glb(glb: bytes) -> trimesh.Scene:
    """A .glb as a trimesh scene at its real size."""
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    divisor = _position_divisor(glb)
    if divisor > 1:
        for geom in scene.geometry.values():
            geom.vertices = geom.vertices / divisor  # also drops the (quantized) normals trimesh read
    return scene


def _material_name(mesh: trimesh.Trimesh) -> str:
    return str(getattr(getattr(mesh.visual, "material", None), "name", None) or "unnamed")


def materials(scene: trimesh.Scene) -> list[str]:
    """Material names in a model: what an asset part's 'colors' can change."""
    return sorted({_material_name(g) for g in scene.geometry.values()})


def _asset_meshes(part: Part) -> list[tuple[trimesh.Trimesh, str]]:
    """A stored model's meshes, recolored, with the bottom center of the whole model at the origin."""
    p = part.params
    glb = model_store.file_path(p["model"], f"v{p['version']}_preview.glb").read_bytes()
    scene = load_glb(glb)
    unknown = set(p["colors"]) - set(materials(scene))
    if unknown:
        raise SpecError(f"Part {part.name}: {p['model']} has no material {', '.join(map(repr, sorted(unknown)))}. "
                        f"Its materials are: {', '.join(materials(scene))}")
    meshes = [g for g in scene.dump() if isinstance(g, trimesh.Trimesh)]
    (x0, y0, z0), (x1, _, z1) = scene.bounds
    pieces = []
    for k, mesh in enumerate(meshes):
        mesh.apply_translation([-(x0 + x1) / 2, -y0, -(z0 + z1) / 2])
        name = _material_name(mesh)
        if name in p["colors"]:
            old = mesh.visual.material
            factor = getattr(old, "baseColorFactor", None)
            alpha = 1.0 if factor is None else float(factor[3]) / 255  # trimesh keeps it as 0–255
            new = PBRMaterial(name=name, baseColorFactor=[*(_linear(c) for c in p["colors"][name]), alpha],
                              metallicFactor=getattr(old, "metallicFactor", None),
                              roughnessFactor=getattr(old, "roughnessFactor", None),
                              alphaMode=getattr(old, "alphaMode", None))
            mesh.visual = trimesh.visual.TextureVisuals(uv=getattr(mesh.visual, "uv", None), material=new)
        pieces.append((mesh, f"{part.name}/{k}:{name}"))
    return pieces


_MIRROR = {"x": np.diag([-1.0, 1, 1, 1]), "y": np.diag([1.0, -1, 1, 1]), "z": np.diag([1.0, 1, -1, 1])}


def build_scene(parts: list[Part], detail: str = "preview") -> trimesh.Scene:
    segments = DETAIL[detail]
    scene = trimesh.Scene()
    for i, part in enumerate(parts, 1):
        if part.shape == "asset":
            pieces = _asset_meshes(part)
        else:
            mesh = _mesh(part, segments, detail)
            mesh.visual = trimesh.visual.TextureVisuals(material=_material(part))
            pieces = [(mesh, part.name)]
        # The node name carries the shape, so the Blender step knows what to bevel.
        kind = "roundbox" if part.shape == "box" and part.params.get("round") else part.shape
        for mesh, name in pieces:
            mesh.apply_transform(_transform(part))
            copies = [(mesh, name, "")]
            if part.mirror:
                reflected = mesh.copy()
                reflected.apply_transform(_MIRROR[part.mirror])  # trimesh keeps the faces facing outward
                copies.append((reflected, f"{name} (mirrored)", "m"))
            for m, n, suffix in copies:
                tag = f"{i:03d}{suffix}"
                scene.add_geometry(m, node_name=f"{tag}_{n}__{kind}", geom_name=f"{tag}_{n}")
    return scene


def to_glb(scene: trimesh.Scene) -> bytes:
    return scene.export(file_type="glb")


def summary(scene: trimesh.Scene) -> tuple[list[float], int]:
    """(size [width, height, depth] in meters, triangle count)."""
    lo, hi = scene.bounds
    return [round(float(v), 3) for v in (hi - lo)], int(sum(len(g.faces) for g in scene.geometry.values()))


# ---- Checks -------------------------------------------------------------------------

def _display_name(geom_name: str) -> str:
    """'003m_mirror (mirrored)' -> 'mirror (mirrored)'."""
    return geom_name.split("_", 1)[1] if "_" in geom_name else geom_name


def _touching(a: trimesh.Trimesh, b: trimesh.Trimesh, tol: float) -> bool:
    """True if a and b touch, overlap, or one sits inside the other."""
    for src, dst in ((a, b), (b, a)):
        pts = np.vstack([src.vertices, src.triangles_center])
        if len(pts) > 400:
            pts = pts[np.linspace(0, len(pts) - 1, 400).astype(int)]
        if dst.is_watertight and dst.contains(pts).any():
            return True
        _, dist, _ = trimesh.proximity.closest_point(dst, pts)
        if dist.min() <= tol:
            return True
    return False


def _gap(a: trimesh.Trimesh, b: trimesh.Trimesh) -> float:
    pts = np.vstack([a.vertices, a.triangles_center])
    return float(trimesh.proximity.closest_point(b, pts)[1].min())


def floating_parts(scene: trimesh.Scene) -> list[tuple[str, float]]:
    """Parts not connected to the main object, with their gap in meters.

    Parts count as connected if they touch, overlap or one is inside the other
    (within 1% of the object's size). Anything else is floating in the air.
    """
    names = list(scene.geometry)
    meshes = [scene.geometry[n] for n in names]
    if len(meshes) < 2:
        return []
    size = float(np.linalg.norm(scene.extents))
    tol = max(0.002, size * 0.01)
    bounds = np.array([m.bounds for m in meshes])  # (n, 2, 3)

    links: list[set[int]] = [set() for _ in meshes]
    # The meshes of one asset part share a tag ('003_house/0:plaster'): they are one part.
    tags = [n.split("_", 1)[0] for n in names]
    for i in range(len(meshes)):
        links[i] |= {j for j in range(len(meshes)) if j != i and tags[j] == tags[i]}
    for i in range(len(meshes)):
        for j in range(i + 1, len(meshes)):
            box_gap = np.maximum(0, np.maximum(bounds[j, 0] - bounds[i, 1], bounds[i, 0] - bounds[j, 1]))
            if np.linalg.norm(box_gap) > tol:
                continue  # their bounding boxes are apart, so the parts are too
            if _touching(meshes[i], meshes[j], tol):
                links[i].add(j)
                links[j].add(i)

    groups, seen = [], set()
    for start in range(len(meshes)):
        if start in seen:
            continue
        group, todo = set(), [start]
        while todo:
            k = todo.pop()
            if k not in group:
                group.add(k)
                todo += links[k] - group
        seen |= group
        groups.append(group)
    if len(groups) == 1:
        return []

    main = max(groups, key=lambda g: sum(float(meshes[k].area) for k in g))
    floating = []
    for group in groups:
        if group is main:
            continue
        for k in sorted(group):
            gap = min(_gap(meshes[k], meshes[m]) for m in main)
            floating.append((_display_name(names[k]), round(gap, 3)))
    return floating


# ---- Small changes ------------------------------------------------------------------

def apply_changes(
    spec: dict[str, Any],
    update_parts: list[dict[str, Any]] | None = None,
    add_parts: list[dict[str, Any]] | None = None,
    remove_parts: list[str] | None = None,
) -> dict[str, Any]:
    """Apply a small change to a spec, so Claude doesn't have to rewrite the whole object.

    update_parts: [{"name": "wheel", "color": "red", "round": null}, ...]  (null removes a field)
    add_parts:    new parts, as in a full spec
    remove_parts: names of parts to delete
    """
    parts = [dict(p) for p in spec.get("parts", [])]
    by_name = {p.get("name"): p for p in parts}
    missing = [n for n in (remove_parts or []) if n not in by_name]
    missing += [u.get("name") for u in (update_parts or []) if u.get("name") not in by_name]
    if missing:
        raise SpecError(f"No part called {', '.join(map(repr, missing))}. The parts are: "
                        + ", ".join(repr(p.get("name")) for p in parts))
    for change in update_parts or []:
        part = by_name[change["name"]]
        for key, value in change.items():
            if key == "name":
                continue
            if value is None:
                part.pop(key, None)
            else:
                part[key] = value
    parts = [p for p in parts if p.get("name") not in set(remove_parts or [])]
    parts += [dict(p) for p in add_parts or []]
    return {**spec, "parts": parts}
