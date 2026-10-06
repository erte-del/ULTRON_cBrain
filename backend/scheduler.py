"""Runs scheduled jobs (storage/job_store.py): Ultron acting on its own.

A loop checks every half minute which jobs are due. Each run is its own short
conversation, separate from yours, and tells you the result through notify.py.

Jobs run on the local model (JARVIS_OLLAMA_MODEL) when one is set, except jobs that
change things ("allow" list) or say "brain": "claude". If the local model is down or
fails twice, the job runs on Claude instead, and the notification says so.

Safe defaults:
  - a job can only use 'read' tools: anything that sends, creates, changes or deletes is
    refused, and the job tells you what it would suggest instead. The one way round it is
    a job's "allow" list of tool names in jobs.json, written by hand: Ultron can't set it
  - one job at a time, and none once JARVIS_JOBS_MAX_USAGE of the Pro 5-hour limit is used
  - watchers don't run during JARVIS_QUIET_HOURS
  - a job that was due while the Mac slept still runs if it's under CATCH_UP late, once
"""

import asyncio
import logging
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

import config
import events
import hub
import notify
import usage
from brain.base import Error, TextDelta, ToolStart
from brain.brain_claudecode import ClaudeCodeBrain
from storage import job_store
from tools import registry

log = logging.getLogger("ultron.scheduler")

CHECK_EVERY_S = 30
CATCH_UP = timedelta(hours=3)
JOB_TIMEOUT_S = 300
NOTHING = "NOTHING"  # a job's reply when there's nothing to tell you

# (provider, gateway model) of the brain in use, set by main.py: jobs run on the same
# one, so your emails never go to a provider you didn't pick.
current_brain: Callable[[], tuple[str, str]] = lambda: (config.PROVIDER, config.GATEWAY_MODEL)

_lock = asyncio.Lock()  # one job at a time
_tasks: set[asyncio.Task] = set()


def quiet(now: datetime) -> bool:
    """Inside JARVIS_QUIET_HOURS? (They may run over midnight: 23:00-07:00.)"""
    if not config.QUIET_HOURS:
        return False
    start, end = config.QUIET_HOURS.split("-")
    t = now.strftime("%H:%M")
    return start <= t < end if start <= end else t >= start or t < end


def due(job: dict, now: datetime) -> bool:
    if not job["enabled"]:
        return False
    last = job["last_run"] or job["created"]
    if job["every_min"]:
        return now.timestamp() - last >= job["every_min"] * 60 and not quiet(now)
    hour, minute = map(int, job["at"].split(":"))
    moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment > now:
        moment -= timedelta(days=1)  # today's time hasn't come: was yesterday's missed?
    if job["days"] and job_store.DAYS[moment.weekday()] not in job["days"]:
        return False
    return last < moment.timestamp() and now - moment <= CATCH_UP


def _gate(job: dict):
    """What this job may use: 'read' tools, plus the tools on its own "allow" list."""
    async def check(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        if registry.classify(tool_name) == "read" or tool_name in job.get("allow", ()):
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="Scheduled jobs can only look things up. Tell the user what you'd suggest instead."
        )
    return check


_read_only = _gate({})


def job_prompt(job: dict) -> str:
    now = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z (UTC%z)")
    lines = [
        f"[Now: {now}]",
        f'[This is your scheduled job "{job["title"]}", running on its own: the user isn\'t here. '
        "You can only look things up; anything that sends, creates, changes or deletes is refused, "
        "so say what you'd suggest instead. Your final reply is sent to the user's phone as a "
        "notification: plain text, no markdown, short, nothing that needs an answer right now.]",
    ]
    if job.get("allow"):
        lines.append(f"[The one exception, approved by the user for this job: {', '.join(job['allow'])}.]")
    # Any job may stay silent ("text me only if there's homework"), not just watchers.
    lines.append(f"[If there's nothing to tell the user, reply with exactly {NOTHING}.]")
    if job["every_min"]:
        if job["last_text"]:
            lines.append(f"[You already told them this, don't repeat it: {job['last_text']}]")
    return "\n".join([*lines, job["prompt"]])


