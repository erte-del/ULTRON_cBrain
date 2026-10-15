import importlib.util
import unittest
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
        known = {t.tool.name for t in registry.TOOLS}
        for c in bench.CASES:
            self.assertLessEqual(set(c.expect), known, c.name)


if __name__ == "__main__":
    unittest.main()
