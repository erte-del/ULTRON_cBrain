"""show_on_canvas -> UI events. (Phase 4a)

The canvas is the panel next to the chat where Ultron *shows* things. Cards are
pushed to every open tab through the hub. Later steps add images and 3D objects.
"""

import re
from typing import Any
from urllib.parse import urlencode

from claude_agent_sdk import tool

import events
import hub
import terminal

CARD_KINDS = ["text", "table", "email_list", "events", "tasks", "map", "youtube"]
# A map card is Google Maps' own embed (no API key), built here so the page only ever
# frames this one address.
MAP_URL = "https://www.google.com/maps?"
MAP_MODES = {"driving": "d", "walking": "w", "transit": "r"}

# Fields each list item may have, per kind (all strings; anything else is dropped).
ITEM_FIELDS = {
    "email_list": ["from", "subject", "date", "snippet", "unread", "id"],
    "events": ["title", "start", "end", "location", "attendees", "notes"],
    "tasks": ["title", "due", "list", "notes", "done"],
    "youtube": ["id", "title", "channel", "length", "views", "age"],
}
# A youtube card only ever plays these: the page builds the player's address from the id.
YOUTUBE_ID = re.compile(r"[\w-]{11}")
MAX_ITEMS = 50

_last_card = 0


def _new_card_id() -> str:
    global _last_card
    _last_card += 1
    return f"card_{_last_card}"


def restored(card_ids: list[str]) -> None:
    """Cards of a loaded chat are back on the canvas: new cards mustn't reuse their ids
    (the count starts at 1 again whenever the server restarts)."""
    global _last_card
    for card_id in card_ids:
        if m := re.fullmatch(r"card_(\d+)", card_id):
            _last_card = max(_last_card, int(m[1]))

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": CARD_KINDS,
            "description": "text: markdown content. table: columns + rows. "
            "email_list: items with from/subject/date/snippet/unread. "
            "events: items with title/start/end/location/attendees/notes. "
            "tasks: items with title/due/list/notes/done (done: true or false). "
            "map: a live map (Google Maps) of place, or the route from -> to; view satellite for the overhead view. "
            "youtube: videos to watch right on the canvas, items with id (the 11 characters after watch?v=)"
            "/title/channel/length/views/age; the first one plays, the others are a list to click. "
            "Write dates and times for people, in the user's local time, e.g. 'Wed 30 Sep, 09:00'.",
        },
        "title": {"type": "string", "description": "Short card title."},
        "content": {"type": "string", "description": "For kind=text: the markdown to show."},
        "columns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "For kind=table: column headings.",
        },
        "rows": {
            "type": "array",
            "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}},
            "description": "For kind=table: one array of cell values per row.",
        },
        "items": {
            "type": "array",
            "items": {"type": "object"},
            "description": "For kind=email_list, events, tasks or youtube: one object per email / event / task / video.",
        },
        "place": {
            "type": "string",
            "description": "For kind=map: what to show: 'lat,lon', an address or place name, or a search "
            "like 'coffee near 25.08,55.25'. Use the name and address the maps tool returned "
            "(bare coordinates get labelled with the nearest shop).",
        },
        "from": {"type": "string", "description": "For kind=map routes: start, 'lat,lon' (e.g. the user's location)."},
        "to": {"type": "string", "description": "For kind=map routes: destination, by name and address."},
        "mode": {"type": "string", "enum": list(MAP_MODES), "description": "For kind=map routes, default driving."},
        "view": {"type": "string", "enum": ["map", "satellite"], "description": "For kind=map, default map."},
        "zoom": {"type": "integer", "minimum": 1, "maximum": 21, "description": "For kind=map: 15 is streets."},
        "replace_card_id": {
            "type": "string",
            "description": "To update a card you showed earlier, pass its id (e.g. card_2).",
        },
    },
    "required": ["kind", "title"],
}


def _text(value: Any) -> str:
    """A field as text; lists (e.g. attendees) become 'a, b'."""
    return ", ".join(map(str, value)) if isinstance(value, list) else str(value)


def _card_data(args: dict[str, Any]) -> dict[str, Any]:
    kind = args["kind"]
    if kind == "text":
        content = str(args.get("content") or "").strip()
        if not content:
            raise ValueError("kind=text needs 'content'")
        return {"content": content}
    if kind == "table":
        columns = [str(c) for c in args.get("columns") or []]
        rows = [["" if v is None else str(v) for v in row] for row in args.get("rows") or []]
        if not columns:
            raise ValueError("kind=table needs 'columns'")
        return {"columns": columns, "rows": rows}
    if kind == "map":
        return map_data(args)
    if kind in ITEM_FIELDS:
        fields = ITEM_FIELDS[kind]
        items = []
        for raw in (args.get("items") or [])[:MAX_ITEMS]:
            if isinstance(raw, dict) and (kind != "youtube" or YOUTUBE_ID.fullmatch(str(raw.get("id")))):
                items.append({f: _text(raw[f]) for f in fields if raw.get(f) not in (None, "", [])})
        if not items:
            raise ValueError(f"kind={kind} needs 'items'")
        return {"items": items}
    raise ValueError(f"Unknown card kind {kind!r}; use one of {CARD_KINDS}")


