"""The Ollama buttons through the real websocket: "try again", "continue with Claude" and the tools
panel. The brain and the turn are replaced, so nothing starts Claude Code or Ollama. Run from the
backend folder:
    .venv/bin/python -m unittest discover tests
"""

import json
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import main

ORIGIN = {"origin": "http://127.0.0.1:8000"}


class FakeWork:
    """Records what the handlers ran, and lets a test wait for it."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.done = threading.Event()

    def recorder(self, name):
        async def run(*args, **kw):
            self.calls.append((name, args, kw))
            self.done.set()
        return run


class FallbackSocketTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)  # no `with`: don't start Claude Code
        self.work = FakeWork()

    def send(self, patches, message):
        with mock.patch.multiple(main, **patches), self.client.websocket_connect("/ws", headers=ORIGIN) as ws:
            ws.send_text(json.dumps(message))
            self.assertTrue(self.work.done.wait(5), "the handler never ran")

    def test_retry_sends_the_same_message_and_files_again_on_the_same_brain(self):
        upload = "a" * 12
        with mock.patch.object(main.upload_store, "UPLOAD_ID", __import__("re").compile("^a{12}$")):
            self.send({"run_turn": self.work.recorder("run_turn")},
                      {"type": "user.fallback", "action": "retry", "text": "  what is this?  ", "files": [upload, "../bad"], "history": []})
        (name, args, _), = self.work.calls
        self.assertEqual(name, "run_turn")
        self.assertEqual(args[1], "what is this?")  # (send, text, model_override, selected_image, files, device)
        self.assertEqual(args[4], [upload])  # an id that isn't one of ours is dropped

    def test_continue_on_claude_switches_first_then_sends_with_the_chat_in_front(self):
        order = []

        async def switch(provider):
            order.append(("switch", provider))
            main.brain.provider = "claude"

        async def turn(send, text, *rest):
            order.append(("turn", text))
            self.work.done.set()

        previous = main.brain.provider
        main.brain.provider = "ollama"
        try:
            self.send({"switch_provider": switch, "run_turn": turn},
                      {"type": "user.fallback", "action": "claude", "text": "and the second one?",
                       "history": [{"role": "user", "text": "list my tasks"}]})
        finally:
            main.brain.provider = previous
        self.assertEqual(order[0], ("switch", "claude"))
        self.assertEqual(order[1][0], "turn")
        self.assertIn("User: list my tasks", order[1][1])
        self.assertTrue(order[1][1].endswith("and the second one?"))

    def test_continue_on_claude_does_not_send_if_the_switch_failed(self):
        async def switch(provider):
            pass  # the brain stays on Ollama, as when switching fails

        turned, sent = [], []

        async def turn(*a):
            turned.append(a)

        async def send(ev):
            sent.append(ev["state"])

        previous = main.brain.provider
        main.brain.provider = "ollama"
        try:
            import asyncio
            with mock.patch.multiple(main, switch_provider=switch, run_turn=turn):
                asyncio.run(main.continue_on_claude(send, "hi", [], [], None, None, ""))
        finally:
            main.brain.provider = previous
        self.assertEqual(turned, [])
        self.assertEqual(sent, ["thinking", "idle"])  # busy while switching, idle again when it fails

    def test_an_empty_fallback_message_does_nothing(self):
        ran = []

        async def turn(*a):
            ran.append(a)

        with mock.patch.multiple(main, run_turn=turn), self.client.websocket_connect("/ws", headers=ORIGIN) as ws:
            ws.send_text(json.dumps({"type": "user.fallback", "action": "retry", "text": "  ", "history": []}))
            ws.send_text(json.dumps({"type": "user.text", "text": "x"}))  # something after it that does run
            self.work.done.wait(0.5)
        self.assertEqual([a[1] for a in ran], ["x"])

    def test_the_tools_panel_sets_the_groups_on_the_ollama_brain(self):
        previous = main.brain.provider
        main.brain.provider = "ollama"
        sets = []

        async def set_groups(names):
            sets.append(names)
            self.work.done.set()

        try:
            self.send({"set_groups": set_groups}, {"type": "user.groups", "on": ["mac", "gmail"]})
        finally:
            main.brain.provider = previous
        self.assertEqual(sets, [["mac", "gmail"]])

    def test_the_tools_panel_is_refused_on_other_brains(self):
        previous = main.brain.provider
        main.brain.provider = "claude"
        sets = []

        async def set_groups(names):
            sets.append(names)

        try:
            with mock.patch.multiple(main, set_groups=set_groups), self.client.websocket_connect("/ws", headers=ORIGIN) as ws:
                ws.send_text(json.dumps({"type": "user.groups", "on": ["mac"]}))
                seen = []
                for _ in range(40):  # the greeting events, then our notice
                    seen.append(ws.receive_json())
                    if seen[-1]["type"] == "notice":
                        break
        finally:
            main.brain.provider = previous
        self.assertEqual(sets, [])
        self.assertEqual(seen[-1]["type"], "notice")

    def test_clean_files_keeps_only_real_ids(self):
        self.assertEqual(main.clean_files("nope"), [])
        self.assertEqual(main.clean_files(None), [])
        self.assertEqual(main.clean_files([1, "../x"]), [])


if __name__ == "__main__":
    unittest.main()
