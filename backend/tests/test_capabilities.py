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

    def test_everyday_words_with_other_meanings_switch_nothing_on(self):
        for text in (
            "unit tests passed, I'll leave it", "play it safe", "let's play along", "he wants to play a game", "play football later", "I got a message from Sarah", "the event handler fired", "The shell company sold products",
            "take note that I like tea", "close the windows", "Order me a pizza",
            "What's the model of growth in economics?", "Explain Python decorators",
        ):
            self.assertEqual(cap.match(text), set(), text)
        self.assertEqual(cap.match("How long does it take to drive to the airport?"), {"travel"})  # not Google Drive

    def test_clear_requests_still_switch_the_right_group_on(self):
        for text, group in (
            ("Play some jazz", "music"), ("Play Taylor Swift", "music"), ("play despacito", "music"), ("pause the music", "music"), ("Search my notes for chemistry", "notes"),
            ("my chemistry test tomorrow", "school"), ("Did my last build fail?", "vercel"),
            ("How many orders did my store get?", "shopify"), ("open the terminal", "terminal"),
            ("Send a message to Sam", "messages"), ("Draw me a cat", "images"), ("Open my Google Drive", "drive"),
            ("I'm hungry", "phone"), ("When should I leave?", "travel"), ("What's due tomorrow?", "tasks"),
            ("Message Sam that I'm late", "messages"), ("message him about lunch", "messages"),
            ("what time should I leave", "travel"), ("how long will it take to get to work", "travel"),
            ("any events today?", "calendar"), ("what's due?", "tasks"), ("anything due Friday", "tasks"),
            ("Run some python on this csv", "mac"), ("Check my PC", "pc"),
        ):
            self.assertIn(group, cap.match(text), text)

    def test_the_spoken_reply_rules_are_always_in_the_local_prompt(self):
        # agent.py marks voice messages [Spoken]; this paragraph is what tells the model what that means.
        for groups in (set(), {"mac"}, {"gmail", "calendar"}):
            self.assertIn("A message that starts with [Spoken]", cap.system_prompt(groups))

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


class ChangesSettingTest(unittest.TestCase):
    def brain(self) -> ClaudeCodeBrain:
        b = ClaudeCodeBrain()
        b.provider, b.local_model = "ollama", "ultron-qwen3-14b"
        return b

    def test_chat_may_change_things_by_default(self):
        b = self.brain()
        self.assertFalse(b.looks_only)
        self.assertIn("remember", cap.visible_tools(set(), b.looks_only))

    def test_none_makes_local_chat_look_only(self):
        with mock.patch.object(config, "OLLAMA_CHANGES", "none"):
            b = self.brain()
            self.assertTrue(b.looks_only)
            self.assertNotIn("remember", cap.visible_tools(set(), b.looks_only))
            self.assertIn("recall", cap.visible_tools(set(), b.looks_only))
            with mock.patch.object(registry, "mcp_servers", return_value={}) as servers:
                b._options()
            self.assertNotIn("remember", servers.call_args[0][0])  # the model is built without it
            self.assertFalse(cap.tool_visible("mcp__claude_ai_Gmail__create_draft", b.looks_only, ()))

    def test_none_does_not_touch_claude_or_other_brains(self):
        with mock.patch.object(config, "OLLAMA_CHANGES", "none"):
            b = ClaudeCodeBrain()
            b.provider = "claude"
            self.assertFalse(b.looks_only)

    def test_a_job_always_looks_only_unless_allowed(self):
        b = self.brain()
        b.background = True
        self.assertTrue(b.looks_only)


class GroupsPanelTest(unittest.TestCase):
    def brain(self) -> ClaudeCodeBrain:
        b = ClaudeCodeBrain()
        b.provider, b.local_model = "ollama", "ultron-qwen3-14b"
        return b

    def test_every_group_has_a_title_in_the_catalog(self):
        self.assertEqual({c["name"] for c in cap.catalog()}, {g.name for g in cap.GROUPS})
        self.assertEqual(set(cap.TITLES), {g.name for g in cap.GROUPS})

    def test_switching_by_hand_sets_the_groups_and_tells_the_pages(self):
        import asyncio
        b = self.brain()
        told = []
        b.on_groups = lambda: told.append(sorted(b.groups))
        asyncio.run(b.set_groups({"mac", "gmail", "nonsense"}))
        self.assertEqual(b.groups, {"mac", "gmail"})
        self.assertIn("mac_read", cap.visible_tools(b.groups))
        asyncio.run(b.set_groups({"mac", "gmail"}))  # no change, nothing to say
        asyncio.run(b.set_groups(set()))
        self.assertEqual(told, [["gmail", "mac"], []])

    def test_a_new_conversation_clears_the_groups_and_says_so(self):
        import asyncio
        b = self.brain()
        b.groups = {"mac"}
        told = []
        b.on_groups = lambda: told.append(sorted(b.groups))
        asyncio.run(b.new_conversation("ollama"))
        self.assertEqual((b.groups, told), (set(), [[]]))

    def test_event_shape(self):
        import events
        ev = events.groups_state(["mac"], cap.catalog())
        self.assertEqual((ev["type"], ev["on"]), ("ollama.groups", ["mac"]))


if __name__ == "__main__":
    unittest.main()
