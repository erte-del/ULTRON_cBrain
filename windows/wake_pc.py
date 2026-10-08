"""Windows PC: say "Hey Ultron" and the Mac's Ultron opens.

Ultron's brain runs only on the Mac. This PC runs no Ultron backend: it only listens to the
default microphone, and when an utterance starts with "Hey Ultron" it opens the Mac's Ultron
page (over Tailscale, like the phone) in its own full-screen Edge window. While that window is
open the page does the listening, so this stays quiet until it's closed.

Audio never leaves this PC: speech is cut into utterances by Silero VAD (backend/voice/vad.py)
and checked by faster-whisper small.en on the CPU. Nothing is sent anywhere.

Settings: windows/wake_pc.env (see wake_pc.env.example). Log: windows/wake_pc.log.
    ..\\backend\\.venv\\Scripts\\python.exe wake_pc.py           listen (what the task runs)
    ..\\backend\\.venv\\Scripts\\python.exe wake_pc.py --check   is the Mac's page reachable?
    ..\\backend\\.venv\\Scripts\\python.exe wake_pc.py --open    open the window once, as on a wake
Started at logon, with no window, by wake_pc.ps1 on.
"""

import asyncio
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from voice import vad  # noqa: E402  (only numpy; it doesn't import the backend's config)

ENV_FILE = HERE / "wake_pc.env"
LOG_FILE = HERE / "wake_pc.log"
MODELS = HERE / "whisper"  # faster-whisper downloads small.en here once (~250 MB)
PROFILE = HERE / "edge-profile"  # the Edge window's own profile: remembers the mic permission

REOPEN_S = 60  # the mic is reopened this often (when you aren't talking), so a new default mic is used
RETRY_S = 10  # no mic: try again after this long
OPENING_S = 20  # after opening the window, give it this long to appear before listening again
WINDOW_CHECK_S = 3  # how often to look for the open window
NO_SPEECH = 0.6  # parts Whisper thinks are more likely silence than this are dropped

# Copied from backend/voice/stt.py (which imports the full backend's config).
# The hint makes Whisper write "Ultron" instead of Aldron, Uldren or Aldrin.
WAKE_HINT = "Hey Ultron."
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "oi", "yo"}

log = logging.getLogger("wake_pc")
_model = None


def after_wake(text: str) -> str | None:
    """What follows "(Hey) Ultron" at the start of text ("" if nothing does), or None when
    it isn't addressed to Ultron ("I was talking about Ultron" isn't)."""
    for i, word in enumerate(re.finditer(r"[\w']+", text)):
        w = word.group().lower()
        if w == "ultron":
            return text[word.end():].lstrip(" ,.!?;:-—").strip()
        if w not in GREETINGS or i >= 2:
            return None
    return None


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    """KEY=value lines; # starts a comment. Quotes around a value are dropped."""
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():  # -sig: PowerShell 5 writes a BOM
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip().strip("\"'")
    return out


SETTINGS = read_env()
URL = SETTINGS.get("ULTRON_URL", "").rstrip("/")  # https://<mac-name>.<tailnet>.ts.net
OPEN_WITH = SETTINGS.get("ULTRON_OPEN", "")  # your own script/shortcut instead of the Edge window
MODEL = SETTINGS.get("WAKE_MODEL", "small.en")


# --- Opening the Mac's Ultron -------------------------------------------------------------

def edge_command(url: str) -> list[str]:
    """Ultron's page full screen in an Edge window of its own. Its own profile means its own
    browser process, so the flags work even if Edge is already open."""
    return ["cmd", "/c", "start", "", "msedge", f"--app={url}", "--start-fullscreen",
            "--autoplay-policy=no-user-gesture-required", f"--user-data-dir={PROFILE}"]


def open_command(target: str) -> list[str] | None:
    """How to run your own opener: a PowerShell script, a batch file, or anything else
    Windows can open (a shortcut, a URL). None means os.startfile."""
    ext = Path(target).suffix.lower()
    if ext == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", target]
    if ext in (".bat", ".cmd"):
        return ["cmd", "/c", target]
    if ext in (".py", ".pyw"):
        return [sys.executable, target]
    return None


def open_window() -> None:
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if OPEN_WITH:
        cmd = open_command(OPEN_WITH)
        if cmd is None:
            os.startfile(OPEN_WITH)  # .lnk, .url, .exe, …
        else:
            subprocess.Popen(cmd, creationflags=no_window)
    else:
        url = URL + "/?wake=1"  # ?wake: the page opens in voice mode and says hello
        log.info("Opening %s", url)
        subprocess.Popen(edge_command(url), creationflags=no_window)


