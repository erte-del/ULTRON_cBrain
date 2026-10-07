"""Voice tests: the end-of-speech detector (voice/vad.py), speech to text
and talking over a reply. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import unittest
from unittest.mock import patch

import numpy as np

import config
from voice import stt, tts, vad


def pcm(seconds: float, loud: bool) -> bytes:
    n = int(seconds * vad.RATE)
    return (np.full(n, 8000 if loud else 0, "<i2")).tobytes()


# Stand-in for Silero: a loud frame is speech.
def loudness(frames: np.ndarray) -> float:
    return float(np.abs(frames[-vad.FRAME:]).mean() > 0.1)


class EndpointerTest(unittest.TestCase):
    def feed(self, ears: vad.Endpointer, audio: bytes, chunk: int = 3200) -> list[np.ndarray]:
        # In 100 ms pieces, like the browser sends it.
        out = [ears.feed(audio[i:i + chunk]) for i in range(0, len(audio), chunk)]
        return [u for u in out if u is not None]

    def test_utterance_ends_after_silence(self):
        ears = vad.Endpointer(loudness)
        said = self.feed(ears, pcm(0.5, False) + pcm(1.0, True) + pcm(0.4, False))
        self.assertEqual(said, [])  # still within the pause you're allowed
        self.assertTrue(ears.speaking)
        said = self.feed(ears, pcm(0.5, False))
        self.assertEqual(len(said), 1)
        self.assertFalse(ears.speaking)
        # The speech, a little from before it, and the quiet that ended it.
        self.assertAlmostEqual(len(said[0]) / vad.RATE, 1.0 + 0.3 + 0.7, delta=0.1)

    def test_short_noise_is_dropped(self):
        ears = vad.Endpointer(loudness)
        self.assertEqual(self.feed(ears, pcm(0.1, True) + pcm(1.0, False)), [])
        self.assertFalse(ears.speaking)

    def test_odd_chunks_and_reset(self):
        ears = vad.Endpointer(loudness)
        self.feed(ears, pcm(1.0, True), chunk=777)  # odd byte counts don't break it
        self.assertTrue(ears.speaking)
        ears.reset()
        self.assertFalse(ears.speaking)
        self.assertEqual(self.feed(ears, pcm(1.0, False)), [])

    def test_silero_ignores_silence(self):
        ears = vad.Endpointer()  # the real model
        noise = (np.random.default_rng(1).normal(0, 30, vad.RATE * 2)).astype("<i2").tobytes()
        self.assertEqual(self.feed(ears, noise), [])
        self.assertFalse(ears.speaking)


class TalkOverTest(unittest.IsolatedAsyncioTestCase):
    """Talking while Ultron answers (main.hear): words stop the reply, a cough doesn't."""

    async def hear(self, said: str) -> tuple[bool, list[dict]]:
        import main

        sent: list[dict] = []

        async def send(ev: dict) -> None:
            sent.append(ev)

        reply = asyncio.create_task(asyncio.sleep(60))
        with patch.object(main.stt, "transcribe", return_value=said):
            await main.hear(send, np.zeros(1, np.float32), {reply})
        stopped = reply.done()
        reply.cancel()
        return stopped, sent

    async def test_words_stop_the_reply(self):
        stopped, sent = await self.hear("wait, make it Friday")
        self.assertTrue(stopped)
        self.assertEqual(sent, [{"type": "voice.transcript", "text": "wait, make it Friday"}])

    async def test_no_words_keep_the_reply(self):
        stopped, _ = await self.hear("")
        self.assertFalse(stopped)


class GroqTest(unittest.TestCase):
    """Speech to text through Groq (voice/stt.py), and the local model when that fails."""

    def test_drops_silence_from_groq_answer(self):
        answer = b'{"text": "x", "segments": [{"text": " Remind me at five.", "no_speech_prob": 0.01},' \
                 b' {"text": " Thank you.", "no_speech_prob": 0.9}]}'
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = answer
            self.assertEqual(stt.groq(np.zeros(1600, np.float32)), "Remind me at five.")

    def test_falls_back_to_the_local_model(self):
        with patch.object(config, "GROQ_API_KEY", "gsk_test"), \
                patch.object(stt, "groq", side_effect=OSError("offline")), \
                patch.object(stt, "local", return_value="hello") as local:
            self.assertEqual(stt.transcribe(np.zeros(1600, np.float32)), "hello")
            local.assert_called_once()


class SpeakingTest(unittest.TestCase):
    """What Ultron says out loud (voice/tts.py)."""

    def stream(self, reply: str, step: int = 3) -> list[str]:
        parts = tts.Sentences()
        out = [s for i in range(0, len(reply), step) for s in parts.feed(reply[i:i + step])]
        return out + parts.flush()

    def test_sentences_come_out_as_they_finish(self):
        parts = tts.Sentences()
        self.assertEqual(parts.feed("You have three things. The fir"), ["You have three things."])
        self.assertEqual(parts.feed("st is at 9.30 with Dr. Smith, e.g. a check-up."), [])
        self.assertEqual(parts.flush(), ["The first is at 9.30 with Dr. Smith, e.g. a check-up."])

    def test_long_first_sentence_starts_early(self):
        # Cut at its first pause, so the voice starts sooner; later sentences stay whole.
        said = self.stream("Quietly dignified, mildly electric and calm, and he never coughs up a hairball. "
                           "Ask me again later, if you like.")
        self.assertEqual(said, ["Quietly dignified, mildly electric and calm,", "and he never coughs up a hairball.",
                                "Ask me again later, if you like."])
        # Markdown after a full stop doesn't hide the end of the sentence.
        self.assertEqual(self.stream("**Circuit.** Quietly dignified."), ["Circuit.", "Quietly dignified."])

    def test_markdown_isnt_read_out(self):
        reply = ("## Tomorrow\n- **Dentist** at nine.\n- Lunch, see [the menu](https://x.com/m).\n\n"
                 "| Time | What |\n|---|---|\n| 9:00 | Dentist |\n\n```python\nprint('hi')\n```\n"
                 "Details are on the canvas: https://example.com")
        self.assertEqual(self.stream(reply), ["Tomorrow", "Dentist at nine.", "Lunch, see the menu.",
                                              "Details are on the canvas:"])

    def test_own_voice_is_an_echo(self):
        tts.said("You have three things tomorrow, starting with the dentist at nine.")
        self.assertTrue(tts.is_echo("three things tomorrow starting with the dentist"))
        self.assertFalse(tts.is_echo("move the dentist to Friday please"))
        self.assertFalse(tts.is_echo("stop"))  # short: always you


if __name__ == "__main__":
    unittest.main()
