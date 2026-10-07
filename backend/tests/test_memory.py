"""Memory: remember -> new chat -> recall, secrets refused, saving asks first.
    .venv/bin/python -m unittest tests.test_memory
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from brain.brain_claudecode import ClaudeCodeBrain
from storage import memory_store
from tools import memory, registry


def call(tool, args):
    return asyncio.run(tool.handler(args))


class MemoryTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(memory_store, "MEMORY_FILE", Path(tempfile.mkdtemp()) / "memory.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.vault = Path(tempfile.mkdtemp())  # never the real one
        patch = mock.patch.object(config, "VAULT_DIR", self.vault)
        patch.start()
        self.addCleanup(patch.stop)

    def test_remember_then_a_new_chat_knows_it(self):
        result = call(memory.remember, {"text": "Prefers  meetings in the morning.", "category": "preferences"})
        self.assertIn("mem_1", result["content"][0]["text"])
        # a new conversation: the memory is in its system prompt
        self.assertIn("- mem_1 [preferences] Prefers meetings in the morning.", ClaudeCodeBrain()._options().system_prompt)
        self.assertIn("mem_1", call(memory.recall, {"query": "MORNING meetings"})["content"][0]["text"])
        self.assertIn("Nothing", call(memory.recall, {"query": "evening"})["content"][0]["text"])

    def test_forget(self):
        call(memory.remember, {"text": "'Sarah' is Sarah K. from work.", "category": "people"})
        self.assertIn("Sarah K.", call(memory.forget, {"memory_id": "mem_1"})["content"][0]["text"])
        self.assertEqual(memory_store.entries(), [])
        self.assertEqual(memory_store.prompt_block(), "")
        self.assertTrue(call(memory.forget, {"memory_id": "mem_1"})["is_error"])

    def test_saving_and_deleting_ask_first_and_the_card_shows_the_memory(self):
        self.assertEqual(registry.classify("mcp__ultron__remember"), "act")
        self.assertEqual(registry.classify("mcp__ultron__forget"), "act")
        self.assertEqual(registry.classify("mcp__ultron__recall"), "read")
        memory_store.add("Lives in Izmir.", "facts")
        title, _, details = registry.describe_call("mcp__ultron__forget", {"memory_id": "mem_1"})
        self.assertEqual(title, "Forget this")
        self.assertIn(["memory", "Lives in Izmir."], details)

    def test_secrets_are_never_stored(self):
        for text in ["My bank password is hunter2", "Wifi şifresi: kedi1234", "Card 4111 1111 1111 1111 exp 12/29",
                     "Use key sk-ant-REDACTED for the API",
                     "Telegram bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1"]:
            result = call(memory.remember, {"text": text, "category": "facts"})
            self.assertTrue(result.get("is_error"), text)
        for text in ["Phone number is +90 532 123 45 67", "Dentist is Dr. Demir on Alsancak street",
                     "Never wants to be asked for a password twice"]:
            self.assertIsNone(memory_store.secret_in(text), text)
        self.assertEqual(memory_store.entries(), [])

    def test_edit_ids_and_bad_input(self):
        memory_store.add("Works on Ultron.", "projects")
        second = memory_store.add("Decided to use TickTick.", "decisions", source="you")
        memory_store.delete("mem_1")
        self.assertEqual(memory_store.add("Has an Android phone.", "facts")["id"], "mem_3")  # ids aren't reused
        memory_store.update(second["id"], "Decided to use TickTick for reminders.", "decisions")
        self.assertEqual(memory_store.entries()[0]["text"], "Decided to use TickTick for reminders.")
        for text, category in [("", "facts"), ("x" * 501, "facts"), ("Fine", "secrets")]:
            with self.assertRaises(ValueError):
                memory_store.add(text, category)
        with self.assertRaises(KeyError):
            memory_store.update("mem_99", "x", "facts")

    def test_the_prompt_only_gets_the_newest(self):
        for i in range(40):
            memory_store.add(f"Fact number {i} about the user, long enough to fill the budget up.", "facts")
        block = memory_store.prompt_block()
        self.assertLess(len(block), memory_store.PROMPT_CHARS + 300)
        self.assertIn("Fact number 39", block)
        self.assertNotIn("Fact number 0 ", block)
        self.assertIn("find them with recall", block)


    def test_the_vault_gets_the_memory_and_conversation_notes(self):
        memory_store.add("Lives in Dubai.", "facts")
        second = memory_store.add("Likes F1.", "preferences")
        memory_store.delete(second["id"])
        self.assertIn("- Lives in Dubai.", (self.vault / "Ultron" / "memory" / "Facts.md").read_text())
        self.assertNotIn("F1", (self.vault / "Ultron" / "memory" / "Preferences.md").read_text())

        path = memory_store.save_conversation("Revision: plan / SAT?", "Made a revision plan.\nwifi password is kedi1\n\nAbout him: tired.", 0)
        self.assertTrue(path.startswith("Ultron/memory/Conversations/1970-01-01 "), path)
        self.assertTrue(path.endswith(" Revision plan SAT.md"), path)  # no / ? : in file names
        memory_store.save_conversation("Later", "Talked about F1.")
        block = memory_store.conversations_block()
        self.assertNotIn("kedi1", block)
        self.assertLess(block.index("Talked about F1"), block.index("Made a revision plan"))  # newest first
        self.assertIn("Talked about F1", ClaudeCodeBrain()._options().system_prompt)


    def test_facts_learned_from_a_conversation(self):
        memory_store.add("Lives in Dubai.", "facts")
        saved = memory_store.learn(" - [people] Deniz is his cousin in Izmir.\n- [facts] lives in dubai.\n"
                                   "- [secrets] Nope.\n- [facts] His wifi password is kedi1234\nnothing else")
        self.assertEqual([m["text"] for m in saved], ["Deniz is his cousin in Izmir."])
        self.assertEqual(saved[0]["source"], "conversation")
        self.assertIn("Deniz", (self.vault / "Ultron" / "memory" / "People.md").read_text())
        self.assertEqual(memory_store.learn("Remember: nothing"), [])

if __name__ == "__main__":
    unittest.main()
