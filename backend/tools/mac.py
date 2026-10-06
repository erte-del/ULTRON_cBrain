"""This Mac: Shortcuts, apps, URLs, the clipboard, a few settings, your files, and Python
in a sandbox.

  mac_read   (read) battery / volume / dark mode / Wi-Fi, location, the clipboard, your Shortcuts,
             and files in Ultron's folder (JARVIS_FILES_DIR, default ~/Jarvis Files) and in
             config.ALLOWED_DIRS (Desktop, Documents, Downloads; searched with Spotlight).
  mac_change (act)  opens apps, web pages and files, runs a Shortcut, copies to the
             clipboard, sets volume / mute / dark mode, and moves, renames or trashes
             files. No card inside Ultron's folder; a move or trash that touches anything
             outside it asks first, and so do files you marked important (registry.needs_ok).
  run_python (act)  Python for data work (CSV analysis, quick scripts) in a macOS sandbox:
             no network, no other programs or apps, reads only Ultron's folder, writes
             only its Output subfolder.

Files never leave those folders: nothing is moved out of them, nothing is overwritten, and
"delete" puts the file in the Trash. Ultron's own code is out of reach. Only documents open
(no apps, scripts or installers, which matters most in Downloads), and apps only from the
Applications folders.
"""

import asyncio
import base64
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool
from pypdf.errors import PdfReadError

import config

from .homework import _text
from .uploads import IMAGES, IWORK, READABLE, jpeg_of, text_of

MAX_CHARS = 20_000
MAX_FILES = 50
# Built by scripts/setup_location.sh: macOS only gives Location to an app bundle.
LOCATION_APP = config.STORAGE_DIR / "UltronLocation.app"
PYTHON_TIMEOUT_S = 60
SHORTCUT_TIMEOUT_S = 120
APP_DIRS = [Path("/Applications"), Path("/Applications/Utilities"), Path("/System/Applications"),
            Path("/System/Applications/Utilities"), Path.home() / "Applications"]
# Files mac_change may open: documents only, so nothing in the folder can run as a program.
DOCUMENTS = {"pdf", "txt", "md", "rtf", "csv", "tsv", "json", "xml", "log", "doc", "docx", "xls", "xlsx",
             "ppt", "pptx", "pages", "numbers", "key", "odt", "ods", "png", "jpg", "jpeg", "gif", "heic",
             "webp", "tiff", "bmp", "svg", "mp3", "m4a", "wav", "aac", "flac", "mp4", "mov", "m4v", "zip"}
ACTIONS = ["open_app", "open_url", "open_file", "run_shortcut", "copy", "volume", "mute", "dark_mode",
           "move", "trash"]

# The sandbox for run_python. Later rules win: all of your home is unreadable except
# Ultron's folder and Python itself.
PROFILE = """(version 1)
(allow default)
(deny network*)
(deny appleevent-send)
(deny mach-lookup)
(deny process-exec)
(allow process-exec (literal {python}))
(deny file-write*)
(allow file-write* (subpath {output}) (literal "/dev/null"))
(deny file-read* (subpath {home}) (subpath "/Volumes") (subpath "/private/var/folders"))
(allow file-read* (subpath {folder}) (subpath {base}))
"""


async def _run(*cmd: str, stdin: bytes | None = None, timeout: float = 30, **kw: Any) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). The command is killed after `timeout` seconds."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kw,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"{Path(cmd[0]).name} took over {timeout:g} s and was stopped") from None
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _out(*cmd: str, **kw: Any) -> str:
    code, out, err = await _run(*cmd, **kw)
    if code:
        msg = err.strip()
        if "-1743" in msg or "not allowed" in msg.lower():
            msg = "macOS didn't allow it. Allow Ultron in System Settings → Privacy & Security → Automation."
        raise RuntimeError(msg or f"{cmd[0]} failed")
    return out.strip()


def _folder() -> Path:
    config.FILES_DIR.mkdir(parents=True, exist_ok=True)
    return config.FILES_DIR.resolve()


def _roots() -> list[Path]:
    """Ultron's folder first, then the allowed folders of yours."""
    return [_folder(), *(d.resolve() for d in config.ALLOWED_DIRS)]


