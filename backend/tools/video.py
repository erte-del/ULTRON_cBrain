"""generate_video: short AI videos made on this Mac with Wan through mlx-video.

Two models; the better one installed is used:
  Wan 2.2 TI2V 5B   text or a still image to video, 1280x704, 24 fps   scripts/setup_video.sh 5b
  Wan 2.1 T2V 1.3B  text to video only, 832x480, 16 fps (~13 min for 5 s on an M5)   scripts/setup_video.sh
Either way it's slow, so the tool starts the job in the background and returns right away: the
canvas card shows progress and then the video, and the chat stays free.
One video at a time (the model uses most of the Mac while it runs).
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config
import events
import hub
from PIL import Image

from storage import video_store

log = logging.getLogger("ultron.video")

@dataclass(frozen=True)
class Model:
    folder: str
    fps: int
    long_side: int
    short_side: int
    steps: dict[str, int]
    eta: str  # for a 5 s clip on fast, on an M5
    images: bool  # can start from a still image


# Best first. ponytail: the 5B time is an estimate from its size; measure it once it's set up.
MODELS = [
    Model("Wan2.2-TI2V-5B-MLX", 24, 1280, 704, {"fast": 20, "best": 40}, "about an hour", True),
    Model("Wan2.1-T2V-1.3B-MLX", 16, 832, 480, {"fast": 10, "best": 20}, "about 13 minutes", False),  # ~67 s/step
]
MAX_SECONDS = 5
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
TIMEOUT_S = 3 * 60 * 60
_PROGRESS = re.compile(rb"Diffusion:[^|]*\|[^|]*\|\s*(\d+)/(\d+)")

_job: asyncio.Task | None = None


def python() -> Path:
    return config.WAN_DIR / ".venv" / "bin" / "python"


def model() -> Model | None:
    """The best model that is set up, or None."""
    return next((m for m in MODELS if (config.WAN_DIR / m.folder / "config.json").exists()), None)


def frames_for(seconds: float, fps: int = 16) -> int:
    """Wan needs 4n+1 frames: 5 s -> 81 frames at 16 fps, 121 at 24."""
    seconds = min(max(seconds, 1.0), MAX_SECONDS)
    return 4 * max(1, round(seconds * fps / 4)) + 1


def size_for(m: Model, portrait: bool) -> tuple[int, int]:
    """(width, height). Portrait (9:16) suits Reels."""
    return (m.short_side, m.long_side) if portrait else (m.long_side, m.short_side)


def last_progress(output: bytes) -> tuple[int, int] | None:
    """The latest 'Diffusion: 40%|███ | 12/30' tqdm step in a chunk of output."""
    found = _PROGRESS.findall(output)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


async def _show(rec: video_store.VideoRecord) -> None:
    await asyncio.to_thread(video_store.save, rec)
    await hub.emit(events.canvas_card(rec.id, "video", rec.title, video_store.card_data(rec)))


async def _render(rec: video_store.VideoRecord, m: Model, frames: int, steps: int, image: str | None) -> None:
    out = video_store.folder(rec.id) / "rendering.mp4"
    proc = await asyncio.create_subprocess_exec(
        str(python()), "-m", "mlx_video.models.wan_2.generate",
        "--model-dir", str(config.WAN_DIR / m.folder), "--prompt", rec.prompt,
        "--width", str(rec.width), "--height", str(rec.height), "--num-frames", str(frames),
        "--steps", str(steps), "--output-path", str(out), *(["--image", image] if image else []),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    tail = b""
    try:
        async with asyncio.timeout(TIMEOUT_S):
            while chunk := await proc.stdout.read(4096):
                tail = (tail + chunk)[-4000:]
                step = last_progress(chunk)
                if step and step[0] / step[1] > rec.progress:
                    rec.progress = step[0] / step[1]
                    await _show(rec)
            await proc.wait()
        if proc.returncode != 0 or not out.exists():
            log.error("Video %s failed:\n%s", rec.id, tail.decode(errors="replace"))
            raise RuntimeError("the video model failed (details in the backend log)")
        out.rename(out.with_name(video_store.FILE))
        rec.status, rec.progress = "done", 1.0
        await _show(rec)
        await hub.emit(events.notice(f"Your video “{rec.title}” is ready on the canvas."))
    except (Exception, asyncio.CancelledError) as e:
        if proc.returncode is None:
            proc.kill()
        rec.status = "failed"
        rec.error = "It took too long." if isinstance(e, TimeoutError) else f"Couldn't make it: {e}"
        log.exception("Video %s failed", rec.id)
        await _show(rec)
        if isinstance(e, asyncio.CancelledError):
            raise


@tool(
    "generate_video",
    "Make a short AI video (1–5 seconds, no sound) on this Mac with the Wan model, from a text "
    "description or by animating a still image (image: a file path; needs the Wan 2.2 model). "
    "Portrait 9:16 by default, for Reels; with an image, the image's own shape. It is slow (the "
    "result says how long; shorter clips are quicker). This starts it and returns right away; the "
    "canvas shows progress and then the video. One video at a time. The user confirms first. "
    "Write the prompt in English, as one detailed shot: subject, action, setting, camera "
    "(e.g. slow dolly-in, close-up), lighting and style; with an image, describe the motion. "
    "Simple scenes with one clear subject and motion work best; readable text, hands and crowds "
    "come out poorly.",
    {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed English description of the shot."},
            "title": {"type": "string", "description": "Short name, e.g. 'Cat on a piano'."},
            "seconds": {"type": "number", "description": f"Length, 1–{MAX_SECONDS} (default 5)."},
            "image": {"type": "string", "description": "Optional: path of a still (.jpg/.png/.webp) to animate."},
            "shape": {"type": "string", "enum": ["portrait", "landscape"],
                      "description": "Text-only videos: portrait 9:16 (default) or landscape."},
            "quality": {
                "type": "string",
                "enum": ["fast", "best"],
                "description": "fast (default) or best (about twice as long, more detail).",
            },
        },
        "required": ["prompt"],
    },
)
async def generate_video(args: dict[str, Any]) -> dict[str, Any]:
    global _job
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return _text("Not started: the prompt is empty.", is_error=True)
    m = model()
    if not python().exists() or not m:
        return _text("Video generation isn't set up on this Mac yet. The user needs to run "
                     "scripts/setup_video.sh 5b once (it downloads about 34 GB).", is_error=True)
    if _job and not _job.done():
        return _text("Another video is still being made; wait until it's finished.", is_error=True)

    image, portrait = None, args.get("shape") != "landscape"
    if args.get("image"):
        if not m.images:
            return _text("Animating an image needs the Wan 2.2 model: the user runs "
                         "scripts/setup_video.sh 5b once (about 34 GB). Not started.", is_error=True)
        path = Path(str(args["image"])).expanduser()
        if path.suffix.lower() not in IMAGE_TYPES or not path.is_file():
            return _text(f"No .jpg, .png or .webp image at {path}. Not started.", is_error=True)
        try:
            with Image.open(path) as im:
                w, h = im.size
        except OSError:
            return _text(f"Couldn't read the image {path}. Not started.", is_error=True)
        image, portrait = str(path), h > w

    width, height = size_for(m, portrait)
    frames = frames_for(float(args.get("seconds") or MAX_SECONDS), m.fps)
    steps = m.steps.get(str(args.get("quality") or "fast"), m.steps["fast"])
    title = str(args.get("title") or prompt[:40])
    rec = await asyncio.to_thread(video_store.create, title, prompt, round(frames / m.fps, 1), width, height)
    await _show(rec)
    # ponytail: the job lives in this process; a backend restart mid-render leaves the card "rendering"
    _job = asyncio.create_task(_render(rec, m, frames, steps, image))
    log.info("Video %s started with %s: %s frames, %s steps", rec.id, m.folder, frames, steps)
    return _text(f"{rec.id} has started ({rec.seconds} s, {width}x{height}, {steps} steps). A 5 s clip takes "
                 f"{m.eta} on fast; the canvas shows progress and plays the video when it's done. "
                 "Tell the user briefly; don't wait for it.")
