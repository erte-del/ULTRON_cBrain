"""The user's Windows PC, over Tailscale: windows/ultron_pc.py runs there.

  pc_read   (read) battery / volume / dark mode / Wi-Fi, the clipboard, files in its Ultron folder
            and the PC's Desktop, Documents and Downloads, and what's inside them (read here, on the Mac)
  pc_change (act)  the same changes as mac_change (no Shortcuts), plus media keys and a terminal.
            A move or trash outside the PC's Ultron folder asks first (registry.needs_ok).
  pc_run    (act)  Python or PowerShell on the PC. Not sandboxed, so it always asks first.

Off when JARVIS_PC_URL / JARVIS_PC_TOKEN aren't set; says so when the PC is asleep or off.
"""

import asyncio
import base64
import json
import posixpath
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from claude_agent_sdk import tool
from pypdf.errors import PdfReadError

import config

from .homework import _text
from .uploads import IMAGES, READABLE, jpeg_of, text_of

TIMEOUT_S = 75  # the PC stops a run after 60 s
ACTIONS = ["open_app", "open_url", "open_file", "open_terminal", "copy", "volume", "mute", "dark_mode", "media", "move", "trash"]


def _post(path: str, args: dict[str, Any]) -> dict[str, Any]:
    req = Request(config.PC_URL + path, data=json.dumps(args).encode(),
                  headers={"Authorization": f"Bearer {config.PC_TOKEN}", "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=TIMEOUT_S, context=config.ssl_context()) as r:
            return json.load(r)
    except HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"text": f"The PC answered {e.code}.", "is_error": True}


async def _ask(path: str, args: dict[str, Any]) -> dict[str, Any]:
    """The PC's answer {"text", "is_error", ...}. RuntimeError if it isn't set up or reachable."""
    if not (config.PC_URL and config.PC_TOKEN):
        raise RuntimeError("The PC isn't set up: JARVIS_PC_URL and JARVIS_PC_TOKEN in .env (see windows/ultron_pc.py).")
    try:
        return await asyncio.to_thread(_post, path, args)
    except (URLError, OSError, ValueError):
        raise RuntimeError("The PC isn't reachable: it's off or asleep, Tailscale is down there, or "
                           "ultron_pc.py isn't running.") from None


async def _call(path: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        found = await _ask(path, args)
    except RuntimeError as e:
        return _text(str(e), True)
    return _text(str(found.get("text", "")), bool(found.get("is_error")))


async def pc_name() -> str:
    """The PC's computer name (what Spotify calls it). RuntimeError if the PC can't say."""
    found = await _ask("/read", {"what": "name"})
    if found.get("is_error") or not found.get("text"):
        raise RuntimeError(f"The PC didn't give its name: {found.get('text')}")
    return str(found["text"])


def leaves_folder(args: dict[str, Any]) -> bool:
    """A pc_change move or trash with a path outside the PC's Ultron folder ('~/...', a full path or
    '..'): it asks first. The PC refuses those unless outside_ok, which only pc_change sets."""
    if args.get("action") not in ("move", "trash"):
        return False
    for key in ("path", "to"):
        p = str(args.get(key) or "").strip().replace("\\", "/")
        if p.startswith(("~", "/")) or re.match(r"[A-Za-z]:", p) or posixpath.normpath(p or ".").startswith(".."):
            return True
    return False


def opens_link(args: dict[str, Any]) -> bool:
    """A pc_change open_url that isn't a plain web address (ms-settings:): it asks first."""
    url = str(args.get("url") or "").strip().lower()
    return args.get("action") == "open_url" and not url.startswith(("http://", "https://"))


# One Start-Process line that opens an app by bare name (no path, dot, dash or arguments, so it
# can't pass flags or run a file it just wrote).
_LAUNCH_LINE = re.compile(r"""start-process\s+(?:-filepath\s+)?(["']?)(\w[\w ]*)\1""", re.IGNORECASE)


def only_launches(args: dict[str, Any]) -> bool:
    """A pc_run whose PowerShell is nothing but Start-Process lines opening apps: no card."""
    if args.get("lang") != "powershell":
        return False
    lines = [ln.strip() for ln in str(args.get("code") or "").splitlines() if ln.strip()]
    return bool(lines) and all(_LAUNCH_LINE.fullmatch(ln) for ln in lines)


@tool(
    "pc_read",
    "Read things on the user's Windows PC. what: 'status' (battery, volume, dark mode, Wi-Fi), "
    "'clipboard' (the PC's copied text), 'files' (files whose name or folder has every word of query, "
    "newest first, in the PC's Ultron folder and its Desktop, Documents and Downloads; folder narrows it "
    "to one; an empty query lists all of the Ultron folder but only the top level of the others), or "
    f"'content' (what's inside the file at path: {READABLE}; images come back as a picture). Paths come "
    "back ready for pc_change: plain for the Ultron folder, '~/...' for the others.",
    {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["status", "clipboard", "files", "content"]},
            "query": {"type": "string", "description": "For files: words in the name or folder."},
            "folder": {"type": "string", "enum": ["all", "ultron", "Desktop", "Documents", "Downloads"],
                       "description": "For files: where to look (default all)."},
            "path": {"type": "string", "description": "For content: a path pc_read what=files gave."},
        },
        "required": ["what"],
    },
)
async def pc_read(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("what") != "content":
        return await _call("/read", args)
    try:
        found = await _ask("/read", args)
        if "data" not in found:
            return _text(str(found.get("text", "")), True)
        shown = str(found["text"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, Path(shown.replace("\\", "/")).name or "file")  # keeps the suffix text_of goes by
            p.write_bytes(base64.b64decode(found["data"]))
            if p.suffix.lower() in IMAGES and (jpeg := await asyncio.to_thread(jpeg_of, p)):
                return {"content": [{"type": "text", "text": f"{shown} (on the PC):"},
                                    {"type": "image", "data": base64.b64encode(jpeg).decode(), "mimeType": "image/jpeg"}]}
            return _text(f"{shown} (on the PC):\n\n{await asyncio.to_thread(text_of, p)}")
    except (RuntimeError, OSError, ValueError, PdfReadError) as e:
        return _text(f"pc_read: {e}", True)


@tool(
    "pc_change",
    "Do something on the user's Windows PC. action: 'open_app' (name: any app or game, e.g. 'chrome' or "
    "'rocket league': the Start menu name or part of it, else a Start Menu or Desktop shortcut's name, which "
    "covers installed Steam/Epic/Riot games; nicknames like 'rl' work via nicknames.json in the PC's Ultron "
    "folder), 'open_url' (http or https; also ms-settings: links, which ask the user first), 'open_file' (path: a document or a .lnk/.url shortcut; a folder opens in Explorer), "
    "'open_terminal' (a terminal window on the PC's screen, for the user to type in), "
    "'copy' (text to the PC's clipboard), 'volume' (level 0-100), 'mute' (on), 'dark_mode' (on), "
    "'media' (name: play_pause, next or previous, for whatever is playing, e.g. Spotify), 'move' "
    "(path → to, also renames; into a folder if 'to' is one), 'trash' (path, to the Recycle Bin). Paths are "
    "relative to the PC's Ultron folder, or '~/...' as pc_read gave them for its Desktop, Documents and "
    "Downloads; nothing else is reachable and nothing is overwritten. Moving or trashing outside the "
    "Ultron folder asks the user first.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTIONS},
            "name": {"type": "string", "description": "App or game name, or the media key."},
            "url": {"type": "string"},
            "path": {"type": "string"},
            "to": {"type": "string", "description": "For move: the new path or folder."},
            "text": {"type": "string"},
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
            "on": {"type": "boolean"},
        },
        "required": ["action"],
    },
)
async def pc_change(args: dict[str, Any]) -> dict[str, Any]:
    # needs_ok asked the user exactly when this is True, so the PC may go outside its Ultron folder.
    return await _call("/change", {**args, "outside_ok": leaves_folder(args)})


@tool(
    "pc_run",
    "Run code on the user's Windows PC. lang 'python' (whatever the PC's Python has installed) or "
    "'powershell'. It runs as the user, NOT sandboxed, in the Output subfolder of the PC's Ultron folder "
    "(its files are ../name), and is stopped after 60 seconds. Print the results. The user approves "
    "every run. For data work that doesn't need the PC, use run_python on the Mac instead. "
    "Never use it to open an app, game, file or link: pc_change does those without asking (open_app "
    "for apps and games; it's fine if one is already running). Never use Steam ids or launcher links.",
    {
        "type": "object",
        "properties": {"code": {"type": "string"}, "lang": {"type": "string", "enum": ["python", "powershell"]}},
        "required": ["code"],
    },
)
async def pc_run(args: dict[str, Any]) -> dict[str, Any]:
    return await _call("/run", args)
