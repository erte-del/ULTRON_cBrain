"""Settings loaded from .env."""

import functools
import logging
import os
import re
import ssl
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
STORAGE_DIR = BACKEND_DIR / "storage"

load_dotenv(ROOT_DIR / ".env")

# Ultron.app and launchd start him with PATH=/usr/bin:/bin:..., which hides Homebrew's ffmpeg/ffprobe.
if sys.platform == "darwin":
    os.environ["PATH"] = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "")])

HOST = os.getenv("JARVIS_HOST", "127.0.0.1")
PORT = int(os.getenv("JARVIS_PORT", "8000"))
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
# Ultron's own Telegram bot, for texting you (tools/telegram.py).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
# Ultron's own Instagram (tools/instagram.py). Ultron renews it into storage/instagram_token.json.
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
# The MacroDroid webhook on your phone, for its volume (tools/phone.py).
MACRODROID_WEBHOOK = os.getenv("MACRODROID_WEBHOOK", "").strip()
# Teams on the web, which Ultron reads in Chrome (tools/homework.py).
HOMEWORK_URL = os.getenv("JARVIS_HOMEWORK_URL", "").strip() or "https://teams.cloud.microsoft/"
# The Amazon site Ultron browses in Chrome (tools/amazon.py).
AMAZON_URL = (os.getenv("JARVIS_AMAZON_URL", "").strip() or "https://www.amazon.ae").rstrip("/")
# Your Obsidian vault: the folder Ultron searches, reads and (with your approval) writes notes in.
_VAULT = os.getenv("JARVIS_VAULT", "").strip()
VAULT_DIR = Path(_VAULT).expanduser() if _VAULT else None
# Ultron's own folder: it changes files here without asking, and its
# sandboxed Python reads from here (results go to its Output subfolder).
FILES_DIR = Path(os.getenv("JARVIS_FILES_DIR", "").strip() or "~/Jarvis Files").expanduser()
# Your folders Ultron may also search and open files in, and (with your approval) move, rename
# and trash them. The rest of the disk is out of reach, and so is Ultron's own code (ROOT_DIR).
# macOS must allow it: System Settings → Privacy & Security → Files & Folders → Ultron.
ALLOWED_DIRS = [Path.home() / d for d in ("Desktop", "Documents", "Downloads")]
# Ready-made 3D models Ultron looks in first (tools/library3d.py). Drop .glb files in here.
LIBRARY_3D_DIR = Path(os.getenv("JARVIS_3D_LIBRARY", "").strip() or BACKEND_DIR / "library3d").expanduser()
# 3DAssets.dev: a free online library of CC0 .glb models. Ultron searches it through its public
# MCP server (no key needed to read) and downloads the .glb from one of these hosts only.
# Empty URL = don't use it.
ASSETS_3D_MCP_URL = os.getenv("JARVIS_3DASSETS_MCP", "https://3dassets.dev/mcp").strip()
ASSETS_3D_HOSTS = [h.strip().lower() for h in os.getenv("JARVIS_3DASSETS_HOSTS", "3dassets.dev").split(",") if h.strip()]
BLENDER_PATH = os.getenv("BLENDER_PATH", "/Applications/Blender.app/Contents/MacOS/Blender")
# Local video generation (Wan 2.1 through mlx-video). scripts/setup_video.sh puts its
# own Python and the model weights here.
WAN_DIR = Path(os.getenv("JARVIS_WAN_DIR") or STORAGE_DIR / "wan")
# Local image generation (FLUX.2 Klein through mflux): scripts/setup_images.sh.
FLUX_DIR = Path(os.getenv("JARVIS_FLUX_DIR") or STORAGE_DIR / "flux")

# Voice mode: the faster-whisper model that turns your speech into text (voice/stt.py).
# small.en is fast and English only; "small" or "large-v3-turbo" also hear other languages.
STT_MODEL = os.getenv("JARVIS_STT_MODEL", "").strip() or "small.en"
# With a Groq key (console.groq.com, free), your speech goes to Groq's Whisper large-v3-turbo
# instead: more accurate and faster. The local model above stays the fallback.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
# Ultron's voice when it answers you in voice mode (voice/tts.py): a Kokoro voice, the same
# ones as Reels. b = British, a = American; m = man, f = woman. bm_lewis: low and steady.
VOICE = os.getenv("JARVIS_VOICE", "").strip() or "bm_lewis"

