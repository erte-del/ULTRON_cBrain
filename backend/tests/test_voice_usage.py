"""ElevenLabs voice: the Kokoro fallback, what's logged per sentence and reply, and voice_usage.
Nothing is sent to ElevenLabs and Kokoro isn't loaded. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_voice_usage
"""

import asyncio
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import config
from tools import voice_usage
from voice import tts


class ElevenTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for patch in (mock.patch.object(tts, "USAGE_FILE", self.dir / "u.jsonl"),
                      mock.patch.object(config, "TTS", "elevenlabs"),
                      mock.patch.object(config, "ELEVEN_KEY", "k"),
                      mock.patch.object(config, "ELEVEN_VOICE", "v"),
                      mock.patch.object(tts, "_reply_chars", 0)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_eleven_speaks_and_is_counted(self):
        with mock.patch.object(tts, "_eleven", return_value=b"WAVDATA") as eleven, mock.patch.object(tts, "_kokoro") as kokoro:
            self.assertEqual(tts.speak("Hello there."), b"WAVDATA")
            tts.speak("Second.")
            tts.reply_done()
        self.assertEqual(eleven.call_count, 2)
        kokoro.assert_not_called()
        stats = voice_usage.logged()
        self.assertEqual((stats["replies"], stats["eleven_replies"], stats["eleven_chars"]), (1, 1, 19))

    def test_out_of_characters_falls_back_to_kokoro(self):
        err = urllib.error.HTTPError("u", 401, "quota", {}, None)
        with mock.patch.object(tts, "_eleven", side_effect=err), mock.patch.object(tts, "_kokoro", return_value=b"KOKORO") as kokoro:
            self.assertEqual(tts.speak("Hi."), b"KOKORO")
        kokoro.assert_called_once()
        tts.reply_done()
        self.assertEqual(voice_usage.logged()["fallbacks"], 1)

    def test_kokoro_when_eleven_is_off(self):
        with mock.patch.object(config, "TTS", "kokoro"), mock.patch.object(tts, "_kokoro", return_value=b"K") as kokoro:
            tts.speak("Hi.")
        kokoro.assert_called_once()

    def test_voice_usage_reports_plan_and_average(self):
        with mock.patch.object(tts, "_eleven", return_value=b"W"):
            tts.speak("x" * 100)
            tts.reply_done()
            tts.speak("y" * 300)
            tts.reply_done()
        plan = {"used": 400, "limit": 10000, "resets": None}
        with mock.patch.object(voice_usage, "account", return_value=plan):
            text = asyncio.run(voice_usage.voice_usage.handler({}))["content"][0]["text"]
        self.assertIn("400 of 10,000 characters used, 9,600 left", text)
        self.assertIn("About 48 more replies", text)  # 9600 // avg 200
