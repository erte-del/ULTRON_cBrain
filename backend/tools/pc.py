"""The user's Windows PC, over Tailscale: windows/ultron_pc.py runs there.

  pc_read   (read) battery / volume / dark mode / Wi-Fi, the clipboard, files in its Ultron folder
  pc_change (act)  the same changes as mac_change (no Shortcuts), plus media keys and a terminal
  pc_run    (act)  Python or PowerShell on the PC. Not sandboxed, so it always asks first.

Off when JARVIS_PC_URL / JARVIS_PC_TOKEN aren't set; says so when the PC is asleep or off.
"""

import asyncio
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from claude_agent_sdk import tool

import config

from .homework import _text

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


async def _call(path: str, args: dict[str, Any]) -> dict[str, Any]:
    if not (config.PC_URL and config.PC_TOKEN):
        return _text("The PC isn't set up: JARVIS_PC_URL and JARVIS_PC_TOKEN in .env (see windows/ultron_pc.py).", True)
    try:
        found = await asyncio.to_thread(_post, path, args)
    except (URLError, OSError, ValueError):
        return _text("The PC isn't reachable: it's off or asleep, Tailscale is down there, or ultron_pc.py "
                     "isn't running.", True)
    return _text(str(found.get("text", "")), bool(found.get("is_error")))


@tool(
    "pc_read",
    "Read things on the user's Windows PC. what: 'status' (battery, volume, dark mode, Wi-Fi), "
    "'clipboard' (the PC's copied text), or 'files' (files in the PC's Ultron folder whose path has "
    "every word of query; empty query lists them all).",
    {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["status", "clipboard", "files"]},
            "query": {"type": "string", "description": "For files: words in the name or folder."},
        },
        "required": ["what"],
    },
)
async def pc_read(args: dict[str, Any]) -> dict[str, Any]:
    return await _call("/read", args)


@tool(
    "pc_change",
    "Do something on the user's Windows PC. action: 'open_app' (name as in the Start menu), 'open_url' "
    "(http or https), 'open_file' (path: a document in the PC's Ultron folder; a folder opens in Explorer), "
    "'open_terminal' (a terminal window on the PC's screen, for the user to type in), "
    "'copy' (text to the PC's clipboard), 'volume' (level 0-100), 'mute' (on), 'dark_mode' (on), "
    "'media' (name: play_pause, next or previous, for whatever is playing, e.g. Spotify), 'move' "
    "(path → to, also renames), 'trash' (path, to the Recycle Bin). Paths are relative to the PC's Ultron "
    "folder; nothing can be moved out of it or overwritten.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTIONS},
            "name": {"type": "string", "description": "App name, or the media key."},
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
    return await _call("/change", args)


@tool(
    "pc_run",
    "Run code on the user's Windows PC. lang 'python' (whatever the PC's Python has installed) or "
    "'powershell'. It runs as the user, NOT sandboxed, in the Output subfolder of the PC's Ultron folder "
    "(its files are ../name), and is stopped after 60 seconds. Print the results. The user approves "
    "every run. For data work that doesn't need the PC, use run_python on the Mac instead.",
    {
        "type": "object",
        "properties": {"code": {"type": "string"}, "lang": {"type": "string", "enum": ["python", "powershell"]}},
        "required": ["code"],
    },
)
async def pc_run(args: dict[str, Any]) -> dict[str, Any]:
    return await _call("/run", args)