# How hard Claude thinks before answering: low | medium | high | xhigh | max.
# Thinking was the biggest single use of the Pro limit, so the default is medium.
EFFORT = os.getenv("JARVIS_EFFORT", "medium").strip().lower()
if EFFORT not in ("low", "medium", "high", "xhigh", "max"):
    raise SystemExit(f"JARVIS_EFFORT={EFFORT!r}: use low, medium, high, xhigh or max")

# Which claude.ai connectors Ultron loads: "all", or names like "Gmail, Canva".
# Each connector's tool list goes into every new conversation, so fewer = cheaper.
CONNECTORS = [c.strip().lower() for c in os.getenv("JARVIS_CONNECTORS", "all").split(",") if c.strip()]

# After this many minutes without a message, a big conversation starts over fresh.
# Claude's copy of the conversation (the cache) expires after an hour, so the next
# message would otherwise send the whole thing again at full price. 0 = never.
NEW_CHAT_AFTER_IDLE_MIN = int(os.getenv("JARVIS_NEW_CHAT_AFTER_IDLE_MIN", "60"))

# Scheduled jobs (scheduler.py). Watchers ("tell me when…") don't run during quiet hours;
# jobs you set for a time of day always do. "" = no quiet hours.
QUIET_HOURS = os.getenv("JARVIS_QUIET_HOURS", "23:00-07:00").strip()
if QUIET_HOURS and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", QUIET_HOURS):
    raise SystemExit(f"JARVIS_QUIET_HOURS={QUIET_HOURS!r}: use HH:MM-HH:MM, e.g. 23:00-07:00")
# Jobs are skipped once this much of the Pro plan's 5-hour window is used (0-1), so
# background work never locks you out of Ultron yourself.
JOBS_MAX_USAGE = float(os.getenv("JARVIS_JOBS_MAX_USAGE", "0.8"))

if HOST not in ("127.0.0.1", "localhost", "::1"):
    raise SystemExit(f"JARVIS_HOST={HOST!r} refused: Ultron only listens on this machine.")

# Ultron on your phone: the address "tailscale serve" gives this Mac. Tailscale passes
# your own devices through to 127.0.0.1, so Ultron still only listens on this machine.
REMOTE_ORIGIN = os.getenv("JARVIS_REMOTE_ORIGIN", "").strip().rstrip("/")
if REMOTE_ORIGIN and not re.fullmatch(r"https://[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net", REMOTE_ORIGIN):
    raise SystemExit(f"JARVIS_REMOTE_ORIGIN={REMOTE_ORIGIN!r}: use your Tailscale address, e.g. https://mac.tail1234.ts.net")

# The user's Windows PC (optional): the address "tailscale serve" gives it, and the token
# windows/ultron_pc.py checks. Only a tailnet address, so it's never the public internet.
PC_URL = os.getenv("JARVIS_PC_URL", "").strip().rstrip("/")
PC_TOKEN = os.getenv("JARVIS_PC_TOKEN", "").strip()
if PC_URL and not re.fullmatch(r"https://[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net", PC_URL):
    raise SystemExit(f"JARVIS_PC_URL={PC_URL!r}: use the PC's Tailscale address, e.g. https://pc.tail1234.ts.net")

# Which brain Ultron runs on. You can switch in the UI (gear icon); this is the choice
# at startup.
#   claude    - Claude on your Pro login (the default)
#   omniroute - OmniRoute (npm i -g omniroute), a gateway to other providers' models.
#               Doesn't use your Pro limit. The claude.ai connectors (Gmail, ...) stay
#               off, so your emails never go to those providers.
PROVIDERS = ("claude", "omniroute")
PROVIDER = os.getenv("JARVIS_PROVIDER", "claude").strip().lower()
if PROVIDER not in PROVIDERS:
    raise SystemExit(f"JARVIS_PROVIDER={PROVIDER!r}: use {' or '.join(PROVIDERS)}")

