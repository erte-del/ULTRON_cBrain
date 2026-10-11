"""Text to speech: Ultron's voice in voice mode.

Kokoro (the same voices as Reels, bm_lewis by default: JARVIS_VOICE) through ONNX, on this
computer (Mac or Windows, on the CPU, ~5x faster than real time). Its files (~350 MB)
download once, the first time voice mode is turned on, into storage/voice/kokoro.

The reply streams in as text; Sentences cuts it into sentences as they finish, cleaned of
markdown (no code, tables or links read out), so the first one plays while Claude is still
writing the rest.
"""

import io
import json
import logging
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

import config

log = logging.getLogger("ultron.tts")

FOLDER = config.STORAGE_DIR / "voice" / "kokoro"
FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]
DOWNLOAD = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"

ECHO_S = 30  # how long what Ultron said counts as a possible echo
ELEVEN_URL = "https://api.elevenlabs.io/v1/"
USAGE_FILE = config.STORAGE_DIR / "voice" / "voice_usage.jsonl"  # one line per sentence and per reply
_reply_chars = 0  # ElevenLabs characters in the reply being spoken
last_error = ""  # why ElevenLabs last failed, for voice_usage
_prev = ""  # the sentence before, in this reply: tells ElevenLabs how to carry the tone on
_engine = None
_lock = threading.Lock()
_said: list[tuple[float, str]] = []  # (when, sentence): what Ultron said out loud lately


def ready() -> bool:
    return _engine is not None


def load():
    """Kokoro, loaded (and downloaded) the first time it's needed."""
    global _engine
    with _lock:
        if _engine is None:
            FOLDER.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                path = FOLDER / name
                if not path.exists():
                    part = path.with_name(name + ".part")
                    with urllib.request.urlopen(DOWNLOAD + name, timeout=60, context=config.ssl_context()) as r, \
                            open(part, "wb") as f:
                        shutil.copyfileobj(r, f)
                    part.replace(path)
            from kokoro_onnx import Kokoro

            _engine = Kokoro(str(FOLDER / FILES[0]), str(FOLDER / FILES[1]))
    return _engine


def eleven_ready() -> bool:
    return config.TTS == "elevenlabs" and bool(config.ELEVEN_KEY and config.ELEVEN_VOICE)


def _eleven(text: str) -> bytes:
    """One sentence from ElevenLabs as WAV (24 kHz, the same format Kokoro gives). Raises OSError."""
    body = json.dumps({"text": text, "model_id": config.ELEVEN_MODEL, **({"previous_text": _prev} if _prev else {})}).encode()
    req = urllib.request.Request(
        f"{ELEVEN_URL}text-to-speech/{config.ELEVEN_VOICE}?output_format=wav_24000", data=body, method="POST",
        headers={"xi-api-key": config.ELEVEN_KEY, "Content-Type": "application/json", "Accept": "audio/wav"})
    with urllib.request.urlopen(req, timeout=30, context=config.ssl_context()) as r:
        return r.read()


def _why(e: OSError) -> str:
    """'HTTP 402: Free users cannot use library voices...' - ElevenLabs says why in the body."""
    if not isinstance(e, urllib.error.HTTPError):
        return str(e)
    try:
        detail = json.loads(e.read())["detail"]
        return f"HTTP {e.code}: {detail['message'] if isinstance(detail, dict) else detail}"
    except (OSError, ValueError, KeyError, TypeError):
        return f"HTTP {e.code}"


def _record(kind: str, engine: str, chars: int) -> None:
    """Append to USAGE_FILE: what the voice spoke, and with which engine."""
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with USAGE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "engine": engine, "chars": chars}) + "\n")


def reply_done() -> None:
    """A whole reply has been spoken: note its ElevenLabs characters, then start the count again."""
    global _reply_chars, _prev
    _prev = ""
    _record("reply", "elevenlabs" if _reply_chars else "kokoro", _reply_chars)
    _reply_chars = 0