def allowed_path(path: str) -> Path:
    """The file a path names: relative paths are in Ultron's folder, '~/Downloads/x.pdf' or a
    full path must be inside an allowed folder. ValueError for anywhere else."""
    full = (_folder() / Path(path.strip()).expanduser()).resolve()  # also follows symlinks out
    if full.is_relative_to(config.ROOT_DIR) or not any(full.is_relative_to(r) for r in _roots()):
        raise ValueError(f"{path!r} is outside the folders Ultron may use ({', '.join(map(_show, _roots()))}).")
    return full


def leaves_folder(args: dict[str, Any]) -> bool:
    """A mac_change move or trash that touches anything outside Ultron's folder: it asks first."""
    if args.get("action") not in ("move", "trash"):
        return False
    for key in ("path", "to"):
        try:
            if not allowed_path(str(args.get(key) or "")).is_relative_to(_folder()):
                return True
        except ValueError:
            pass  # mac_change refuses it anyway
    return False


def _show(p: Path) -> str:
    """How Ultron names a path: relative in its own folder, else ~/Downloads/x.pdf."""
    if p.is_relative_to(_folder()):
        return p.relative_to(_folder()).as_posix() or "."
    return "~/" + p.relative_to(Path.home()).as_posix() if p.is_relative_to(Path.home()) else str(p)


