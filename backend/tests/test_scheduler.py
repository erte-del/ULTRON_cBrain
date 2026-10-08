"""Scheduled jobs: when they're due, read-only runs, notifications, the usage guard.
Nothing is sent and Claude isn't called.
    .venv/bin/python -m unittest tests.test_scheduler
"""

import asyncio
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import config
import notify
import scheduler
import usage
from storage import job_store
from tools import jobs, registry

MON_8 = datetime(2026, 9, 28, 8, 0)  # a Monday


def job(**fields):
    base = {"id": "job_1", "title": "T", "prompt": "p", "at": "", "days": [], "every_min": 0, "once": False,
            "enabled": True, "created": MON_8.timestamp() - 86400, "last_run": 0.0, "last_text": ""}
    return {**base, **fields}


class DueTest(unittest.TestCase):
    def test_time_of_day(self):
        briefing = job(at="08:00", days=["mon", "tue", "wed", "thu", "fri"])
        self.assertFalse(scheduler.due(briefing, MON_8.replace(hour=7, minute=59)))
        self.assertTrue(scheduler.due(briefing, MON_8))
        self.assertTrue(scheduler.due(briefing, MON_8.replace(hour=10)))  # the Mac was asleep at 8
        self.assertFalse(scheduler.due(briefing, MON_8.replace(hour=12)))  # too late to be useful
        self.assertFalse(scheduler.due({**briefing, "last_run": MON_8.timestamp() + 5}, MON_8.replace(minute=1)))
        self.assertFalse(scheduler.due(briefing, MON_8.replace(day=27)))  # Sunday
        self.assertFalse(scheduler.due({**briefing, "enabled": False}, MON_8))
        # made at 08:01 for 08:00: waits for tomorrow
        self.assertFalse(scheduler.due({**briefing, "created": MON_8.timestamp() + 60}, MON_8.replace(minute=2)))

    def test_late_evening_job_is_caught_up_after_midnight(self):
        wrap_up = job(at="23:30", days=["sun"])
        self.assertTrue(scheduler.due(wrap_up, MON_8.replace(hour=0, minute=30)))

    def test_watchers_wait_their_interval_and_sleep_in_quiet_hours(self):
        watcher = job(every_min=30, last_run=MON_8.timestamp())
        with mock.patch.object(config, "QUIET_HOURS", "23:00-07:00"):
            self.assertFalse(scheduler.due(watcher, MON_8.replace(minute=29)))
            self.assertTrue(scheduler.due(watcher, MON_8.replace(minute=30)))
            self.assertFalse(scheduler.due(watcher, MON_8.replace(day=29, hour=2)))
            self.assertTrue(scheduler.quiet(MON_8.replace(hour=23, minute=30)))
            self.assertFalse(scheduler.quiet(MON_8.replace(hour=7)))
            # a job set for a time of day runs anyway: you chose the time
            self.assertTrue(scheduler.due(job(at="06:30"), MON_8.replace(hour=6, minute=30)))


class JobsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pushed: list[tuple[str, str]] = []

        async def push(title, text):
            self.pushed.append((title, text))

        for target, name, value in [(job_store, "JOBS_FILE", Path(tempfile.mkdtemp()) / "jobs.json"),
                                    (notify, "push", push), (usage, "windows", {}),
                                    (config, "OLLAMA_MODEL", "")]:
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def answer(self, text):
        async def ask(job):
            return text
        return mock.patch.object(scheduler, "_ask", ask)

    async def test_scheduling_asks_first_and_listing_doesnt(self):
        self.assertEqual(registry.classify("mcp__ultron__schedule_job"), "act")
        self.assertEqual(registry.classify("mcp__ultron__change_job"), "act")
        self.assertEqual(registry.classify("mcp__ultron__list_jobs"), "read")
        result = await jobs.schedule_job.handler({"title": "Morning briefing", "prompt": "Calendar, tasks.", "at": "08:00", "days": ["mon"]})
        self.assertIn("job_1: 08:00 mon", result["content"][0]["text"])
        _, _, details = registry.describe_call("mcp__ultron__change_job", {"job_id": "job_1", "action": "delete"})
        self.assertIn(["job", "Morning briefing (08:00 mon)"], details)
        self.assertIn("Morning briefing", (await jobs.list_jobs.handler({}))["content"][0]["text"])
        await jobs.change_job.handler({"job_id": "job_1", "action": "pause"})
        self.assertFalse(job_store.get("job_1")["enabled"])
        await jobs.change_job.handler({"job_id": "job_1", "action": "delete"})
        self.assertEqual(job_store.jobs(), [])

    async def test_bad_jobs_are_refused(self):
        for args in [{"title": "x", "prompt": "p"}, {"title": "x", "prompt": "p", "at": "8am"},
                     {"title": "x", "prompt": "p", "at": "08:00", "every_minutes": 30},
                     {"title": "x", "prompt": "p", "every_minutes": 5}, {"title": "", "prompt": "p", "at": "08:00"},
                     {"title": "x", "prompt": "p", "at": "08:00", "days": ["someday"]}]:
            self.assertTrue((await jobs.schedule_job.handler(args)).get("is_error"), args)
        for _ in range(job_store.MAX_JOBS):
            job_store.add("x", "p", at="08:00")
        with self.assertRaises(ValueError):
            job_store.add("one too many", "p", at="08:00")

    async def test_jobs_can_only_look_things_up(self):
        allow = await scheduler._read_only("mcp__claude_ai_Gmail__search_threads", {}, None)
        deny = await scheduler._read_only("mcp__claude_ai_Gmail__send_message", {}, None)
        self.assertEqual((allow.behavior, deny.behavior), ("allow", "deny"))
        self.assertEqual((await scheduler._read_only("mcp__ultron__schedule_job", {}, None)).behavior, "deny")

    async def test_a_job_may_use_the_tools_on_its_allow_list_and_no_others(self):
        create = "mcp__claude_ai_TickTick__create_task"
        gate = scheduler._gate({"allow": [create]})
        self.assertEqual((await gate(create, {}, None)).behavior, "allow")
        self.assertEqual((await gate("mcp__claude_ai_TickTick__delete_task", {}, None)).behavior, "deny")
        self.assertEqual((await scheduler._gate(job_store.add("T", "p", at="08:00"))(create, {}, None)).behavior, "deny")

    async def test_a_run_notifies_and_is_logged(self):
        made = job_store.add("Morning briefing", "Calendar, tasks.", at="08:00")
        with self.answer("Two meetings today."):
            await scheduler.run_job(made["id"])
        self.assertEqual(self.pushed, [("Morning briefing", "Two meetings today.")])
        self.assertEqual(job_store.runs()[0]["status"], "told")
        self.assertGreater(job_store.get(made["id"])["last_run"], time.time() - 5)

    async def test_a_daily_job_can_stay_silent(self):
        made = job_store.add("Homework", "Any homework due?", at="16:00")
        self.assertIn("reply with exactly NOTHING", scheduler.job_prompt(made))
        with self.answer("NOTHING"):
            await scheduler.run_job(made["id"])
        self.assertEqual((self.pushed, job_store.runs()[0]["status"]), ([], "nothing"))

    async def test_a_watcher_stays_silent_until_there_is_news_then_stops(self):
        made = job_store.add("Sarah's reply", "Has Sarah replied?", every_min=30, once=True)
        self.assertIn("reply with exactly NOTHING", scheduler.job_prompt(made))
        with self.answer("NOTHING"):
            await scheduler.run_job(made["id"])
        self.assertEqual((self.pushed, job_store.runs()[0]["status"]), ([], "nothing"))
        self.assertTrue(job_store.get(made["id"])["enabled"])
        with self.answer("Sarah replied: yes to Friday."):
            await scheduler.run_job(made["id"])
        self.assertEqual(len(self.pushed), 1)
        self.assertFalse(job_store.get(made["id"])["enabled"])
        self.assertIn("don't repeat it: Sarah replied", scheduler.job_prompt(job_store.get(made["id"])))

    async def test_jobs_stop_when_the_pro_limit_is_nearly_used(self):
        made = job_store.add("Briefing", "p", at="08:00")
        usage.windows["five_hour"] = {"used": 0.85, "resets_at": time.time() + 3600, "reported_at": time.time()}
        ask = mock.AsyncMock()
        with mock.patch.object(scheduler, "_ask", ask):
            await scheduler.run_job(made["id"])
        ask.assert_not_called()
        self.assertEqual(job_store.runs()[0]["status"], "skipped")

    async def test_a_failed_run_is_logged_not_raised(self):
        made = job_store.add("Briefing", "p", at="08:00")
        with mock.patch.object(scheduler, "_ask", mock.AsyncMock(side_effect=RuntimeError("overloaded"))):
            await scheduler.run_job(made["id"])
        self.assertEqual((job_store.runs()[0]["status"], job_store.runs()[0]["text"]), ("failed", "overloaded"))
        self.assertEqual(self.pushed, [])


