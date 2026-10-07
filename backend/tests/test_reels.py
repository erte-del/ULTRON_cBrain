"""reel_edit, the tool around reel.py, with real FFmpeg. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_reels
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import reel
from tools import reels


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class ReelEditTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        for patch in (mock.patch.object(reels.config, "FILES_DIR", self.dir / "files"),
                      mock.patch.object(reels, "VOICE_DIR", self.dir / "voice"),  # not set up: macOS say
                      mock.patch.object(reels, "WHISPER", self.dir / "voice" / "whisper")):
            patch.start()
            self.addCleanup(patch.stop)
        self.clip = str(self.dir / "clip.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:duration=4",
                        "-f", "lavfi", "-i", "sine=duration=4", "-pix_fmt", "yuv420p", self.clip], check=True)

    def run_tool(self, **args):
        result = asyncio.run(reels.reel_edit.handler(args))
        return result, result["content"][0]["text"]

    def test_steps_chain_into_a_reel(self):
        _, text = self.run_tool(op="join", inputs=[self.clip, self.clip], output="joined")
        joined = self.dir / "files" / "Instagram" / "joined.mp4"
        self.assertIn("ready for Instagram", text)
        _, text = self.run_tool(op="caption", inputs=[str(joined)], output="final", text="Hi", position="top")
        self.assertIn("ready for Instagram", text)
        self.assertEqual(reel.check(str(self.dir / "files" / "Instagram" / "final.mp4")), [])

    def test_output_name_cannot_leave_the_folder(self):
        self.run_tool(op="export", inputs=[self.clip], output="../../escape")
        self.assertTrue((self.dir / "files" / "Instagram" / "escape.mp4").exists())
        self.assertFalse((self.dir / "escape.mp4").exists())

    @unittest.skipUnless(shutil.which("say"), "needs macOS say")
    def test_voice_from_text(self):
        result, text = self.run_tool(op="voice", inputs=[self.clip], output="spoken", say="Hello, I am Ultron.")
        self.assertNotIn("is_error", result)
        self.assertIn("ready for Instagram", text)

    def test_words_captions_follow_the_transcript(self):
        timed = [{"word": " Hello", "start": 0.2, "end": 0.6}, {"word": " there.", "start": 0.6, "end": 1.0}]
        with mock.patch.object(reels, "transcribe", return_value=timed):
            result, text = self.run_tool(op="words", inputs=[self.clip], output="worded")
        self.assertNotIn("is_error", result)
        self.assertIn("ready for Instagram", text)
        with mock.patch.object(reels, "transcribe", return_value=[]):
            result, text = self.run_tool(op="words", inputs=[self.clip], output="silent")
        self.assertIn("No speech", text)

    def test_words_and_voices_need_the_setup(self):
        result, text = self.run_tool(op="words", inputs=[self.clip], output="x")
        self.assertIn("setup_voice.sh", text)
        py = reels._voice_python()
        py.parent.mkdir(parents=True)
        py.touch()
        for bad in ("darth_vader", None):  # no default voice: Ultron picks one
            with self.assertRaises(ValueError):
                reels.speak("hi", self.dir, bad)

    def test_treated_voices_filter_the_plain_one(self):
        py = reels._voice_python()
        py.parent.mkdir(parents=True)
        py.touch()
        def fake_kokoro(cmd):
            self.assertIn("bm_lewis", cmd)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=110:d=2:sample_rate=24000",
                            str(self.dir / "line.wav")], check=True)
        for name in reels.EFFECTS:
            (self.dir / "line.wav").unlink(missing_ok=True)
            with mock.patch.object(reels, "_run", fake_kokoro):
                out = reels.speak("hi", self.dir, name)
            self.assertEqual(out.name, "treated.wav")
            self.assertGreater(reel.probe(str(out))["seconds"], 1.5)

    def test_turkish_goes_to_piper_and_captions_ask_for_turkish(self):
        with self.assertRaises(ValueError):  # not set up yet
            reels.speak("Merhaba", self.dir, "tr_dfki")
        py = reels._voice_python()
        py.parent.mkdir(parents=True)
        py.touch()
        (reels.VOICE_DIR / "piper").mkdir()
        (reels.VOICE_DIR / "piper" / reels.PIPER["tr_dfki"]).touch()
        calls = []
        with mock.patch.object(reels, "_run", lambda cmd, stdin=None: calls.append((cmd, stdin))):
            out = reels.speak("Merhaba, ben Ultron.", self.dir, "tr_dfki")
        cmd, stdin = calls[0]
        self.assertIn("piper", cmd)
        self.assertEqual(stdin, "Merhaba, ben Ultron.")  # the text never becomes an argument
        self.assertEqual(out, self.dir / "line.wav")

        (reels.WHISPER).mkdir(parents=True)
        (reels.WHISPER / "weights.safetensors").touch()
        def fake_whisper(cmd, stdin=None):
            self.assertEqual(json.loads(cmd[-1])["language"], "tr")
            (self.dir / "words.json").write_text('{"segments": []}')
        with mock.patch.object(reels, "_run", fake_whisper):
            self.assertEqual(reels.transcribe(str(self.clip), self.dir, "tr"), [])

    def test_every_voice_has_a_description(self):
        self.assertTrue(set(reels.EFFECTS) <= set(reels.VOICES))
        self.assertTrue(all(len(d) > 20 for d in reels.VOICES.values()))

    def test_frames_folder_becomes_a_reel(self):
        folder = self.dir / "frames"
        folder.mkdir()
        for i in range(60):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x{i * 4:02x}0000:s=1080x1920",
                            "-frames:v", "1", str(folder / f"f{i:03d}.png")], check=True)
        _, text = self.run_tool(op="frames", inputs=[str(folder)], output="drawn", fps=20)
        self.assertIn("(3.0 s), ready for Instagram", text)
        result, _ = self.run_tool(op="frames", inputs=[self.clip], output="x")  # a file, not a folder
        self.assertTrue(result.get("is_error"))

    def test_bad_input_is_an_error_not_a_crash(self):
        result, text = self.run_tool(op="cut", inputs=[str(self.dir / "missing.mp4")], output="x", start=0, end=1)
        self.assertTrue(result.get("is_error"))
        result, _ = self.run_tool(op="spin", inputs=[self.clip], output="x")
        self.assertTrue(result.get("is_error"))


if __name__ == "__main__":
    unittest.main()
