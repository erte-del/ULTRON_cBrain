"""Assetto Corsa Competizione telemetry on the Windows PC (acc-telemetry/, its lap viewer over Tailscale).

  acc_read (read)  live state, session, last lap, lap comparison, tyres, fuel, events, saved laps.
                   GET <JARVIS_ACC_URL>/api/tool/<name>; nothing is changed.

Off when JARVIS_ACC_URL isn't set; says so when the PC is asleep or ACC / the viewer isn't running.
"""

import asyncio
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from claude_agent_sdk import tool

import config

from . import canvas
from .homework import _text

TIMEOUT_S = 20
WHATS = ["get_live_state", "get_session_info", "get_last_lap_summary", "compare_laps", "get_tyre_report",
         "get_fuel_report", "get_recent_events", "list_laps", "get_lap"]
# Which arguments each call takes (the viewer ignores the rest).
PARAMS = {
    "get_last_lap_summary": ["lap_id"],
    "compare_laps": ["lap_a", "lap_b"],
    "get_recent_events": ["limit", "lap", "kind"],
    "list_laps": ["track", "car", "limit"],
    "get_lap": ["lap_id", "include_trace", "points"],
}


def _get(name: str, query: dict[str, Any]) -> Any:
    qs = urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in query.items()})
    req = Request(f"{config.ACC_URL}/api/tool/{name}" + (f"?{qs}" if qs else ""))
    try:
        with urlopen(req, timeout=TIMEOUT_S, context=config.ssl_context()) as r:
            return json.load(r)
    except HTTPError as e:
        if e.code == 403:
            raise RuntimeError("The PC's lap viewer refused this address: set ACC_ALLOWED_HOSTS to the PC's "
                               "Tailscale name there and restart it.") from None
        if e.code == 404:
            raise RuntimeError(f"The lap viewer has no call named {name}: update acc-telemetry on the PC.") from None
        raise RuntimeError(f"The PC's lap viewer answered {e.code}.") from None


async def _ask(name: str, args: dict[str, Any]) -> Any:
    if not config.ACC_URL:
        raise RuntimeError("ACC telemetry isn't set up: JARVIS_ACC_URL in .env (see acc-telemetry/README.md).")
    query = {k: args[k] for k in PARAMS.get(name, []) if args.get(k) not in (None, "")}
    try:
        return await asyncio.to_thread(_get, name, query)
    except (URLError, OSError, ValueError):
        raise RuntimeError("The PC's ACC lap viewer isn't reachable: the PC is off or asleep, Tailscale is down "
                           "there, or the acc-telemetry viewer isn't running (start it with ACC running).") from None


def _compare_rows(res: dict[str, Any]) -> list[list[str]]:
    rows = []
    for r in res.get("biggest") or []:
        if "name" in r and "delta_s" in r:
            rows.append([str(r["name"]), f"{r['delta_s']:+.3f} s"])
    return rows


@tool(
    "acc_read",
    "Read the user's Assetto Corsa Competizione telemetry from their Windows PC (live while they drive, "
    "and saved laps). what: 'get_live_state' (speed, gear, tyres, fuel, lap, delta to best), "
    "'get_session_info' (track, car, session, weather), 'get_last_lap_summary' (sector times and per-corner "
    "braking and speeds; lap_id optional), 'compare_laps' (where lap_a lost or gained time against lap_b, "
    "by corner; defaults last vs best; also shown as a table on the canvas), 'get_tyre_report', "
    "'get_fuel_report', 'get_recent_events' (lockups, wheelspin, off-tracks; limit, lap, kind), "
    "'list_laps' (saved laps; track, car, limit), 'get_lap' (one lap by lap_id; include_trace only if asked). "
    "A lap is an id from list_laps, or 'last', 'previous', 'best'. Positive delta = the first lap was slower. "
    "If the PC is asleep or ACC isn't running, say so.",
    {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": WHATS},
            "lap_id": {"type": "string", "description": "For get_lap / get_last_lap_summary."},
            "lap_a": {"type": "string", "description": "For compare_laps (default last)."},
            "lap_b": {"type": "string", "description": "For compare_laps (default best)."},
            "track": {"type": "string"},
            "car": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "lap": {"type": "integer", "description": "For get_recent_events: only this lap number."},
            "kind": {"type": "string", "description": "For get_recent_events: lockup, wheelspin, off-track…"},
            "include_trace": {"type": "boolean"},
            "points": {"type": "integer", "minimum": 2, "maximum": 200},
        },
        "required": ["what"],
    },
)
async def acc_read(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("what") or "")
    if name not in WHATS:
        return _text(f"acc_read: what must be one of {', '.join(WHATS)}.", True)
    try:
        found = await _ask(name, args)
    except RuntimeError as e:
        return _text(str(e), True)
    if name == "compare_laps" and isinstance(found, dict) and not found.get("error") and (rows := _compare_rows(found)):
        a, b = found.get("lap_a") or {}, found.get("lap_b") or {}
        await canvas.show_table(f"ACC: {a.get('lap', args.get('lap_a') or 'last')} vs {b.get('lap', args.get('lap_b') or 'best')} "
                                f"(total {found.get('total_delta_s', 0):+.3f} s)", ["Corner / straight", "Delta (+ = slower)"], rows)
    return _text(json.dumps(found, ensure_ascii=False), isinstance(found, dict) and bool(found.get("error")))
