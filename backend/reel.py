"""reel: cut, join, caption and export videos for Instagram Reels, on top of FFmpeg.

Every command writes a Reel-ready file: 1080x1920 (9:16), 30 fps, H.264 + AAC, faststart.
Clips of any shape are scaled to fit and padded with black; clips with no sound get silence,
so anything can be joined with anything.

    python reel.py cut     in.mp4 out.mp4 --start 2 --end 9.5
    python reel.py join    out.mp4 a.mp4 b.mp4 c.mp4
    python reel.py caption in.mp4 out.mp4 --text "Hello" [--at top|middle|bottom] [--start 0 --end 3]
    python reel.py music   in.mp4 out.mp4 --track song.mp3 [--volume 0.25] [--replace]
    python reel.py voice   in.mp4 out.mp4 --speech line.wav [--at 1.5] [--volume 1]
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
AUDIO = ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", *AUDIO]
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


def music(src: str, out: str, track: str, volume: float = 0.25, replace: bool = False) -> None:
    """Lay a track under the video: looped or trimmed to the video's length, faded in and out.
    By default the clip's own sound stays on top; replace=True drops it."""
    with tempfile.TemporaryDirectory() as tmp:
        fitted = str(Path(tmp) / "fitted.mp4")
        export(src, fitted)
        seconds = probe(fitted)["seconds"]
        fade_out = max(seconds - 2, 0)
        bed = (f"[1:a]atrim=0:{seconds},asetpts=PTS-STARTPTS,volume={volume},"
               f"afade=t=in:d=1,afade=t=out:st={fade_out}:d=2,aresample=48000,aformat=channel_layouts=stereo")
        mix = f"{bed}[a]" if replace else f"{bed}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        ffmpeg("-i", fitted, "-stream_loop", "-1", "-i", track, "-filter_complex", mix,
               "-map", "0:v", "-map", "[a]", "-c:v", "copy", *AUDIO, "-t", str(seconds), out)


STEREO = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
# Ducking: whenever the voice is louder than THRESHOLD, everything under it is pushed down by
# up to RATIO. ponytail: fixed settings tuned on test tones; tune by ear once Ultron has a real voice.
DUCK = "sidechaincompress=threshold=0.02:ratio=10:attack=10:release=350"


def voice(src: str, out: str, speech: str, at: float = 0.0, volume: float = 1.0) -> None:
    """Lay a voiceover on the video starting at `at` seconds, ducking the sound under it.
    If the voice runs past the end, the last frame is held until it finishes."""
    with tempfile.TemporaryDirectory() as tmp:
        fitted = str(Path(tmp) / "fitted.mp4")
        export(src, fitted)
        video_s = probe(fitted)["seconds"]
        total = max(video_s, at + probe(speech)["seconds"])
        graph = ";".join([
            f"[0:v]tpad=stop_mode=clone:stop_duration={total - video_s}[v]",
            f"[1:a]{STEREO},volume={volume},adelay={int(at * 1000)}:all=1,apad,asplit=2[sc][vo]",
            f"[0:a]{STEREO},apad[bed]",
            f"[bed][sc]{DUCK}[ducked]",
            f"[ducked][vo]amix=inputs=2:duration=first:normalize=0[a]",
        ])
        ffmpeg("-i", fitted, "-i", speech, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
               *ENCODE, "-t", str(total), out)


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
    m = sub.add_parser("music")
    m.add_argument("src"); m.add_argument("out"); m.add_argument("--track", required=True)
    m.add_argument("--volume", type=float, default=0.25)
    m.add_argument("--replace", action="store_true", help="drop the clip's own sound")
    v = sub.add_parser("voice")
    v.add_argument("src"); v.add_argument("out"); v.add_argument("--speech", required=True)
    v.add_argument("--at", type=float, default=0.0); v.add_argument("--volume", type=float, default=1.0)
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
        elif a.cmd == "music":
            music(a.src, a.out, a.track, a.volume, a.replace)
        elif a.cmd == "voice":
            voice(a.src, a.out, a.speech, a.at, a.volume)
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
