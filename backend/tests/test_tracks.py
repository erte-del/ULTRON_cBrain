import asyncio
import unittest
from unittest import mock

from tools import registry, tracks


class TracksTest(unittest.TestCase):
    def test_nicknames_find_the_track(self):
        self.assertEqual(tracks.find_track("Bathurst"), "mount-panorama")
        self.assertEqual(tracks.find_track("the Ring"), "nurburgring-24h")
        self.assertEqual(tracks.find_track("COTA"), "cota")
        self.assertIsNone(tracks.find_track("pizza"))

    def test_corner_answer_uses_the_numbered_corner(self):
        out = asyncio.run(tracks.track_info.handler({"track": "imola", "question": "corner 5"}))
        text = out["content"][0]["text"]
        self.assertIn("Corner 5: left-hander", text)
        self.assertIn("estimate", text)

    def test_unnumbered_track_says_so(self):
        out = asyncio.run(tracks.track_info.handler({"track": "snetterton", "question": "corner 3"}))
        self.assertIn("no numbered corners yet", out["content"][0]["text"])

    def test_show_track_puts_a_track_card_on_the_canvas(self):
        with mock.patch("tools.canvas.hub.emit", new=mock.AsyncMock()) as emit:
            out = asyncio.run(tracks.show_track.handler({"track": "spa"}))
        event = emit.await_args.args[0]
        self.assertEqual(event["kind"], "track")
        self.assertTrue(event["data"]["points"])
        self.assertNotIn("is_error", out)

    def test_both_track_tools_are_read(self):
        self.assertIn("mcp__ultron__show_track", registry.auto_allowed())
        self.assertIn("mcp__ultron__track_info", registry.auto_allowed())


if __name__ == "__main__":
    unittest.main()
