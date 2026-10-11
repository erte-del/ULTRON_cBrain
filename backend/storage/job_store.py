"""Scheduled jobs and the log of their runs, in storage/jobs.json.

A job is a prompt Ultron runs on its own (scheduler.py), either
  - at a time of day: {"at": "08:00", "days": ["mon", ...]} (no days = every day), or
  - every so many minutes: {"every_min": 30}, a watcher. It only tells you when there's
    something to tell; with "once" it stops after the first time it does.
The run log is also the notification history: each run that told you something keeps
the text.
"""

import json
import re
import threading
import time

from config import STORAGE_DIR

JOBS_FILE = STORAGE_DIR / "jobs.json"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # datetime.weekday() order
MAX_JOBS = 10
# Every watcher run is a fresh Claude conversation (~30K tokens), so not too often.
MIN_EVERY_MIN = 15
MAX_RUNS = 100  # older runs are dropped
MAX_PROMPT_CHARS = 2000

_lock = threading.Lock()


def _read() -> dict:
    try:
        data = json.loads(JOBS_FILE.read_text())
        return {"jobs": data["jobs"], "runs": data["runs"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {"jobs": [], "runs": []}


def _write(data: dict) -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_FILE.with_suffix(".tmp")  # a crash mid-write mustn't lose the jobs
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(JOBS_FILE)


def jobs() -> list[dict]:
    return _read()["jobs"]


def runs() -> list[dict]:
    """Newest first."""
    return _read()["runs"][::-1]


def get(job_id: str) -> dict:
    """KeyError if there's no such job."""
    job = next((j for j in jobs() if j["id"] == job_id), None)
    if job is None:
        raise KeyError(job_id)
    return job


def label(job_id: str) -> str | None:
    """'Morning briefing (08:00 mon, tue)', for the confirmation card of change_job."""
    try:
        job = get(job_id)
    except KeyError:
        return None
    return f"{job['title']} ({when(job)})"


def when(job: dict) -> str:
    """'every 30 min' or '08:00 mon, tue' or '08:00 every day'."""
    if job["every_min"]:
        return f"every {job['every_min']} min" + (", until it finds something" if job["once"] else "")
    return f"{job['at']} {', '.join(job['days']) or 'every day'}" + (", once I'm at the computer" if job.get("when_active") else "")


def add(title: str, prompt: str, at: str = "", days: list[str] | None = None,
        every_min: int = 0, once: bool = False, when_active: bool = False) -> dict:
    """ValueError with the reason if the job can't be scheduled like that."""
    title, prompt = " ".join(str(title).split())[:80], str(prompt).strip()
    days = [str(d).lower()[:3] for d in days or []]
    if not title or not prompt:
        raise ValueError("A job needs a title and a prompt.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"The prompt is too long ({len(prompt)} characters, the limit is {MAX_PROMPT_CHARS}).")
    if bool(at) == bool(every_min):
        raise ValueError("Give either a time of day (at) or an interval (every_minutes), not both.")
    if at and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise ValueError(f"at={at!r}: use 24-hour HH:MM, e.g. 08:00.")
    if any(d not in DAYS for d in days):
        raise ValueError(f"days={days!r}: use {', '.join(DAYS)}.")
    if every_min and every_min < MIN_EVERY_MIN:
        raise ValueError(f"Watchers can't run more often than every {MIN_EVERY_MIN} minutes (each run uses the Pro limit).")
    with _lock:
        data = _read()
        if len(data["jobs"]) >= MAX_JOBS:
            raise ValueError(f"There are already {MAX_JOBS} jobs. Delete one first.")
        # Ids aren't reused, so the run log never points at the wrong job.
        used = [j["id"] for j in data["jobs"]] + [r["job_id"] for r in data["runs"]]
        number = max((int(i.removeprefix("job_")) for i in used), default=0) + 1
        job = {"id": f"job_{number}", "title": title, "prompt": prompt, "at": at, "days": days,
               "every_min": int(every_min), "once": bool(once and every_min), "enabled": True,
               "when_active": bool(when_active and at),
               "created": time.time(), "last_run": 0.0, "last_text": ""}
        data["jobs"].append(job)
        _write(data)
    return job


def change(job_id: str, **fields) -> dict:
    """Set fields of a job (enabled, last_run, last_text). KeyError if it's gone."""
    with _lock:
        data = _read()
        job = next((j for j in data["jobs"] if j["id"] == job_id), None)
        if job is None:
            raise KeyError(job_id)
        job.update(fields)
        _write(data)
    return job


def delete(job_id: str) -> dict:
    """KeyError if there's no such job. Its runs stay in the log."""
    with _lock:
        data = _read()
        job = next((j for j in data["jobs"] if j["id"] == job_id), None)
        if job is None:
            raise KeyError(job_id)
        data["jobs"].remove(job)
        _write(data)
    return job


def log_run(job: dict, status: str, text: str = "") -> None:
    """status: told (you were notified: text), nothing (nothing to tell), skipped or
    failed (text says why)."""
    with _lock:
        data = _read()
        data["runs"] = [*data["runs"], {"job_id": job["id"], "title": job["title"], "time": time.time(),
                                        "status": status, "text": text}][-MAX_RUNS:]
        _write(data)
