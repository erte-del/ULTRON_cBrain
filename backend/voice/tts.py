"""Text to speech: Ultron's voice in voice mode.

Kokoro (the same voices as Reels, bm_lewis by default: JARVIS_VOICE) through ONNX, on this
computer (Mac or Windows, on the CPU, ~5x faster than real time). Its files (~350 MB)
download once, the first time voice mode is turned on, into storage/voice/kokoro.

The reply streams in as text; Sentences cuts it into sentences as they finish, cleaned of
markdown (no code, tables or links read out), so the first one plays while Claude is still
writing the rest.
"""

import io
import re
import shutil
import threading
import time
import urllib.request
import wave

import numpy as np

import config

FOLDER = config.STORAGE_DIR / "voice" / "kokoro"
FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]
DOWNLOAD = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"

ECHO_S = 30  # how long what Ultron said counts as a possible echo
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


def speak(text: str) -> bytes:
    """One sentence as a WAV file (24 kHz, 16-bit mono)."""
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


# The first sentence of a reply is said sooner if it's long: cut at its first pause (comma,
# dash, ...) after this many characters, so Ultron starts talking while it writes the rest.
FIRST_CUT = 40
_PAUSE = re.compile(r"[,;:—–]\s+|\s[-–—]\s+")


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
            if not self._started and not out:
                cut = next((m for m in _PAUSE.finditer(self._line) if m.start() >= FIRST_CUT), None)
                if cut and (c := clean(self._line[:cut.end()])):
                    out.append(c)
                    self._line = self._line[cut.end():]
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
