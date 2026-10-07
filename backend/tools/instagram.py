"""Instagram: Ultron posts Reels to its own account (ai.ultron.120) through the Graph API.

Two steps, so you always see the video before it goes out:
  instagram_preview (read)  checks the file is a valid Reel and puts it on the canvas with
                            its caption
  instagram_post    (act)   asks you on a card first (ASK_TOOLS), then posts. It only posts a
                            file that was previewed, unchanged, with the same caption

With Instagram Login, Meta only takes a video from a public URL (no direct upload), so the
file goes to Litterbox (litterbox.catbox.moe), a free host that deletes it after an hour.

The access token lasts 60 days. Ultron renews it once a week (refresh_loop, started in
main.py) and keeps the newest one in storage/instagram_token.json; .env holds the first one.
"""

import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config
import events
import hub
import reel
from storage import video_store

log = logging.getLogger("ultron.instagram")

GRAPH = "https://graph.instagram.com/v25.0"
TOKEN_FILE = config.STORAGE_DIR / "instagram_token.json"
REFRESH_EVERY_S = 7 * 24 * 3600  # Meta allows a refresh once the token is a day old
LITTERBOX = "https://litterbox.catbox.moe/resources/internals/api.php"
UPLOAD_TIMEOUT_S = 600
POLL_EVERY_S = 5
# ponytail: waits in the tool call while Meta processes the video (usually under a minute);
# move to a background job like generate_video if long Reels time out.
PROCESS_TIMEOUT_S = 300

# sha256 of each previewed file -> the caption you saw with it. In memory: after a restart,
# preview again.
_previewed: dict[str, str] = {}


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


# --- token ---

def _load() -> dict[str, Any]:
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(token: str) -> None:
    TOKEN_FILE.touch(mode=0o600)
    TOKEN_FILE.write_text(json.dumps({"access_token": token, "refreshed_at": time.time()}))


def token() -> str:
    return _load().get("access_token") or config.INSTAGRAM_ACCESS_TOKEN


def refresh_if_due() -> bool:
    """Swap the token for a fresh 60-day one if the last swap was over a week ago."""
    tok = token()
    if not tok or time.time() - _load().get("refreshed_at", 0) < REFRESH_EVERY_S:
        return False
    url = f"https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token={tok}"
    with urllib.request.urlopen(url, timeout=20, context=config.ssl_context()) as r:
        _save(json.load(r)["access_token"])
    log.info("Instagram token renewed")
    return True


async def refresh_loop() -> None:
    """Started by main.py: check once at start and then daily, so the token never lapses."""
    while True:
        try:
            await asyncio.to_thread(refresh_if_due)
        except (OSError, ValueError, KeyError) as e:  # e.g. the token is under a day old
            log.warning("Instagram token not renewed: %s", e)
        await asyncio.sleep(24 * 3600)


# --- Graph API ---

def _graph(method: str, path: str, **params: Any) -> dict[str, Any]:
    data = urllib.parse.urlencode(params).encode() if method == "POST" else None
    url = f"{GRAPH}/{path}" + ("" if data else "?" + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=config.ssl_context()) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message") or str(e)
        except ValueError:
            msg = str(e)
        raise RuntimeError(f"Instagram: {msg}") from None


def upload(path: Path) -> str:
    """Put the file on Litterbox for an hour; returns its public URL."""
    run = subprocess.run(["curl", "-sS", "--fail", "-F", "reqtype=fileupload", "-F", "time=1h",
                          "-F", f"fileToUpload=@{path}", LITTERBOX],
                         capture_output=True, text=True, timeout=UPLOAD_TIMEOUT_S)
    url = run.stdout.strip()
    if run.returncode or not url.startswith("https://"):
        raise RuntimeError(f"Upload failed: {run.stderr.strip() or url or 'no answer'}")
    return url


