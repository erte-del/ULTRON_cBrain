"""capture: a screen replay buffer Ultron can clip, like Insights Capture's clips mode.

FFmpeg records the screen into a ring of 5-second segments (the last few minutes, nothing older).
Ultron bookmarks moments ("that was sick") and cuts clips from the buffer: the last N seconds,
or a window around a bookmark. Clips become normal videos on the canvas and can be trimmed and
merged. With JARVIS_CAPTURE_ALWAYS_ON (default) the buffer starts with Ultron; `stop` turns it off and deletes it.

Mac: avfoundation (needs Screen Recording permission; JARVIS_CAPTURE_SCREEN picks the display).
Windows: gdigrab. Game sound needs a loopback device: set JARVIS_CAPTURE_AUDIO (see .env.example); without it, video only.
"""

import asyncio
import atexit
import math
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config
import reel
from storage import video_store

from .video import _show, _text

BUF = config.STORAGE_DIR / "capture_buffer"
SEG = 5  # seconds per segment
MAX_MINUTES = 10
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]

_proc: subprocess.Popen | None = None
_log = None
_marks: list[dict[str, Any]] = []
_recording = False  # True: keep every segment as a full recording, not a ring


def window(a: float, b: float, buffer_end: float, total: float) -> tuple[float, float]:
    """(seek, length) into a joined buffer that is `total` s long and ends at time `buffer_end`,
    for the wall-clock span a..b, cut to what the buffer holds."""
    begin = buffer_end - total
    a, b = max(a, begin), min(b, buffer_end)
    return a - begin, b - a


def _source() -> list[str]:
    audio = config.CAPTURE_AUDIO
    if sys.platform == "win32":
        return ["-f", "gdigrab", "-framerate", "30", "-i", "desktop",
                *(["-f", "dshow", "-i", f"audio={audio}"] if audio else [])]
    return ["-f", "avfoundation", "-framerate", "30", "-capture_cursor", "1", "-i", f"{config.CAPTURE_SCREEN}:{audio or 'none'}"]


def _encoder() -> list[str]:
    sound = ["-c:a", "aac", "-b:a", "160k"] if config.CAPTURE_AUDIO else ["-an"]
    if sys.platform == "darwin":
        return ["-c:v", "h264_videotoolbox", "-b:v", "6M", *sound]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", *sound]


def running() -> bool:
    return _proc is not None and _proc.poll() is None


def start(minutes: int) -> str:
    """minutes > 0: rolling buffer. minutes == 0: record everything until stopped."""
    global _proc, _log, _recording
    if running():
        if _recording == (minutes == 0):
            return "Already recording."
        stop_process()  # switching between the rolling buffer and a full recording
    shutil.rmtree(BUF, ignore_errors=True)
    BUF.mkdir(parents=True)
    _marks.clear()
    _recording = minutes == 0
    wrap = [] if _recording else ["-segment_wrap", str(math.ceil(minutes * 60 / SEG) + 1)]
    _log = open(BUF / "ffmpeg.log", "wb")
    _proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *_source(), "-vf", "scale=-2:1080",
         "-pix_fmt", "yuv420p", *_encoder(), "-g", "30", "-f", "segment", "-segment_time", str(SEG),
         "-segment_format", "mpegts", *wrap, "-reset_timestamps", "1", str(BUF / "s%05d.ts")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=_log)
    return f"Recording the screen into a {minutes}-minute buffer." if minutes else "Recording until you stop it."


def stop_process() -> bool:
    global _proc
    was = running()
    if was:
        _proc.terminate()
        try:
            _proc.wait(5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None
    if _log:
        _log.close()
    return was


def stop() -> str:
    was = stop_process()
    shutil.rmtree(BUF, ignore_errors=True)
    return "Stopped; the buffer is deleted." if was else "It wasn't recording."


atexit.register(stop)


def _segments() -> list[Path]:
    return sorted(BUF.glob("s*.ts"), key=lambda p: p.stat().st_mtime)


def _concat(files: list[Path], out: str, ss: float = 0, length: float | None = None, copy: bool = False) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{Path(f).as_posix()}'\n" for f in files), encoding="utf-8")
        reel.ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-ss", str(ss),
                    *(["-t", str(length)] if length else []),
                    *(["-c", "copy", "-movflags", "+faststart"] if copy else ENCODE), out)


