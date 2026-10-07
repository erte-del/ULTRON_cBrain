"""Instagram posting with Meta and Litterbox faked. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_instagram
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import reel
from storage import video_store
from tools import instagram, registry


class FakeMeta:
    """Answers the Graph API calls publish() makes, and records them."""

    def __init__(self, statuses=("IN_PROGRESS", "FINISHED")):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, method, path, **params):
        self.calls.append((method, path, params))
        if path == "me":
            return {"user_id": "178"}
        if path == "178/media":
            return {"id": "c1"}
        if path == "c1":
            return {"status_code": self.statuses.pop(0), "status": "Error: bad video"}
        if path == "178/media_publish":
            return {"id": "m1"}
        if path == "m1":
            return {"permalink": "https://www.instagram.com/reel/abc/"}
        raise AssertionError(path)


class Fakes:
    """A real Reel file, with Meta, Litterbox and storage faked."""

    @classmethod
    def setUpClass(cls):
        cls.src = Path(tempfile.mkdtemp())
        raw = cls.src / "raw.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=4",
                        "-f", "lavfi", "-i", "sine=duration=4", "-pix_fmt", "yuv420p", str(raw)], check=True)
        cls.reel = cls.src / "reel.mp4"
        reel.export(str(raw), str(cls.reel))
        cls.raw = raw

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src)

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.emit = mock.AsyncMock()
        self.meta = FakeMeta()
        self.upload = mock.Mock(return_value="https://litter.catbox.moe/x.mp4")
        for patch in (
            mock.patch.object(video_store, "VIDEOS_DIR", tmp / "videos"),
            mock.patch.object(instagram.image_store, "ASSETS_DIR", tmp / "assets"),
            mock.patch.object(instagram.hub, "emit", self.emit),
            mock.patch.object(instagram, "TOKEN_FILE", tmp / "token.json"),
            mock.patch.object(instagram.config, "INSTAGRAM_ACCESS_TOKEN", "env-token"),
            mock.patch.object(instagram, "_graph", self.meta),
            mock.patch.object(instagram, "upload", self.upload),
            mock.patch.object(instagram, "POLL_EVERY_S", 0),
            mock.patch.dict(instagram._previewed, clear=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def call(self, t, video, caption="Hello from Ultron #ai"):
        return asyncio.run(t.handler({"video": str(video), "caption": caption}))


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class InstagramTest(Fakes, unittest.TestCase):

    def test_preview_then_post(self):
        result = self.call(instagram.instagram_preview, self.reel)
        self.assertNotIn("is_error", result)
        card = self.emit.call_args.args[0]
        self.assertEqual(card["kind"], "video")
        self.assertEqual(card["data"]["prompt"], "Hello from Ultron #ai")  # caption shown on the card
        self.assertTrue(card["data"]["url"])

        result = self.call(instagram.instagram_post, self.reel)
        self.assertNotIn("is_error", result)
        self.assertIn("instagram.com/reel/abc", result["content"][0]["text"])
        create = next(c for c in self.meta.calls if c[1] == "178/media")[2]
        self.assertEqual(create, {"media_type": "REELS", "video_url": "https://litter.catbox.moe/x.mp4",
                                  "caption": "Hello from Ultron #ai"})
        self.assertEqual(self.meta.calls[-2][2], {"creation_id": "c1"})

    def test_post_refuses_without_preview(self):
        result = self.call(instagram.instagram_post, self.reel)
        self.assertTrue(result.get("is_error"))
        self.upload.assert_not_called()

    def test_post_refuses_a_changed_caption(self):
        self.call(instagram.instagram_preview, self.reel)
        result = self.call(instagram.instagram_post, self.reel, caption="Something else")
        self.assertTrue(result.get("is_error"))
        self.upload.assert_not_called()

    def test_one_approval_one_post(self):
        self.call(instagram.instagram_preview, self.reel)
        self.call(instagram.instagram_post, self.reel)
        again = self.call(instagram.instagram_post, self.reel)
        self.assertTrue(again.get("is_error"))
        self.assertEqual(self.upload.call_count, 1)

    def test_preview_rejects_files_that_arent_reels(self):
        result = self.call(instagram.instagram_preview, self.raw)  # 320x240
        self.assertTrue(result.get("is_error"))
        self.assertIn("size", result["content"][0]["text"])
        self.emit.assert_not_called()

    def test_processing_error_is_reported_not_posted(self):
        self.meta.statuses = ["ERROR"]
        self.call(instagram.instagram_preview, self.reel)
        result = self.call(instagram.instagram_post, self.reel)
        self.assertTrue(result.get("is_error"))
        self.assertNotIn("178/media_publish", [c[1] for c in self.meta.calls])

    def test_cover_frame_is_sent_as_thumb_offset(self):
        args = {"video": str(self.reel), "caption": "c", "cover_at": 1.5}
        asyncio.run(instagram.instagram_preview.handler(args))
        result = asyncio.run(instagram.instagram_post.handler(args))
        self.assertNotIn("is_error", result)
        create = next(c for c in self.meta.calls if c[1] == "178/media")[2]
        self.assertEqual(create["thumb_offset"], 1500)

    def test_cover_image_is_shown_then_uploaded(self):
        from PIL import Image
        cover = self.src / "cover.jpg"
        Image.new("RGB", (1080, 1920), "red").save(cover)
        args = {"video": str(self.reel), "caption": "c", "cover_image": str(cover)}
        asyncio.run(instagram.instagram_preview.handler(args))
        self.assertIn("image", [c.args[0]["kind"] for c in self.emit.call_args_list])
        asyncio.run(instagram.instagram_post.handler(args))
        create = next(c for c in self.meta.calls if c[1] == "178/media")[2]
        self.assertEqual(create["cover_url"], "https://litter.catbox.moe/x.mp4")
        self.assertEqual(self.upload.call_args_list[0].args[0], cover)

    def test_post_refuses_a_cover_that_wasnt_previewed(self):
        self.call(instagram.instagram_preview, self.reel)
        args = {"video": str(self.reel), "caption": "Hello from Ultron #ai", "cover_at": 2}
        result = asyncio.run(instagram.instagram_post.handler(args))
        self.assertTrue(result.get("is_error"))
        self.upload.assert_not_called()

    def test_cover_outside_the_video_is_refused(self):
        args = {"video": str(self.reel), "caption": "c", "cover_at": 99}
        result = asyncio.run(instagram.instagram_preview.handler(args))
        self.assertTrue(result.get("is_error"))

    def test_posting_always_asks(self):
        self.assertTrue(registry.needs_ok(registry.PREFIX + "instagram_post", {}))
        self.assertFalse(registry.needs_ok(registry.PREFIX + "instagram_preview", {}))


class TokenTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.file = tmp / "token.json"
        for patch in (mock.patch.object(instagram, "TOKEN_FILE", self.file),
                      mock.patch.object(instagram.config, "INSTAGRAM_ACCESS_TOKEN", "env-token")):
            patch.start()
            self.addCleanup(patch.stop)

    def renew(self, new="fresh-token"):
        answer = mock.MagicMock()
        answer.__enter__.return_value = answer
        answer.read.return_value = json.dumps({"access_token": new, "expires_in": 5184000}).encode()
        with mock.patch.object(instagram.urllib.request, "urlopen", return_value=answer) as urlopen:
            done = instagram.refresh_if_due()
        return done, urlopen

    def test_first_run_renews_the_env_token_and_keeps_the_new_one(self):
        done, urlopen = self.renew()
        self.assertTrue(done)
        self.assertIn("access_token=env-token", urlopen.call_args.args[0])
        self.assertEqual(instagram.token(), "fresh-token")
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_no_renewal_within_a_week(self):
        self.file.write_text(json.dumps({"access_token": "t", "refreshed_at": time.time() - 3600}))
        done, urlopen = self.renew()
        self.assertFalse(done)
        urlopen.assert_not_called()

    def test_renews_after_a_week(self):
        self.file.write_text(json.dumps({"access_token": "old", "refreshed_at": time.time() - 8 * 86400}))
        done, urlopen = self.renew("newer")
        self.assertTrue(done)
        self.assertIn("access_token=old", urlopen.call_args.args[0])
        self.assertEqual(instagram.token(), "newer")


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class ScheduleTest(Fakes, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.notify = mock.AsyncMock()
        queue = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, queue)
        for patch in (mock.patch.object(instagram, "QUEUE_DIR", queue),
                      mock.patch.object(instagram, "QUEUE_FILE", queue / "queue.json"),
                      mock.patch.object(instagram.notify, "push", self.notify)):
            patch.start()
            self.addCleanup(patch.stop)

    def schedule(self, at="2099-01-01 18:00", **extra):
        args = {"video": str(self.reel), "caption": "Later #ai", "cover_at": 1, "at": at, **extra}
        asyncio.run(instagram.instagram_preview.handler(args))
        return asyncio.run(instagram.instagram_schedule.handler(args))

    def soon(self):
        return datetime.fromtimestamp(time.time() + 3600).strftime("%Y-%m-%d %H:%M")

    def test_posts_when_due_from_its_own_copy(self):
        result = self.schedule(self.soon())
        self.assertNotIn("is_error", result)
        self.upload.assert_not_called()  # nothing goes out at scheduling time
        (entry,) = instagram._queue()
        asyncio.run(instagram.post_due(now=entry["at"] - 1))
        self.upload.assert_not_called()
        asyncio.run(instagram.post_due(now=entry["at"] + 1))
        create = next(c for c in self.meta.calls if c[1] == "178/media")[2]
        self.assertEqual((create["caption"], create["thumb_offset"]), ("Later #ai", 1000))
        self.assertEqual(instagram._queue()[0]["status"], "posted")
        self.assertIn("instagram.com/reel/abc", self.notify.call_args.args[1])
        self.assertFalse((instagram.QUEUE_DIR / entry["id"]).exists())
        asyncio.run(instagram.post_due(now=entry["at"] + 60))
        self.assertEqual(self.upload.call_count, 1)  # never twice

    def test_needs_a_preview_and_uses_it_up(self):
        args = {"video": str(self.reel), "caption": "x", "at": self.soon()}
        self.assertTrue(asyncio.run(instagram.instagram_schedule.handler(args)).get("is_error"))
        self.schedule(self.soon())
        again = asyncio.run(instagram.instagram_post.handler({"video": str(self.reel), "caption": "Later #ai",
                                                               "cover_at": 1}))
        self.assertTrue(again.get("is_error"))

    def test_refuses_past_times_and_bad_formats(self):
        self.assertTrue(self.schedule("2020-01-01 10:00").get("is_error"))
        self.assertTrue(self.schedule("tomorrow at six").get("is_error"))

    def test_too_late_is_missed_not_posted(self):
        self.schedule(self.soon())
        (entry,) = instagram._queue()
        asyncio.run(instagram.post_due(now=entry["at"] + instagram.LATE_LIMIT_S + 1))
        self.upload.assert_not_called()
        self.assertEqual(instagram._queue()[0]["status"], "missed")

    def test_failure_is_reported(self):
        self.meta.statuses = ["ERROR"]
        self.schedule(self.soon())
        (entry,) = instagram._queue()
        asyncio.run(instagram.post_due(now=entry["at"] + 1))
        self.assertEqual(instagram._queue()[0]["status"], "failed")
        self.assertEqual(self.notify.call_args.args[0], "Instagram post failed")

    def test_cancel(self):
        self.schedule(self.soon())
        (entry,) = instagram._queue()
        result = asyncio.run(instagram.instagram_cancel.handler({"id": entry["id"]}))
        self.assertNotIn("is_error", result)
        asyncio.run(instagram.post_due(now=entry["at"] + 1))
        self.upload.assert_not_called()
        self.assertTrue(asyncio.run(instagram.instagram_cancel.handler({"id": entry["id"]})).get("is_error"))

    def test_scheduling_asks_reading_the_queue_doesnt(self):
        self.assertTrue(registry.needs_ok(registry.PREFIX + "instagram_schedule", {}))
        self.assertEqual(registry.classify("mcp__ultron__instagram_queue"), "read")


class CommentsTest(unittest.TestCase):
    def fake(self, method, path, **params):
        if path == "me/media":
            return {"data": [{"id": "r1", "caption": "x" * 200, "permalink": "p"}]}
        if path == "r1/comments":
            return {"data": [{"id": "9", "text": "nice", "username": "a",
                              "replies": {"data": [{"id": "10", "text": "thanks", "username": "ai.ultron.120"}]}},
                             {"id": "11", "text": "wow", "username": "b"}]}
        if path == "9/replies":
            return {"id": "12"}
        raise AssertionError(path)

    def test_comments_flatten_replies(self):
        with mock.patch.object(instagram, "_graph", self.fake):
            posts = instagram.comments()
        first, second = posts[0]["comments"]
        self.assertEqual(first["replies"][0]["text"], "thanks")
        self.assertNotIn("replies", second)
        self.assertEqual(len(posts[0]["caption"]), 80)

    def test_reply_posts_the_message(self):
        graph = mock.Mock(side_effect=self.fake)
        with mock.patch.object(instagram, "_graph", graph), \
             mock.patch.object(instagram.config, "INSTAGRAM_ACCESS_TOKEN", "t"):
            result = asyncio.run(instagram.instagram_reply.handler({"comment": "9", "message": "Thank you!"}))
            bad = asyncio.run(instagram.instagram_reply.handler({"comment": "9/../me", "message": "x"}))
        self.assertNotIn("is_error", result)
        graph.assert_called_once_with("POST", "9/replies", message="Thank you!")
        self.assertTrue(bad.get("is_error"))

    def test_reading_is_free_replying_asks(self):
        self.assertEqual(registry.classify("mcp__ultron__instagram_comments"), "read")
        self.assertTrue(registry.needs_ok(registry.PREFIX + "instagram_reply", {}))


class StatsTest(unittest.TestCase):
    def fake(self, method, path, **params):
        if path == "me":
            return {"username": "ai.ultron.120", "followers_count": 12, "media_count": 2}
        if path == "me/media":
            return {"data": [{"id": "r1", "caption": "x" * 200, "media_product_type": "REELS"},
                             {"id": "r2", "caption": "new", "media_product_type": "REELS"}]}
        if path == "r1/insights":
            return {"data": [{"name": "views", "values": [{"value": 340}]},
                             {"name": "ig_reels_avg_watch_time", "values": [{"value": 4250}]}]}
        raise RuntimeError("Instagram: insights not ready")

    def test_stats_lists_posts_with_their_numbers(self):
        with mock.patch.object(instagram, "_graph", self.fake):
            s = instagram.stats()
        self.assertEqual((s["followers"], s["posts"]), (12, 2))
        first, second = s["latest"]
        self.assertEqual((first["views"], first["avg_watch_s"], len(first["caption"])), (340, 4.2, 80))
        self.assertNotIn("id", first)
        self.assertIn("not ready", second["insights"])  # one post's error doesn't sink the rest

    def test_stats_is_a_read_tool(self):
        self.assertEqual(registry.classify("mcp__ultron__instagram_stats"), "read")


if __name__ == "__main__":
    unittest.main()
