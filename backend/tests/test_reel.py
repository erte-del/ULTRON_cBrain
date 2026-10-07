"""reel.py against real FFmpeg, on tiny generated clips. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_reel
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import reel


def make_clip(path: Path, seconds: float, size: str, sound: bool) -> str:
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={seconds}"]
    if sound:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    subprocess.run([*args, "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class ReelTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.wide = make_clip(self.dir / "wide.mp4", 4, "640x360", sound=True)
        self.mute = make_clip(self.dir / "mute.mp4", 2, "360x640", sound=False)

    def out(self, name: str) -> str:
        return str(self.dir / name)

    def test_export_makes_a_reel(self):
        reel.export(self.wide, self.out("e.mp4"))
        self.assertEqual(reel.check(self.out("e.mp4")), [])

    def test_join_mixes_shapes_and_silent_clips(self):
        reel.join(self.out("j.mp4"), [self.wide, self.mute])
        self.assertEqual(reel.check(self.out("j.mp4")), [])
        self.assertAlmostEqual(reel.probe(self.out("j.mp4"))["seconds"], 6, delta=0.2)

    def test_cut_keeps_only_the_range(self):
        reel.cut(self.wide, self.out("c.mp4"), 0.5, 3.5)
        self.assertAlmostEqual(reel.probe(self.out("c.mp4"))["seconds"], 3, delta=0.15)

    def test_caption_with_awkward_characters(self):
        reel.caption(self.wide, self.out("t.mp4"), "It's 50% off: \"really\", isn't it?", at="top", start=1, end=3)
        self.assertEqual(reel.check(self.out("t.mp4")), [])

    def test_check_flags_problems(self):
        problems = reel.check(self.mute)
        self.assertTrue(any("size" in p for p in problems))
        self.assertTrue(any("length" in p for p in problems))
        self.assertIn("no audio track", problems)

    def test_cut_rejects_backwards_range(self):
        with self.assertRaises(ValueError):
            reel.cut(self.wide, self.out("x.mp4"), 3, 1)


if __name__ == "__main__":
    unittest.main()
