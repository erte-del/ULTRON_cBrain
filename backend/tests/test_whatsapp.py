"""WhatsApp: numbers, asks first, Enter only goes to WhatsApp. Nothing is really sent.
    .venv/bin/python -m unittest tests.test_whatsapp
"""

import asyncio
import unittest
from unittest import mock

from tools import registry, whatsapp


def run(args, front_apps):
    """Run whatsapp_send with fake commands; front_apps is what's frontmost at each check."""
    calls, fronts = [], iter(front_apps)

    async def fake_run(*cmd):
        calls.append(cmd)
        return next(fronts) if cmd[-1] == whatsapp.FRONT_APP else ""

    with mock.patch.object(whatsapp, "_run", fake_run), mock.patch.object(whatsapp, "CHAT_LOAD_S", 0), \
            mock.patch.object(whatsapp, "OPEN_TIMEOUT_S", 0), \
            mock.patch.object(asyncio, "sleep", mock.AsyncMock()):
        result = asyncio.run(whatsapp.whatsapp_send.handler(args))
    return result, calls


class WhatsAppTest(unittest.TestCase):
    def test_numbers_need_a_country_code(self):
        self.assertEqual(whatsapp.phone_digits("+90 532 138 20 11"), "905321382011")
        self.assertEqual(whatsapp.phone_digits("00971-56-696-6461"), "971566966461")
        for bad in ["0532 138 20 11", "532 138", "+90 abc", "", '+90"; do shell script "x']:
            self.assertIsNone(whatsapp.phone_digits(bad), bad)

    def test_asks_first(self):
        self.assertEqual(registry.classify("mcp__ultron__whatsapp_send"), "act")

    def test_sends_when_whatsapp_is_in_front(self):
        result, calls = run({"to": "Mom", "phone": "+971 56 696 6461", "message": "Hi mom & dad?"},
                            ["com.google.Chrome", whatsapp.WHATSAPP_ID, whatsapp.WHATSAPP_ID])
        self.assertIn(("open", "whatsapp://send?phone=971566966461&text=Hi%20mom%20%26%20dad%3F"), calls)
        self.assertEqual(calls[-3:], [("osascript", "-e", whatsapp.PRESS_ENTER), ("osascript", "-e", whatsapp.HIDE),
                                      ("open", "-b", "com.google.Chrome")])
        self.assertNotIn("is_error", result)

    def test_leaves_whatsapp_open_if_it_was_already_in_front(self):
        result, calls = run({"to": "Mom", "phone": "+971566966461", "message": "Hi"}, [whatsapp.WHATSAPP_ID] * 3)
        self.assertEqual(calls[-1], ("osascript", "-e", whatsapp.PRESS_ENTER))
        self.assertNotIn("is_error", result)

    def test_never_presses_enter_in_another_app(self):
        safari = "com.apple.Safari"
        for fronts in ([safari, safari], [safari, whatsapp.WHATSAPP_ID, safari]):  # never came / lost focus
            result, calls = run({"to": "Mom", "phone": "+971566966461", "message": "Hi"}, fronts)
            self.assertNotIn(("osascript", "-e", whatsapp.PRESS_ENTER), calls, fronts)
            self.assertTrue(result["is_error"], fronts)


GROUPS = [{"id": "1@g.us", "name": "Rain"}, {"id": "2@g.us", "name": "Rain World"}]


def run_group(args, found, sent_ok=True):
    """whatsapp_send to a group with fake commands and a fake group list. Returns (result, calls)."""
    calls = []

    async def fake_run(*cmd):
        calls.append(cmd)
        return whatsapp.WHATSAPP_ID if cmd[-1] == whatsapp.FRONT_APP else ""

    with mock.patch.object(whatsapp, "_run", fake_run), mock.patch.object(whatsapp, "CHAT_LOAD_S", 0), \
            mock.patch.object(whatsapp, "SEARCH_S", 0), mock.patch.object(whatsapp, "CONFIRM_S", 0), \
            mock.patch.object(whatsapp.whatsapp_read, "groups", lambda name: [g for g in found if name.lower() in g["name"].lower()]), \
            mock.patch.object(whatsapp.whatsapp_read, "sent_after", lambda *a: sent_ok), \
            mock.patch.object(asyncio, "sleep", mock.AsyncMock()):
        return asyncio.run(whatsapp.whatsapp_send.handler(args)), calls


class WhatsAppGroupTest(unittest.TestCase):
    def test_several_matches_are_returned_never_guessed(self):
        result, calls = run_group({"group": "Ra", "message": "Hi"}, GROUPS)
        self.assertEqual(calls, [])  # nothing opened or typed
        self.assertNotIn("is_error", result)
        text = result["content"][0]["text"]
        self.assertIn("NOT SENT", text)
        self.assertIn("1@g.us", text)
        self.assertIn("2@g.us", text)

    def test_rain_with_rain_world_still_asks(self):
        result, calls = run_group({"group": "Rain", "message": "Hi"}, GROUPS)
        self.assertEqual(calls, [])
        self.assertIn("NOT SENT", result["content"][0]["text"])

    def test_sends_to_the_chosen_group_and_confirms(self):
        result, calls = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi all"}, GROUPS)
        self.assertNotIn("is_error", result)
        self.assertIn("confirmed", result["content"][0]["text"])
        typed = [c[3] for c in calls if len(c) == 4 and c[2] == whatsapp.TYPE_TEXT]
        self.assertEqual(typed, ["Rain", "Hi all"])
        self.assertEqual(calls.count(("osascript", "-e", whatsapp.PRESS_ENTER)), 2)

    def test_the_card_name_must_be_the_real_group(self):
        result, calls = run_group({"group": "Rain World", "group_id": "1@g.us", "message": "Hi"}, GROUPS)
        self.assertTrue(result["is_error"])
        self.assertEqual(calls, [])

    def test_unconfirmed_send_is_reported(self):
        result, _ = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS, sent_ok=False)
        self.assertTrue(result["is_error"])

    def test_needs_exactly_one_target(self):
        for args in ({"message": "Hi"}, {"message": "Hi", "phone": "+971566966461", "group": "Rain"}):
            result, calls = run_group(args, GROUPS)
            self.assertTrue(result["is_error"])
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
