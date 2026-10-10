"""ACC tracks: show a track's map on the canvas, and answer facts about it. (read)

The data is built once by scripts/ (see library_tracks/). show_track draws the layout with its
braking zones, overtaking spots and numbered corners. track_info answers from the 51GT3 info
text (length, turns, elevation, country...), and corner questions from the numbered corners.
Anything the files don't say is reported as missing so Ultron can search the web for it.
"""

import json
import re
import unicodedata
from functools import lru_cache
from typing import Any

from claude_agent_sdk import tool

import config
from . import canvas

LIB = config.TRACKS_DIR


# words that match every track's text and so say nothing
STOP_WORDS = {"circuit", "track", "tell", "about", "what", "where", "does", "have", "with", "from", "that", "this", "your", "lap", "race", "racing", "corner", "corners", "turn", "turns"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=1)
def _facts() -> dict[str, Any]:
    path = LIB / "_facts.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=None)
def _track(tid: str) -> dict[str, Any]:
    return json.loads((LIB / f"{tid}.json").read_text(encoding="utf-8"))


def find_track(query: str) -> str | None:
    """The track id the query names: longest matching alias wins ('bathurst' -> mount-panorama)."""
    q = f" {_norm(query)} "
    best, best_len = None, 0
    for tid, entry in _facts().items():
        for alias in [tid.replace("-", " "), *entry.get("aliases", [])]:
            a = _norm(alias)
            if a and f" {a} " in q and len(a) > best_len:
                best, best_len = tid, len(a)
    return best


def _name(tid: str) -> str:
    try:
        return _track(tid)["name"]
    except (OSError, KeyError):
        return tid


def _card_data(tid: str) -> dict[str, Any]:
    t = _track(tid)
    return {
        "id": tid,
        "name": t["name"],
        "length_m": t["length_m"],
        "points": t["layout"]["points"],
        "numbered_corners": t.get("numbered_corners", []),
        "numbering_status": t.get("numbering_status", ""),
        "braking_zones": [z for z in t.get("braking_zones", []) if z["class"] in ("heavy", "medium")],
        "notes": t.get("notes", []),
        "estimate_warning": t.get("estimate_warning", ""),
        "attribution": t.get("attribution", ""),
    }


def _corner_line(c: dict[str, Any], zones: list[dict[str, Any]]) -> str:
    text = f"Corner {c['number']}{c.get('letter', '')}: {c.get('direction', '?')}-hander"
    if "est_min_speed_kmh" in c:
        text += f", about {c['est_min_speed_kmh']} km/h at its slowest in a GT3 (estimate)"
    if "radius_m" in c:
        text += f", radius about {c['radius_m']} m"
    near = [z for z in zones if abs(z["apex"] - c["fraction"]) < 0.01 or abs(z["end"] - c["fraction"]) < 0.01]
    for z in near:
        text += f"; {z['class']} braking zone" + (" (overtaking spot)" if z["overtaking_candidate"] else "")
    return text


@tool(
    "show_track",
    "Show an ACC track on the canvas: its layout, heavy and medium braking zones (red/orange), "
    "overtaking spots (star) and numbered corners. Use it when the user says which track they "
    "race or asks to see one. Give the track by name or nickname (e.g. 'Imola', 'Bathurst', 'COTA', "
    "'the Ring' for the Nordschleife). The braking zones are estimates; the card says so.",
    {
        "type": "object",
        "properties": {"track": {"type": "string", "description": "The track's name, e.g. 'Spa', 'Mount Panorama'."}},
        "required": ["track"],
    },
)
async def show_track(args: dict[str, Any]) -> dict[str, Any]:
    tid = find_track(str(args.get("track") or ""))
    if tid is None:
        return {"content": [{"type": "text", "text": f"No ACC track matches {args.get('track')!r}. Ask which track they mean."}],
                "is_error": True}
    data = _card_data(tid)
    card_id = await canvas.show_card("track", data["name"], data)
    corners = len(data["numbered_corners"])
    note = f"{corners} numbered corners" if corners else f"no numbered corners yet ({data['numbering_status']})"
    return {"content": [{"type": "text", "text": f"Shown {data['name']} on the canvas as {card_id}: "
                         f"{data['length_m'] / 1000:.3f} km, {note}."}]}


@tool(
    "track_info",
    "Facts about an ACC track: length, turns, elevation, country, location, grade, other names, and "
    "what the 51GT3 info text says. Pass the question too, to get the matching part of the text "
    "(e.g. 'history', 'overtaking') and the corner details for 'corner 5' or 'turn 5'. If the answer "
    "isn't in the files it says so: then search the web for it.",
    {
        "type": "object",
        "properties": {
            "track": {"type": "string", "description": "The track's name or nickname."},
            "question": {"type": "string", "description": "What the user asked, e.g. 'corner 5', 'how long', 'where is it'."},
        },
        "required": ["track"],
    },
)
async def track_info(args: dict[str, Any]) -> dict[str, Any]:
    tid = find_track(str(args.get("track") or ""))
    if tid is None:
        return {"content": [{"type": "text", "text": f"No ACC track matches {args.get('track')!r}."}], "is_error": True}
    question = str(args.get("question") or "")
    lines = [f"{_name(tid)} (track id {tid})"]
    entry = _facts().get(tid, {})
    for key, label in (("length", "Length"), ("turns", "Turns"), ("elevation", "Elevation change"), ("grade", "FIA grade"),
                       ("country", "Country"), ("region", "Region"), ("location", "Location"),
                       ("english_name", "Official name"), ("also_known_as", "Also known as")):
        if entry.get("facts", {}).get(key):
            lines.append(f"{label}: {entry['facts'][key]}")
    t = _track(tid)
    lines.append(f"Our layout length: {t['length_m']} m (site length as given above)")
    m = re.search(r"corner\s*(\d+)|turn\s*(\d+)|\bt(\d+)\b", question, re.I)
    if m:
        number = int(next(g for g in m.groups() if g))
        match = [c for c in t.get("numbered_corners", []) if c["number"] == number]
        if match:
            lines.append(_corner_line(match[0], t.get("braking_zones", [])))
        elif not t.get("numbered_corners"):
            lines.append(f"Corner {number}: this track has no numbered corners yet ({t.get('numbering_status', '')}).")
        else:
            lines.append(f"Corner {number}: not one of this track's {len(t['numbered_corners'])} numbered corners.")
    text_path = LIB / "info" / f"{tid}.txt"
    if text_path.exists() and question:
        words = [w for w in _norm(question).split() if len(w) > 3 and not w.isdigit()]
        paras = [p.strip() for p in text_path.read_text(encoding="utf-8").split("\n")
                 if len(p.strip()) > 40 and " : " not in p]  # skip the spec lines
        words = [w for w in words if w not in STOP_WORDS]
        hits = [p for p in paras if words and any(w in _norm(p) for w in words)]
        if hits:
            lines.append("From the info text:\n" + "\n".join(hits[:3]))
    if t.get("notes") and question:
        lines += [f"Guide note: {n['text']} ({n['source']})" for n in t["notes"]]
    answered = len(lines) > 3 or bool(m)  # more than the header and the length line
    if not answered:
        lines.append("Not in the files for this question: search the web for it.")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}