GATEWAY_URL = (os.getenv("JARVIS_GATEWAY_URL") or "http://localhost:20128").strip().rstrip("/")
GATEWAY_KEY = os.getenv("JARVIS_GATEWAY_KEY", "").strip()
if not GATEWAY_URL.startswith(("http://", "https://")):
    raise SystemExit(f"JARVIS_GATEWAY_URL={GATEWAY_URL!r}: must start with http:// or https://")
# Gateway models you can switch between in the app, as OmniRoute names them
# ("provider/model"). The first is the default. Each needs its provider connected in
# OmniRoute's dashboard.
GATEWAY_MODELS = [
    m.strip()
    for m in os.getenv("JARVIS_GATEWAY_MODELS", "gemini/gemini-3.1-flash-lite, gemini/gemini-3.8-flash, groq/openai/gpt-oss-120b").split(",")
    if m.strip()
]
if not GATEWAY_MODELS:
    raise SystemExit("JARVIS_GATEWAY_MODELS is empty: list at least one OmniRoute model")
# Claude Code's own sonnet / opus / haiku names (e.g. for WebFetch) go to this one.
GATEWAY_MODEL = GATEWAY_MODELS[0]

# If any of these are set, Claude Code uses them instead of the Pro login.
_API_AUTH_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
# Where Claude Code's model names go. Your own values (from .env) are kept for the
# gateway only: on the Pro login they would ask Claude for a model it doesn't have.
_MODEL_VARS = ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL")
_GATEWAY_MODELS = {var: os.environ.pop(var) for var in _MODEL_VARS if os.environ.get(var)}
# All of the above: the terminal tab leaves them out, so `claude` there uses your own login.
CLAUDE_ENV_VARS = (*_API_AUTH_VARS, *_MODEL_VARS)

log = logging.getLogger("ultron.config")
_gateway_env_set = False  # True while the variables below were put there by Ultron


def set_login(provider: str = "claude") -> None:
    """Point Claude Code at the Pro login (provider "claude") or at the gateway.

    The Claude Code subprocesses (Ultron and ask_expert) inherit this process's
    environment when they start, so setting it here is enough.
    """
    global _gateway_env_set
    for var in (*_API_AUTH_VARS, *_MODEL_VARS):
        removed = os.environ.pop(var, None) is not None
        if removed and not _gateway_env_set and var in _API_AUTH_VARS:
            log.warning("Removed %s from the environment (Ultron uses the Pro login).", var)
    _gateway_env_set = provider == "omniroute"
    if _gateway_env_set:
        os.environ["ANTHROPIC_BASE_URL"] = GATEWAY_URL
        # Always set a token: without one Claude Code would send the Pro login's token
        # to the gateway. Placeholder for gateways that don't check keys.
        os.environ["ANTHROPIC_AUTH_TOKEN"] = GATEWAY_KEY or "ultron-gateway"
        for var in _MODEL_VARS:
            os.environ[var] = _GATEWAY_MODELS.get(var, GATEWAY_MODEL)


@functools.cache
def ssl_context() -> ssl.SSLContext:
    """For urlopen to HTTPS sites: Python's own certificates plus the Mac keychain's, like curl.

    Networks that re-sign HTTPS (a school firewall) put their own certificate in the keychain;
    without it every HTTPS call fails with "self-signed certificate in certificate chain".
    """
    ctx = ssl.create_default_context()
    try:
        pem = subprocess.run(["security", "find-certificate", "-a", "-p"],
                             capture_output=True, text=True, timeout=10).stdout
        if pem:
            ctx.load_verify_locations(cadata=pem)
    except (OSError, subprocess.SubprocessError, ssl.SSLError) as e:
        log.warning("Couldn't load the keychain's certificates: %s", e)
    # Python 3.13's strict check rejects firewall CAs that don't mark Basic Constraints
    # critical; curl and Python 3.12 accept them. The chain is still verified.
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx
