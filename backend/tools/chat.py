"""new_chat and trim_chat: Ultron starts a fresh conversation, or drops the older part of this one.

The tools only ask. The restart itself happens in main.run_turn once this reply is
finished, because restarting inside a turn would cut the reply off.
"""

from typing import Any

from claude_agent_sdk import tool

requested = False
trim: dict | None = None  # {"first_turn": int, "cleared": str} or {"undo": True}
# Kept up to date by brain/agent.py: the oldest and latest turn numbers, and whether a trim can be undone.
state = {"oldest": 0, "current": 0, "can_undo": False}


def take() -> bool:
    """True once if new_chat was called during the turn that just ended."""
    global requested
    was, requested = requested, False
    return was


def take_trim() -> dict | None:
    """The trim_chat request of the turn that just ended, once."""
    global trim
    was, trim = trim, None
    return was


@tool(
    "new_chat",
    "Start a fresh conversation (the same as the new chat button): the current chat is saved to memory "
    "and the screen is cleared. Call it when the user asks to start, open or begin a new chat, "
    "conversation or thread, or to start over. Not for a new topic inside the same chat. "
    "You must call this tool: saying you are starting one does nothing by itself. Write one very short line "
    "(e.g. 'Starting a new chat.') and call it in the same turn; it starts as soon as you finish.",
    {"type": "object", "properties": {}},
)
async def new_chat(args: dict[str, Any]) -> dict[str, Any]:
    global requested
    requested = True
    return {"content": [{"type": "text", "text": "A new chat starts as soon as you finish this reply. "
                         "Don't write anything more than one short line."}]}


def _answer(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], **({"is_error": True} if is_error else {})}


@tool(
    "trim_chat",
    "Drop the older part of THIS chat and keep going with the recent topic, without a new chat: the "
    "earlier messages disappear from the screen and from what you remember of the conversation. Call it "
    "when the user asks to clear, drop, forget or cut away what came before ('clear out everything before "
    "this, we moved on', 'forget the earlier stuff about school, keep the Spotify part', 'start a new chat "
    "for what we're discussing now'). Not for a plain 'new chat' or 'start over from nothing' (that is "
    "new_chat), and never just because the subject changed: only when they ask. "
    "Every message you receive starts with a [Turn N] tag. first_turn is the number of the FIRST turn "
    "to keep: the turn where the topic they want to keep begins; everything before it goes. It must be "
    "after the oldest turn and no later than this one. If you can't tell where the topic changed, ask one "
    "short question instead of guessing. cleared is a few words on what is removed ('school work'). "
    "undo=true brings back what the last trim removed (only the last one) instead. "
    "The trim happens as soon as you finish this reply, so write ONE short sentence saying what you cleared "
    "and what you kept, e.g. 'Cleared the school-work part, kept from the Spotify question on.'",
    {
        "type": "object",
        "properties": {
            "first_turn": {"type": "integer", "description": "The N of the first [Turn N] to keep."},
            "cleared": {"type": "string", "description": "A few words on what is removed."},
            "undo": {"type": "boolean", "description": "Bring back what the last trim removed."},
        },
    },
)
async def trim_chat(args: dict[str, Any]) -> dict[str, Any]:
    global trim
    if args.get("undo"):
        if not state["can_undo"]:
            return _answer("There is no trim to undo.", True)
        trim = {"undo": True}
        return _answer("The cleared part comes back as soon as you finish this reply. Say so in one short sentence.")
    first = args.get("first_turn")
    if not isinstance(first, int) or isinstance(first, bool):
        return _answer("Give first_turn: the number N of the first [Turn N] to keep.", True)
    if first <= state["oldest"]:
        return _answer(f"Turn {first} is already the oldest in this chat (turn {state['oldest']}): nothing before it to clear.", True)
    if first > state["current"]:
        return _answer(f"There is no turn {first} yet; this is turn {state['current']}.", True)
    trim = {"first_turn": first, "cleared": str(args.get("cleared") or "").strip()[:120]}
    return _answer("The earlier part is cleared as soon as you finish this reply. Write one short sentence: "
                   "what you cleared and what you kept. Nothing more.")
