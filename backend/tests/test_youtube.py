"""YouTube: the search it fetches, how it reads the page, what it refuses, and that watch_short
leaves nothing on disk. Nothing is fetched (the 'download' is an FFmpeg test clip).
    .venv/bin/python -m unittest tests.test_youtube
"""

import asyncio
import json
import shutil
import subprocess
import unittest
from unittest import mock

from tools import registry, youtube

VIDEO = {"videoId": "dQw4w9WgXcQ", "title": {"runs": [{"text": "Never Gonna Give You Up"}]},
         "ownerText": {"runs": [{"text": "Rick Astley"}]}, "lengthText": {"simpleText": "3:33"},
         "viewCountText": {"simpleText": "1,700,000,000 views"}, "publishedTimeText": {"simpleText": "16y ago"}}
# Results sit in shelves nested anywhere; a repeat and a bad id are dropped.
DATA = {"contents": [{"videoRenderer": VIDEO}, {"shelf": {"items": [{"videoRenderer": VIDEO},
        {"videoRenderer": {**VIDEO, "videoId": "x\" onclick=1"}}]}}]}
PAGE = f"<script>var ytInitialData = {json.dumps(DATA)};</script><script>var x = {{}};</script>"
SHORT = {"accessibilityText": "#1 Productivity Hack, 949 thousand views - play Short",
         "onTap": {"innertubeCommand": {"reelWatchEndpoint": {"videoId": "X7QmaNpl4P4"}}}}
SHORTS_PAGE = PAGE.replace(json.dumps(DATA), json.dumps({"shelf": [{"shortsLockupViewModel": SHORT}] * 2}))


class YoutubeTest(unittest.TestCase):
    def call(self, page=PAGE, **args):
        async def fake_fetch(url):
            self.url = url
            return page

        self.url = None
        with mock.patch.object(youtube, "_fetch", fake_fetch):
            return asyncio.run(youtube.youtube.handler(args))

    def test_only_reads(self):
        self.assertEqual(registry.classify("mcp__ultron__youtube"), "read")

    def test_search(self):
        result = self.call(query="rick astley & friends")
        self.assertEqual(self.url, "https://www.youtube.com/results?search_query=rick+astley+%26+friends&hl=en")
        lines = result["content"][0]["text"].splitlines()
        self.assertEqual(lines[0], "https://www.youtube.com/watch?v=dQw4w9WgXcQ | Never Gonna Give You Up | "
                                   "Rick Astley | 3:33 | 1,700,000,000 views | 16y ago")
        self.assertEqual(sum("watch?v=" in line for line in lines), 1)

    def test_refuses_empty_query_and_empty_page(self):
        self.assertTrue(self.call(query="  ")["is_error"])
        self.assertIsNone(self.url)  # nothing was fetched
        self.assertTrue(self.call(page="<html>consent</html>", query="x")["is_error"])

    def test_shorts_search(self):
        result = self.call(page=SHORTS_PAGE, query="productivity", shorts=True)
        self.assertIn("&sp=EgIQCQ%3D%3D", self.url)
        self.assertEqual(result["content"][0]["text"].splitlines()[0],
                         "https://www.youtube.com/shorts/X7QmaNpl4P4 | #1 Productivity Hack, 949 thousand views")

    def test_link_id(self):
        for link in ("https://www.youtube.com/shorts/X7QmaNpl4P4", "https://youtu.be/X7QmaNpl4P4?si=1",
                     "https://www.youtube.com/watch?v=X7QmaNpl4P4&t=3", "X7QmaNpl4P4"):
            self.assertEqual(youtube.LINK_ID.search(link).group(1), "X7QmaNpl4P4")
        self.assertIsNone(youtube.LINK_ID.search("https://evil.example/short"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_watch_short_deletes_the_video(self):
        folders = []

        def fake_download(vid, folder):
            folders.append(folder)
            video = folder / "short.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=270x480:duration=3",
                            "-pix_fmt", "yuv420p", str(video)], check=True)
            return video, {"title": "Hack", "view_count": 5, "duration": 3}

        with mock.patch.object(youtube, "download", fake_download), \
             mock.patch.object(youtube.reels, "transcribe", return_value=[{"word": " hi"}]):
            result = asyncio.run(youtube.watch_short.handler({"url": "https://youtu.be/X7QmaNpl4P4"}))
        self.assertIn("Title: Hack\nViews: 5\n", result["content"][0]["text"])
        self.assertIn("Said (Whisper, en): hi", result["content"][0]["text"])
        self.assertEqual([c["type"] for c in result["content"][1:]], ["image"] * youtube.FRAMES)
        self.assertFalse(folders[0].exists())

        with mock.patch.object(youtube, "download", side_effect=lambda vid, folder: (folders.append(folder),
                               (folder / "x").write_text("half"), (_ for _ in ()).throw(RuntimeError("cut off")))):
            result = asyncio.run(youtube.watch_short.handler({"url": "X7QmaNpl4P4"}))
        self.assertTrue(result["is_error"])
        self.assertFalse(folders[1].exists())  # deleted after a failure too
        self.assertTrue(asyncio.run(youtube.watch_short.handler({"url": "x", "language": "en; rm"}))["is_error"])

    def test_canvas_card_only_takes_video_ids(self):
        from tools import canvas
        card = canvas._card_data({"kind": "youtube", "items": [
            {"id": "dQw4w9WgXcQ", "title": "Never", "length": "3:33", "url": "https://evil.example"},
            {"id": "../../evil?x=1", "title": "Bad"}]})
        self.assertEqual(card, {"items": [{"id": "dQw4w9WgXcQ", "title": "Never", "length": "3:33"}]})
        with self.assertRaises(ValueError):
            canvas._card_data({"kind": "youtube", "items": [{"id": "nope"}]})


if __name__ == "__main__":
    unittest.main()
