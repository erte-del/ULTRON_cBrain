"""reel: cut, join, caption and export videos for Instagram Reels, on top of FFmpeg.

Every command writes a Reel-ready file: 1080x1920 (9:16), 30 fps, H.264 + AAC, faststart.
Clips of any shape are scaled to fit and padded with black; clips with no sound get silence,
so anything can be joined with anything.

    python reel.py cut     in.mp4 out.mp4 --start 2 --end 9.5
    python reel.py join    out.mp4 a.mp4 b.mp4 c.mp4
    python reel.py caption in.mp4 out.mp4 --text "Hello" [--at top|middle|bottom] [--start 0 --end 3]
    python reel.py export  in.mp4 out.mp4
    python reel.py check   out.mp4
"""

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

W, H, FPS = 1080, 1920, 30
MIN_S, MAX_S = 3, 15 * 60  # what the Graph API accepts for a Reel
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_SIZE = 72
WRAP = 22  # characters per caption line at FONT_SIZE on a 1080 px frame
ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
FIT = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
       f"setsar=1,fps={FPS},format=yuv420p")


def probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    return {
        "seconds": float(info["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "video": next((s for s in info["streams"] if s["codec_type"] == "video"), None),
    }


def ffmpeg(*args: str) -> None:
    run = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                         capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr.strip() or "ffmpeg failed")


def join(out: str, clips: list[str]) -> None:
    """Fit each clip to the Reel frame (silence where there is no sound) and play them in order."""
    inputs, parts = [], []
    for i, clip in enumerate(clips):
        inputs += ["-i", clip]
        info = probe(clip)
        parts.append(f"[{i}:v]{FIT}[v{i}]")
        audio = f"[{i}:a]" if info["has_audio"] else f"anullsrc=r=48000:cl=stereo,atrim=0:{info['seconds']},"
        parts.append(f"{audio}aresample=48000,aformat=channel_layouts=stereo[a{i}]")
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
    parts.append(f"{pairs}concat=n={len(clips)}:v=1:a=1[v][a]")
    ffmpeg(*inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", *ENCODE, out)


def export(src: str, out: str) -> None:
    join(out, [src])


def cut(src: str, out: str, start: float, end: float) -> None:
    if end <= start:
        raise ValueError("--end must be after --start")
    with tempfile.TemporaryDirectory() as tmp:
        part = str(Path(tmp) / "part.mp4")
        # -ss before -i seeks fast; re-encoding (in join) keeps the cut frame-accurate.
        ffmpeg("-ss", str(start), "-to", str(end), "-i", src, "-c:v", "libx264", "-crf", "16",
               "-c:a", "aac", part)
        join(out, [part])


def caption(src: str, out: str, text: str, at: str = "bottom",
            start: float | None = None, end: float | None = None) -> None:
    y = {"top": "h*0.12", "middle": "(h-text_h)/2", "bottom": "h*0.78-text_h"}[at]
    with tempfile.TemporaryDirectory() as tmp:
        # textfile= avoids FFmpeg's escaping rules for quotes, colons and commas in the caption.
        txt = Path(tmp) / "caption.txt"
        txt.write_text(textwrap.fill(text, WRAP))
        draw = (f"drawtext=fontfile='{FONT}':textfile='{txt}':fontsize={FONT_SIZE}:fontcolor=white:"
                f"borderw=5:bordercolor=black:line_spacing=12:text_align=C:x=(w-text_w)/2:y={y}")
        if start is not None or end is not None:
            draw += f":enable='between(t,{start or 0},{end if end is not None else 1e9})'"
        fitted = str(Path(tmp) / "fitted.mp4")
        export(src, fitted)
        ffmpeg("-i", fitted, "-vf", draw, *ENCODE, out)


def check(path: str) -> list[str]:
    """What would stop the Graph API from taking this file as a Reel. Empty list = fine."""
    info = probe(path)
    v = info["video"]
    problems = []
    if not v:
        return ["no video stream"]
    if (v["width"], v["height"]) != (W, H):
        problems.append(f"size is {v['width']}x{v['height']}, want {W}x{H}")
    if v["codec_name"] != "h264":
        problems.append(f"video codec is {v['codec_name']}, want h264")
    if not MIN_S <= info["seconds"] <= MAX_S:
        problems.append(f"length is {info['seconds']:.1f} s, must be {MIN_S} s to {MAX_S // 60} min")
    if not info["has_audio"]:
        problems.append("no audio track")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reel", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut")
    c.add_argument("src"); c.add_argument("out")
    c.add_argument("--start", type=float, required=True); c.add_argument("--end", type=float, required=True)
    j = sub.add_parser("join")
    j.add_argument("out"); j.add_argument("clips", nargs="+")
    t = sub.add_parser("caption")
    t.add_argument("src"); t.add_argument("out"); t.add_argument("--text", required=True)
    t.add_argument("--at", choices=["top", "middle", "bottom"], default="bottom")
    t.add_argument("--start", type=float); t.add_argument("--end", type=float)
    e = sub.add_parser("export")
    e.add_argument("src"); e.add_argument("out")
    k = sub.add_parser("check")
    k.add_argument("src")
    a = p.parse_args(argv)

    try:
        if a.cmd == "cut":
            cut(a.src, a.out, a.start, a.end)
        elif a.cmd == "join":
            join(a.out, a.clips)
        elif a.cmd == "caption":
            caption(a.src, a.out, a.text, a.at, a.start, a.end)
        elif a.cmd == "export":
            export(a.src, a.out)
        problems = check(a.out if a.cmd != "check" else a.src)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print("\n".join(problems) if problems else "ready for Instagram")
    return 1 if problems and a.cmd == "check" else 0


if __name__ == "__main__":
    sys.exit(main())
