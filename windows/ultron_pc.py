"""Ultron on a Windows PC: the same reads and changes as mac_read / mac_change, over Tailscale.

  POST /read   {"what": "status" | "clipboard" | "files" | "content" | "folder" | "name", "query", "folder", "path"}
                                                                             = mac_read
  POST /change {"action": "open_app" | "open_url" | "open_file" | "open_terminal" | "copy" |
                "volume" | "mute" | "dark_mode" | "media" | "move" | "trash", ...}  = mac_change
  POST /capture {"action": "start" | "stop" | "status" | "clip", "minutes", "seconds"}
                rolling screen buffer on the PC; clip sends the last N seconds back as mp4 bytes
  POST /run    {"code", "lang": "python" | "powershell"}                       = run_python
  -> {"text": "...", "is_error": bool}. Every call needs "Authorization: Bearer <token.txt>".

It listens on 127.0.0.1 only; `tailscale serve` passes your own devices through to it over
HTTPS. Nothing reaches the public internet. Files: ULTRON_PC_FOLDER plus your Desktop, Documents
and Downloads; nothing leaves them, a move or trash outside ULTRON_PC_FOLDER needs Ultron's
approval flag (the Mac asks you first), nothing is overwritten, "trash" goes to the Recycle Bin, only documents and shortcuts open, and apps only from the Start menu or Start Menu/Desktop shortcuts (nicknames.json maps 'rl' to 'rocket league').
/run is NOT sandboxed (Windows has no sandbox-exec): it runs as you, in the folder's Output
subfolder, killed after 60 s. Ultron asks you before every /run.

Setup: install Python 3.11+ and Tailscale (the Mac's account), then run install.ps1 once.
Updates: every start (logon, or Stop/Start-ScheduledTask Ultron) git-pulls this repo first and runs
the new code. Offline or local edits: it keeps running the code it has.
"""

import atexit
import base64
import ctypes
import difflib
import hmac
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

PORT = int(os.getenv("ULTRON_PC_PORT", "8765"))
TOKEN_FILE = Path(__file__).with_name("token.txt")  # written by install.ps1
TOKEN = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
FOLDER = Path(os.getenv("ULTRON_PC_FOLDER", "").strip() or Path.home() / "Ultron Files")
MAX_CHARS = 20_000
MAX_FILES = 50
MAX_BODY = 1_000_000
MAX_READ = 20_000_000  # bytes sent back for "content"; the Mac pulls the text out
# Your folders, by their Windows names (they may live in OneDrive).
SHELL_FOLDERS = {"Desktop": "Desktop", "Documents": "Personal", "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}
RUN_TIMEOUT_S = 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DOCUMENTS = {"pdf", "txt", "md", "rtf", "csv", "tsv", "json", "xml", "log", "doc", "docx", "xls", "xlsx",
             "ppt", "pptx", "odt", "ods", "png", "jpg", "jpeg", "gif", "heic", "webp", "tiff", "bmp", "svg",
             "mp3", "m4a", "wav", "aac", "flac", "mp4", "mov", "m4v", "mkv", "zip"}
SHORTCUTS = {".lnk", ".url"}  # you put them on the Desktop, so they open like apps
ACTIONS = ["open_app", "open_url", "open_file", "open_terminal", "copy", "volume", "mute", "dark_mode", "media", "move", "trash"]
# open_url: the web, plus Windows Settings. Never file:, javascript:, ... Apps and games open by name (open_app).
URL_SCHEMES = ("http://", "https://", "ms-settings:")
URL_OK = re.compile(r"(?i)https?://[^\s/]\S*|ms-settings:\S+")
NICKNAMES_FILE = "nicknames.json"  # in the Ultron folder, yours to edit: {"rl": "rocket league", ...}
NICKNAMES = {"rl": "rocket league", "cs": "counter-strike", "r6": "rainbow six", "lol": "league of legends",
             "league": "league of legends", "val": "valorant", "mc": "minecraft", "acc": "assetto corsa competizione"}
MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
REPO = Path(__file__).resolve().parents[1]


def ps(script: str, stdin: str = "") -> str:
    """Run PowerShell, UTF-8 both ways. RuntimeError with its message if it fails."""
    utf8 = "[Console]::InputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", utf8 + script],
                       input=stdin, capture_output=True, encoding="utf-8", errors="replace",
                       timeout=30, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "PowerShell failed")
    return r.stdout.strip()


# --- the folder fence (same rules as the Mac) ----------------------------------------

