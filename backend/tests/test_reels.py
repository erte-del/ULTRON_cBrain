"""reel_edit, the tool around reel.py, with real FFmpeg. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_reels
"""

import asyncio
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
        patch = mock.patch.object(reels.config, "FILES_DIR", self.dir / "files")
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

    def test_bad_input_is_an_error_not_a_crash(self):
        result, text = self.run_tool(op="cut", inputs=[str(self.dir / "missing.mp4")], output="x", start=0, end=1)
        self.assertTrue(result.get("is_error"))
        result, _ = self.run_tool(op="spin", inputs=[self.clip], output="x")
        self.assertTrue(result.get("is_error"))


if __name__ == "__main__":
    unittest.main()
