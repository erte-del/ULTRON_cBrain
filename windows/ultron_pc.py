"""Ultron on a Windows PC: the same reads and changes as mac_read / mac_change, over Tailscale.

  POST /read   {"what": "status" | "clipboard" | "files", "query"}             = mac_read
  POST /change {"action": "open_app" | "open_url" | "open_file" | "open_terminal" | "copy" |
                "volume" | "mute" | "dark_mode" | "media" | "move" | "trash", ...}  = mac_change
  POST /run    {"code", "lang": "python" | "powershell"}                       = run_python
  -> {"text": "...", "is_error": bool}. Every call needs "Authorization: Bearer <token.txt>".

It listens on 127.0.0.1 only; `tailscale serve` passes your own devices through to it over
HTTPS. Nothing reaches the public internet. Files never leave ULTRON_PC_FOLDER, nothing is
overwritten, "trash" goes to the Recycle Bin, only documents open, and apps only from the Start menu.
/run is NOT sandboxed (Windows has no sandbox-exec): it runs as you, in the folder's Output
subfolder, killed after 60 s. Ultron asks you before every /run.

Setup: install Python 3.11+ and Tailscale (the Mac's account), then run install.ps1 once.
"""

import ctypes
import difflib
import hmac
import json
import os
import re
import subprocess
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
RUN_TIMEOUT_S = 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DOCUMENTS = {"pdf", "txt", "md", "rtf", "csv", "tsv", "json", "xml", "log", "doc", "docx", "xls", "xlsx",
             "ppt", "pptx", "odt", "ods", "png", "jpg", "jpeg", "gif", "heic", "webp", "tiff", "bmp", "svg",
             "mp3", "m4a", "wav", "aac", "flac", "mp4", "mov", "m4v", "mkv", "zip"}
ACTIONS = ["open_app", "open_url", "open_file", "open_terminal", "copy", "volume", "mute", "dark_mode", "media", "move", "trash"]
MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


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


def in_folder(path: str) -> Path:
    root = folder()
    full = (root / Path(path.strip()).expanduser()).resolve()  # also follows links out
    if not full.is_relative_to(root):
        raise ValueError(f"{path!r} is outside Ultron's folder ({root}).")
    return full


def rel(p: Path) -> str:
    return p.relative_to(folder()).as_posix() or "."


def find_files(query: str) -> list[dict[str, Any]]:
    root, words, found = folder(), query.lower().split(), []
    for p in root.rglob("*"):
        r = p.relative_to(root)
        if any(part.startswith(".") for part in r.parts) or not all(w in r.as_posix().lower() for w in words):
            continue
        st = p.stat()
        found.append({"path": r.as_posix() + ("/" if p.is_dir() else ""), "size": st.st_size,
                      "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")})
    return sorted(found, key=lambda f: f["modified"], reverse=True)


def move(path: str, to: str) -> str:
    src, dest = in_folder(path), in_folder(to)
    if src == folder():
        raise ValueError("Ultron's folder itself can't be moved.")
    if not src.exists():
        raise ValueError(f"{path!r} doesn't exist in Ultron's folder.")
    if dest.is_dir():
        dest = dest / src.name
    if dest.exists():
        raise ValueError(f"{rel(dest)!r} already exists; nothing is ever overwritten. Pick another name.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    return f"Moved {rel(src)} → {rel(dest)}."


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


def open_app(name: str) -> str:
    """By its Start menu name; Store apps too. Only what the Start menu lists."""
    apps = json.loads(ps("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress") or "[]")
    apps = {a["Name"].lower(): a for a in ([apps] if isinstance(apps, dict) else apps)}
    app = apps.get(name.strip().lower())
    if app is None:
        near = difflib.get_close_matches(name.strip().lower(), apps, n=5, cutoff=0.4)
        raise ValueError(f"No Start menu app called {name!r}." +
                         (f" Close: {', '.join(apps[n]['Name'] for n in near)}." if near else ""))
    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app["AppID"]])
    return f"Opened {app['Name']}."