def folder() -> Path:
    FOLDER.mkdir(parents=True, exist_ok=True)
    return FOLDER.resolve()


def user_dirs() -> dict[str, Path]:
    """Your Desktop, Documents and Downloads, wherever Windows keeps them."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return {n: Path(os.path.expandvars(winreg.QueryValueEx(k, v)[0])) for n, v in SHELL_FOLDERS.items()}
    except (ImportError, OSError):  # not Windows (tests), or a value is missing
        return {n: Path.home() / n for n in SHELL_FOLDERS}


def roots() -> dict[str, Path]:
    """Ultron's folder first, then yours."""
    return {"ultron": folder(), **{n: d.resolve() for n, d in user_dirs().items() if d.is_dir()}}


def allowed(path: str, outside_ok: bool = True) -> Path:
    """Relative paths are in Ultron's folder; '~/Desktop/x' or a full path must be in one of yours.
    With outside_ok False, only Ultron's folder."""
    full = (folder() / Path(path.strip()).expanduser()).resolve()  # also follows links out
    ok = list(roots().values()) if outside_ok else [folder()]
    if full.is_relative_to(REPO) or not any(full.is_relative_to(r) for r in ok):
        where = ", ".join(map(str, ok))
        raise ValueError(f"{path!r} is outside the folders Ultron may use here ({where})." +
                         ("" if outside_ok else " Use a ~/ path so the user is asked first."))
    return full


def show(p: Path) -> str:
    """Relative in Ultron's folder, else ~/Desktop/x."""
    if p.is_relative_to(folder()):
        return p.relative_to(folder()).as_posix() or "."
    return "~/" + p.relative_to(Path.home()).as_posix() if p.is_relative_to(Path.home()) else str(p)


def find_files(query: str, where: str = "all") -> list[dict[str, Any]]:
    """Every word of the query in the path, newest first. With no query, your folders list only
    their top level (like the Mac)."""
    words, found = query.lower().split(), []
    for name, root in roots().items():
        if where not in ("all", name):
            continue
        # ponytail: walks the whole folder on every search (no Spotlight here); use Windows Search if slow.
        for p in root.rglob("*") if name == "ultron" or words else root.iterdir():
            r = p.relative_to(root)
            if any(part.startswith(".") for part in r.parts) or not all(w in r.as_posix().lower() for w in words):
                continue
            if p.is_relative_to(REPO):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            found.append({"path": show(p) + ("/" if p.is_dir() else ""), "size": st.st_size,
                          "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")})
    return sorted(found, key=lambda f: f["modified"], reverse=True)


def tree_size(d: Path) -> int:
    """Bytes in a folder, all the way down. Unreadable folders are skipped. (Same as tools/mac.py.)"""
    total = 0
    for top, _, files in os.walk(d):
        for f in files:
            try:
                total += os.lstat(os.path.join(top, f)).st_size
            except OSError:
                pass
    return total


def list_folder(d: Path) -> dict[str, Any]:
    """What's in a folder (no hidden files), folders first, each folder with its full size."""
    items, total = [], 0
    for p in sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            st = p.lstat()
        except OSError:
            continue
        size = tree_size(p) if p.is_dir() and not p.is_symlink() else st.st_size
        total += size
        if not p.name.startswith("."):
            items.append({"name": p.name + ("/" if p.is_dir() else ""), "size": size,
                          "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")})
    return {"folder": show(d), "total_size": total, "items": items[:MAX_FILES],
            **({"more": len(items) - MAX_FILES} if len(items) > MAX_FILES else {})}


def move(path: str, to: str, outside_ok: bool = False) -> str:
    src, dest = allowed(path, outside_ok), allowed(to, outside_ok)
    if src in roots().values():
        raise ValueError(f"{show(src)} itself can't be moved.")
    if not src.exists():
        raise ValueError(f"{path!r} doesn't exist.")
    if dest.is_dir():
        dest = dest / src.name
    if dest.exists():
        raise ValueError(f"{show(dest)!r} already exists; nothing is ever overwritten. Pick another name.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    return f"Moved {show(src)} → {show(dest)}."


# --- Windows bits --------------------------------------------------------------------

class _Power(ctypes.Structure):
    _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                ("saver", ctypes.c_ubyte), ("life", ctypes.c_ulong), ("full", ctypes.c_ulong)]


