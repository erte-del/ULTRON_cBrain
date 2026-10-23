"""trim_chat: drop the older part of a chat and keep the recent topic.
Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import unittest
from unittest import mock

from brain import agent
from brain.agent import Ultron
from brain.base import Done, TextDelta
from storage import chat_store
from tools import chat, registry


class FakeBrain:
    provider = "claude"
    model = "sonnet"
    context_tokens = 0
    last_active = 0.0

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.restarts = 0

    async def send(self, text, images=None, model="sonnet"):
        self.prompts.append(text)
        yield TextDelta(f"reply to: {text.rsplit(chr(10), 1)[-1]}")
        yield Done("claude-sonnet-5")

    async def restart_session(self) -> None:
        self.restarts += 1

    async def new_conversation(self, provider=None, resume=None) -> None:
        pass


class TrimChatTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.notes: list[str] = []

        async def write_note(transcript):
            self.notes.append(transcript)
            return "Title\n\nWhat happened."

        patches = [
            mock.patch.object(agent, "write_note", write_note),
            mock.patch.object(agent.memory_store, "save_conversation", return_value=None),
            mock.patch.object(agent.memory_write, "learn", return_value=[]),
            mock.patch.object(agent.memory_search, "wake_context", return_value=""),
            mock.patch.object(agent.memory_surface, "related_hint", return_value=""),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.brain = FakeBrain()
        self.ultron = Ultron(self.brain)

    async def say(self, text):
        return [ev async for ev in self.ultron.handle_text(text)]

    async def three_turns(self):
        for text in ("school: when is the maths test?", "school: and physics?", "play some Spotify"):
            await self.say(text)

    async def test_turns_are_numbered_and_announced(self):
        evs = await self.say("hello")
        self.assertEqual(evs[0], {"type": "conversation.turn", "turn": 1})
        await self.say("again")
        self.assertIn("[Turn 2]", self.brain.prompts[-1])
        self.assertEqual(chat.state, {"oldest": 1, "current": 2, "can_undo": False})

    async def test_trim_keeps_the_recent_part_and_notes_the_rest(self):
        await self.three_turns()
        self.assertEqual(await self.ultron.trim(3, "school work"), 2)
        self.assertEqual(self.brain.restarts, 1)
        self.assertEqual([t["n"] for t in self.ultron.turns], [3])
        await self.say("add Daft Punk to it")
        prompt = self.brain.prompts[-1]
        self.assertIn("Everything before turn 3 was cleared", prompt)
        self.assertIn("school work", prompt)
        self.assertIn("User: play some Spotify", prompt)
        self.assertNotIn("maths", prompt)
        self.assertIn("[Turn 4]", prompt)
        await self.say("and another")  # the seed is sent once
        self.assertNotIn("cleared", self.brain.prompts[-1])
        await asyncio.gather(*self.ultron.notes)
        await self.ultron.wrap_up()
        self.assertIn("maths test", self.notes[0])  # the dropped part, written when it was dropped
        self.assertNotIn("maths", self.notes[-1])  # not again at the end of the chat
        self.assertIn("Spotify", self.notes[-1])

    async def test_nothing_to_trim_before_the_first_turn_or_after_the_last(self):
        await self.three_turns()
        self.assertEqual(await self.ultron.trim(1), 0)
        self.assertEqual(await self.ultron.trim(9), 0)
        self.assertEqual(self.brain.restarts, 0)

    async def test_undo_brings_the_whole_chat_back_once(self):
        await self.three_turns()
        await self.ultron.trim(3)
        self.assertTrue(chat.state["can_undo"])
        self.assertEqual(await self.ultron.untrim(), 2)
        self.assertEqual(await self.ultron.untrim(), 0)
        self.assertEqual([t["n"] for t in self.ultron.turns], [1, 2, 3])
        await self.say("so, the maths test")
        self.assertIn("maths", self.brain.prompts[-1])

    async def test_a_loaded_chat_carries_on_from_its_numbers(self):
        messages = [{"role": "user", "text": "hi", "turn": 5}, {"role": "assistant", "text": "hello"},
                    {"role": "user", "text": "more"}, {"role": "assistant", "text": "ok"}]
        tagged = self.ultron.adopt(messages)
        self.assertEqual([m.get("turn") for m in tagged if m["role"] == "user"], [5, 6])
        evs = await self.say("next")
        self.assertEqual(evs[0]["turn"], 7)

    async def test_new_conversation_starts_counting_again(self):
        await self.three_turns()
        await self.ultron.trim(3)
        await self.ultron.new_conversation()
        self.assertEqual((self.ultron.turn, self.ultron.turns, self.ultron.trimmed), (0, [], None))


class TrimChatToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        chat.state.update(oldest=1, current=6, can_undo=False)
        chat.take_trim()

    async def test_asks_for_a_trim_once(self):
        out = await chat.trim_chat.handler({"first_turn": 4, "cleared": "school work"})
        self.assertNotIn("is_error", out)
        self.assertEqual(chat.take_trim(), {"first_turn": 4, "cleared": "school work"})
        self.assertIsNone(chat.take_trim())

    async def test_refuses_a_turn_that_is_not_in_the_chat(self):
        for args in ({"first_turn": 1}, {"first_turn": 7}, {}, {"first_turn": "four"}, {"undo": True}):
            out = await chat.trim_chat.handler(args)
            self.assertTrue(out.get("is_error"), args)
        self.assertIsNone(chat.take_trim())

    async def test_undo_only_after_a_trim(self):
        chat.state["can_undo"] = True
        await chat.trim_chat.handler({"undo": True})
        self.assertEqual(chat.take_trim(), {"undo": True})

    def test_is_an_act_tool_with_a_title(self):
        self.assertEqual(next(t.kind for t in registry.TOOLS if t.tool.name == "trim_chat"), "act")
        self.assertEqual(registry.TITLES["trim_chat"], "Clear the earlier part of this chat")


class SavedTrimmedChatTest(unittest.TestCase):
    def test_turn_numbers_are_saved_with_messages_and_cards(self):
        messages = chat_store._clean([{"role": "user", "text": "hi", "turn": 5}, {"role": "assistant", "text": "yo", "turn": 5}])
        self.assertEqual(messages[0]["turn"], 5)
        self.assertNotIn("turn", messages[1])
        cards = chat_store._clean_cards([{"id": "a", "kind": "text", "title": "t", "data": {}, "turn": 6}])
        self.assertEqual(cards[0]["turn"], 6)


if __name__ == "__main__":
    unittest.main()