class LocalModelTest(unittest.IsolatedAsyncioTestCase):
    """Jobs on the local model (Ollama), and falling back to Claude."""
    def setUp(self):
        JobsTest.setUp(self)  # same temp job file and caught notifications
        for target, name, value in [(config, "OLLAMA_MODEL", "qwen3:8b"), (scheduler, "ollama_up", lambda: True)]:
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.calls: list[bool] = []

    def models(self, local_reply):
        """_ask that answers 'claude' on Claude and local_reply (or raises it) locally."""
        async def ask(job, local=False):
            self.calls.append(local)
            if not local:
                return "claude"
            if isinstance(local_reply, Exception):
                raise local_reply
            return local_reply
        return mock.patch.object(scheduler, "_ask", ask)

    async def test_jobs_run_locally_and_say_so(self):
        made = job_store.add("Briefing", "p", at="08:00")
        with self.models("Two meetings."):
            await scheduler.run_job(made["id"])
        self.assertEqual((self.calls, self.pushed), ([True], [("Briefing", "Two meetings.\n\n(qwen3:8b)")]))
        self.assertEqual(job_store.get(made["id"])["last_text"], "Two meetings.")  # no footer

    async def test_jobs_that_change_things_or_ask_for_claude_stay_on_claude(self):
        self.assertFalse(scheduler.runs_local({"allow": ["mcp__claude_ai_TickTick__create_task"]}))
        self.assertFalse(scheduler.runs_local({"brain": "claude"}))
        self.assertTrue(scheduler.runs_local({}))
        with mock.patch.object(config, "OLLAMA_MODEL", ""):
            self.assertFalse(scheduler.runs_local({}))

    async def test_a_failing_local_model_is_retried_then_claude_does_it(self):
        made = job_store.add("Briefing", "p", at="08:00")
        with self.models(RuntimeError("model crashed")):
            await scheduler.run_job(made["id"])
        self.assertEqual(self.calls, [True, True, False])
        self.assertIn("claude\n\n(The local model failed: model crashed.", self.pushed[0][1])

    async def test_ollama_down_goes_straight_to_claude(self):
        made = job_store.add("Briefing", "p", at="08:00")
        with self.models("unused"), mock.patch.object(scheduler, "ollama_up", lambda: False):
            await scheduler.run_job(made["id"])
        self.assertEqual(self.calls, [False])
        self.assertIn("wasn't running", self.pushed[0][1])

    async def test_local_jobs_ignore_the_pro_limit_but_a_fallback_never_vanishes(self):
        usage.windows["five_hour"] = {"used": 0.95, "resets_at": time.time() + 3600, "reported_at": time.time()}
        made = job_store.add("Briefing", "p", at="08:00")
        with self.models("Two meetings."):
            await scheduler.run_job(made["id"])
        self.assertEqual(job_store.runs()[0]["status"], "told")
        with self.models(RuntimeError("down")):
            await scheduler.run_job(made["id"])
        self.assertEqual(job_store.runs()[0]["status"], "skipped")
        self.assertIn("Skipped", self.pushed[-1][1])


class NotifyTest(unittest.IsolatedAsyncioTestCase):
    async def test_mac_phone_and_the_next_message(self):
        mac, text = mock.AsyncMock(), mock.MagicMock()
        with mock.patch.object(notify, "_mac", mac), mock.patch.object(notify.telegram, "send_text", text), \
                mock.patch.object(notify.telegram, "configured", lambda: True):
            await notify.push("Briefing", "Two meetings.")
        mac.assert_awaited_once_with("Briefing", "Two meetings.")
        text.assert_called_once_with("Briefing\n\nTwo meetings.")
        self.assertEqual(notify.take_unseen(), ["Briefing: Two meetings."])
        self.assertEqual(notify.take_unseen(), [])


if __name__ == "__main__":
    unittest.main()
