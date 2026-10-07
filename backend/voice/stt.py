"""Speech to text.

With GROQ_API_KEY set: Groq's hosted Whisper large-v3-turbo (your audio goes to Groq, ~0.3 s).
Otherwise, or when Groq fails (no internet, limit reached): faster-whisper on this computer
(Mac or Windows, on the CPU). That model (JARVIS_STT_MODEL, default small.en, ~250 MB)
downloads once, the first time voice mode is turned on, into storage/voice/faster-whisper.
"""

import io
import json
import logging
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

HINT = "Ultron, TickTick, Spotify, Gmail, Canva, WhatsApp, Obsidian."

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


def transcribe(audio: np.ndarray) -> str:
    """The words in 16 kHz float32 audio ("" if there were none)."""
    if config.GROQ_API_KEY:
        try:
            return groq(audio)
        except Exception as e:  # never log the request: it carries the key
            log.warning("Groq speech to text failed (%s); using the local model", e)
    return local(audio)


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


def local(audio: np.ndarray) -> str:
    english_only = config.STT_MODEL.endswith(".en")
    # One careful pass (beam 5) and no retries: when unsure, Whisper otherwise tries again up
    # to five times with more randomness, which is slow (seconds) and invents words.
    # The prompt spells the names it can't guess.
    segments, _ = load().transcribe(audio, language="en" if english_only else None, beam_size=5,
                                    temperature=0.0, initial_prompt=HINT,
                                    vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments if s.no_speech_prob < NO_SPEECH).strip()
