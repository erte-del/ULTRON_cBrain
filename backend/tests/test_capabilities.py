"""What the local model gets, and when. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import unittest
from unittest import mock

import config
from brain import capabilities as cap
from brain.brain_claudecode import ClaudeCodeBrain
from tools import registry


class MatchTest(unittest.TestCase):
    def test_small_talk_switches_nothing_on(self):
        self.assertEqual(cap.match("hi, who are you?"), set())

    def test_words_switch_groups_on(self):
        self.assertIn("gmail", cap.match("Any unread email from Sarah?"))
        self.assertIn("vercel", cap.match("did my last deployment fail"))
        self.assertTrue({"calendar", "tasks"} <= cap.match("Morning briefing"))

    def test_canvas_only_when_something_needs_it(self):
        self.assertNotIn("show_on_canvas", cap.visible_tools(cap.match("Order me a pizza from the corner shop")))
        self.assertNotIn("show_on_canvas", cap.visible_tools(cap.match("hi")))
        self.assertIn("show_on_canvas", cap.visible_tools(cap.match("Put a table on the canvas")))
        self.assertIn("show_on_canvas", cap.visible_tools(cap.match("What's on my calendar?")))
        self.assertNotIn("About the canvas", cap.system_prompt(set()))

    def test_every_group_names_real_tools_and_prompt_paragraphs(self):
        real = {t.tool.name for t in registry.TOOLS}
        for g in cap.GROUPS:
            self.assertFalse(set(g.tools) - real, g.name)
            for start in g.prompt:
                self.assertTrue(any(p.startswith(start) for p in cap._PARAGRAPHS), f"{g.name}: {start}")
        self.assertFalse(set(cap.CORE_TOOLS) - real)


class ToolsTest(unittest.TestCase):
    def test_the_base_is_small_and_has_no_connectors_or_expert(self):
        seen = cap.visible_tools(set())
        self.assertNotIn("ask_expert", seen)
        self.assertNotIn("mac_change", seen)
        self.assertIn("recall", seen)
        self.assertLess(len(seen), 15)
        self.assertEqual(cap.connectors_for(set()), set())
        self.assertLess(len(cap.system_prompt(set())), 12_000)  # ~3k tokens, not 33k chars

    def test_a_group_adds_its_tools_prompt_and_connector(self):
        self.assertIn("mac_read", cap.visible_tools({"mac"}))
        self.assertIn("About this Mac", cap.system_prompt({"mac"}))
        with mock.patch.object(config, "OLLAMA_CONNECTORS", ["gmail"]):
            self.assertEqual(cap.connectors_for({"gmail", "calendar"}), {"gmail"})  # calendar isn't allowed

    def test_a_job_can_only_look_unless_its_allow_list_says_otherwise(self):
        self.assertNotIn("remember", cap.visible_tools(set(), background=True))
        self.assertIn("remember", cap.visible_tools(set(), background=True, allow=(registry.PREFIX + "remember",)))

    def test_connector_tools_are_trimmed(self):
        vis = cap.tool_visible
        self.assertTrue(vis("mcp__claude_ai_Vercel__list_deployments", False, ()))
        self.assertFalse(vis("mcp__claude_ai_Vercel__create_project", False, ()))
        self.assertFalse(vis("mcp__claude_ai_Vercel__add_route", True, ()))
        self.assertFalse(vis("mcp__claude_ai_Shopify__update-product", False, ()))
        self.assertTrue(vis("mcp__claude_ai_Gmail__search_threads", True, ()))
        self.assertFalse(vis("mcp__claude_ai_Gmail__create_draft", True, ()))  # a job only looks
        self.assertTrue(vis("mcp__claude_ai_Gmail__create_draft", False, ()))  # in chat the gate decides
        self.assertTrue(vis("mcp__claude_ai_Gmail__create_draft", True, ("mcp__claude_ai_Gmail__create_draft",)))
        self.assertFalse(vis("mcp__claude_ai_Supabase__delete_branch", False, ()))
        self.assertEqual(cap.groups_for_tools(("mcp__claude_ai_TickTick__create_task",)), {"tasks", "school"})


class BrainTest(unittest.TestCase):
    def brain(self) -> ClaudeCodeBrain:
        b = ClaudeCodeBrain()
        b.provider, b.local_model = "ollama", "ultron-qwen3-14b"
        return b

    def test_options_follow_the_groups(self):
        b = self.brain()
        base = b._options()
        self.assertNotIn("About the calendar", base.system_prompt)
        b.groups = {"calendar"}
        self.assertIn("About the calendar", b._options().system_prompt)
        self.assertLess(len(base.system_prompt), len(b._options().system_prompt))


if __name__ == "__main__":
    unittest.main()
