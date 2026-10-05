"""Files you upload from your computer.

    storage/uploads/upl_001/report.pdf

Images go to the image store instead (see main.upload), so they land on the canvas
and the image tools can edit them.
"""

import re
import shutil
import threading
from pathlib import Path

from config import STORAGE_DIR

from . import image_store

UPLOADS_DIR = STORAGE_DIR / "uploads"
UPLOAD_ID = re.compile(r"^upl_\d{3,6}$")
MAX_BYTES = 25 * 1024 * 1024

SCREEN_NAME = "screen.jpg"  # what a screen capture is saved as (see main.screen)
KEEP_SCREENS = 10  # older captures are deleted: they can show anything on the screen

_lock = threading.Lock()


def save(name: str, data: bytes) -> str:
    """Store a file and return its id (upl_001, ...)."""
    name = Path(name).name.strip()[:120]
    if name in ("", ".", ".."):
        name = "file"
    with _lock:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        numbers = [int(p.name[4:]) for p in UPLOADS_DIR.glob("upl_*") if UPLOAD_ID.match(p.name)]
        upload_id = f"upl_{max(numbers, default=0) + 1:03d}"
        folder = UPLOADS_DIR / upload_id
        folder.mkdir()
        (folder / name).write_bytes(data)
    return upload_id


def find(upload_id: str) -> Path:
    """The stored file of an upload."""
    if not UPLOAD_ID.match(upload_id):
        raise KeyError(f"Not an upload id: {upload_id!r}")
    files = list((UPLOADS_DIR / upload_id).glob("*"))
    if not files:
        raise KeyError(f"No upload called {upload_id}")
    return files[0]


def label(file_id: str) -> str:
    """'upl_003 (report.pdf)' or 'img_007 (photo.jpg, on the canvas)', for the prompt."""
    try:
        if image_store.IMAGE_ID.match(file_id):
            return f"{file_id} ({image_store.load(file_id).title}, on the canvas)"
        return f"{file_id} ({find(file_id).name})"
    except KeyError:
        return file_id


def prune_screens(keep: int = KEEP_SCREENS) -> None:
    """Delete all but the newest `keep` screen captures."""
    with _lock:
        folders = sorted(
            (p for p in UPLOADS_DIR.glob("upl_*") if UPLOAD_ID.match(p.name) and (p / SCREEN_NAME).exists()),
            key=lambda p: int(p.name[4:]),
        )
        for folder in folders[:-keep] if keep else folders:
            shutil.rmtree(folder, ignore_errors=True)