def _speakers():
    from pycaw.pycaw import AudioUtilities  # py -m pip install pycaw
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):  # pycaw 2024+
        return dev.EndpointVolume
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    return ctypes.cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                       ctypes.POINTER(IAudioEndpointVolume))


def status() -> str:
    p = _Power()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p))
    battery = "none" if p.flag & 128 or p.percent == 255 else \
        f"{p.percent}%" + (", charging" if p.flag & 8 else "")
    try:
        sp = _speakers()
        sound = f"{round(sp.GetMasterVolumeLevelScalar() * 100)}%" + (", muted" if sp.GetMute() else "")
    except ImportError:
        sound = "unknown (py -m pip install pycaw on the PC)"
    except Exception as e:  # comtypes COMError: no speakers
        sound = f"unknown ({e})"
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as k:
        light = winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
    wlan = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                          errors="replace", creationflags=NO_WINDOW).stdout
    state, ssid = re.search(r"^\s*State\s*:\s*(.+)$", wlan, re.M), re.search(r"^\s*SSID\s*:\s*(.+)$", wlan, re.M)
    wifi = ("connected to " + ssid[1].strip() if state and "connected" == state[1].strip() and ssid else
            state[1].strip() if state else "no Wi-Fi (or Windows hides it: Location is off)")
    return "\n".join([f"Battery: {battery}", f"Power: {'AC' if p.ac == 1 else 'battery'}",
                      f"Sound: {sound}", f"Appearance: {'light' if light else 'dark'}", f"Wi-Fi: {wifi}"])


def pick(names: list[str], want: str) -> str | None:
    """Like the Mac: 'chrome' -> Google Chrome. Exact, else shortest starting with it, else containing it."""
    names = sorted(names, key=len)
    return next((n for match in (lambda n: n == want, lambda n: n.startswith(want), lambda n: want in n)
                 for n in names if want and match(n)), None)


def shortcuts() -> dict[str, Path]:
    """Shortcuts in the Start Menu folders (Windows' /Applications: installers and Steam, Epic, Riot put one there)
    and on your Desktop and the Public one, by lowercase name. The Desktop wins a name clash."""
    menu = r"Microsoft\Windows\Start Menu\Programs"
    dirs = [Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / menu, Path(os.getenv("APPDATA", "")) / menu,
            Path(os.getenv("PUBLIC", r"C:\Users\Public")) / "Desktop", user_dirs()["Desktop"]]
    return {p.stem.lower(): p for d in dirs if d.is_dir() for p in d.rglob("*") if p.suffix.lower() in SHORTCUTS}


def real_name(name: str) -> str:
    """'rl' -> 'rocket league' from nicknames.json (written with NICKNAMES the first time), else the name as said."""
    f = folder() / NICKNAMES_FILE
    if not f.exists():
        f.write_text(json.dumps(NICKNAMES, indent=2), encoding="utf-8")
    want = name.strip().lower()
    return {k.lower(): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()}.get(want, want).lower()


def open_app(name: str) -> str:
    """By its Start menu name or part of it (Store apps too), else a Start Menu or Desktop shortcut's name."""
    apps = json.loads(ps("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress") or "[]")
    apps = {a["Name"].lower(): a for a in ([apps] if isinstance(apps, dict) else apps)}
    want = real_name(name)
    if n := pick(list(apps), want):
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + apps[n]["AppID"]])
        return f"Opened {apps[n]['Name']}."
    links = shortcuts()
    if n := pick(list(links), want):
        os.startfile(links[n])  # .url (steam://, com.epicgames.launcher://) or .lnk: its launcher runs it
        return f"Opened {links[n].stem}."
    near = difflib.get_close_matches(want, [*apps, *links], n=5, cutoff=0.4)
    raise ValueError(f"No Start menu app or shortcut called {name!r}." +
                     (f" Close: {', '.join(near)}." if near else ""))


def launch(url: str) -> str:
    if not URL_OK.fullmatch(url):
        raise ValueError(f"Only {', '.join(URL_SCHEMES)} addresses can be opened.")
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} open {url}", file=sys.stderr)
    os.startfile(url)
    return f"Opened {url}."


def show_in_explorer(p: Path) -> None:
    subprocess.Popen(f'explorer.exe /select,"{p}"')


def dark_mode(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if on else 1)
    # Tell open windows and the taskbar to repaint (WM_SETTINGCHANGE).
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "ImmersiveColorSet", 2, 1000, None)


