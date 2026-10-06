"""maps: places nearby and travel times, from Apple Maps on this Mac. (read)

No API key: UltronLocation.app (scripts/locate.swift, built by scripts/setup_location.sh)
asks MapKit, which also knows where this Mac is. Driving times leaving now use live
traffic, later ones Apple's traffic forecast. Places are searched near the user (or near
another place), nearest first.
"""

import json
from typing import Any
from urllib.parse import urlencode

from claude_agent_sdk import tool

from .homework import _text
from . import mac
from .mac import locator

MODES = ["driving", "walking", "transit"]


@tool(
    "maps",
    "Apple Maps. action 'search': places matching query ('coffee', 'pharmacy', 'Carrefour') near the "
    "user, or near another place, nearest first, with address, distance, phone and website. action "
    "'directions': travel time and distance to a place or address (from the user's location unless "
    "'from' is given), by mode driving (default, with traffic), walking or transit; give depart_at "
    "or arrive_by (ISO 8601 with the UTC offset) for a later trip. Returns depart/arrive times, an "
    "Apple Maps link and a Google Maps link (for the PC or the phone).",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "directions"]},
            "query": {"type": "string", "description": "search: what to look for."},
            "near": {"type": "string", "description": "search: around this place instead of the user."},
            "radius_m": {"type": "number", "description": "search: the area to search around, default 5000 (results can be further)."},
            "to": {"type": "string", "description": "directions: a place name or address."},
            "from": {"type": "string", "description": "directions: start, if not where the user is."},
            "mode": {"type": "string", "enum": MODES},
            "depart_at": {"type": "string"},
            "arrive_by": {"type": "string"},
        },
        "required": ["action"],
    },
)
async def maps(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action")
    if action == "search" and not str(args.get("query") or "").strip():
        return _text("maps search needs a query.", True)
    if action == "directions" and not str(args.get("to") or "").strip():
        return _text("maps directions needs 'to'.", True)
    if action not in ("search", "directions"):
        return _text(f"maps: action must be search or directions (got {action!r}).", True)
    if args.get("mode", "driving") not in MODES:
        return _text(f"maps: mode must be one of {', '.join(MODES)}.", True)
    params = {k: v for k, v in args.items() if k != "action" and v not in (None, "")}
    try:
        found = await locator(action, params)
    except (RuntimeError, OSError, ValueError) as e:
        return _text(f"maps: {e}", True)
    if action == "directions":
        found["google_maps_link"] = google_link(args)
    return _text(json.dumps(found, ensure_ascii=False))


def google_link(args: dict[str, Any]) -> str:
    """The same trip in Google Maps; without 'from' it starts where the user is."""
    origin = args.get("from") or (",".join(map(str, mac.phone_here)) if mac.phone_here else None)
    q = {"api": 1, **({"origin": origin} if origin else {}), "destination": args["to"],
         "travelmode": args.get("mode") or "driving"}
    return "https://www.google.com/maps/dir/?" + urlencode(q)
