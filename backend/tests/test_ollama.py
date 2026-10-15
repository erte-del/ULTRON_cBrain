"""Ollama as a chat brain: which models are offered and how the brain is set up. Run from the
backend folder:
    .venv/bin/python -m unittest discover tests
"""

import unittest
from unittest import mock

import config
import ollama
from brain.brain_claudecode import ClaudeCodeBrain

INSTALLED = ["qwen3:8b", "ultron-qwen3-8b:latest", "ultron-qwen3-14b:latest"]


class ModelsTest(unittest.TestCase):
    def test_plain_models_are_not_offered(self):
        with mock.patch.object(config, "OLLAMA_MODEL", ""):
            self.assertEqual(ollama.chat_models(INSTALLED), ["ultron-qwen3-8b:latest", "ultron-qwen3-14b:latest"])

    def test_the_model_named_in_env_is_offered_and_preferred(self):
        with mock.patch.object(config, "OLLAMA_MODEL", "qwen3:8b"):
            self.assertIn("qwen3:8b", ollama.chat_models(INSTALLED))
            self.assertEqual(ollama.default_model(INSTALLED), "qwen3:8b")

    def test_latest_tag_is_ignored_when_matching(self):
        self.assertTrue(ollama.has(INSTALLED, "ultron-qwen3-8b"))
        self.assertFalse(ollama.has(INSTALLED, "ultron-qwen3-4b"))

    def test_default_falls_back_to_an_ultron_model_or_none(self):
        with mock.patch.object(config, "OLLAMA_MODEL", "gone"):
            self.assertEqual(ollama.default_model(INSTALLED), "ultron-qwen3-8b:latest")
            self.assertIsNone(ollama.default_model(["qwen3:8b"]))

    def test_not_running_is_none(self):
        with mock.patch.object(ollama.urllib.request, "urlopen", side_effect=OSError):
            self.assertIsNone(ollama.installed())


class BrainTest(unittest.TestCase):
    def brain(self) -> ClaudeCodeBrain:
        b = ClaudeCodeBrain()
        b.provider, b.local_model = "ollama", "ultron-qwen3-8b"
        b._model = b.local_model
        return b

    def test_talks_to_ollama_on_this_machine_with_no_thinking(self):
        env = self.brain()._options().env
        self.assertEqual(env["ANTHROPIC_BASE_URL"], config.OLLAMA_URL)
        self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "ultron-qwen3-8b")
        self.assertEqual(env["MAX_THINKING_TOKENS"], "0")

    def test_no_claude_only_tools(self):
        o = self.brain()._options()
        self.assertEqual(o.tools, ["WebFetch"])
        self.assertIn("mcp__ultron__ask_expert", o.disallowed_tools)

    def test_new_conversation_keeps_the_local_model(self):
        import asyncio
        b = self.brain()
        asyncio.run(b.new_conversation("ollama"))
        self.assertEqual(b.model, "ultron-qwen3-8b")


if __name__ == "__main__":
    unittest.main()