def trash(path: str, outside_ok: bool = False) -> str:
    p = allowed(path, outside_ok)
    if p in roots().values() or not p.exists():
        raise ValueError(f"{path!r} isn't a file or folder Ultron can trash.")
    # The path goes in on stdin, never into the script text.
    ps("$p=[Console]::In.ReadToEnd(); Add-Type -AssemblyName Microsoft.VisualBasic; "
       "if (Test-Path -LiteralPath $p -PathType Container) "
       "{[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p,'OnlyErrorDialogs','SendToRecycleBin')} "
       "else {[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin')}",
       stdin=str(p))
    return f"Moved {show(p)} to the Recycle Bin (it can be restored from there)."


# --- the two calls -------------------------------------------------------------------

def read(args: dict[str, Any]) -> str | dict[str, Any]:
    what = args.get("what")
    if what == "status":
        return status()
    if what == "clipboard":
        return ps("Get-Clipboard -Raw")[:MAX_CHARS] or "The clipboard is empty or isn't text."
    if what == "files":
        where = str(args.get("folder") or "all")
        found = find_files(str(args.get("query") or ""), where)
        more = f" (newest {MAX_FILES} of {len(found)})" if len(found) > MAX_FILES else ""
        return f"Found{more}: " + json.dumps(found[:MAX_FILES], ensure_ascii=False) if found else \
            f"Nothing matches in {'any folder' if where == 'all' else where}."
    if what == "folder":
        p = allowed(str(args.get("path") or ""))
        if not p.is_dir():
            raise ValueError(f"{args.get('path')!r} isn't a folder.")
        return json.dumps(list_folder(p), ensure_ascii=False)
    if what == "content":  # the bytes: the Mac reads PDFs, Office files and images
        p = allowed(str(args.get("path") or ""))
        if not p.is_file():
            raise ValueError(f"{args.get('path')!r} isn't a file.")
        if p.stat().st_size > MAX_READ:
            raise ValueError(f"{show(p)} is over {MAX_READ // 1_000_000} MB; too big to read.")
        return {"text": show(p), "data": base64.b64encode(p.read_bytes()).decode()}
    if what == "name":  # Spotify calls the PC by this name
        return platform.node()
    raise ValueError(f"what must be one of status, clipboard, files, content, folder (got {what!r}).")


def change(args: dict[str, Any]) -> str:
    action = args.get("action")
    name, path, text = str(args.get("name") or ""), str(args.get("path") or ""), str(args.get("text") or "")
    on = bool(args.get("on", True))
    outside_ok = args.get("outside_ok") is True  # set by the Mac after the user approved
    if action == "open_app":
        return open_app(name)
    if action == "open_url":
        return launch(str(args.get("url") or "").strip())
    if action == "open_file":
        p = allowed(path)
        if p.is_dir():
            os.startfile(p)  # a folder opens in Explorer
            return f"Opened {show(p)} in Explorer."
        if not p.is_file():
            raise ValueError(f"{path!r} doesn't exist.")
        if p.suffix.lower().lstrip(".") not in DOCUMENTS and p.suffix.lower() not in SHORTCUTS:
            show_in_explorer(p)
            raise ValueError(f"Ultron only opens documents, not {p.suffix or 'files without a type'}; "
                             f"showed {show(p)} in Explorer instead.")
        os.startfile(p)
        return f"Opened {show(p)}."
    if action == "open_terminal":  # a window on the PC's screen; what runs in it is up to you
        try:
            subprocess.Popen(["wt.exe", "-d", str(folder())])
        except FileNotFoundError:  # no Windows Terminal: a plain PowerShell window
            subprocess.Popen(["powershell.exe", "-NoExit"], cwd=folder(), creationflags=subprocess.CREATE_NEW_CONSOLE)
        return "Opened a terminal on the PC, in Ultron's folder."
    if action == "copy":
        ps("Set-Clipboard -Value ([Console]::In.ReadToEnd())", stdin=text)
        return "Copied to the PC's clipboard."
    if action == "volume":
        level = max(0, min(100, int(args.get("level", 50))))
        sp = _speakers()
        sp.SetMute(0, None)
        sp.SetMasterVolumeLevelScalar(level / 100, None)
        return f"Volume set to {level}."
    if action == "mute":
        _speakers().SetMute(int(on), None)
        return "Muted." if on else "Unmuted."
    if action == "dark_mode":
        dark_mode(on)
        return f"{'Dark' if on else 'Light'} mode on."
    if action == "media":  # whatever is playing: Spotify, YouTube in a browser, ...
        key = MEDIA_KEYS.get(name)
        if key is None:
            raise ValueError(f"media name must be one of {', '.join(MEDIA_KEYS)}.")
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        return f"Pressed {name.replace('_', '/')}."
    if action == "move":
        return move(path, str(args.get("to") or ""), outside_ok)
    if action == "trash":
        return trash(path, outside_ok)
    raise ValueError(f"action must be one of {', '.join(ACTIONS)} (got {action!r}).")


