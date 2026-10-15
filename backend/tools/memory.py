"""remember / recall / forget: what Ultron knows about you between chats.

The notes live in storage/memory_store.py. remember and forget are 'act' tools, so
scheduled jobs can't use them; in chat they run without a card (you asked for that), and you
see and delete memories in the memory panel. recall only reads.
"""

import json
from typing import Any

from claude_agent_sdk import tool

import events
import hub
from storage import memory_store


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


async def _changed() -> None:
    """Keep the memory panel in every open tab up to date."""
    await hub.emit(events.memory_list(memory_store.entries()))


CATEGORY = {
    "type": "string",
    "enum": list(memory_store.CATEGORIES),
    "description": "preferences: how they like things. people: who someone is, aliases "
    "('Sarah' = Sarah K. from work). projects: what they're working on or plan to do (with when). decisions: things "
    "they decided. facts: about the user themselves.",
}


@tool(
    "remember",
    "Save one lasting fact about the user to memory, so you know it in later chats. "
    "One short, self-contained sentence per call, in the "
    "user's language. Never passwords, card numbers, keys or other secrets (they're refused).",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The fact, e.g. 'Prefers meetings in the morning.'"},
            "category": CATEGORY,
        },
        "required": ["text", "category"],
    },
)
async def remember(args: dict[str, Any]) -> dict[str, Any]:
    try:
        memory = memory_store.add(str(args.get("text") or ""), str(args.get("category") or ""))
    except ValueError as e:
        return _text(str(e), True)
    await _changed()
    return _text(f"Saved to memory as {memory['id']}.")


@tool(
    "recall",
    "Search what you remember about the user (read-only). Finds memories containing every "
    "word of the query; use one or two key words, or leave the query empty to list "
    "everything (or everything in one category). Call it whenever the user asks what you know or remember "
    "about a person or topic, or before you say you don't know something about them; never answer that from the chat alone.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Key words, e.g. 'Sarah' or 'meetings'."},
            "category": CATEGORY,
        },
    },
)
async def recall(args: dict[str, Any]) -> dict[str, Any]:
    found = memory_store.search(str(args.get("query") or ""), args.get("category") or None)
    if not found:
        return _text("Nothing in memory matches.")
    return _text(json.dumps(
        [{k: m[k] for k in ("id", "category", "text")} for m in found], ensure_ascii=False))


@tool(
    "forget",
    "Delete one memory by its id (mem_3). Find the id "
    "with recall first if you don't have it.",
    {
        "type": "object",
        "properties": {"memory_id": {"type": "string", "description": "e.g. mem_3"}},
        "required": ["memory_id"],
    },
)
async def forget(args: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(args.get("memory_id") or "")
    try:
        memory = memory_store.delete(memory_id)
    except KeyError:
        return _text(f"There's no memory {memory_id!r}.", True)
    await _changed()
    return _text(f"Forgotten: {memory['text']}")
