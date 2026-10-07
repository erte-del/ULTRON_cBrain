"""reel_edit: Ultron edits its Instagram Reels with reel.py (FFmpeg).

Reads clips, music and voice files from anywhere on this Mac, and only ever writes into
Ultron's own folder: JARVIS_FILES_DIR/Instagram. Every result is a Reel-ready .mp4.
A voice line can come from a file or from text, spoken with macOS `say` for now.
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config
import reel

OPS = ["cut", "join", "caption", "music", "voice", "export"]
SAY_TIMEOUT_S = 60


def out_dir() -> Path:
    folder = config.FILES_DIR / "Instagram"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _file(path: Any, what: str) -> str:
    p = Path(str(path or "")).expanduser()
    if not p.is_file():
        raise ValueError(f"No {what} file at {p}")
    return str(p)


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


def edit(args: dict[str, Any]) -> Path:
    op = args.get("op")
    if op not in OPS:
        raise ValueError(f"op must be one of {', '.join(OPS)}")
    inputs = [_file(p, "video") for p in args.get("inputs") or []]
    if not inputs:
        raise ValueError("Give at least one input video")
    name = Path(str(args.get("output") or "reel")).stem or "reel"  # a name only: never leaves the folder
    out = str(out_dir() / f"{name}.mp4")
    src = inputs[0]
    if op == "cut":
        reel.cut(src, out, float(args["start"]), float(args["end"]))
    elif op == "join":
        reel.join(out, inputs)
    elif op == "caption":
        if not str(args.get("text") or "").strip():
            raise ValueError("caption needs text")
        reel.caption(src, out, args["text"], args.get("position") or "bottom", args.get("start"), args.get("end"))
    elif op == "music":
        reel.music(src, out, _file(args.get("track"), "music"), float(args.get("volume", 0.25)),
                   bool(args.get("replace")))
    elif op == "voice":
        with tempfile.TemporaryDirectory() as tmp:
            if args.get("say"):
                speech = str(Path(tmp) / "line.aiff")
                subprocess.run(["say", "-o", speech, "--", str(args["say"])], check=True, timeout=SAY_TIMEOUT_S)
            else:
                speech = _file(args.get("speech"), "voice")
            reel.voice(src, out, speech, float(args.get("at", 0)), float(args.get("volume", 1.0)))
    else:
        reel.export(src, out)
    return Path(out)


@tool(
    "reel_edit",
    "Edit a video for Ultron's Instagram. Each call makes one Reel-ready .mp4 (1080x1920, 9:16) in "
    "Ultron's Instagram folder and returns its path; chain calls to build a Reel step by step "
    "(e.g. join clips, then music, then voice, then caption). Ops: cut (inputs[0], start, end), "
    "join (all inputs in order), caption (text, position, optional start/end), music (track, "
    "volume, replace), voice (say: text to speak, or speech: an audio file; at: start second; "
    "music under it is lowered automatically), export (any video -> Reel format).",
    {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": OPS},
            "inputs": {"type": "array", "items": {"type": "string"}, "description": "Video file paths."},
            "output": {"type": "string", "description": "Name for the result, e.g. 'octopus_v2'."},
            "start": {"type": "number", "description": "Seconds: cut start, or when a caption appears."},
            "end": {"type": "number", "description": "Seconds: cut end, or when a caption disappears."},
            "text": {"type": "string", "description": "Caption text on the video."},
            "position": {"type": "string", "enum": ["top", "middle", "bottom"]},
            "track": {"type": "string", "description": "Music file path, licensed for reuse."},
            "volume": {"type": "number", "description": "Music (default 0.25) or voice (default 1) volume."},
            "replace": {"type": "boolean", "description": "Music only: drop the clip's own sound."},
            "say": {"type": "string", "description": "Voice: the words to speak."},
            "speech": {"type": "string", "description": "Voice: an audio file instead of say."},
            "at": {"type": "number", "description": "Voice: second the line starts."},
        },
        "required": ["op", "inputs", "output"],
    },
)
async def reel_edit(args: dict[str, Any]) -> dict[str, Any]:
    try:
        out = await asyncio.to_thread(edit, args)
        problems = await asyncio.to_thread(reel.check, str(out))
        seconds = (await asyncio.to_thread(reel.probe, str(out)))["seconds"]
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as e:
        return _text(f"reel_edit failed: {e}", True)
    note = "ready for Instagram" if not problems else "not postable yet: " + "; ".join(problems)
    return _text(f"Saved {out} ({seconds:.1f} s), {note}.")
