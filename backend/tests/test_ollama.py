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


class WarmTest(unittest.TestCase):
    def test_asks_ollama_to_load_the_model_and_keep_it(self):
        import json
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.assertTrue(ollama.warm("ultron-qwen3-14b"))
        req = urlopen.call_args[0][0]
        self.assertTrue(req.full_url.endswith("/api/generate"))
        self.assertEqual(json.loads(req.data), {"model": "ultron-qwen3-14b", "prompt": "", "keep_alive": "30m"})

    def test_false_when_ollama_is_down(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError):
            self.assertFalse(ollama.warm("x"))


class ConnectorToolCacheTest(unittest.TestCase):
    """A connector's tool list is remembered, so only a connector whose tools we hadn't seen restarts the session."""

    def run_connect(self, status_tools, known):
        import asyncio
        import tempfile
        from pathlib import Path
        from brain import brain_claudecode as bc

        class Client:
            starts = 0

            def __init__(self, options): pass
            async def connect(self): Client.starts += 1
            async def disconnect(self): pass
            async def get_mcp_status(self):
                return {"mcpServers": [{"name": "claude.ai Gmail", "status": "connected", "tools": status_tools}]}

        b = ClaudeCodeBrain()
        b.provider, b.local_model = "ollama", "ultron-qwen3-14b"
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bc, "DISCOVERED_FILE", Path(tmp) / "tools.json"), \
                mock.patch.object(bc, "_discovered", known), \
                mock.patch.object(bc, "ClaudeSDKClient", Client), \
                mock.patch.object(ClaudeCodeBrain, "_wait_for_connectors", mock.AsyncMock()):
            asyncio.run(b._connect())
            saved = bc._load_discovered()
        return Client.starts, saved

    def test_first_time_restarts_once_and_is_saved(self):
        starts, saved = self.run_connect(["search_threads", "create_draft"], {})
        self.assertEqual(starts, 2)
        self.assertEqual(sorted(saved["claude.ai Gmail"]), ["mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Gmail__search_threads"])

    def test_known_tools_do_not_restart(self):
        known = {"claude.ai Gmail": ["mcp__claude_ai_Gmail__search_threads"]}
        starts, _ = self.run_connect(["search_threads"], known)
        self.assertEqual(starts, 1)

    def test_a_connector_that_gained_tools_restarts(self):
        known = {"claude.ai Gmail": ["mcp__claude_ai_Gmail__search_threads"]}
        starts, saved = self.run_connect(["search_threads", "new_tool"], known)
        self.assertEqual(starts, 2)
        self.assertIn("mcp__claude_ai_Gmail__new_tool", saved["claude.ai Gmail"])

    def test_a_shorter_status_does_not_shrink_the_cache_or_restart(self):
        known = {"claude.ai Gmail": ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__create_draft"]}
        starts, saved = self.run_connect(["search_threads"], known)  # the status leaves out a tool we hid
        self.assertEqual(starts, 1)
        self.assertIn("mcp__claude_ai_Gmail__create_draft", known["claude.ai Gmail"])

    def test_a_broken_cache_file_is_ignored(self):
        import tempfile
        from pathlib import Path
        from brain import brain_claudecode as bc
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.json"
            f.write_text("{nope", encoding="utf-8")
            with mock.patch.object(bc, "DISCOVERED_FILE", f):
                self.assertEqual(bc._load_discovered(), {})


if __name__ == "__main__":
    unittest.main()
