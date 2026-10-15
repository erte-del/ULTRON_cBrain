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


def _moment(value) -> tuple[float, bool]:
    """(timestamp, all day?) of a calendar start or end. Floating times count as local."""
    if isinstance(value, datetime):
        return value.astimezone().timestamp(), False
    return datetime.combine(value, datetime.min.time()).astimezone().timestamp(), True


def events(now: datetime | None = None, hours: int = 36, data: bytes | None = None) -> list[dict]:
    """Events from now to `hours` ahead, soonest first: [{start, end, all_day, title, place}].
    RuntimeError if the calendar can't be read."""
    now = (now or datetime.now()).astimezone()
    try:
        cal = icalendar.Calendar.from_ical(data if data is not None else _fetch())
        found = recurring_ical_events.of(cal).between(now, now + timedelta(hours=hours))
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"couldn't understand the calendar ({type(e).__name__})") from None
    out = []
    for ev in found:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start, all_day = _moment(ev["DTSTART"].dt)
        end = _moment(ev["DTEND"].dt)[0] if ev.get("DTEND") else start
        out.append({"start": start, "end": end, "all_day": all_day, "title": _clean(ev.get("SUMMARY", "(no title)"), 80),
                    "place": _clean(ev["LOCATION"], 60) if ev.get("LOCATION") else ""})
    return sorted(out, key=lambda e: e["start"])[:MAX_EVENTS]


def line(ev: dict) -> str:
    when = datetime.fromtimestamp(ev["start"]).astimezone()
    label = when.strftime("%a") + " all day" if ev["all_day"] else f"{when:%a %H:%M}-{datetime.fromtimestamp(ev['end']):%H:%M}"
    return f"- {label}: {ev['title']}" + (f" @ {ev['place']}" if ev["place"] else "")


def calendar_text(now: datetime | None = None, hours: int = 36, data: bytes | None = None) -> str:
    """The events as one line each. RuntimeError if the calendar can't be read."""
    return "\n".join(line(e) for e in events(now, hours, data)) or f"(nothing in the next {hours} hours)"


def busy_now(evs: list[dict], now: datetime) -> str:
    """'In a meeting until 15:00 (Dentist)' or 'Nothing on the calendar right now; next at 14:00 (Dentist)'."""
    t = now.astimezone().timestamp()
    timed = [e for e in evs if not e["all_day"]]
    current = [e for e in timed if e["start"] <= t < e["end"]]
    if current:
        e = current[0]
        return f"On the calendar right now until {datetime.fromtimestamp(e['end']):%H:%M}: {e['title']}"
    later = [e for e in timed if e["start"] > t]
    if later:
        return f"Nothing on the calendar right now; next is {later[0]['title']} at {datetime.fromtimestamp(later[0]['start']):%a %H:%M}"
    return "Nothing on the calendar right now or in the next day and a half"
