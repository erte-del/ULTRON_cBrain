"""3D models and their versions, stored as files.

    storage/models/mdl_001/
        meta.json          title, current version, one entry per version, finished exports
        v1.json            the scene spec Claude wrote
        v1_preview.glb     the low-detail preview shown in the browser
        final_v3.fbx       a finished export (only after you approved it)
"""

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import STORAGE_DIR

MODELS_DIR = STORAGE_DIR / "models"
MODEL_ID = re.compile(r"^mdl_\d{3,6}$")
FORMATS = ["blend", "fbx", "obj", "stl", "gltf", "glb"]
_FILE = re.compile(r"^(v\d{1,4}_preview\.glb|final_v\d{1,4}\.(" + "|".join(FORMATS) + r"|zip))$")

_lock = threading.Lock()


@dataclass
class ModelVersion:
    version: int
    note: str
    parts: int
    size: list[float]  # [width, height, depth] in meters
    source: str = ""  # "library" for a ready-made model from the 3D library


@dataclass
class Export:
    version: int
    format: str
    file: str


@dataclass
class ModelRecord:
    id: str
    title: str
    current: int = 1
    versions: list[ModelVersion] = field(default_factory=list)
    exports: list[Export] = field(default_factory=list)

    def get(self, version: int | None = None) -> ModelVersion:
        wanted = self.current if version is None else version
        for v in self.versions:
            if v.version == wanted:
                return v
        raise KeyError(f"{self.id} has no version {wanted} (it has v1–v{len(self.versions)})")


def folder(model_id: str) -> Path:
    if not MODEL_ID.match(model_id):
        raise KeyError(f"Not a model id: {model_id!r}")
    return MODELS_DIR / model_id


def _save(rec: ModelRecord) -> None:
    (folder(rec.id) / "meta.json").write_text(json.dumps(asdict(rec), indent=1))


def load(model_id: str) -> ModelRecord:
    path = folder(model_id) / "meta.json"
    if not path.exists():
        raise KeyError(f"No 3D model called {model_id}")
    raw = json.loads(path.read_text())
    raw["versions"] = [ModelVersion(**v) for v in raw["versions"]]
    raw["exports"] = [Export(**e) for e in raw.get("exports", [])]
    return ModelRecord(**raw)


def create(title: str) -> ModelRecord:
    with _lock:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        numbers = [int(p.name[4:]) for p in MODELS_DIR.glob("mdl_*") if MODEL_ID.match(p.name)]
        rec = ModelRecord(id=f"mdl_{max(numbers, default=0) + 1:03d}", title=title[:80])
        folder(rec.id).mkdir()
    return rec


def add_version(rec: ModelRecord, spec: dict[str, Any], preview_glb: bytes, note: str,
                parts: int, size: list[float], source: str = "") -> ModelVersion:
    with _lock:
        number = len(rec.versions) + 1
        (folder(rec.id) / f"v{number}.json").write_text(json.dumps(spec, indent=1))
        (folder(rec.id) / f"v{number}_preview.glb").write_bytes(preview_glb)
        v = ModelVersion(number, note[:120], parts, size, source)
        rec.versions.append(v)
        rec.current = number
        _save(rec)
    return v


def set_current(rec: ModelRecord, version: int) -> None:
    rec.get(version)
    rec.current = version
    _save(rec)


def spec(rec: ModelRecord, version: int | None = None) -> dict[str, Any]:
    v = rec.get(version)
    return json.loads((folder(rec.id) / f"v{v.version}.json").read_text())


def add_export(rec: ModelRecord, version: int, fmt: str, filename: str) -> Export:
    e = Export(version, fmt, filename)
    rec.exports = [x for x in rec.exports if x.file != filename] + [e]
    _save(rec)
    return e


def file_path(model_id: str, filename: str) -> Path:
    """Path of a stored preview or export, for the web server. Anything else is refused."""
    if not _FILE.match(filename):
        raise KeyError(filename)
    path = folder(model_id) / filename
    if not path.exists():
        raise KeyError(filename)
    return path


def download_name(rec: ModelRecord, filename: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", rec.title.lower()).strip("_")[:40] or rec.id
    return f"{slug}_{filename.removeprefix('final_')}"


def card_data(rec: ModelRecord) -> dict[str, Any]:
    base = f"/models/{rec.id}"
    return {
        "model_id": rec.id,
        "current": rec.current,
        "versions": [
            {"version": v.version, "note": v.note, "parts": v.parts, "size": v.size, "source": v.source,
             "preview_url": f"{base}/v{v.version}_preview.glb"}
            for v in rec.versions
        ],
        "exports": [
            {"version": e.version, "format": e.format, "url": f"{base}/{e.file}", "name": download_name(rec, e.file)}
            for e in rec.exports
        ],
    }