def run(args: dict[str, Any]) -> tuple[str, bool]:
    """Python or PowerShell, as you, in Output. (output, failed)."""
    code, lang = str(args.get("code") or ""), args.get("lang") or "python"
    if not code.strip():
        raise ValueError("run needs code.")
    if lang == "python":
        cmd, stdin = [sys.executable, "-I", "-X", "utf8", "-"], code
    elif lang == "powershell":
        import base64
        encoded = base64.b64encode(("[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + code).encode("utf-16-le")).decode()
        cmd, stdin = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-EncodedCommand", encoded], ""
    else:
        raise ValueError(f"lang must be python or powershell (got {lang!r}).")
    output = folder() / "Output"
    output.mkdir(exist_ok=True)
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, encoding="utf-8", errors="replace",
                           cwd=output, timeout=RUN_TIMEOUT_S, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"took over {RUN_TIMEOUT_S} s and was stopped") from None
    text = r.stdout[-MAX_CHARS:] + (f"\n[stderr]\n{r.stderr[-MAX_CHARS // 4:]}" if r.stderr.strip() else "")
    return text.strip() or "(no output; print the results)", r.returncode != 0


def stop_old_copies() -> None:
    """Stop earlier ultron_pc.py processes. Stopping the task leaves its --no-update child running, and it
    would keep answering on the port with the old code."""
    keep = f"{os.getpid()},{os.getppid()}"
    try:
        ps("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -like "
           f"'*ultron_pc.py*' -and $_.ProcessId -notin @({keep}) }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        print(f"couldn't stop old copies: {e}", file=sys.stderr)


def update() -> bool:
    """git pull the repo this file is in. True if new code came down. Any failure (offline, local
    edits, diverged history) keeps the code as it is."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}  # never wait on a login

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, errors="replace",
                              timeout=60, env=env, creationflags=NO_WINDOW)
    try:
        before = git("rev-parse", "HEAD").stdout.strip()
        pulled = git("pull", "--ff-only")
        if pulled.returncode:
            print(f"update skipped, running the code as it is: {pulled.stderr.strip()}", file=sys.stderr)
            return False
        after = git("rev-parse", "HEAD").stdout.strip()
        if before == after:
            return False
        if git("diff", "--name-only", before, after, "--", "windows/requirements.txt").stdout.strip():
            subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-r",
                            str(Path(__file__).with_name("requirements.txt"))],
                           capture_output=True, timeout=300, creationflags=NO_WINDOW)
        print(f"updated {before[:7]} -> {after[:7]}", file=sys.stderr)
        return True
    except (OSError, subprocess.TimeoutExpired) as e:  # no git, or the network hung
        print(f"update skipped: {e}", file=sys.stderr)
        return False


SEG = 5  # seconds per buffer segment
MAX_CLIP_S = 60  # keeps the reply (base64 over Tailscale) to a sane size
_cap: subprocess.Popen | None = None
_cap_log = None


def _buf() -> Path:
    return folder() / "capture_buffer"


def _segments() -> list[Path]:
    return sorted(_buf().glob("s*.ts"), key=lambda p: p.stat().st_mtime)


def _stop_capture() -> bool:
    global _cap
    was = _cap is not None and _cap.poll() is None
    if was:
        _cap.terminate()
        try:
            _cap.wait(5)
        except subprocess.TimeoutExpired:
            _cap.kill()
    _cap = None
    if _cap_log:
        _cap_log.close()
    return was


atexit.register(_stop_capture)


def capture(args: dict[str, Any]) -> str | dict[str, Any]:
    """The whole PC desktop into a rolling buffer of 5 s segments (video only), like the Mac's capture."""
    global _cap, _cap_log
    act = args.get("action")
    ffmpeg = shutil.which("ffmpeg")
    if act in ("start", "clip") and not ffmpeg:
        raise RuntimeError("ffmpeg isn't installed on the PC: winget install -e --id Gyan.FFmpeg, then restart Ultron.")
    running = _cap is not None and _cap.poll() is None
    if act == "stop":
        was = _stop_capture()
        shutil.rmtree(_buf(), ignore_errors=True)
        return "Stopped; the PC buffer is deleted." if was else "The PC wasn't recording."
    if act == "status":
        if _cap is not None and not running:
            return f"ffmpeg stopped by itself on the PC: {(_buf() / 'ffmpeg.log').read_text(encoding='utf-8', errors='replace')[-500:].strip() or 'nothing'}"
        return "The PC is recording." if running else "The PC isn't recording."
    if act == "start" or (act == "clip" and not running):
        _stop_capture()  # closes a dead ffmpeg's log: Windows can't delete an open file
        shutil.rmtree(_buf(), ignore_errors=True)
        _buf().mkdir(parents=True)
        minutes = min(max(int(args.get("minutes") or 5), 1), 10)
        _cap_log = open(_buf() / "ffmpeg.log", "wb")
        _cap = subprocess.Popen(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "gdigrab", "-framerate", "30", "-i", "desktop",
             "-vf", "scale=-2:1080", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an",
             "-g", "30", "-f", "segment", "-segment_time", str(SEG), "-segment_format", "mpegts",
             "-segment_wrap", str(minutes * 60 // SEG + 1), "-reset_timestamps", "1", str(_buf() / "s%05d.ts")],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=_cap_log, creationflags=NO_WINDOW)
        if act == "clip":
            raise RuntimeError("The PC wasn't recording, so there is nothing to clip yet: it has started now. Ask again afterwards.")
        return f"Recording the PC screen into a {minutes}-minute buffer."
    if act == "clip":
        if not running:
            raise RuntimeError("ffmpeg stopped by itself on the PC; say 'status' to see why.")
        want = min(max(float(args.get("seconds") or 30), 1), MAX_CLIP_S)
        segs = _segments()[-(int(want // SEG) + 2):]  # a spare for the partly written newest one
        if not segs:
            raise RuntimeError("No footage has arrived on the PC yet; wait a few seconds.")
        with tempfile.TemporaryDirectory() as tmp:
            lst, joined, out = Path(tmp, "l.txt"), Path(tmp, "j.mp4"), Path(tmp, "clip.mp4")
            lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in segs), encoding="utf-8")
            for cmd in (["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)],
                        ["-sseof", f"-{want}", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(out)]):
                r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *cmd], capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW)
                if r.returncode:
                    raise RuntimeError(f"ffmpeg: {r.stderr.strip()[-300:]}")
            return {"text": "clip.mp4", "data": base64.b64encode(out.read_bytes()).decode()}
    raise ValueError("action must be start, stop, status or clip.")


ROUTES = {"/read": read, "/change": change, "/run": run, "/capture": capture}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        given = self.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(given, f"Bearer {TOKEN}".encode()):
            return self.reply(401, "Wrong or missing token.", True)
        route = ROUTES.get(self.path)
        size = int(self.headers.get("Content-Length") or 0)
        if route is None or size > MAX_BODY:
            return self.reply(404 if route is None else 413, "No such call.", True)
        try:
            result, extra = route(json.loads(self.rfile.read(size) or b"{}")), {}
            if isinstance(result, dict):  # {"text", "data"}: a file's bytes
                extra = result
                result = extra.pop("text")
            text, err = result if isinstance(result, tuple) else (result, False)
        except Exception as e:  # COMError, TypeError, ...: still an answer, not "the PC isn't reachable"
            text, err, extra = f"{type(e).__name__}: {e}" if not str(e) else str(e), True, {}
        self.reply(200, text, err, **extra)

    def reply(self, code: int, text: str, is_error: bool, **extra: Any) -> None:
        body = json.dumps({"text": text, "is_error": is_error, **extra}, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if len(TOKEN) < 20:
        sys.exit(f"No token in {TOKEN_FILE}: run install.ps1 first.")
    if sys.stderr is None:  # pythonw has no console: log next to the script
        sys.stderr = open(Path(__file__).with_name("ultron_pc.log"), "a", buffering=1, encoding="utf-8")
    stop_old_copies()
    if "--no-update" not in sys.argv and update():
        # New code on disk: run it, and pass its exit code on so the task's restart-on-failure still works.
        sys.exit(subprocess.call([sys.executable, __file__, "--no-update"]))
    # ponytail: one request at a time (keeps pycaw's COM on one thread). Fine for one Ultron.
    HTTPServer.allow_reuse_address = False  # on Windows it lets a second copy share the port, and the old one answers
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
