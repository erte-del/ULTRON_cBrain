"""change_ui: Ultron restyles the page for this chat only.

The page applies the style sheet on top of its standard look (ui.layout event); a new chat,
a loaded chat or the reset button in the top bar put the standard look back.
"""

from typing import Any

from claude_agent_sdk import tool

import events
import hub
import ui_state


@tool(
    "change_ui",
    "Change how the page looks for this chat only, with CSS that is applied on top of the standard look "
    "(layout, sizes, colors, fonts, which panels show, how big the canvas is...). The user's window size is in "
    "the [Device: ...] note of every message. Use it when the user asks for a different look or layout, or when "
    "something would show better in another layout (a wide table, a big map, a video, a 3D model). "
    "css adds to what you already changed; replace=true throws the earlier changes away first. "
    "reset=true goes back to the standard look (the user also has a reset button in the top bar, and every new chat "
    "starts standard). The top bar and approval cards always stay visible. See 'About the look of the screen' for class names.",
    {
        "type": "object",
        "properties": {
            "css": {"type": "string", "description": "CSS to apply. No @import, no url() except data:image/."},
            "replace": {"type": "boolean", "description": "Drop the earlier changes first (default false: add on top)."},
            "reset": {"type": "boolean", "description": "Back to the standard look; css is ignored."},
        },
    },
)
async def change_ui(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("reset"):
        ui_state.reset()
        await hub.emit(events.ui_layout(""))
        return {"content": [{"type": "text", "text": "The standard look is back."}]}
    sheet = str(args.get("css") or "").strip()
    if not sheet:
        return {"content": [{"type": "text", "text": "Give css to apply, or reset=true."}], "is_error": True}
    if problem := ui_state.apply(sheet, replace=args.get("replace") is True):
        return {"content": [{"type": "text", "text": problem}], "is_error": True}
    if not await hub.emit(events.ui_layout(ui_state.css)):
        return {"content": [{"type": "text", "text": "Nobody has the page open, so nothing changed on screen."}], "is_error": True}
    return {"content": [{"type": "text", "text": f"The look is changed ({len(ui_state.css)} characters of CSS in use)."}]}
