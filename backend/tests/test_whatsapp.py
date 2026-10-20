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


# What the screen reader saw with "Rain" searched (points from the window's top-left), from a real screenshot.
SEARCH_SCREEN = [(398, 22, 435, 34, "Chats"), (281, 67, 310, 81, "Rain"), (240, 136, 287, 152, "Chats"),
                 (312, 179, 342, 194, "Rain"), (312, 247, 385, 262, "Rain World"), (240, 325, 289, 341, "Media"),
                 (240, 423, 320, 439, "Messages"), (254, 559, 285, 574, "Rain")]
CHAT_LIST = [(10, 50, 42, 67, "Chats"), (398, 22, 435, 34, "Chats"), (312, 179, 342, 194, "Rain")]
COMMUNITIES = [(10, 50, 42, 67, "Q Chats"), (390, 22, 470, 34, "Communities"), (312, 66, 380, 80, "Rain World")]
PICTURE = [(400, 400, 600, 430, "a photo, no sidebar")]
OPENED = lambda title: [(667, 13, 700, 28, title), (667, 29, 850, 44, "Andrey, Ayaan, Hadi, Hasan, You")]


def run_group(args, found, sent_ok=True, screens=None):
    """whatsapp_send to a group with fake commands, screen and group list. Returns (result, calls, clicks)."""
    calls, clicks = [], []
    screens = iter(screens if screens is not None else [CHAT_LIST, SEARCH_SCREEN, OPENED("Rain")])

    async def fake_run(*cmd):
        calls.append(cmd)
        return whatsapp.WHATSAPP_ID if cmd[-1] == whatsapp.FRONT_APP else ""

    async def fake_click(x, y):
        clicks.append((x, y))

    with mock.patch.object(whatsapp, "_run", fake_run), mock.patch.object(whatsapp, "CHAT_LOAD_S", 0), \
            mock.patch.object(whatsapp, "SEARCH_S", 0), mock.patch.object(whatsapp, "CONFIRM_S", 0), \
            mock.patch.object(whatsapp.whatsapp_ui, "window", mock.AsyncMock(return_value=(0, 30, 1920, 972))), \
            mock.patch.object(whatsapp.whatsapp_ui, "read_screen", lambda rect: _async(next(screens))), \
            mock.patch.object(whatsapp.whatsapp_ui, "click", fake_click), \
            mock.patch.object(whatsapp.whatsapp_read, "groups", lambda name: [g for g in found if name.lower() in g["name"].lower()]), \
            mock.patch.object(whatsapp.whatsapp_read, "sent_after", lambda *a: sent_ok), \
            mock.patch.object(asyncio, "sleep", mock.AsyncMock()):
        return asyncio.run(whatsapp.whatsapp_send.handler(args)), calls, clicks


async def _async(value):
    return value


class WhatsAppGroupTest(unittest.TestCase):
    def test_several_matches_are_returned_never_guessed(self):
        result, calls, clicks = run_group({"group": "Ra", "message": "Hi"}, GROUPS)
        self.assertEqual(calls, [])  # nothing opened or typed
        self.assertNotIn("is_error", result)
        text = result["content"][0]["text"]
        self.assertIn("NOT SENT", text)
        self.assertIn("1@g.us", text)
        self.assertIn("2@g.us", text)

    def test_exact_name_wins_over_longer_names(self):
        result, calls, clicks = run_group({"group": "Rain", "message": "Hi"}, GROUPS)
        self.assertNotIn("is_error", result)
        self.assertIn("confirmed", result["content"][0]["text"])

    def test_no_exact_name_asks(self):
        result, calls, clicks = run_group({"group": "Rain Wor", "message": "Hi"}, GROUPS)
        self.assertEqual(calls, [])
        self.assertIn("NOT SENT", result["content"][0]["text"])

    def test_gets_back_to_the_chat_list_from_a_picture(self):
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS,
                                          screens=[PICTURE, CHAT_LIST, SEARCH_SCREEN, OPENED("Rain")])
        self.assertNotIn("is_error", result)
        self.assertEqual(calls.index(("osascript", "-e", whatsapp.ESCAPE)) < calls.index(("osascript", "-e", whatsapp.SEARCH)), True)

    def test_gets_back_to_the_chat_list_from_another_tab(self):
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS,
                                          screens=[COMMUNITIES, CHAT_LIST, SEARCH_SCREEN, OPENED("Rain")])
        self.assertNotIn("is_error", result)
        self.assertEqual(clicks[0], (60, 88.5))  # the sidebar's Chats button, before searching
        self.assertEqual(len(clicks), 2)

    def test_gives_up_if_it_cannot_reach_the_chat_list(self):
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS,
                                          screens=[PICTURE] * 8)
        self.assertTrue(result["is_error"])
        self.assertNotIn(("osascript", "-e", whatsapp.SEARCH), calls)

    def test_sends_to_the_chosen_group_and_confirms(self):
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi all"}, GROUPS)
        self.assertNotIn("is_error", result)
        self.assertIn("confirmed", result["content"][0]["text"])
        typed = [c[3] for c in calls if len(c) == 4 and c[2] == whatsapp.TYPE_TEXT]
        self.assertEqual(typed, ["Rain", "Hi all"])
        self.assertEqual(calls.count(("osascript", "-e", whatsapp.PRESS_ENTER)), 1)  # only after the title matched
        self.assertEqual(clicks, [(335, 219)])  # the "Rain" row under Chats, not "Rain World" or the message hit

    def test_clicks_the_exact_name_even_when_listed_second(self):
        screen = [(240, 136, 287, 152, "Chats"), (312, 179, 385, 194, "Rain World"), (312, 247, 342, 262, "Rain"),
                  (240, 325, 289, 341, "Media")]
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS,
                                          screens=[CHAT_LIST, screen, OPENED("Rain")])
        self.assertEqual(clicks, [(335, 287)])

    def test_nothing_typed_if_the_opened_chat_is_not_the_group(self):
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS,
                                          screens=[CHAT_LIST, SEARCH_SCREEN, OPENED("Rain World")])
        self.assertTrue(result["is_error"])
        self.assertNotIn(("osascript", "-e", whatsapp.PRESS_ENTER), calls)
        self.assertFalse([c for c in calls if len(c) == 4 and c[3] == "Hi"])

    def test_nothing_clicked_if_the_group_is_not_in_the_results(self):
        result, calls, clicks = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS,
                                          screens=[CHAT_LIST, [(240, 136, 287, 152, "Chats"), (312, 247, 385, 262, "Rain World")]])
        self.assertTrue(result["is_error"])
        self.assertEqual(clicks, [])

    def test_the_card_name_must_be_the_real_group(self):
        result, calls, clicks = run_group({"group": "Rain World", "group_id": "1@g.us", "message": "Hi"}, GROUPS)
        self.assertTrue(result["is_error"])
        self.assertEqual(calls, [])

    def test_unconfirmed_send_is_reported(self):
        result, *_ = run_group({"group": "Rain", "group_id": "1@g.us", "message": "Hi"}, GROUPS, sent_ok=False)
        self.assertTrue(result["is_error"])

    def test_needs_exactly_one_target(self):
        for args in ({"message": "Hi"}, {"message": "Hi", "phone": "+971566966461", "group": "Rain"}):
            result, calls, clicks = run_group(args, GROUPS)
            self.assertTrue(result["is_error"])
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
