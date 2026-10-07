"""Video generation, with a fake model process instead of Wan. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import main
from storage import video_store
from tools import video

# Stands in for `python -m mlx_video.models.wan_2.generate`: prints tqdm-style
# progress, then writes the file given after --output-path.
FAKE_WAN = """#!/bin/bash
echo "$@" > "$(dirname "$0")/args"
while [ $# -gt 0 ]; do [ "$1" = --output-path ] && OUT="$2"; shift; done
printf 'Loading T5 encoder...\\nDiffusion:  50%%|#####     | 1/2 [00:01<00:01]\\r'
sleep 0.2
printf 'Diffusion: 100%%|##########| 2/2 [00:02<00:00]\\n'
[ -n "${FAIL:-}" ] && exit 1
echo fake-mp4 > "$OUT"
"""


class VideoTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        wan = tmp / "wan"
        (wan / ".venv" / "bin").mkdir(parents=True)
        (wan / "Wan2.1-T2V-1.3B-MLX").mkdir()
        (wan / "Wan2.1-T2V-1.3B-MLX" / "config.json").write_text("{}")
        fake = wan / ".venv" / "bin" / "python"
        fake.write_text(FAKE_WAN)
        fake.chmod(0o755)
        self.wan, self.tmp = wan, tmp
        self.emit = mock.AsyncMock()
        for patch in (
            mock.patch.object(video_store, "VIDEOS_DIR", tmp / "videos"),
            mock.patch.object(video.config, "WAN_DIR", wan),
            mock.patch.object(video.hub, "emit", self.emit),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def add_5b(self):
        (self.wan / "Wan2.2-TI2V-5B-MLX").mkdir()
        (self.wan / "Wan2.2-TI2V-5B-MLX" / "config.json").write_text("{}")

    def args_used(self) -> str:
        return (self.wan / ".venv" / "bin" / "args").read_text()

    def run_job(self, **args):
        async def go():
            result = await video.generate_video.handler({"prompt": "a cat on a piano", **args})
            if video._job:
                await video._job
            return result
        return asyncio.run(go())

    def test_frames_are_4n_plus_1(self):
        self.assertEqual(video.frames_for(5), 81)
        self.assertEqual(video.frames_for(99), 81)
        self.assertEqual(video.frames_for(0), 17)  # at least 1 s
        for s in (1, 2, 2.5, 3, 4):
            self.assertEqual(video.frames_for(s) % 4, 1)

    def test_progress_parsing(self):
        self.assertEqual(video.last_progress(b"Diffusion:  40%|###  | 12/30 [00:30<]"), (12, 30))
        self.assertIsNone(video.last_progress(b"Loading T5 encoder..."))

    def test_render_shows_progress_then_video(self):
        result = self.run_job(title="Cat", seconds=2)
        self.assertNotIn("is_error", result)
        rec = video_store.load("vid_001")
        self.assertEqual((rec.status, rec.progress), ("done", 1.0))
        cards = [c.args[0]["data"] for c in self.emit.call_args_list if c.args[0]["type"] == "canvas.card"]
        self.assertEqual(cards[0]["status"], "rendering")
        self.assertIn(0.5, [c["progress"] for c in cards])
        self.assertEqual(cards[-1]["url"], "/videos/vid_001/video.mp4")

        client = TestClient(main.app)
        self.assertEqual(client.get("/videos/vid_001/video.mp4").content, b"fake-mp4\n")
        self.assertIn("cat.mp4", client.get("/videos/vid_001/video.mp4?download=1").headers["content-disposition"])
        self.assertEqual(client.get("/videos/vid_001/meta.json").status_code, 404)
        self.assertEqual(client.get("/videos/..%2Fx/video.mp4").status_code, 404)

    def test_failed_render_shows_error(self):
        with mock.patch.dict("os.environ", {"FAIL": "1"}):
            self.run_job()
        rec = video_store.load("vid_001")
        self.assertEqual(rec.status, "failed")
        self.assertIn("failed", rec.error)
        self.assertFalse((video_store.folder("vid_001") / "video.mp4").exists())

    def test_portrait_by_default_landscape_on_request(self):
        self.run_job()
        self.assertIn("--width 480 --height 832", self.args_used())
        self.assertIn("Wan2.1-T2V-1.3B-MLX", self.args_used())
        self.run_job(shape="landscape")
        self.assertIn("--width 832 --height 480", self.args_used())

    def test_image_needs_the_5b_model(self):
        result = self.run_job(image="/nonexistent.png")
        self.assertTrue(result["is_error"])
        self.assertIn("setup_video.sh 5b", result["content"][0]["text"])

    def test_animates_an_image_in_its_own_shape_with_5b(self):
        self.add_5b()
        still = self.tmp / "still.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:size=300x200",
                        "-frames:v", "1", str(still)], check=True)
        result = self.run_job(image=str(still))
        self.assertNotIn("is_error", result)
        used = self.args_used()
        self.assertIn("Wan2.2-TI2V-5B-MLX", used)
        self.assertIn(f"--image {still}", used)
        self.assertIn("--width 1280 --height 704 --num-frames 121", used)  # landscape image, 24 fps

    def test_rejects_a_non_image(self):
        self.add_5b()
        text = self.tmp / "notes.txt"
        text.write_text("hi")
        self.assertTrue(self.run_job(image=str(text))["is_error"])

    def test_not_set_up(self):
        with mock.patch.object(video.config, "WAN_DIR", Path("/nonexistent")):
            result = self.run_job()
        self.assertTrue(result["is_error"])
        self.assertIn("setup_video.sh", result["content"][0]["text"])

    def test_is_an_act_tool(self):
        from tools import registry
        self.assertEqual(registry.classify("mcp__ultron__generate_video"), "act")


if __name__ == "__main__":
    unittest.main()
