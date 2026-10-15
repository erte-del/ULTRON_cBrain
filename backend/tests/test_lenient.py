import asyncio
import unittest

from claude_agent_sdk import SdkMcpTool

from tools import lenient

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "days": {"type": "array", "items": {"type": "string", "enum": ["mon", "tue"]}},
        "folder": {"type": "string", "enum": ["all", "Desktop"]},
    },
    "required": ["title"],
}


class LenientTests(unittest.TestCase):
    def test_clean_fixes_case_and_drops_empty_optionals(self):
        out = lenient.clean({"title": "", "days": ["Mon", "TUE"], "folder": ""}, SCHEMA)
        self.assertEqual(out, {"title": "", "days": ["mon", "tue"]})  # required fields stay
        self.assertEqual(lenient.clean({"title": "x", "folder": "desktop"}, SCHEMA)["folder"], "Desktop")

    def test_relaxed_tool_accepts_slips_and_keeps_original_untouched(self):
        seen = []

        async def handler(args):
            seen.append(args)
            return {"content": []}

        tool = SdkMcpTool("t", "does a thing", SCHEMA, handler)
        loose = lenient.relax(tool)
        self.assertNotIn("enum", loose.input_schema["properties"]["folder"])
        self.assertNotIn("enum", loose.input_schema["properties"]["days"]["items"])
        self.assertIn("mon, tue", loose.input_schema["properties"]["days"]["description"])
        self.assertIn("enum", SCHEMA["properties"]["folder"])  # the original schema is unchanged
        asyncio.run(loose.handler({"title": "a", "days": ["Mon"], "folder": ""}))
        self.assertEqual(seen, [{"title": "a", "days": ["mon"]}])


if __name__ == "__main__":
    unittest.main()