def show_in_explorer(p: Path) -> None:
    subprocess.Popen(f'explorer.exe /select,"{p}"')


def dark_mode(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if on else 1)
    # Tell open windows and the taskbar to repaint (WM_SETTINGCHANGE).
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "ImmersiveColorSet", 2, 1000, None)


def trash(path: str) -> str:
    p = in_folder(path)
    if p == folder() or not p.exists():
        raise ValueError(f"{path!r} isn't a file or folder in Ultron's folder.")
    # The path goes in on stdin, never into the script text.
    ps("$p=[Console]::In.ReadToEnd(); Add-Type -AssemblyName Microsoft.VisualBasic; "
       "if (Test-Path -LiteralPath $p -PathType Container) "
       "{[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p,'OnlyErrorDialogs','SendToRecycleBin')} "
       "else {[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin')}",
       stdin=str(p))
    return f"Moved {rel(p)} to the Recycle Bin (it can be restored from there)."


# --- the two calls -------------------------------------------------------------------

def read(args: dict[str, Any]) -> str:
    what = args.get("what")
    if what == "status":
        return status()
    if what == "clipboard":
        return ps("Get-Clipboard -Raw")[:MAX_CHARS] or "The clipboard is empty or isn't text."
    if what == "files":
        found = find_files(str(args.get("query") or ""))
        more = f" (newest {MAX_FILES} of {len(found)})" if len(found) > MAX_FILES else ""
        return f"In {folder()}{more}: " + json.dumps(found[:MAX_FILES]) if found else f"Nothing matches in {folder()}."
    raise ValueError(f"what must be one of status, clipboard, files (got {what!r}).")


def change(args: dict[str, Any]) -> str:
    action = args.get("action")
    name, path, text = str(args.get("name") or ""), str(args.get("path") or ""), str(args.get("text") or "")
    on = bool(args.get("on", True))
    if action == "open_app":
        return open_app(name)
    if action == "open_url":
        url = str(args.get("url") or "").strip()
        if not re.match(r"https?://[^\s/]", url):
            raise ValueError("Only http:// and https:// addresses can be opened.")
        os.startfile(url)
        return f"Opened {url} in the browser."
    if action == "open_file":
        p = in_folder(path)
        if p.is_dir():
            os.startfile(p)  # a folder opens in Explorer
            return f"Opened {rel(p)} in Explorer."
        if not p.is_file():
            raise ValueError(f"{path!r} doesn't exist in Ultron's folder.")
        if p.suffix.lower().lstrip(".") not in DOCUMENTS:
            show_in_explorer(p)
            raise ValueError(f"Ultron only opens documents, not {p.suffix or 'files without a type'}; "
                             f"showed {rel(p)} in Explorer instead.")
        os.startfile(p)
        return f"Opened {rel(p)}."
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
        return move(path, str(args.get("to") or ""))
    if action == "trash":
        return trash(path)
    raise ValueError(f"action must be one of {', '.join(ACTIONS)} (got {action!r}).")


def run(args: dict[str, Any]) -> tuple[str, bool]:
    """Python or PowerShell, as you, in Output. (output, failed)."""
    code, lang = str(args.get("code") or ""), args.get("lang") or "python"
    if not code.strip():
        raise ValueError("run needs code.")
    if lang == "python":
        cmd, stdin = [sys.executable, "-I", "-"], code
    elif lang == "powershell":
        import base64
        encoded = base64.b64encode(code.encode("utf-16-le")).decode()
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


ROUTES = {"/read": read, "/change": change, "/run": run}


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
            result = route(json.loads(self.rfile.read(size) or b"{}"))
            text, err = result if isinstance(result, tuple) else (result, False)
        except (RuntimeError, OSError, ValueError, ImportError, subprocess.TimeoutExpired) as e:
            text, err = str(e), True
        self.reply(200, text, err)

    def reply(self, code: int, text: str, is_error: bool) -> None:
        body = json.dumps({"text": text, "is_error": is_error}, ensure_ascii=False).encode()
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
    # ponytail: one request at a time (keeps pycaw's COM on one thread). Fine for one Ultron.
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