def _why(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return (f"macOS didn't let Ultron into {e.filename or 'that folder'}. Turn it on in System "
                "Settings → Privacy & Security → Files & Folders → Ultron.")
    return str(e)


# --- reading -------------------------------------------------------------------------

# The user's phone [lat, lon] while they're talking from it, so "near me" means near them.
# ponytail: one global for the turn being answered; a scheduled job running during a phone
# turn uses it too. Pass it per call if that ever matters.
phone_here: list[float] | None = None
phone_status: str | None = None  # "Battery: 82%, charging\n...", same turn as phone_here


async def locator(action: str = "where", params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ask UltronLocation.app (where am I / search / directions), from the phone's location
    when the user is on it, else this Mac's. RuntimeError if it can't answer."""
    params = {**(params or {}), **({"here": phone_here} if phone_here else {})}
    if not LOCATION_APP.exists():
        raise RuntimeError("Location isn't set up: run scripts/setup_location.sh once.")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp, "out")
        # Through `open`, so macOS sees the app (with its permission) and not Ultron's Python.
        await _out("open", "-W", "-n", "-g", "--stdout", str(out), str(LOCATION_APP), "--args", action,
                   json.dumps(params, ensure_ascii=False), timeout=150)
        found = json.loads(out.read_text() or '{"error": "no answer"}')
    if found.get("error") == "denied":
        raise RuntimeError("macOS doesn't allow Ultron's location. Turn on Ultron Location in System "
                           "Settings → Privacy & Security → Location Services.")
    if "error" in found:
        raise RuntimeError(found["error"])
    return found


async def _status() -> str:
    battery = (await _out("pmset", "-g", "batt")).splitlines()
    volume = await _out("osascript", "-e", "get volume settings")
    _, style, _ = await _run("defaults", "read", "-g", "AppleInterfaceStyle")  # fails in light mode
    ports = await _out("networksetup", "-listallhardwareports")
    m = re.search(r"Hardware Port: Wi-Fi\nDevice: (\w+)", ports)
    wifi = "no Wi-Fi"
    if m:
        wifi = (await _out("networksetup", "-getairportpower", m[1])).split(":")[-1].strip()
        _, summary, _ = await _run("ipconfig", "getsummary", m[1])
        ssid = re.search(r"^\s+SSID : (.+)$", summary, re.M)
        if wifi == "On":
            wifi = ("connected to " + ssid[1] if ssid and ssid[1] != "<redacted>" else
                    "connected (macOS hides the network's name)" if ssid else "on, not connected")
    return "\n".join([
        "Battery: " + (" ".join(battery[1].split()[1:]) if len(battery) > 1 else "none"),
        "Power: " + (battery[0].removeprefix("Now drawing from ").strip("'") if battery else "?"),
        "Sound: " + volume,
        "Appearance: " + ("dark" if style.strip() == "Dark" else "light"),
        "Wi-Fi: " + wifi,
    ])


def _folder_name(root: Path) -> str:
    return "ultron" if root == _folder() else root.name


async def find_files(query: str, folder: str = "all") -> list[dict[str, Any]]:
    """Files and folders whose path (inside the folder searched) has every word of the query,
    newest first. Ultron's folder is walked; yours are asked of Spotlight, and with no query
    only their top level is listed."""
    words = re.sub(r'["\\*]', "", query.lower()).split()  # nothing that breaks a Spotlight query
    found = []
    for root in _roots():
        if folder not in ("all", _folder_name(root)):
            continue
        if root == _folder():
            paths = root.rglob("*")
        else:
            os.scandir(root).close()  # PermissionError if macOS hasn't let Ultron in
            if words:
                # ponytail: Spotlight only; a folder it doesn't index finds nothing. Fall back to
                # rglob if that ever bites.
                spotlight = " || ".join(f'kMDItemFSName == "*{w}*"cd' for w in words)
                paths = map(Path, (await _out("mdfind", "-onlyin", str(root), spotlight)).splitlines())
            else:
                paths = root.iterdir()
        for p in paths:
            if not p.is_relative_to(root) or p.is_relative_to(config.ROOT_DIR):
                continue
            rel = p.relative_to(root)
            if any(part.startswith(".") for part in rel.parts) or not all(w in rel.as_posix().lower() for w in words):
                continue
            try:
                st = p.stat()
            except FileNotFoundError:
                continue  # Spotlight hasn't caught up with a deleted file
            found.append({"path": _show(p) + ("/" if p.is_dir() else ""), "size": st.st_size,
                          "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")})
    return sorted(found, key=lambda f: f["modified"], reverse=True)


@tool(
    "mac_read",
    "Read things on this Mac. what: 'status' (battery, volume, dark mode, Wi-Fi; the phone's first when "
    "the user is on it), 'location' (where "
    "the user is: their phone's GPS when they're on it, else this Mac's; latitude, longitude, place name, "
    "time zone; for weather, directions, things nearby), 'clipboard' "
    "(the text copied right now), 'shortcuts' (the user's Shortcuts, to run with mac_change), or "
    f"'content' (what's inside the file at path: {READABLE}; images come back as a picture), or "
    "'files' (files whose name or folder has every word of query, newest first, in Ultron's folder and "
    "the user's Desktop, Documents and Downloads; folder narrows it to one; an empty query lists all of "
    "Ultron's folder but only the top level of the others). Paths come back ready for mac_change: "
    "plain for Ultron's folder, '~/Downloads/...' for the others. For sums over a CSV in Ultron's "
    "folder, use run_python.",
    {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["status", "location", "clipboard", "shortcuts", "files", "content"]},
            "path": {"type": "string", "description": "For content: a path mac_read what=files gave."},
            "query": {"type": "string", "description": "For files: words in the name or folder."},
            "folder": {"type": "string", "enum": ["all", "ultron", *(d.name for d in config.ALLOWED_DIRS)],
                       "description": "For files: where to look (default all)."},
        },
        "required": ["what"],
    },
)
async def mac_read(args: dict[str, Any]) -> dict[str, Any]:
    what = args.get("what")
    try:
        if what == "status":
            if phone_status:  # they're on the phone: its readings first, the Mac's after
                return _text(f"The user's phone (they're on it):\n{phone_status}\nVolume and the Wi-Fi "
                             f"network's name can't be read from the phone.\n\nThis Mac:\n{await _status()}")
            return _text(await _status())
        if what == "location":
            found = {**await locator(), "from": "the user's phone" if phone_here else "this Mac"}
            return _text(json.dumps(found, ensure_ascii=False))
        if what == "clipboard":
            text = await _out("pbpaste")
            return _text(text[:MAX_CHARS] if text else "The clipboard is empty or holds something that isn't text.")
        if what == "shortcuts":
            names = await _out("shortcuts", "list")
            return _text(names or "The user has no Shortcuts.")
        if what == "files":
            folder = str(args.get("folder") or "all")
            found = await find_files(str(args.get("query") or ""), folder)
            more = f" (newest {MAX_FILES} of {len(found)})" if len(found) > MAX_FILES else ""
            return _text(f"Found{more}: " + json.dumps(found[:MAX_FILES], ensure_ascii=False) if found else
                         f"Nothing matches in {'any folder' if folder == 'all' else folder}.")
        if what == "content":
            p = allowed_path(str(args.get("path") or ""))
            if not (p.is_file() or p.suffix.lower() in IWORK and p.exists()):  # old iWork files are folders
                return _text(f"mac_read: {args.get('path')!r} isn't a file.", True)
            if p.suffix.lower() in IMAGES and (jpeg := await asyncio.to_thread(jpeg_of, p)):
                return {"content": [{"type": "text", "text": f"{_show(p)}:"},
                                    {"type": "image", "data": base64.b64encode(jpeg).decode(), "mimeType": "image/jpeg"}]}
            return _text(f"{_show(p)}:\n\n{await asyncio.to_thread(text_of, p)}")
    except (RuntimeError, OSError, ValueError, PdfReadError) as e:
        return _text(f"mac_read: {_why(e)}", True)
    return _text(f"mac_read: what must be one of status, location, clipboard, shortcuts, files, content (got {what!r}).", True)


# --- changing ------------------------------------------------------------------------

def find_app(name: str) -> Path | None:
    """'safari' -> Safari.app, 'unity' -> Unity Hub.app, 'chrome' -> Google Chrome.app: the exact name,
    else the shortest name starting with it, else the shortest containing it. Only the Applications folders."""
    want = name.strip().lower().removesuffix(".app")
    if not want or "/" in want:
        return None
    apps = sorted(installed_apps(), key=lambda a: len(a.stem))
    for match in (lambda n: n == want, lambda n: n.startswith(want), lambda n: want in n):
        found = next((a for a in apps if match(a.stem.lower())), None)
        if found:
            return found
    return None


def installed_apps() -> list[Path]:
    return [app for d in APP_DIRS if d.is_dir() for app in d.glob("*.app")]


async def _shortcut(name: str, text: str) -> str:
    names = (await _out("shortcuts", "list")).splitlines()
    real = next((n for n in names if n.lower() == name.strip().lower()), None)
    if real is None:
        raise ValueError(f"There's no Shortcut called {name!r}. The user's Shortcuts: {', '.join(names) or 'none'}.")
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["shortcuts", "run", real, "--output-path", f"{tmp}/out"]
        if text:
            Path(tmp, "in.txt").write_text(text)
            cmd += ["--input-path", f"{tmp}/in.txt"]
        await _out(*cmd, timeout=SHORTCUT_TIMEOUT_S)
        out = Path(tmp, "out")
        result = out.read_bytes()[:MAX_CHARS].decode(errors="replace") if out.is_file() else ""
    return f"Ran the Shortcut {real!r}." + (f" It returned: {result}" if result.strip() else "")


def move(path: str, to: str) -> str:
    src, dest = allowed_path(path), allowed_path(to)
    if src in _roots():
        raise ValueError(f"{_show(src)} itself can't be moved.")
    if not src.exists():
        raise ValueError(f"{path!r} doesn't exist.")
    if dest.is_dir():
        dest = dest / src.name  # "move it into Invoices"
    if dest.exists():
        raise ValueError(f"{_show(dest)!r} already exists; nothing is ever overwritten. Pick another name.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    return f"Moved {_show(src)} → {_show(dest)}."


async def _trash(path: str) -> str:
    p = allowed_path(path)
    if p in _roots() or not p.exists():
        raise ValueError(f"{path!r} isn't a file or folder Ultron can trash.")
    await _out("osascript", "-e", "on run argv", "-e",
               'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)', "-e", "end run", str(p))
    return f"Moved {_show(p)} to the Trash (it can be put back from there)."


@tool(
    "mac_change",
    "Do something on this Mac. action: 'open_app' (name: the app's name or part of it, e.g. 'unity'; "
    "if it isn't found you get the list of installed apps to pick from), 'open_url' (url, http or https), "
    "'open_file' (path: a document opens in its app, a folder shows in Finder), "
    "'run_shortcut' (name, optional text as its input), 'copy' (text to the clipboard), "
    "'volume' (level 0-100), 'mute' (on), 'dark_mode' (on), 'move' (path → to, also renames; "
    "into a folder if 'to' is one), 'trash' (path, to the Trash). Paths are relative to Ultron's folder, "
    "or '~/Desktop/...', '~/Documents/...', '~/Downloads/...' for the user's own; nothing else is "
    "reachable and nothing is overwritten. Moving or trashing outside Ultron's folder asks the user "
    "first. For Do Not Disturb or Focus, run a Shortcut that sets it.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTIONS},
            "name": {"type": "string", "description": "App or Shortcut name."},
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
async def mac_change(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action")
    name, path, text = str(args.get("name") or ""), str(args.get("path") or ""), str(args.get("text") or "")
    try:
        if action == "open_app":
            app = find_app(name)
            if app is None:
                names = sorted({a.stem for a in installed_apps()}, key=str.lower)
                return _text(f"No app called {name!r}. Installed apps: {', '.join(names)}. If one of these is "
                             "what the user meant, open it by that name; otherwise say it isn't installed.", True)
            await _out("open", "-a", str(app))
            return _text(f"Opened {app.stem}.")
        if action == "open_url":
            url = str(args.get("url") or "").strip()
            if not re.match(r"https?://[^\s/]", url):
                return _text("Only http:// and https:// addresses can be opened.", True)
            await _out("open", url)
            return _text(f"Opened {url} in the browser.")
        if action == "open_file":
            p = allowed_path(path)
            if p.is_dir():
                await _out("open", "-R", str(p))  # shows it in Finder; never launches a bundle
                return _text(f"Showed {_show(p)} in Finder.")
            if not p.is_file():
                return _text(f"{path!r} doesn't exist.", True)
            if p.suffix.lower().lstrip(".") not in DOCUMENTS:
                await _out("open", "-R", str(p))
                return _text(f"Ultron only opens documents, not {p.suffix or 'files without a type'}; "
                             f"showed {_show(p)} in Finder instead.", True)
            await _out("open", str(p))
            return _text(f"Opened {_show(p)}.")
        if action == "run_shortcut":
            return _text(await _shortcut(name, text))
        if action == "copy":
            await _out("pbcopy", stdin=text.encode())
            return _text("Copied to the clipboard.")
        if action == "volume":
            level = max(0, min(100, int(args.get("level", 50))))
            await _out("osascript", "-e", f"set volume output volume {level} without output muted")
            return _text(f"Volume set to {level}.")
        if action == "mute":
            on = bool(args.get("on", True))
            await _out("osascript", "-e", f"set volume {'with' if on else 'without'} output muted")
            return _text("Muted." if on else "Unmuted.")
        if action == "dark_mode":
            on = bool(args.get("on", True))
            await _out("osascript", "-e",
                       f'tell application "System Events" to tell appearance preferences to set dark mode to {str(on).lower()}')
            return _text(f"{'Dark' if on else 'Light'} mode on.")
        if action == "move":
            return _text(move(path, str(args.get("to") or "")))
        if action == "trash":
            return _text(await _trash(path))
    except (RuntimeError, OSError, ValueError) as e:
        return _text(f"mac_change: {_why(e)}", True)
    return _text(f"mac_change: action must be one of {', '.join(ACTIONS)} (got {action!r}).", True)


# --- sandboxed Python ----------------------------------------------------------------

def _sb(path: Path) -> str:
    return json.dumps(str(path.resolve()))  # an SBPL string


@tool(
    "run_python",
    "Run Python 3 (standard library only: csv, json, statistics, math, re, datetime, ...) for data "
    "work: analysing a CSV, totals, conversions, quick scripts. It runs in a sandbox: no internet, "
    "can't start other programs, can only read files in Ultron's folder (as ../name.csv), and can only "
    "write in its Output subfolder, which is the working directory. Print the results; at most "
    f"{PYTHON_TIMEOUT_S} seconds. Find files first with mac_read what=files.",
    {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
)
async def run_python(args: dict[str, Any]) -> dict[str, Any]:
    code = str(args.get("code") or "")
    if not code.strip():
        return _text("run_python needs code.", True)
    folder = _folder()
    output = folder / "Output"
    output.mkdir(exist_ok=True)
    python = Path(sys._base_executable).resolve()  # not the venv: it lives in your home
    profile = PROFILE.format(python=_sb(python), output=_sb(output), home=_sb(Path.home()),
                             folder=_sb(folder), base=_sb(Path(sys.base_prefix)))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder), "TMPDIR": str(output), "LANG": "en_US.UTF-8"}
    try:
        exit_code, out, err = await _run("/usr/bin/sandbox-exec", "-p", profile, str(python), "-I", "-",
                                         stdin=code.encode(), timeout=PYTHON_TIMEOUT_S, cwd=output, env=env)
    except (RuntimeError, OSError) as e:
        return _text(f"run_python: {e}", True)
    text = out[-MAX_CHARS:] + (f"\n[stderr]\n{err[-MAX_CHARS // 4:]}" if err.strip() else "")
    return _text(text.strip() or "(no output; print the results)", is_error=exit_code != 0)