def cut_buffer(a: float, b: float | None, out: str) -> float:
    """Write wall-clock span a..b of the buffer to `out`; returns its length. b=None: the last `a`
    seconds counted back from the newest footage (not from the clock, which runs a moment ahead)."""
    if b is None:
        newest = _segments()[-1].stat().st_mtime if _segments() else 0
        a, b = newest - a, newest
    segs = [s for s in _segments() if s.stat().st_mtime >= a and s.stat().st_mtime - SEG <= b]
    if not segs:
        raise ValueError("the buffer holds nothing from that time")
    end = segs[-1].stat().st_mtime
    total = sum(reel.probe(str(s))["seconds"] for s in segs)
    ss, length = window(a, b, end, total)
    if length < 0.5:
        raise ValueError("the buffer holds nothing from that time")
    _concat(segs, out, ss, length)
    return length


async def _new(title: str, make, show: bool = True) -> video_store.VideoRecord:
    """Make a library video: make(path) fills the file; a thumbnail is added. show puts it on the canvas."""
    rec = await asyncio.to_thread(video_store.create, title, "capture", 0, 0, 0, "capture")
    folder = video_store.folder(rec.id)
    path = str(folder / video_store.FILE)
    try:
        await asyncio.to_thread(make, path)
        info = reel.probe(path)
        rec.seconds = round(info["seconds"], 1)
        await asyncio.to_thread(reel.ffmpeg, "-ss", str(min(1, info["seconds"] / 2)), "-i", path, "-frames:v", "1",
                                "-vf", "scale=480:-2", str(folder / video_store.THUMB))
    except Exception:
        await asyncio.to_thread(video_store.delete, rec.id)
        raise
    v = info["video"] or {}
    rec.width, rec.height, rec.status, rec.progress = v.get("width", 0), v.get("height", 0), "done", 1.0
    if show:
        await _show(rec)
    else:
        await asyncio.to_thread(video_store.save, rec)
    return rec


async def finish_recording() -> video_store.VideoRecord:
    """Stop a full recording and put it in the library."""
    segs = await asyncio.to_thread(lambda: (stop_process(), _segments())[1])
    if not segs:
        raise ValueError("nothing was recorded")
    rec = await _new(time.strftime("Recording - %H:%M"), lambda out: _concat(segs, out, copy=True), show=False)
    if config.CAPTURE_ALWAYS_ON:
        await asyncio.to_thread(start, config.CAPTURE_MINUTES)  # back to the rolling buffer
    return rec


async def trim_to_library(video_id: str, start: float, end: float, title: str = "") -> video_store.VideoRecord:
    """Save start..end of a library video as a new clip (the original stays)."""
    if end <= start:
        raise ValueError("end must be after start")
    src = video_store.folder(video_id) / video_store.FILE
    return await _new(title or f"Clip - {video_store.load(video_id).title}"[:80],
                      lambda out: _concat([src], out, start, end - start), show=False)


def _clip_span(args: dict[str, Any]) -> tuple[float, float | None]:
    if args.get("bookmark"):
        m = next((m for m in _marks if m["id"] == args["bookmark"]), None)
        if not m:
            raise ValueError(f"no bookmark {args['bookmark']}")
        return m["at"] - float(args.get("before") or 15), m["at"] + float(args.get("after") or 5)
    return float(args.get("seconds") or 30), None  # the last N seconds


