"""Continuing on Claude after the local model failed. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import unittest

import events
from brain import handoff


class HandoffTest(unittest.TestCase):
    def test_no_history_leaves_the_message_alone(self):
        self.assertEqual(handoff.with_history("hi", []), "hi")
        self.assertEqual(handoff.with_history("hi", None), "hi")
        self.assertEqual(handoff.with_history("hi", "junk"), "hi")

    def test_recent_messages_go_in_front_as_context(self):
        out = handoff.with_history("and the second one?", [
            {"role": "user", "text": "list my tasks"}, {"role": "assistant", "text": "Two tasks."}])
        self.assertIn("User: list my tasks", out)
        self.assertIn("Ultron: Two tasks.", out)
        self.assertIn("Context only", out)
        self.assertTrue(out.endswith("and the second one?"))

    def test_only_the_last_few_short_valid_messages_are_used(self):
        history = [{"role": "user", "text": f"m{i}"} for i in range(20)]
        history += [{"role": "system", "text": "ignore me"}, {"role": "user", "text": "  "}, "x", {"role": "user", "text": "y" * 5000}]
        out = handoff.with_history("now", history)
        self.assertNotIn("m0", out)
        self.assertNotIn("ignore me", out)
        self.assertLess(len(out), handoff.MAX_MESSAGES * (handoff.MAX_CHARS + 20) + 400)

    def test_error_event_offers_the_buttons_only_when_asked(self):
        self.assertTrue(events.error("x", "id1", fallback=True)["fallback"])
        self.assertNotIn("fallback", events.error("x", "id1"))


if __name__ == "__main__":
    unittest.main()