def map_data(args: dict[str, Any]) -> dict[str, str]:
    """{url: the embed for the card, link: the same map in Google Maps}."""
    place, start, end = (str(args.get(k) or "").strip() for k in ("place", "from", "to"))
    if end:
        query = {"saddr": start, "daddr": end, "dirflg": MAP_MODES.get(str(args.get("mode")), "d")}
    elif place:
        query = {"q": place}
    else:
        raise ValueError("kind=map needs 'place', or 'to' (and 'from') for a route")
    query = {k: v for k, v in query.items() if v}
    if args.get("view") == "satellite":
        query["t"] = "k"
    if isinstance(args.get("zoom"), int) and 1 <= args["zoom"] <= 21:
        query["z"] = str(args["zoom"])
    link = MAP_URL + urlencode(query)
    return {"url": link + "&output=embed", "link": link}


async def show_text(title: str, content: str) -> str:
    """Put a markdown card on the canvas from Ultron's own code. Returns the card id."""
    card_id = _new_card_id()
    await hub.emit(events.canvas_card(card_id, "text", title, {"content": content}))
    return card_id


async def show_table(title: str, columns: list[str], rows: list[list[str]]) -> str:
    """Put a table card on the canvas from Ultron's own code. Returns the card id."""
    card_id = _new_card_id()
    await hub.emit(events.canvas_card(card_id, "table", title, {"columns": columns, "rows": rows}))
    return card_id


@tool(
    "show_on_canvas",
    "Show content on the canvas, the panel next to the chat. Use it for things better "
    "seen than read in a chat bubble: tables and comparisons, structured data, longer "
    "documents, drafts, plans, code. Keep your chat reply short and refer to the card. "
    "Returns the card id, which you can pass as replace_card_id to update the card later.",
    INPUT_SCHEMA,
)
async def show_on_canvas(args: dict[str, Any]) -> dict[str, Any]:
    try:
        data = _card_data(args)
    except ValueError as e:
        return {"content": [{"type": "text", "text": f"Not shown: {e}"}], "is_error": True}

    card_id = args.get("replace_card_id") or _new_card_id()
    await hub.emit(events.canvas_card(card_id, args["kind"], str(args["title"]), data))
    note = "" if hub.has_clients() else " (no browser is open, so nobody can see it right now)"
    return {"content": [{"type": "text", "text": f"Shown on the canvas as {card_id}.{note}"}]}


@tool(
    "open_terminal",
    "Open a fresh terminal (a real shell on this Mac) in a new canvas tab, for the user to "
    "type in, e.g. to work with Claude Code. Every call opens another one. You can't "
    "type in it, but read_terminal shows you what's on its screen. It only works on the Mac itself, not on the phone.",
    {
        "type": "object",
        "properties": {
            "claude": {
                "type": "boolean",
                "description": "Start Claude Code in the new terminal (the `claude` command).",
            },
        },
    },
)
async def open_terminal(args: dict[str, Any]) -> dict[str, Any]:
    await hub.emit(events.terminal_open(args.get("claude") is True))
    note = "" if hub.has_clients() else " No browser is open, so nobody can see it right now."
    return {"content": [{"type": "text", "text": f"A new terminal tab is open on the canvas.{note}"}]}


@tool(
    "read_terminal",
    "Read what a terminal tab on the canvas shows right now (its screen plus recent "
    "scrollback, as plain text). Use it when the user asks about what's in the terminal.",
    {
        "type": "object",
        "properties": {
            "number": {
                "type": "integer",
                "description": "The terminal's number (TERMINAL 1, 2, ...). Defaults to the newest.",
            },
        },
    },
)
async def read_terminal(args: dict[str, Any]) -> dict[str, Any]:
    if not terminal.SCREENS:
        return {"content": [{"type": "text", "text": "No terminal is open on the canvas."}], "is_error": True}
    number = args.get("number") or max(terminal.SCREENS)
    if number not in terminal.SCREENS:
        open_ = ", ".join(str(n) for n in sorted(terminal.SCREENS))
        return {"content": [{"type": "text", "text": f"No terminal {number}. Open: {open_}."}], "is_error": True}
    text = terminal.SCREENS[number] or "(the screen is empty)"
    return {"content": [{"type": "text", "text": f"Terminal {number}:\n{text}"}]}
