"""Which WhatsApp group does the user mean? (read-only, plus remembering what they call a group)

"the rain gc", "science habibis", "the boys": the words are matched against the group names in WhatsApp's
database (whatsapp_read.groups) and against what the user has called groups before. A clear winner is used;
if it's close, or nothing fits, Ultron asks (never guesses). When a message to a group goes out after the
user approved it, the words they used are saved as a memory ('WhatsApp group alias: "the boys" = "Science
Habibis"', People) so next time it just knows; they see and delete it in the memory panel.
"""

import difflib
import re
from typing import Any

from claude_agent_sdk import tool

import whatsapp_read
from storage import memory_store

FILLER = {"the", "a", "my", "our", "gc", "group", "groupchat", "chat", "whatsapp", "wa", "in", "on", "to", "for",
          "with", "of", "grp", "gp"}
SURE = 0.8  # a match this good, and clearly ahead of the next, is used without asking
LEAD = 0.12
ASK_FROM = 0.5
ALIAS = re.compile(r'^WhatsApp group alias: "(.+)" = "(.+)"$')


def _words(text: str) -> list[str]:
    words = re.findall(r"\w+", str(text).casefold())
    return [w for w in words if w not in FILLER] or words


def _key(text: str) -> str:
    return "".join(_words(text))


def score(said: str, name: str) -> float:
    """0..1: how well what the user said fits a group's name."""
    q, g = _words(said), _words(name)
    if not q or not g:
        return 0.0
    if "".join(q) == "".join(g):
        return 1.0
    hits = [any(w == x for w in g) for x in q], [any(len(x) >= 3 and w.startswith(x) for w in g) for x in q]
    if all(a or b for a, b in zip(*hits)):  # every word they said is in the name (or starts it)
        return max(0.95 - 0.1 * (len(g) - len(q)) - (0.1 if not all(hits[0]) else 0), 0.7)
    return round(0.9 * difflib.SequenceMatcher(None, "".join(q), "".join(g)).ratio(), 3)  # typos


def aliases() -> dict[str, str]:
    """{what the user calls it (normalized): the group's name}, from memory; the newest wins."""
    found: dict[str, str] = {}
    for m in reversed(memory_store.entries()):  # oldest first
        if hit := ALIAS.match(m["text"]):
            found[_key(hit.group(1))] = hit.group(2)
    return found


def resolve(said: str, groups: list[dict]) -> tuple[str, list[dict], str]:
    """(verdict, groups, how): 'use' with the one group, 'ask' with the best few, or 'none'."""
    said = " ".join(str(said).split())
    named = aliases().get(_key(said))
    if named:
        same = [g for g in groups if _key(g["name"]) == _key(named)]
        if len(same) == 1:
            return "use", same, "what you've called it before"
    exact = [g for g in groups if " ".join(g["name"].split()).casefold() == said.casefold()]
    if len(exact) == 1:
        return "use", exact, "exact name"
    ranked = sorted(((score(said, g["name"]), g) for g in groups), key=lambda r: -r[0])
    ranked = [r for r in ranked if r[0] >= ASK_FROM]
    if not ranked:
        return "none", [], ""
    if ranked[0][0] >= SURE and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= LEAD):
        return "use", [ranked[0][1]], "close match"
    return "ask", [g for _, g in ranked[:5]], ""


def remember_alias(said: str, name: str) -> str:
    """Save that `said` means the group `name`, unless that's already known or `said` is just the name.
    Returns a short note for the tool result ('' if nothing was saved)."""
    said = " ".join(str(said).split())
    if len(_key(said)) < 2 or _key(said) == _key(name) or aliases().get(_key(said), "") == name:
        return ""
    try:
        for m in memory_store.entries():  # it used to mean another group
            if (hit := ALIAS.match(m["text"])) and _key(hit.group(1)) == _key(said):
                memory_store.delete(m["id"])
        memory_store.add(f'WhatsApp group alias: "{said}" = "{name}"', "people")
    except (ValueError, KeyError):
        return ""
    return f' Remembered: "{said}" means the group "{name}".'


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


@tool(
    "whatsapp_groups",
    "Work out which WhatsApp group chat the user means from whatever words they used ('the rain gc', "
    "'science habibis', 'the boys'): it knows what they've called groups before. Read-only. Call it before "
    "whatsapp_send to a group and pass on what it says; if it's not sure it lists the closest groups: "
    "ask the user which one, never guess.",
    {
        "type": "object",
        "properties": {"said": {"type": "string", "description": "The user's own words for the group."}},
        "required": ["said"],
    },
)
async def whatsapp_groups(args: dict[str, Any]) -> dict[str, Any]:
    said = " ".join(str(args.get("said") or "").split())
    if not said:
        return _text("Say which group.", True)
    try:
        verdict, found, how = resolve(said, whatsapp_read.groups(""))
    except RuntimeError as e:
        return _text(f"Couldn't look up WhatsApp groups: {e}.", True)
    if verdict == "use":
        g = found[0]
        return _text(f'The group is "{g["name"]}" ({how}). To message it call whatsapp_send with group "{g["name"]}", '
                     f'group_id {g["id"]} and said "{said}".')
    if verdict == "ask":
        options = "; ".join(f'"{g["name"]}" (group_id {g["id"]})' for g in found)
        return _text(f"Not sure which group {said!r} is. Closest: {options}. Ask the user which one (name the options), "
                     "then call whatsapp_send with that group's name, its group_id and said set to their words: "
                     "it's remembered for next time.")
    return _text(f"No WhatsApp group looks like {said!r}. Ask the user for the group's name.")