def runs_local(job: dict) -> bool:
    return bool(config.OLLAMA_MODEL) and not job.get("allow") and job.get("brain") != "claude"


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(config.OLLAMA_URL + "/api/version", timeout=3):
            return True
    except OSError:
        return False


async def _ask(job: dict, local: bool = False) -> str:
    """Run the job's prompt in a fresh conversation; the reply text. RuntimeError if it failed."""
    provider, gateway_model = ("ollama", config.OLLAMA_MODEL) if local else current_brain()
    # Watchers run often, so they get the cheapest model.
    model = ("haiku" if job["every_min"] else "sonnet") if provider == "claude" else gateway_model
    brain = ClaudeCodeBrain(can_use_tool=_gate(job))
    brain.provider = provider
    text = ""
    try:
        async with asyncio.timeout(JOB_TIMEOUT_S):
            async for ev in brain.send(job_prompt(job), model=model):
                match ev:
                    case TextDelta():
                        text += ev.text
                    case ToolStart():
                        text = ""  # only what comes after the last tool is the answer
                    case Error():
                        raise RuntimeError(ev.message)
    except TimeoutError:
        raise RuntimeError(f"no answer within {JOB_TIMEOUT_S // 60} minutes") from None
    finally:
        await brain.close()
    if local and not text.strip():  # small models sometimes stop without a word: not "nothing to say"
        raise RuntimeError("it gave no answer")
    return text.strip()


async def run_job(job_id: str) -> None:
    """Run one job now and tell the user the result. Never raises."""
    async with _lock:
        try:
            job = job_store.change(job_id, last_run=time.time())  # first: a crash mustn't rerun it forever
        except KeyError:
            return
        try:
            log.info("Running job %s (%s)", job["id"], job["title"])
            text, footer = None, ""
            if runs_local(job):
                footer = "(The local model wasn't running, so Claude did this.)"
                if await asyncio.to_thread(ollama_up):
                    for attempt in (1, 2):
                        try:
                            text = await _ask(job, local=True)
                            footer = f"({config.OLLAMA_MODEL})"
                            break
                        except RuntimeError as e:
                            log.warning("Job %s failed on the local model (try %d): %s", job_id, attempt, e)
                            footer = f"(The local model failed: {str(e)[:100]}. Claude did this instead.)"
            if text is None:
                five = usage.snapshot("claude", 0)["windows"].get("five_hour")
                if current_brain()[0] == "claude" and five and five["used"] >= config.JOBS_MAX_USAGE:
                    reason = f"{round(five['used'] * 100)}% of the 5-hour limit is used"
                    job_store.log_run(job, "skipped", reason)
                    if footer:  # it should have run locally: don't let it vanish silently
                        await notify.push(job["title"], f"Skipped: the local model failed and {reason}.")
                    return
                text = await _ask(job)
            if not text or text.upper().startswith(NOTHING):
                job_store.log_run(job, "nothing")
                return
            job_store.log_run(job, "told", text)
            job_store.change(job_id, last_text=text[:500], **({"enabled": False} if job["once"] else {}))
            await notify.push(job["title"], f"{text}\n\n{footer}" if footer else text)
        except KeyError:
            pass  # deleted while it ran
        except Exception as e:
            log.exception("Job %s failed", job_id)
            job_store.log_run(job, "failed", str(e)[:300])
        finally:
            await hub.emit(events.jobs_list(job_store.jobs(), job_store.runs()))


def run_soon(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def loop() -> None:
    """Started with the server; runs until it's cancelled at shutdown."""
    while True:
        try:
            now = datetime.now()
            for job in job_store.jobs():
                if due(job, now):
                    await run_job(job["id"])
        except Exception:
            log.exception("Scheduler check failed")
        await asyncio.sleep(CHECK_EVERY_S)
