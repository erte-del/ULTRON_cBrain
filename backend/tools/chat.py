"""new_chat: Ultron starts a fresh conversation when you ask for one.

The tool only asks for it. The restart itself happens in main.run_turn once this reply is
finished, because restarting inside a turn would cut the reply off.
"""

from typing import Any

from claude_agent_sdk import tool

requested = False


def take() -> bool:
    """True once if new_chat was called during the turn that just ended."""
    global requested
    was, requested = requested, False
    return was


@tool(
    "new_chat",
    "Start a fresh conversation (the same as the new chat button): the current chat is saved to memory "
    "and the screen is cleared. Call it when the user asks to start, open or begin a new chat, "
    "conversation or thread, or to start over. Not for a new topic inside the same chat. "
    "Say one very short line first (e.g. 'Starting a new chat.'); it starts as soon as you finish.",
    {"type": "object", "properties": {}},
)
async def new_chat(args: dict[str, Any]) -> dict[str, Any]:
    global requested
    requested = True
    return {"content": [{"type": "text", "text": "A new chat starts as soon as you finish this reply. "
                         "Don't write anything more than one short line."}]}
