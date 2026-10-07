"""Stock clips and music, with Pexels and Openverse faked. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_stock
"""

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import stock

REAL_FETCH = stock._fetch  # kept before setUp replaces it

PEXELS_VIDEO = {
    "id": 123, "url": "https://www.pexels.com/video/123/", "duration": 12, "width": 2160, "height": 3840,
    "user": {"name": "Ana", "url": "https://www.pexels.com/@ana"},
    "video_files": [
        {"file_type": "video/mp4", "width": 720, "height": 1280, "link": "https://videos.pexels.com/sd.mp4"},
        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://videos.pexels.com/hd.mp4"},
        {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "https://videos.pexels.com/4k.mp4"},
    ],
}
TRACK = {"id": "abc-1", "title": "Sunrise", "creator": "Bo", "creator_url": "https://jamendo.com/bo",
         "license": "by", "license_version": "3.0", "license_url": "https://creativecommons.org/licenses/by/3.0/",
         "url": "https://prod-1.storage.jamendo.com/?trackid=1", "foreign_landing_url": "https://jamendo.com/t/1",
         "source": "jamendo", "duration": 95000,
         "attribution": '"Sunrise" by Bo is licensed under CC BY 3.0.'}


class StockTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.api = mock.Mock()
        self.fetch = mock.Mock(side_effect=lambda url, dest: dest.write_bytes(b"media"))
        for patch in (mock.patch.object(stock.config, "FILES_DIR", tmp),
                      mock.patch.object(stock.config, "PEXELS_API_KEY", "key"),
                      mock.patch.object(stock, "_get_json", self.api),
                      mock.patch.object(stock, "_fetch", self.fetch)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_tool(self, t, **args):
        result = asyncio.run(t.handler(args))
        return result, result["content"][0]["text"]

    def test_best_file_is_full_hd_not_4k(self):
        self.assertEqual(stock.best_file(PEXELS_VIDEO["video_files"])["link"], "https://videos.pexels.com/hd.mp4")
        small = [f for f in PEXELS_VIDEO["video_files"] if f["width"] == 720]
        self.assertEqual(stock.best_file(small)["width"], 720)  # nothing big enough: take the largest

    def test_video_search_asks_for_portrait(self):
        self.api.return_value = {"videos": [PEXELS_VIDEO]}
        _, text = self.run_tool(stock.stock_search, kind="video", query="ocean")
        self.assertIn("orientation=portrait", self.api.call_args.args[0])
        self.assertEqual(json.loads(text)[0]["id"], "123")

    def test_music_search_only_asks_for_reusable_licences(self):
        self.api.return_value = {"results": [TRACK]}
        self.run_tool(stock.stock_search, kind="music", query="upbeat")
        url = self.api.call_args.args[0]
        self.assertIn("license=by%2Ccc0%2Cpdm", url)
        self.assertIn("category=music", url)

    def test_video_download_saves_licence_and_credit(self):
        self.api.return_value = PEXELS_VIDEO
        result, text = self.run_tool(stock.stock_download, kind="video", id="123")
        self.assertNotIn("is_error", result)
        path = stock.stock_dir() / "pexels_123.mp4"
        self.assertEqual(self.fetch.call_args.args, ("https://videos.pexels.com/hd.mp4", path))
        info = json.loads(path.with_suffix(".json").read_text())
        self.assertEqual(info["credit"], "Video by Ana on Pexels")
        self.assertIn(str(path), text)

    def test_music_download_rechecks_the_licence(self):
        self.api.return_value = {**TRACK, "license": "by-sa"}
        result, _ = self.run_tool(stock.stock_download, kind="music", id="abc-1")
        self.assertTrue(result.get("is_error"))
        self.fetch.assert_not_called()

    def test_music_download_gives_the_credit_line(self):
        self.api.return_value = TRACK
        _, text = self.run_tool(stock.stock_download, kind="music", id="abc-1")
        self.assertIn("CC BY 3.0", text)
        self.assertIn('"Sunrise" by Bo', text)

    def test_second_download_uses_the_saved_copy(self):
        self.api.return_value = PEXELS_VIDEO
        self.run_tool(stock.stock_download, kind="video", id="123")
        self.run_tool(stock.stock_download, kind="video", id="123")
        self.assertEqual(self.fetch.call_count, 1)

    def test_odd_ids_and_kinds_are_refused(self):
        for kind, item in (("video", "../etc"), ("music", "a/../b"), ("photo", "1")):
            result, _ = self.run_tool(stock.stock_download, kind=kind, id=item)
            self.assertTrue(result.get("is_error"), (kind, item))
        self.api.assert_not_called()

    def test_fetch_refuses_plain_http(self):
        with self.assertRaises(RuntimeError):
            REAL_FETCH("http://example.com/a.mp3", stock.stock_dir() / "a.mp3")


if __name__ == "__main__":
    unittest.main()
