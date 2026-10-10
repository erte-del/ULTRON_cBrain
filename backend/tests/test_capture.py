"""Screen clipping: the buffer window maths and the not-recording guard. Run from backend:
    .venv/bin/python -m unittest tests.test_capture
"""

import asyncio
import os
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import reel
from storage import video_store
from tools import capture


class CaptureTest(unittest.TestCase):
    def test_window_is_cut_to_the_buffer(self):
        # buffer holds 60 s ending at t=1000 (starts 940); ask for 930..960
        self.assertEqual(capture.window(930, 960, 1000, 60), (0, 20))
        self.assertEqual(capture.window(970, 1100, 1000, 60), (30, 30))

    def test_clip_while_off_starts_the_buffer(self):
        with mock.patch.object(capture, "start") as start:  # never really record in a test
            out = asyncio.run(capture.capture.handler({"action": "clip"}))
        start.assert_called_once()
        self.assertTrue(out.get("is_error"))


    def test_last_n_seconds_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(capture, "BUF", Path(tmp)):
            now = time.time()
            for i in range(3):  # three 5 s segments, the newest finished "now"
                seg = Path(tmp) / f"s{i:05d}.ts"
                reel.ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=5", "-pix_fmt", "yuv420p", str(seg))
                os.utime(seg, (now - 5 * (2 - i),) * 2)
            out = str(Path(tmp) / "clip.mp4")
            self.assertAlmostEqual(capture.cut_buffer(7, None, out), 7, delta=0.3)
            self.assertAlmostEqual(reel.probe(out)["seconds"], 7, delta=0.5)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class LibraryTest(unittest.TestCase):
    def test_trim_saves_a_new_clip_with_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(video_store, "VIDEOS_DIR", Path(tmp)):
            fake = lambda out: reel.ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=4",
                                           "-pix_fmt", "yuv420p", out)
            src = asyncio.run(capture._new("Match", fake, show=False))
            clip = asyncio.run(capture.trim_to_library(src.id, 1, 3))
            self.assertAlmostEqual(clip.seconds, 2, delta=0.3)
            self.assertTrue((video_store.folder(clip.id) / video_store.THUMB).exists())
            self.assertEqual({r.id for r in video_store.all_records("capture")}, {src.id, clip.id})
            video_store.delete(clip.id)
            self.assertEqual([r.id for r in video_store.all_records("capture")], [src.id])