@tool(
    "capture",
    "Screen clipping, like a game-capture tool's clips mode. action: start (begin a rolling screen "
    f"buffer of the last `minutes` minutes, default 3, max {MAX_MINUTES}; with game sound if set up) · stop (deletes "
    "the buffer) · status · bookmark (mark this moment, optional `label`; returns an id) · clip (save "
    "exactly the last `seconds` (default 30: use it for \"clip that\" or \"capture that\" with no length, never ask; up to the buffer length; works while recording too), or a window around a `bookmark` id: `before` 15 s, `after` 5 s; "
    "it shows on the canvas as a video) · trim (video id, `start`, `end` in seconds) · merge (`videos`: "
    "list of video ids, joined in order). Clips and edits are new videos; originals stay. Nothing is "
    "recorded until start, so start it before the moment you want to catch; say so if the user asks "
    "for a clip while it's off. Tell the user it records their whole screen.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "record", "open", "stop", "status", "bookmark", "clip", "trim", "merge"]},
            "minutes": {"type": "integer"}, "label": {"type": "string"},
            "seconds": {"type": "number"}, "bookmark": {"type": "string"},
            "before": {"type": "number"}, "after": {"type": "number"},
            "video": {"type": "string"}, "start": {"type": "number"}, "end": {"type": "number"},
            "videos": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action"],
    },
)
async def capture(args: dict[str, Any]) -> dict[str, Any]:
    act = args.get("action")
    try:
        if act == "start":
            minutes = min(max(int(args.get("minutes") or 3), 1), MAX_MINUTES)
            return _text(await asyncio.to_thread(start, minutes))
        if act == "record":
            return _text(await asyncio.to_thread(start, 0))
        if act == "open":
            webbrowser.open(f"http://127.0.0.1:{config.PORT}/?captures=1")
            return _text("Opened the capture library in the browser.")
        if act == "stop":
            if _recording and running():
                rec = await finish_recording()
                return _text(f"Saved the recording ({rec.seconds} s) to the library.")
            return _text(await asyncio.to_thread(stop))
        if act == "status":
            marks = "; ".join(f"{m['id']} {m['label']} ({int(time.time() - m['at'])} s ago)" for m in _marks)
            return _text(("Recording. " if running() else "Not recording. ") + (f"Bookmarks: {marks}" if marks else "No bookmarks."))
        if act in ("bookmark", "clip") and not running():
            await asyncio.to_thread(start, config.CAPTURE_MINUTES)
            return _text("The capture was off, so there is nothing to clip yet: it has started now. Tell the user "
                         "it only keeps what happens from now on, and to ask again afterwards.", is_error=True)
        if act == "bookmark":
            m = {"id": f"b{len(_marks) + 1}", "at": time.time(), "label": str(args.get("label") or "moment")}
            _marks.append(m)
            return _text(f"Bookmarked as {m['id']} ({m['label']}).")
        if act == "clip":
            a, b = _clip_span(args)
            rec = await _new(str(args.get("label") or "Clip"), lambda out: cut_buffer(a, b, out))
            want = args.get("seconds") or 30
            short = "" if args.get("bookmark") or rec.seconds >= want - 1 else (
                f" That's all there was: it only had {rec.seconds} s of footage, not {want:g} s"
                " (the buffer is shorter than that or capture just started).")
            return _text(f"{rec.id}: a {rec.seconds} s clip is on the canvas.{short}")
        if act == "trim":
            src = video_store.folder(str(args.get("video"))) / video_store.FILE
            s, e = float(args.get("start") or 0), float(args["end"])
            if e <= s:
                return _text("end must be after start.", is_error=True)
            rec = await _new("Trim", lambda out: _concat([src], out, s, e - s))
            return _text(f"{rec.id}: trimmed to {rec.seconds} s, on the canvas.")
        if act == "merge":
            files = [video_store.folder(v) / video_store.FILE for v in args.get("videos") or []]
            if len(files) < 2:
                return _text("Give at least two video ids.", is_error=True)
            rec = await _new("Merged", lambda out: _concat(files, out))
            return _text(f"{rec.id}: merged {len(files)} clips ({rec.seconds} s), on the canvas.")
        return _text(f"Unknown action {act!r}.", is_error=True)
    except (KeyError, ValueError, RuntimeError, FileNotFoundError) as e:
        return _text(f"Couldn't do that: {e}", is_error=True)
