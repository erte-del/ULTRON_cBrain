"""exam_countdown: a "days until" card for upcoming exams and assessments (read only).

The dates live in TickTick (tasks tagged 'exam', added by the Homework job when Teams has an
IMPORTANT assessment post); this tool only does the counting, so the numbers are never
worked out by the model, and keeps one card on the canvas up to date.
"""

from datetime import date, datetime
from typing import Any

from claude_agent_sdk import tool

import events
import hub

CARD_ID = "exam_countdown"  # the same card every time, so it updates instead of piling up


def countdown(exams: list[dict[str, Any]], today: date | None = None) -> list[list[str]]:
    """Rows [title, date, days left], soonest first; past exams and bad dates are dropped."""
    today = today or datetime.now().astimezone().date()
    rows = []
    for e in exams:
        try:
            when = date.fromisoformat(str(e["date"])[:10])
            title = str(e["title"])
        except (KeyError, ValueError):
            continue
        if (days := (when - today).days) >= 0:
            rows.append((days, title, when))
    return [[t, w.strftime("%a %d %b"), "today" if d == 0 else "tomorrow" if d == 1 else f"{d} days"]
            for d, t, w in sorted(rows)]


@tool(
    "exam_countdown",
    "Show a 'days until' card for upcoming exams and assessments, and return the same lines. "
    "Pass each one's title and date (YYYY-MM-DD), e.g. from TickTick tasks tagged 'exam'. "
    "Exams already past are left out. Always use this for the numbers: don't count days yourself.",
    {"type": "object", "properties": {"exams": {"type": "array", "items": {
        "type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string"}},
        "required": ["title", "date"]}}}, "required": ["exams"]},
)
async def exam_countdown(args: dict[str, Any]) -> dict[str, Any]:
    rows = countdown(args.get("exams") or [])
    if not rows:
        return {"content": [{"type": "text", "text": "No upcoming exams."}]}
    await hub.emit(events.canvas_card(CARD_ID, "table", "Exam countdown",
                                      {"columns": ["Exam", "Date", "In"], "rows": rows}))
    return {"content": [{"type": "text", "text": "\n".join(f"{t}: {w}, {d}" for t, w, d in rows)}]}