def window_open() -> bool:
    """Is Ultron's Edge window open? Looks for an msedge.exe whose command line has its
    profile folder. (Opened with your own script, this can't tell: OPENING_S covers it.)"""
    folder = str(PROFILE).replace("'", "''")
    ps = ("@(Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{folder}') }}).Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, encoding="utf-8", timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return int(out.strip() or 0) > 0
    except Exception as e:
        log.warning("Couldn't check for the Ultron window: %r", e)
        return False


def check_url(url: str = URL) -> str:
    """Load the Mac's page once, from this PC. Returns what happened, in words."""
    if not url:
        return f"No ULTRON_URL in {ENV_FILE}."
    try:
        with urllib.request.urlopen(url + "/", timeout=10) as r:
            page = r.read(4096).decode("utf-8", "replace")
        return f"OK: {url} answered {r.status}" + ("" if "<html" in page.lower() else " (but not with a page)")
    except Exception as e:
        return f"Can't load {url}: {e}"


# --- Listening ----------------------------------------------------------------------------

def load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=str(MODELS))
    return _model


def woken(audio) -> str | None:
    """None if the utterance doesn't start with "Hey Ultron"; else what followed it."""
    segments, _ = load().transcribe(audio, language="en" if MODEL.endswith(".en") else None, beam_size=5,
                                    temperature=0.0, initial_prompt=WAKE_HINT,
                                    vad_filter=False, condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < NO_SPEECH).strip()
    return after_wake(text)


class Window:
    """Whether Ultron's window is open, checked in the background every few seconds."""

    def __init__(self):
        self.open = False
        self.opened_at = -OPENING_S

    def busy(self, now: float) -> bool:
        return self.open or now - self.opened_at < OPENING_S

    async def watch(self) -> None:
        while True:
            was, self.open = self.open, await asyncio.to_thread(window_open)
            if was != self.open:
                log.info("Ultron window %s", "open: not listening" if self.open else "closed: listening again")
            await asyncio.sleep(WINDOW_CHECK_S)


async def listen() -> None:
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    log.info("Loading the speech model (%s)…", MODEL)
    await asyncio.to_thread(load)
    window = Window()
    asyncio.create_task(window.watch())
    ears = vad.Endpointer()
    mic = None
    while True:
        chunks: asyncio.Queue[bytes] = asyncio.Queue()
        try:
            sd._terminate()  # forget the old device list, so the current default mic is found
            sd._initialize()
            with sd.RawInputStream(samplerate=vad.RATE, channels=1, dtype="int16", blocksize=vad.FRAME,
                                   callback=lambda data, *_: loop.call_soon_threadsafe(chunks.put_nowait, bytes(data))):
                if (name := sd.query_devices(kind="input")["name"]) != mic:  # said once per mic, not every reopen
                    log.info("Listening for \"Hey Ultron\" on %s", name)
                    mic = name
                started = loop.time()
                while ears.speaking or loop.time() - started < REOPEN_S:
                    pcm = await asyncio.wait_for(chunks.get(), 2)  # nothing for 2 s: the mic is gone
                    if window.busy(loop.time()):
                        ears.reset()
                        continue
                    if (audio := ears.feed(pcm)) is None:
                        continue
                    said = await asyncio.to_thread(woken, audio)
                    if said is not None and not window.busy(loop.time()):
                        log.info("Heard \"Hey Ultron\": opening the Mac's Ultron")
                        window.opened_at = loop.time()
                        open_window()
        except Exception as e:  # no mic, or it was unplugged: try again soon
            log.warning("Listening paused: %r", e)
            await asyncio.sleep(RETRY_S)
        ears.reset()


def setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=500_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
    for noisy in ("httpx", "huggingface_hub"):  # the model download's request-by-request chatter
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    if "--check" in sys.argv:
        print(check_url())
        return
    if not URL and not OPEN_WITH:
        log.error("Put ULTRON_URL (or ULTRON_OPEN) in %s first", ENV_FILE)
        sys.exit(1)
    if "--open" in sys.argv:
        open_window()
        return
    log.info("Started (pid %d)", os.getpid())
    try:
        asyncio.run(listen())
    except Exception:
        log.exception("Stopped")
        raise


if __name__ == "__main__":
    main()
