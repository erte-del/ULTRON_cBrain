import importlib.util
import unittest
import unittest.mock
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "scripts" / "bench_ollama_tools.py"
_spec = importlib.util.spec_from_file_location("bench_ollama_tools", _path)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


class BenchTests(unittest.TestCase):
    def case(self, name):
        return next(c for c in bench.CASES if c.name == name)

    def test_right_tool_and_args_passes(self):
        c = self.case("remember")
        s = bench.score(c, [{"name": "remember", "args": {"text": "sister is Lina"}}], {"remember": True})
        self.assertTrue(s["ok"])

    def test_extra_or_missing_tool_fails(self):
        c = self.case("jobs_list")
        self.assertFalse(bench.score(c, [], {})["ok"])
        s = bench.score(c, [{"name": "list_jobs", "args": {}}, {"name": "recall", "args": {}}],
                        {"list_jobs": True, "recall": True})
        self.assertFalse(s["ok"])
        self.assertEqual(s["extra"], ["recall"])

    def test_any_call_on_a_chat_case_fails(self):
        c = self.case("chat_hi")
        self.assertTrue(bench.score(c, [], {})["ok"])
        self.assertFalse(bench.score(c, [{"name": "recall", "args": {}}], {"recall": True})["ok"])

    def test_cases_only_use_tools_that_exist(self):
        from tools import registry
        known = {t.tool.name for t in registry.TOOLS} | {n for g in bench.CONNECTOR_TOOLS.values() for n, _, _ in g}
        for c in bench.CASES:
            self.assertLessEqual(set(c.expect), known, c.name)

    def test_connector_tools_are_offered_with_the_group_that_switches_them_on(self):
        case = next(c for c in bench.CASES if c.name == "mail_search")
        _, tools, groups = bench.build(case)
        self.assertIn("gmail", groups)
        self.assertIn(bench.GMAIL_SEARCH, {t["function"]["name"] for t in tools})
        _, tools, _ = bench.build(next(c for c in bench.CASES if c.name == "chat_hi"))
        self.assertNotIn(bench.GMAIL_SEARCH, {t["function"]["name"] for t in tools})

    def test_an_answer_that_ignores_the_tool_result_fails(self):
        c = next(c for c in bench.CASES if c.name == "recall_answer")
        calls = [{"name": "recall", "args": {"query": "Lina"}}]
        self.assertTrue(bench.score(c, calls, {"recall": True}, "Lina is your sister.")["ok"])
        self.assertFalse(bench.score(c, calls, {"recall": True}, "I don't know anyone called that.")["ok"])

    def test_a_tool_called_after_the_result_is_extra_unless_allowed(self):
        c = next(c for c in bench.CASES if c.name == "jobs_answer")
        calls = [{"name": "list_jobs", "args": {}}, {"name": "recall", "args": {}}]
        self.assertEqual(bench.score(c, calls, {"list_jobs": True, "recall": True}, "briefing")["extra"], ["recall"])

    def test_converse_feeds_the_canned_result_back_and_collects_every_call(self):
        c = next(c for c in bench.CASES if c.name == "recall_answer")
        sent = []

        def fake_ask(url, model, system, tools, messages, num_ctx):
            sent.append(list(messages))
            if len(sent) == 1:
                return {"message": {"content": "", "tool_calls": [{"function": {"name": "recall", "arguments": {"query": "Lina"}}}]}}
            return {"message": {"content": "Lina is your sister."}}

        with unittest.mock.patch.object(bench, "ask", fake_ask):
            calls, reply, _ = bench.converse("u", "m", "sys", [], c, 1000)
        self.assertEqual([x["name"] for x in calls], ["recall"])
        self.assertEqual(reply, "Lina is your sister.")
        self.assertEqual(sent[1][-1], {"role": "tool", "tool_name": "recall", "content": c.results["recall"]})

    def test_converse_stops_a_model_that_never_stops_calling_tools(self):
        c = next(c for c in bench.CASES if c.name == "recall_answer")
        looping = {"message": {"content": "", "tool_calls": [{"function": {"name": "recall", "arguments": {}}}]}}
        with unittest.mock.patch.object(bench, "ask", lambda *a: looping):
            calls, reply, _ = bench.converse("u", "m", "sys", [], c, 1000)
        self.assertEqual((len(calls), reply), (bench.MAX_ROUNDS, ""))

    def test_a_one_step_case_asks_once(self):
        c = next(c for c in bench.CASES if c.name == "remember")
        n = []
        with unittest.mock.patch.object(bench, "ask", lambda *a: n.append(1) or {"message": {"tool_calls": [{"function": {"name": "remember", "arguments": {}}}]}}):
            bench.converse("u", "m", "sys", [], c, 1000)
        self.assertEqual(len(n), 1)

    def test_every_routing_example_switches_on_the_right_groups(self):
        self.assertEqual(bench.check_routing(), [])


if __name__ == "__main__":
    unittest.main()
