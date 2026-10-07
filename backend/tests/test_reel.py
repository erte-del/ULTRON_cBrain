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

    def make_track(self, seconds: float, freq: int = 220) -> str:
        path = self.dir / f"track{seconds}.m4a"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}:duration={seconds}", str(path)], check=True)
        return str(path)

    def test_music_loops_a_short_track_to_the_video_length(self):
        reel.music(self.wide, self.out("m.mp4"), self.make_track(1.5))
        self.assertEqual(reel.check(self.out("m.mp4")), [])
        self.assertAlmostEqual(reel.probe(self.out("m.mp4"))["seconds"], 4, delta=0.15)

    def test_music_trims_a_long_track_and_works_on_silent_clips(self):
        reel.music(self.mute, self.out("m2.mp4"), self.make_track(30))
        self.assertAlmostEqual(reel.probe(self.out("m2.mp4"))["seconds"], 2, delta=0.15)

    def test_music_replace_drops_the_clip_sound(self):
        reel.music(self.wide, self.out("r.mp4"), self.make_track(5, freq=1000), volume=1, replace=True)
        # The clip's 440 Hz tone should be gone: a 440 Hz band-pass leaves almost nothing.
        level = subprocess.run(
            ["ffmpeg", "-i", self.out("r.mp4"), "-af", "bandpass=f=440:w=50,volumedetect", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        mean_db = float(level.split("mean_volume:")[1].split("dB")[0])
        self.assertLess(mean_db, -40)

    def level(self, path: str, start: float, seconds: float, freq: int) -> float:
        """Mean loudness (dB) of one frequency band in a stretch of the file."""
        err = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(seconds), "-i", path,
                              "-af", f"bandpass=f={freq}:w=50,volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        return float(err.split("mean_volume:")[1].split("dB")[0])

    def test_voice_ducks_the_sound_under_it(self):
        # Clip's own 440 Hz tone is the "music"; a 1000 Hz tone from 1.5 s to 2.5 s is the "voice".
        reel.voice(self.wide, self.out("v.mp4"), self.make_track(1, freq=1000), at=1.5)
        out = self.out("v.mp4")
        self.assertEqual(reel.check(out), [])
        before = self.level(out, 0.3, 1.0, 440)
        during = self.level(out, 1.8, 0.5, 440)
        after = self.level(out, 3.2, 0.6, 440)
        self.assertLess(during, before - 10)  # music pushed down while the voice speaks
        self.assertGreater(after, during + 6)  # and comes back once it stops
        self.assertGreater(self.level(out, 1.8, 0.5, 1000), during)  # voice is on top

    def test_voice_longer_than_the_clip_holds_the_last_frame(self):
        reel.voice(self.mute, self.out("long.mp4"), self.make_track(3, freq=1000), at=1)
        self.assertAlmostEqual(reel.probe(self.out("long.mp4"))["seconds"], 4, delta=0.15)
        self.assertEqual(reel.check(self.out("long.mp4")), [])

    @unittest.skipUnless(shutil.which("say"), "needs macOS say")
    def test_voice_with_real_speech(self):
        speech = self.dir / "line.aiff"
        subprocess.run(["say", "-o", str(speech), "Hello, I am Ultron."], check=True)
        reel.voice(self.wide, self.out("say.mp4"), str(speech), at=0.5)
        self.assertEqual(reel.check(self.out("say.mp4")), [])

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
