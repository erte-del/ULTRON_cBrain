"""Speech to text.

With GROQ_API_KEY set: Groq's hosted Whisper large-v3-turbo (your audio goes to Groq, ~0.3 s).
Otherwise, or when Groq fails (no internet, limit reached): faster-whisper on this computer
(Mac or Windows, on the CPU). That model (JARVIS_STT_MODEL, default small.en, ~250 MB)
downloads once, the first time voice mode is turned on, into storage/voice/faster-whisper.
"""

import io
import json
import logging
import re
import threading
import uuid
import urllib.request
import wave

import numpy as np

import config

log = logging.getLogger("ultron.stt")

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
GROQ_TIMEOUT_S = 10
NO_SPEECH = 0.6  # parts Whisper thinks are more likely silence than this are dropped

# Whisper invents these on near-silent or noisy audio. Dropped when the audio is quiet.
PHANTOMS = {"thank you", "thanks", "thank you sir", "thanks sir", "thank you very much", "thank you so much",
            "thanks for watching", "thank you for watching", "you", "bye", "okay", "ok"}
SILENT = 0.005  # loudest 100 ms below this (RMS, full scale 1.0): nothing was said, don't transcribe
QUIET = 0.03  # a phantom phrase from audio never louder than this is Whisper's invention

HINT = "Ultron, TickTick, Spotify, Gmail, Canva, WhatsApp, Obsidian."
# Listening for "Hey Ultron": the hint makes Whisper write the name it would otherwise hear as
# Aldron, Uldren or Aldrin; ordinary speech isn't turned into it.
WAKE_HINT = "Hey Ultron."
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "oi", "yo"}

_model = None
_lock = threading.Lock()


def ready() -> bool:
    return _model is not None


def load():
    """The model, loaded (and downloaded) the first time it's needed."""
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(config.STT_MODEL, device="cpu", compute_type="int8",
                                  download_root=str(config.STORAGE_DIR / "voice" / "faster-whisper"))
    return _model


def loudest(audio: np.ndarray) -> float:
    """RMS of the loudest 100 ms of the audio."""
    n = 1600
    if len(audio) < n:
        return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    cut = audio[: len(audio) - len(audio) % n].reshape(-1, n)
    return float(np.sqrt(np.mean(np.square(cut), axis=1)).max())


def phantom(text: str, audio: np.ndarray) -> bool:
    """Whisper's "Thank you" on quiet audio, when nobody said anything."""
    return " ".join(re.findall(r"[\w']+", text.lower())) in PHANTOMS and loudest(audio) < QUIET


def transcribe(audio: np.ndarray) -> str:
    """The words in 16 kHz float32 audio ("" if there were none)."""
    if loudest(audio) < SILENT:
        return ""
    text = ""
    if config.GROQ_API_KEY:
        try:
            text = groq(audio)
        except Exception as e:  # never log the request: it carries the key
            log.warning("Groq speech to text failed (%s); using the local model", e)
            text = local(audio)
    else:
        text = local(audio)
    if phantom(text, audio):
        log.info("Ignored a phantom transcript: %r", text)
        return ""
    return text


def _wav(audio: np.ndarray) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def groq(audio: np.ndarray) -> str:
    fields = {"model": GROQ_MODEL, "language": "en", "temperature": "0", "prompt": HINT,
              "response_format": "verbose_json"}
    boundary = uuid.uuid4().hex
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
             f"Content-Type: audio/wav\r\n\r\n").encode() + _wav(audio) + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(GROQ_URL, data=body, headers={
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "Ultron",  # Groq's firewall turns away Python's default one
    })
    with urllib.request.urlopen(req, timeout=GROQ_TIMEOUT_S, context=config.ssl_context()) as r:
        found = json.loads(r.read().decode("utf-8"))
    segments = found.get("segments")
    if segments is None:
        return str(found.get("text", "")).strip()
    return " ".join(str(s.get("text", "")).strip() for s in segments
                    if s.get("no_speech_prob", 0) < NO_SPEECH).strip()


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


def woken(audio: np.ndarray) -> str | None:
    """Wake word mode: checked on this computer, so speech that isn't for Ultron never leaves
    it. None if you didn't say "Hey Ultron"; else what you asked ("" for nothing yet), written
    down by Groq if it's set up (more accurate)."""
    rest = after_wake(local(audio, WAKE_HINT))
    if rest and config.GROQ_API_KEY:
        try:
            rest = after_wake(groq(audio)) or rest
        except Exception as e:
            log.warning("Groq speech to text failed (%s); using the local words", e)
    return rest


def local(audio: np.ndarray, hint: str = HINT) -> str:
    english_only = config.STT_MODEL.endswith(".en")
    # One careful pass (beam 5) and no retries: when unsure, Whisper otherwise tries again up
    # to five times with more randomness, which is slow (seconds) and invents words.
    # The prompt spells the names it can't guess.
    segments, _ = load().transcribe(audio, language="en" if english_only else None, beam_size=5,
                                    temperature=0.0, initial_prompt=hint,
                                    vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments if s.no_speech_prob < NO_SPEECH).strip()