def speak(text: str) -> bytes:
    """One sentence as a WAV file (24 kHz, 16-bit mono). ElevenLabs if it's set up and works."""
    global _reply_chars, _prev, last_error
    if eleven_ready():
        try:
            wav = _eleven(text)
            _record("sentence", "elevenlabs", len(text))
            _reply_chars += len(text)
            _prev = text
            return wav
        except OSError as e:  # HTTP errors too: out of characters, bad key, no network
            last_error = _why(e)
            log.warning("ElevenLabs failed (%s); Kokoro says this sentence", last_error)
            _record("sentence", "kokoro-fallback", 0)
    return _kokoro(text)


def _kokoro(text: str) -> bytes:
    voice = config.VOICE
    # The first letter is the accent: bm_lewis is a British man, am_onyx an American one.
    audio, rate = load().create(text, voice=voice, lang="en-gb" if voice[:1] == "b" else "en-us")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


# A sentence ends at . ! ? followed by a space and a capital, digit or quote (markdown
# around them, as in **Done.** Next, doesn't hide the end)...
_END = re.compile(r"(?<=[.!?…])[\"'”)*_]*\s+(?=[\"'“(*_]*[A-Z0-9])")
# ...unless the full stop belongs to one of these.
_ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|Prof|Mt|vs|etc|e\.g|i\.e|approx|No)\.$", re.I)


# The start of a reply is said at once: its first few words (or up to its first pause, if
# sooner) go out as soon as they're written, and Ultron talks while it writes the rest.
# Fewer words = sooner, but a choppier start (each piece is said on its own).
FIRST_WORDS = 3
_PAUSE = re.compile(r"[,;:—–]\s+|\s[-–—]\s+")
_FIRST = re.compile(r"\s*(?:\S+\s+){%d}" % FIRST_WORDS)


def split(text: str) -> list[str]:
    """Sentences in text; the last one may be unfinished."""
    out: list[str] = []
    start = 0
    for m in _END.finditer(text):
        if _ABBREV.search(text[start:m.start()]):
            continue
        out.append(text[start:m.start()])
        start = m.end()
    out.append(text[start:])
    return out


def clean(text: str) -> str:
    """What to say out loud: markdown marks, links and web addresses removed."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"^\s*(?:#+|[-*+•]|\d+[.)]|>)\s+", "", text)  # headings, bullets, quotes
    text = re.sub(r"[*_`~|]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if re.search(r"[A-Za-z0-9]", text) else ""


class Sentences:
    """Feed it the reply as it streams; it gives back each sentence ready to say."""

    def __init__(self) -> None:
        self._line = ""  # the unfinished line
        self._code = False  # inside a ``` code block: never read out
        self._started = False  # something has been said already

    def _done_line(self, line: str) -> list[str]:
        if line.lstrip().startswith("```"):
            self._code = not self._code
            return []
        if self._code or line.lstrip().startswith("|"):  # code, tables
            return []
        return [c for s in split(line) if (c := clean(s))]

    def feed(self, text: str) -> list[str]:
        self._line += text
        out: list[str] = []
        while "\n" in self._line:
            line, self._line = self._line.split("\n", 1)
            out += self._done_line(line)
        # Finished sentences in the line still being written.
        if not self._code and not self._line.lstrip().startswith(("|", "`")):
            *done, self._line = split(self._line)
            out += [c for s in done if (c := clean(s))]
            if not self._started and not out and not eleven_ready():  # ElevenLabs answers fast: whole sentences sound better
                ends = [m.end() for m in (_PAUSE.search(self._line), _FIRST.match(self._line)) if m]
                if ends and (c := clean(self._line[:min(ends)])):
                    out.append(c)
                    self._line = self._line[min(ends):]
        self._started = self._started or bool(out)
        return out

    def flush(self) -> list[str]:
        """The rest, once the reply is complete."""
        line, self._line = self._line, ""
        return self._done_line(line)


def said(text: str) -> None:
    """Remember a sentence Ultron is saying, to tell its own voice from yours (is_echo)."""
    now = time.time()
    _said[:] = [(t, s) for t, s in _said if now - t < ECHO_S] + [(now, text)]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def is_echo(heard: str) -> bool:
    """True if what the mic heard is Ultron's own voice from the speakers, not you: almost
    all of its words are in what Ultron just said. Short ones ("stop") are always you."""
    words = _words(heard)
    if len(words) < 3:
        return False
    recent = {w for t, s in _said if time.time() - t < ECHO_S for w in _words(s)}
    return sum(w in recent for w in words) >= 0.8 * len(words)
