"""Voice activity detection: hears where each thing you say starts and ends, so Ultron knows
when you've finished talking. Uses the Silero model that comes with faster-whisper (ONNX,
runs on Mac and Windows), one 32 ms frame at a time.
"""

from collections.abc import Callable

import numpy as np

RATE = 16000  # the browser sends 16 kHz, 16-bit mono PCM (frontend/src/mic.ts)
FRAME = 512  # 32 ms: the size Silero works on
START = 0.5  # speech probability that starts an utterance
STOP = 0.35  # below this a frame counts as silence (lower than START, so it doesn't flicker)
FRAMES_PER_S = RATE / FRAME
END_SILENCE = round(0.7 * FRAMES_PER_S)  # this much quiet means you've finished
MIN_SPEECH = round(0.25 * FRAMES_PER_S)  # shorter is a cough or a click: dropped
MAX_SPEECH = round(30 * FRAMES_PER_S)  # cut off a very long one (or a TV left on)
PRE_ROLL = round(0.3 * FRAMES_PER_S)  # kept from before the start, so the first sound isn't lost


def _silero() -> Callable[[np.ndarray], float]:
    from faster_whisper.vad import get_vad_model

    model = get_vad_model()
    # Two frames in, the speech probability of the second out: the first is its context.
    return lambda frames: float(model(frames).reshape(-1)[-1])


class Endpointer:
    """Feed it the microphone; it hands back each finished utterance as float32 audio."""

    def __init__(self, prob: Callable[[np.ndarray], float] | None = None):
        self._prob = prob or _silero()
        self.reset()

    def reset(self) -> None:
        self._pending = np.zeros(0, np.float32)
        self._prev = np.zeros(FRAME, np.float32)
        self._frames: list[np.ndarray] = []
        self.speaking = False  # you're talking right now
        self._speech = self._silence = 0  # frames since the start / of quiet at the end

    def feed(self, pcm: bytes) -> np.ndarray | None:
        """16-bit mono PCM at 16 kHz. Returns an utterance once you've stopped talking."""
        pcm = pcm[: len(pcm) - len(pcm) % 2]
        self._pending = np.concatenate([self._pending, np.frombuffer(pcm, "<i2").astype(np.float32) / 32768])
        done = None
        while len(self._pending) >= FRAME and done is None:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            p = self._prob(np.concatenate([self._prev, frame]))
            self._prev = frame
            if not self.speaking:
                self._frames = [*self._frames[-PRE_ROLL + 1:], frame]
                if p >= START:
                    self.speaking, self._speech, self._silence = True, 1, 0
                continue
            self._frames.append(frame)
            self._speech += 1
            self._silence = self._silence + 1 if p < STOP else 0
            if self._silence >= END_SILENCE or self._speech >= MAX_SPEECH:
                if self._speech - self._silence >= MIN_SPEECH:
                    done = np.concatenate(self._frames)
                self.speaking, self._frames = False, []
        return done
