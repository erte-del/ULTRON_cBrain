"""What the memory panel shows beyond the plain list, and what its extra buttons do.

`event()` is the memory.list message: the memories (every field), the links between them, the insights with
their evidence / confidence / "why" line, the proposals waiting for you, and the state of the nudge switch.
An old panel that only reads `memories` and `categories` keeps working.
"""

import events
import memory_decay
import memory_insights
import memory_surface
from storage import memory_aux, memory_store

PANEL_STATUSES = ("new", "useful", "not_useful")


def insights_for_panel() -> list[dict]:
    """Insights you can see and rate: not forgotten, not stale. Below-0.6 ones are included but marked hidden
    (so you can see what Ultron isn't showing)."""
    shown = {i["id"] for i in memory_insights.visible()}
    return [{**i, "why": memory_surface.why(i), "shown_to_you": i["id"] in shown}
            for i in sorted(memory_aux.insights(), key=lambda i: -i["confidence"]) if i["status"] in PANEL_STATUSES]


def event() -> events.Event:
    live = {m["id"] for m in memory_store.entries()}
    state = memory_aux.state()
    return events.memory_list(memory_store.entries(), {
        "links": [l for l in memory_aux.links() if l["a"] in live and l["b"] in live],
        "insights": insights_for_panel(),
        "proposals": [p for p in state["proposals"] if p["status"] == "waiting"],
        "proactive": bool(state["proactive"]),
    })


def apply(kind: str, msg: dict) -> None:
    """A button in the panel. ValueError with the reason if it can't be done."""
    try:
        if kind == "user.insight":
            memory_insights.feedback(str(msg.get("id")), str(msg.get("verdict")))
        elif kind == "user.memory_pin":
            memory_store.patch(str(msg.get("id")), pinned=bool(msg.get("pinned")))
        elif kind == "user.link_reject":
            if not memory_aux.reject_link(str(msg.get("a")), str(msg.get("b")), str(msg.get("link_kind"))):
                raise ValueError("That link no longer exists.")
        elif kind == "user.nudges":
            memory_surface.set_proactive(msg.get("on") is True)
        elif kind == "user.proposal":
            if msg.get("action") == "approve":
                memory_decay.approve(str(msg.get("id")))
            else:
                memory_decay.reject(str(msg.get("id")))
        elif kind == "user.memory_restore":
            memory_store.restore(str(msg.get("id")))
    except KeyError:
        raise ValueError("That no longer exists.") from None
