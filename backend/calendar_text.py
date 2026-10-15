"""Your calendar as plain text, read from Google Calendar's private iCal link.

Used by initiative.py, so the local model is handed what's coming up instead of having to call a
connector. No Google Cloud project or login: in Google Calendar, Settings > your calendar >
"Secret address in iCal format", paste it as GOOGLE_CALENDAR_ICAL_URL in .env. Anyone with that
link can read the calendar, so it's treated like a password: never logged, never in an error.
Read-only by nature.
"""

import urllib.request
from datetime import date, datetime, timedelta
from urllib.error import URLError

import icalendar
import recurring_ical_events

import config

MAX_BYTES = 10_000_000
MAX_EVENTS = 25


def configured() -> bool:
    return bool(config.GOOGLE_CALENDAR_ICAL_URL)


def _fetch() -> bytes:
    # The address is the secret, so errors must never include it.
    try:
        with urllib.request.urlopen(config.GOOGLE_CALENDAR_ICAL_URL, timeout=30, context=config.ssl_context()) as r:
            data = r.read(MAX_BYTES + 1)
    except (URLError, TimeoutError, ValueError) as e:
        raise RuntimeError(f"couldn't read the calendar ({type(e).__name__})") from None
    if len(data) > MAX_BYTES:
        raise RuntimeError("the calendar is too big")
    return data


def _clean(text, limit: int) -> str:
    """One line, capped. Event text is somebody else's words: data, never instructions."""
    text = " ".join(str(text).split())
    return text[:limit - 1] + "…" if len(text) > limit else text


def _start(value) -> tuple[float, str]:
    if isinstance(value, datetime):
        moment = value.astimezone() if value.tzinfo else value.astimezone()  # floating time = local
        return moment.timestamp(), moment.strftime("%a %H:%M")
    day = datetime.combine(value, datetime.min.time()).astimezone()
    return day.timestamp(), day.strftime("%a") + " all day"


def calendar_text(now: datetime | None = None, hours: int = 36, data: bytes | None = None) -> str:
    """Events from now to `hours` ahead, soonest first, one per line. RuntimeError if it can't be read."""
    now = (now or datetime.now()).astimezone()
    try:
        cal = icalendar.Calendar.from_ical(data if data is not None else _fetch())
        events = recurring_ical_events.of(cal).between(now, now + timedelta(hours=hours))
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"couldn't understand the calendar ({type(e).__name__})") from None
    found = []
    for ev in events:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        stamp, label = _start(ev["DTSTART"].dt)
        place = f" @ {_clean(ev['LOCATION'], 60)}" if ev.get("LOCATION") else ""
        found.append((stamp, f"- {label}: {_clean(ev.get('SUMMARY', '(no title)'), 80)}{place}"))
    return "\n".join(line for _, line in sorted(found)[:MAX_EVENTS]) or f"(nothing in the next {hours} hours)"