def publish(path: Path, caption: str) -> str:
    """Upload, let Meta fetch and process the video, publish. Returns the post's link."""
    me = _graph("GET", "me", fields="user_id")["user_id"]
    container = _graph("POST", f"{me}/media", media_type="REELS", video_url=upload(path),
                       caption=caption)["id"]
    deadline = time.monotonic() + PROCESS_TIMEOUT_S
    while (status := _graph("GET", container, fields="status_code,status")).get("status_code") != "FINISHED":
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram couldn't process the video: {status.get('status') or status['status_code']}")
        if time.monotonic() > deadline:
            raise RuntimeError("Instagram is still processing the video; it was not posted.")
        time.sleep(POLL_EVERY_S)
    media = _graph("POST", f"{me}/media_publish", creation_id=container)["id"]
    return _graph("GET", media, fields="permalink").get("permalink", "")


# --- tools ---

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _video(args: dict[str, Any]) -> Path:
    path = Path(str(args.get("video") or "")).expanduser()
    if path.suffix.lower() != ".mp4" or not path.is_file():
        raise ValueError(f"No .mp4 file at {path}")
    return path


VIDEO_ARG = {"type": "string", "description": "Full path of the .mp4, made with reel.py."}
CAPTION_ARG = {"type": "string", "description": "The post's caption, hashtags included."}


@tool(
    "instagram_preview",
    "Show a Reel you made (with reel.py) on the canvas, with its caption, before posting it to "
    "Ultron's Instagram. Checks it meets Instagram's rules. Required before instagram_post, "
    "with the same file and caption.",
    {"type": "object", "properties": {"video": VIDEO_ARG, "caption": CAPTION_ARG},
     "required": ["video", "caption"]},
)
async def instagram_preview(args: dict[str, Any]) -> dict[str, Any]:
    try:
        path = _video(args)
        problems = await asyncio.to_thread(reel.check, str(path))
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as e:
        return _text(str(e), True)
    if problems:
        return _text("Not a valid Reel yet: " + "; ".join(problems) + ". Fix it with reel.py export.", True)
    caption = str(args.get("caption") or "").strip()
    info = await asyncio.to_thread(reel.probe, str(path))
    rec = await asyncio.to_thread(video_store.create, "Instagram draft", caption, info["seconds"], reel.W, reel.H)
    await asyncio.to_thread(shutil.copyfile, path, video_store.folder(rec.id) / video_store.FILE)
    rec.status, rec.progress = "done", 1.0
    await asyncio.to_thread(video_store.save, rec)
    await hub.emit(events.canvas_card(rec.id, "video", rec.title, video_store.card_data(rec)))
    _previewed[await asyncio.to_thread(_sha256, path)] = caption
    return _text(f"On the canvas ({info['seconds']:.1f} s). Ask the user if they want it posted, "
                 "then call instagram_post with the same file and caption.")


@tool(
    "instagram_post",
    "Post a Reel to Ultron's own Instagram (ai.ultron.120). The user approves on a card first. "
    "Only works for a file shown with instagram_preview, unchanged, with the same caption. "
    "Takes a minute or two while Instagram processes the video.",
    {"type": "object", "properties": {"video": VIDEO_ARG, "caption": CAPTION_ARG},
     "required": ["video", "caption"]},
)
async def instagram_post(args: dict[str, Any]) -> dict[str, Any]:
    if not token():
        return _text("No Instagram token: add INSTAGRAM_ACCESS_TOKEN to .env.", True)
    try:
        path = _video(args)
    except ValueError as e:
        return _text(str(e), True)
    caption = str(args.get("caption") or "").strip()
    if _previewed.get(await asyncio.to_thread(_sha256, path)) != caption:
        return _text("This file and caption weren't previewed as they are now. Call instagram_preview "
                     "first so the user sees exactly what goes out; nothing was posted.", True)
    try:
        link = await asyncio.to_thread(publish, path, caption)
    except (RuntimeError, OSError, KeyError, subprocess.TimeoutExpired) as e:
        return _text(f"Not posted: {e}", True)
    _previewed.pop(await asyncio.to_thread(_sha256, path), None)  # one approval, one post
    log.info("Posted to Instagram: %s", link)
    return _text(f"Posted to Instagram: {link}")
