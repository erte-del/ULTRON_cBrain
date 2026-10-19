"""Download one Instagram reel, pull out what is in it, print JSON. Run from backend/:

    .venv/bin/python ../.claude/skills/saved-reels/reel_digest.py <reel-url> <work-dir> [browser]

Prints: caption, creator, length, spoken words (Whisper), and paths of 6 frames in <work-dir>.
Nothing else is kept; the skill deletes <work-dir> afterwards. Uses ~/.ultron/instagram-cookies.txt (or JARVIS_IG_COOKIES) if it exists, else the cookies
of the browser (default chrome). Read on this computer only, never printed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

FRAMES = 6
# Cookie file exported from the browser (Netscape cookies.txt). Kept OUTSIDE the project, never committed.
COOKIES = Path(os.getenv("JARVIS_IG_COOKIES") or Path.home() / ".ultron" / "instagram-cookies.txt")


def main(url: str, work: Path, browser: str) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        [sys.executable, "-c", "import sys, truststore; truststore.inject_into_ssl(); import yt_dlp; "
         "sys.argv[0] = 'yt-dlp'; yt_dlp.main()",
         "-q", "--no-warnings", "--no-playlist", *(["--cookies", str(COOKIES)] if COOKIES.is_file() else ["--cookies-from-browser", browser]),
         "-f", "bv*[height<=480]+ba/b[height<=480]/b", "--merge-output-format", "mp4",
         "--max-filesize", "80M", "--write-info-json", "-o", str(work / "reel.%(ext)s"), url],
        capture_output=True, text=True, timeout=180)
    video = work / "reel.mp4"
    if run.returncode or not video.exists():
        return {"url": url, "error": (run.stderr.strip().splitlines() or ["download failed"])[-1]}
    info = json.loads((work / "reel.info.json").read_text(encoding="utf-8"))
    import reel  # noqa: E402  (Ultron's own FFmpeg helpers)
    from tools import reels  # noqa: E402  (its Whisper helper)
    seconds = float(info.get("duration") or 0) or reel.probe(str(video))["seconds"]
    frames = []
    for i in range(FRAMES):
        jpg = work / f"frame{i}.jpg"
        reel.ffmpeg("-ss", f"{seconds * (i + 0.5) / FRAMES:.2f}", "-i", str(video), "-frames:v", "1",
                    "-vf", "scale=-2:640", "-q:v", "4", str(jpg))
        frames.append(str(jpg))
    try:
        words = reels.transcribe(str(video), work, "en")
        said = " ".join(w["word"].strip() for w in words)
    except (ValueError, RuntimeError, OSError) as e:
        said = f"(no transcript: {e})"
    return {"url": url, "creator": info.get("uploader") or info.get("channel"), "title": info.get("title"),
            "caption": (info.get("description") or "")[:2000], "seconds": round(seconds),
            "uploaded": info.get("upload_date"), "said": said or "(nothing said)", "frames": frames}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(json.dumps(main(sys.argv[1], Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "chrome"),
                     ensure_ascii=False, indent=1))
