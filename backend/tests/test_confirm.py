"""Confirmation gate tests. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import unittest

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

import hub
from brain import confirm
from brain.confirm import ConfirmationGate

TOOL = "mcp__claude_ai_Gmail__send_email"
INPUT = {"to": "a@b.com", "subject": "Hi"}


class GateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gate = ConfirmationGate()
        self.sent: list[dict] = []

        async def tab(event):  # a pretend browser tab
            self.sent.append(event)

        self.tab = tab
        hub.connect(tab)

    async def asyncTearDown(self):
        hub.disconnect(self.tab)

    async def ask(self, tool_use_id="t1"):
        return asyncio.create_task(
            self.gate.can_use_tool(TOOL, INPUT, ToolPermissionContext(tool_use_id=tool_use_id))
        )

    async def wait_for_request(self):
        for _ in range(100):
            if any(e["type"] == "confirm.request" for e in self.sent):
                return
            await asyncio.sleep(0.01)
        self.fail("no confirm.request sent")

    async def test_approve(self):
        task = await self.ask()
        await self.wait_for_request()
        request = self.sent[0]
        self.assertEqual(request["title"], "Gmail: Send email")
        self.assertIn(["to", "a@b.com"], request["details"])
        self.assertTrue(self.gate.resolve("t1", True))
        self.assertIsInstance(await task, PermissionResultAllow)
        self.assertEqual(self.sent[-1], {"type": "confirm.resolved", "id": "t1", "status": "approved"})

    async def test_deny(self):
        task = await self.ask()
        await self.wait_for_request()
        self.gate.resolve("t1", False)
        result = await task
        self.assertIsInstance(result, PermissionResultDeny)
        self.assertIn("declined", result.message)

    async def test_no_answer_expires(self):
        old = confirm.CONFIRM_TIMEOUT_S
        confirm.CONFIRM_TIMEOUT_S = 0.05
        try:
            result = await (await self.ask())
        finally:
            confirm.CONFIRM_TIMEOUT_S = old
        self.assertIsInstance(result, PermissionResultDeny)
        self.assertEqual(self.sent[-1]["status"], "expired")

    async def test_no_browser_denies(self):
        hub.disconnect(self.tab)
        result = await (await self.ask())
        self.assertIsInstance(result, PermissionResultDeny)
        self.assertEqual(self.sent, [])

    async def test_late_tab_sees_pending_and_unknown_id_is_rejected(self):
        task = await self.ask()
        await self.wait_for_request()
        self.assertEqual([r["id"] for r in self.gate.pending_requests()], ["t1"])
        self.assertFalse(self.gate.resolve("nope", True))
        self.gate.resolve("t1", True)
        await task
        self.assertEqual(self.gate.pending_requests(), [])
        self.assertFalse(self.gate.resolve("t1", True))  # already answered

    async def test_stopped_reply_ends_its_card_and_tells_the_next_message(self):
        confirm.take_outcomes()
        task = await self.ask()
        await self.wait_for_request()
        self.gate.stop_waiting()  # you talked over the reply ("yeah go ahead and post it now")
        self.assertIsInstance(await task, PermissionResultDeny)
        self.assertEqual(self.sent[-1]["status"], "stopped")
        self.assertEqual(self.gate.pending_requests(), [])  # a later "yes" can't answer it
        told = confirm.take_outcomes()
        self.assertEqual(len(told), 1)
        self.assertIn("did not happen", told[0])
        self.assertEqual(confirm.take_outcomes(), [])  # told once


if __name__ == "__main__":
    unittest.main()
