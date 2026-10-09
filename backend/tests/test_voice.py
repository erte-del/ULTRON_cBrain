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

    async def test_yes_answers_the_card(self):
        import main

        with patch.object(main.gate, "pending_requests", return_value=[{"id": "card-1"}]), \
                patch.object(main.gate, "resolve") as resolve:
            stopped, sent = await self.hear("Yeah, send it.")
        resolve.assert_called_once_with("card-1", True)
        self.assertFalse(stopped)  # the reply carries on with the action
        self.assertEqual(sent, [{"type": "voice.transcript", "text": ""}])  # not a new message

    async def test_wake_word(self):
        import main

        async def woken(said: str | None) -> list[dict]:
            sent: list[dict] = []

            async def send(ev: dict) -> None:
                sent.append(ev)

            with patch.object(main.stt, "woken", return_value=said):
                await main.hear(send, np.zeros(1, np.float32), set(), wake=True)
            return sent

        self.assertEqual(await woken(None), [])  # not for Ultron: nothing happens
        self.assertEqual(await woken(""), [{"type": "voice.wake", "text": ""}])
        self.assertEqual(await woken("turn it down"), [{"type": "voice.wake", "text": "turn it down"}])

    async def test_background_wake(self):
        from voice import wake

        async def check(said: str | None) -> bool:
            wake._opened_at = -wake.OPENING_S
            with patch.object(wake.stt, "woken", return_value=said), patch.object(wake, "open_window") as opened:
                await wake.check(np.zeros(1, np.float32))
            return opened.called

        self.assertFalse(await check(None))  # not for Ultron: no window
        self.assertIsNone(wake.take())
        self.assertTrue(await check("what's on tomorrow?"))
        self.assertEqual(wake.take(), "what's on tomorrow?")  # for the window, once
        self.assertIsNone(wake.take())

    def test_after_wake(self):
        for said, rest in [("Hey Ultron.", ""), ("Hey, Ultron, what's on tomorrow?", "what's on tomorrow?"),
                           ("Ultron, turn the music down.", "turn the music down."),
                           ("I was talking about Ultron yesterday.", None), ("Hey, how are you?", None),
                           ("Ultraviolet light is dangerous.", None)]:
            self.assertEqual(stt.after_wake(said), rest, said)

    def test_yes_or_no(self):
        import main

        for said, answer in [("Yes.", True), ("Okay, go ahead", True), ("No, don't.", False),
                             ("Stop.", False), ("Nope, not now", False), ("Not sure", None),
                             ("Yes, but change the time to five please", None)]:
            self.assertEqual(main.yes_or_no(said), answer, said)

    def test_new_chat_tool_asks_for_a_restart_once(self):
        import asyncio

        from tools import chat

        asyncio.run(chat.new_chat.handler({}))
        self.assertTrue(chat.take())
        self.assertFalse(chat.take())


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

    def test_first_words_are_said_at_once(self):
        # The first few words (or up to a pause, if sooner) go out right away; later sentences stay whole.
        said = self.stream("Quietly dignified, mildly electric and calm, and he never coughs up a hairball. "
                           "Ask me again later, if you like.")
        self.assertEqual(said, ["Quietly dignified,", "mildly electric and calm, and he never coughs up a hairball.",
                                "Ask me again later, if you like."])
        self.assertEqual(self.stream("You have three things tomorrow."), ["You have three", "things tomorrow."])
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



class SpokenReplyTest(unittest.IsolatedAsyncioTestCase):
    """A spoken reply (main.run_turn with voice): said sentence by sentence, and a
    confirmation card on the way is asked out loud."""

    async def test_card_is_asked_out_loud(self):
        import events
        import hub
        import main

        async def reply(*_args):
            yield {"type": "assistant.text_delta", "id": "r", "text": "I'll message Selin now. "}
            await hub.emit(events.confirm_request("c1", "WhatsApp: Send", "", []))
            yield {"type": "assistant.text_delta", "id": "r", "text": "Sent."}

        sent: list[dict] = []

        async def send(ev: dict) -> None:
            sent.append(ev)

        with patch.object(main.ultron, "handle_text", reply), patch.object(main.tts, "speak", return_value=b"wav"):
            await main.run_turn(send, "message Selin", None, None, [], "Mac", voice=True)
        said = [ev["text"] for ev in sent if ev["type"] == "voice.audio"]
        self.assertEqual(said, ["I'll message Selin", "now.", "WhatsApp, Send. Shall I go ahead?", "Sent."])
        self.assertEqual(sent[-1], {"type": "status", "state": "idle"})
        self.assertFalse(hub.has_clients())  # the listener is gone after the reply
    async def test_greeting_is_spoken(self):
        import main

        sent: list[dict] = []

        async def send(ev: dict) -> None:
            sent.append(ev)

        with patch.object(main.tts, "speak", return_value=b"wav"):
            await main.greet(send)
        self.assertEqual([(ev["type"], ev["text"]) for ev in sent], [("voice.audio", "Awake and ready, sir.")])


if __name__ == "__main__":
    unittest.main()
