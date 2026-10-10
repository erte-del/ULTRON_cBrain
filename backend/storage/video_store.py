"""Generated videos, stored as files.

    storage/videos/vid_001/
        meta.json      title, prompt, status (rendering | done | failed), progress
        video.mp4      the finished video
"""

import json
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config import STORAGE_DIR

VIDEOS_DIR = STORAGE_DIR / "videos"
VIDEO_ID = re.compile(r"^vid_\d{3,6}$")
FILE = "video.mp4"
THUMB = "thumb.jpg"

_lock = threading.Lock()


@dataclass
class VideoRecord:
    id: str
    title: str
    prompt: str
    seconds: float
    width: int
    height: int
    status: str = "rendering"  # rendering | done | failed
    progress: float = 0.0  # 0–1 while rendering
    error: str = ""
    kind: str = ""  # "capture" for the clipping library
    created: float = 0.0
    fav: bool = False


def folder(video_id: str) -> Path:
    if not VIDEO_ID.match(video_id):
        raise KeyError(f"Not a video id: {video_id!r}")
    return VIDEOS_DIR / video_id


def save(rec: VideoRecord) -> None:
    (folder(rec.id) / "meta.json").write_text(json.dumps(asdict(rec), indent=1))


def load(video_id: str) -> VideoRecord:
    path = folder(video_id) / "meta.json"
    if not path.exists():
        raise KeyError(f"No video called {video_id}")
    return VideoRecord(**json.loads(path.read_text()))


def create(title: str, prompt: str, seconds: float, width: int, height: int, kind: str = "") -> VideoRecord:
    with _lock:
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        numbers = [int(p.name[4:]) for p in VIDEOS_DIR.glob("vid_*") if VIDEO_ID.match(p.name)]
        rec = VideoRecord(f"vid_{max(numbers, default=0) + 1:03d}", title[:80], prompt, seconds, width, height,
                          kind=kind, created=time.time())
        folder(rec.id).mkdir()
        save(rec)
    return rec


def file_path(video_id: str, filename: str) -> Path:
    """Path of a finished video, for the web server. Anything else is refused."""
    if filename not in (FILE, THUMB):
        raise KeyError(filename)
    path = folder(video_id) / filename
    if not path.exists():
        raise KeyError(filename)
    return path


def download_name(rec: VideoRecord) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", rec.title.lower()).strip("_")[:40] or rec.id
    return f"{slug}.mp4"


def card_data(rec: VideoRecord) -> dict[str, Any]:
    return {
        "video_id": rec.id,
        "prompt": rec.prompt,
        "status": rec.status,
        "progress": rec.progress,
        "error": rec.error,
        "seconds": rec.seconds,
        "width": rec.width,
        "height": rec.height,
        "url": f"/videos/{rec.id}/{FILE}" if rec.status == "done" else "",
        "download_name": download_name(rec),
    }


def all_records(kind: str) -> list[VideoRecord]:
    """Finished videos of one kind, newest first."""
    recs = [load(p.name) for p in VIDEOS_DIR.glob("vid_*") if VIDEO_ID.match(p.name) and (p / "meta.json").exists()]
    return sorted((r for r in recs if r.kind == kind and r.status == "done"), key=lambda r: -r.created)


def delete(video_id: str) -> None:
    shutil.rmtree(folder(video_id))
