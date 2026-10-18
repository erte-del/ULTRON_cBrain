"""Watches: "notify me when X responds", in storage/watches.json.

A watch is a rule, not a prompt: {"channel": "email" or "whatsapp", "who": "Sarah" or "sarah@x.com", "subject": optional
words that must be in the subject (a thread), "once": stop after the first hit}. watcher.py
checks them against new mail without calling any model, so they can run every minute.
"""

import json
import re
import threading
import time

from config import STORAGE_DIR

WATCHES_FILE = STORAGE_DIR / "watches.json"
CHANNELS = ("email", "whatsapp")
MAX_WATCHES = 20
MAX_NOTIFIED = 50  # message ids remembered per watch, so a mail is told once

_lock = threading.Lock()


def _read() -> list[dict]:
    try:
        data = json.loads(WATCHES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(watches: list[dict]) -> None:
    WATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WATCHES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(watches, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(WATCHES_FILE)


def watches() -> list[dict]:
    return _read()


def add(who: str, subject: str = "", once: bool = True, channel: str = "email") -> dict:
    """ValueError with the reason if it can't be added."""
    who, subject = " ".join(str(who).split())[:100], " ".join(str(subject).split())[:100]
    if len(who) < 2:
        raise ValueError("Say who to watch for: a name or an email address.")
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of: {', '.join(CHANNELS)}.")
    if channel == "email" and re.fullmatch(r"\+?[\d\s()-]{6,}", who):
        raise ValueError("A phone number can't be watched in email. For WhatsApp messages use channel 'whatsapp'; "
                         "SMS can't be read.")
    if channel == "whatsapp":
        subject = ""
    with _lock:
        items = _read()
        if len(items) >= MAX_WATCHES:
            raise ValueError(f"There are already {MAX_WATCHES} watches. Stop one first.")
        number = max((int(w["id"].removeprefix("watch_")) for w in items), default=0) + 1
        watch = {"id": f"watch_{number}", "channel": channel, "who": who, "subject": subject, "once": bool(once),
                 "created": time.time(), "notified": []}
        _write([*items, watch])
    return watch


def remove(watch_id: str) -> dict:
    """KeyError if there's no such watch."""
    with _lock:
        items = _read()
        watch = next((w for w in items if w["id"] == watch_id), None)
        if watch is None:
            raise KeyError(watch_id)
        items.remove(watch)
        _write(items)
    return watch


def mark_notified(watch_id: str, message_ids: list[str], done: bool) -> None:
    """Remember told messages; drop the watch if it was a one-off and has now told."""
    with _lock:
        items = _read()
        for w in list(items):
            if w["id"] == watch_id:
                w["notified"] = [*w["notified"], *message_ids][-MAX_NOTIFIED:]
                if done:
                    items.remove(w)
        _write(items)


def describe(watch: dict) -> str:
    text = f"{'WhatsApp messages' if watch.get('channel') == 'whatsapp' else 'email'} from {watch['who']}" + (f" about “{watch['subject']}”" if watch["subject"] else "")
    return text + ("" if watch["once"] else " (keeps watching)")
