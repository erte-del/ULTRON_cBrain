"""schedule_job / list_jobs / change_job: things Ultron does on its own, later.

The jobs live in storage/job_store.py and are run by scheduler.py. Scheduling, pausing
and deleting are 'act' (a scheduled job can't schedule more jobs);
listing only reads.
"""

import json
from datetime import datetime
from typing import Any

from claude_agent_sdk import tool

import events
import hub
from storage import job_store


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


async def _changed() -> None:
    """Keep the schedule panel in every open tab up to date."""
    await hub.emit(events.jobs_list(job_store.jobs(), job_store.runs()))


@tool(
    "schedule_job",
    "Schedule something for you to do later on your own, and tell the user the result as a "
    "notification (on this Mac and their phone). Two kinds. A time of day: at='08:00', with "
    "days (none = every day), e.g. a morning briefing. Or a watcher: every_minutes=30, which "
    "checks something and only notifies when there is something to tell ('tell me when Sarah "
    "replies'); set once=true if it should stop after it has told them. The job runs in a "
    "fresh conversation that can't see this one and can only look things up, so write the "
    "prompt as complete instructions to yourself: what to check, with which tools, what to "
    "report, names and details included. Each watcher "
    f"run uses their Pro limit: keep every_minutes as large as the task allows (minimum {job_store.MIN_EVERY_MIN}).",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short name, shown as the notification's title."},
            "prompt": {"type": "string", "description": "Complete instructions for the job."},
            "at": {"type": "string", "description": "Time of day, 24-hour HH:MM, user's local time."},
            "days": {"type": "array", "items": {"type": "string", "enum": list(job_store.DAYS)},
                     "description": "With at: which days. Leave out for every day."},
            "every_minutes": {"type": "integer", "description": "Watcher: check this often."},
            "once": {"type": "boolean", "description": "Watcher: stop after the first notification."},
            "when_active": {"type": "boolean", "description": "With at: wait until the user is at the computer "
                            "(typing or moving the mouse) instead of firing on the clock; up to 6 hours. For a morning briefing."},
        },
        "required": ["title", "prompt"],
    },
)
async def schedule_job(args: dict[str, Any]) -> dict[str, Any]:
    try:
        job = job_store.add(
            args.get("title") or "", args.get("prompt") or "", str(args.get("at") or ""),
            args.get("days") or [], int(args.get("every_minutes") or 0), bool(args.get("once")), bool(args.get("when_active")),
        )
    except (ValueError, TypeError) as e:
        return _text(str(e), True)
    await _changed()
    return _text(f"Scheduled as {job['id']}: {job_store.when(job)}.")


@tool(
    "list_jobs",
    "List the scheduled jobs (what, when, paused or not) and their most recent runs with "
    "what they told the user (read-only).",
    {"type": "object", "properties": {}},
)
async def list_jobs(args: dict[str, Any]) -> dict[str, Any]:
    stamp = lambda t: datetime.fromtimestamp(t).strftime("%a %d %b %H:%M")
    jobs = [{"id": j["id"], "title": j["title"], "when": job_store.when(j), "paused": not j["enabled"],
             "prompt": j["prompt"]} for j in job_store.jobs()]
    runs = [{"job": r["title"], "time": stamp(r["time"]), "status": r["status"], "text": r["text"]}
            for r in job_store.runs()[:10]]
    if not jobs and not runs:
        return _text("Nothing is scheduled, and nothing has run.")
    return _text(json.dumps({"jobs": jobs, "recent_runs": runs}, ensure_ascii=False))


@tool(
    "change_job",
    "Pause, resume or delete a scheduled job by its id (job_2). Find the id with list_jobs "
    "first. To change what a job does or when, delete it "
    "and schedule a new one.",
    {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "e.g. job_2"},
            "action": {"type": "string", "enum": ["pause", "resume", "delete"]},
        },
        "required": ["job_id", "action"],
    },
)
async def change_job(args: dict[str, Any]) -> dict[str, Any]:
    job_id, action = str(args.get("job_id") or ""), args.get("action")
    try:
        if action == "delete":
            job = job_store.delete(job_id)
        elif action in ("pause", "resume"):
            job = job_store.change(job_id, enabled=action == "resume")
        else:
            return _text("action must be pause, resume or delete.", True)
    except KeyError:
        return _text(f"There's no job {job_id!r}.", True)
    await _changed()
    return _text(f"{job['title']}: {action}d.")
