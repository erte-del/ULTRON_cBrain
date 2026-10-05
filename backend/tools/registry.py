"""All Ultron tools + read/act labels, SDK MCP server.

Every tool is labelled:
  read — runs freely, even in scheduled jobs (searching, looking things up, thinking)
  act  — sends, deletes, buys or changes something. Scheduled jobs can't use it; in chat
         it asks you first only if needs_ok says so (other people, important files)

To add a tool: write it with the SDK's @tool decorator, then add it to TOOLS.
claude.ai connector tools are labelled by their action verb (see connectors.py).
Any other tool Claude Code offers goes through the confirmation gate.
"""

import json
import re
from contextlib import contextmanager

from dataclasses import dataclass
from typing import Any, Literal

import claude_agent_sdk
from claude_agent_sdk import HookMatcher, SdkMcpTool, create_sdk_mcp_server

from storage import job_store, memory_store

from . import connectors, important, web
from .amazon import amazon_change, amazon_read
from .canvas import open_terminal, show_on_canvas
from .contacts import find_contact
from .expert import ask_expert
from .flights import flights
from .homework import check_homework
from .imagegen import generate_image, image_ai_edit
from .jobs import change_job, list_jobs, schedule_job
from .mac import mac_change, mac_read, run_python
from .maps import maps
from .memory import forget, recall, remember
from .notes import read_note, search_notes, write_note
from .important import mark_important, unmark_important
from .images import image_edit, image_search, image_undo, image_versions
from .phone import phone_taxi, phone_volume
from .library3d import search_3d_library, show_from_3d_library
from .models3d import export_3d, get_3d_spec, preview_3d, revert_3d
from .spotify import spotify_control, spotify_playlist_tracks
from .slides import lectures, make_slides, open_slides
from .syllabus import syllabus
from .telegram import text_me
from .textbook import textbook
from .uploads import read_upload
from .video import generate_video
from .whatsapp import whatsapp_send
from .youtube import youtube

SERVER_NAME = "ultron"
PREFIX = f"mcp__{SERVER_NAME}__"  # how Claude Code names tools from this server


@dataclass(frozen=True)
class UltronTool:
    tool: SdkMcpTool[Any]
    kind: Literal["read", "act"]

    @property
    def full_name(self) -> str:
        return PREFIX + self.tool.name


TOOLS: list[UltronTool] = [
    UltronTool(ask_expert, "read"),
    UltronTool(show_on_canvas, "read"),
    # Only opens the tab: what runs in the shell is up to you, typing in it.
    UltronTool(open_terminal, "read"),
    # Image edits only change Ultron's own copies and can always be undone.
    UltronTool(image_search, "read"),
    UltronTool(image_edit, "read"),
    UltronTool(image_undo, "read"),
    UltronTool(image_versions, "read"),
    # AI images are made on this Mac in seconds and only add Ultron's own copies.
    UltronTool(generate_image, "read"),
    UltronTool(image_ai_edit, "read"),
    # The 3D library only reads ready-made models and puts a copy in the 3D panel.
    UltronTool(search_3d_library, "read"),
    UltronTool(show_from_3d_library, "read"),
    # 3D previews only change Ultron's own copies. The final file needs your approval.
    UltronTool(preview_3d, "read"),
    UltronTool(revert_3d, "read"),
    UltronTool(get_3d_spec, "read"),
    UltronTool(export_3d, "act"),
    # Playing music and reading your own playlists change nothing that matters.
    UltronTool(spotify_control, "read"),
    UltronTool(spotify_playlist_tracks, "read"),
    # Only your own phone's media volume. The taxi only opens Careem: you book and pay.
    UltronTool(phone_volume, "read"),
    UltronTool(phone_taxi, "read"),
    # Looks people up in Contacts; never changes them.
    UltronTool(find_contact, "read"),
    # Only reads the school's Assignments page, in a tab it opens and closes itself.
    UltronTool(check_homework, "read"),
    # Reads the exam boards' public spec PDFs (downloaded once).
    UltronTool(syllabus, "read"),
    # Reads the user's own textbook scans on this Mac.
    UltronTool(textbook, "read"),
    # Only adds a new deck to Ultron's Output folder; never overwrites one.
    UltronTool(make_slides, "read"),
    UltronTool(open_slides, "read"),
    # Reads the teacher's lesson decks on this Mac.
    UltronTool(lectures, "read"),
    # Reading Amazon changes nothing; changing the cart or wish list runs without a card.
    # Neither can place an order.
    UltronTool(amazon_read, "read"),
    UltronTool(amazon_change, "act"),
    # Only reads files you uploaded yourself.
    UltronTool(read_upload, "read"),
    # A video ties up the Mac for minutes, but only makes Ultron's own copy: no card.
    UltronTool(generate_video, "act"),
    # Sends a message in your name.
    UltronTool(whatsapp_send, "act"),
    # Only ever texts you: the chat is fixed in .env.
    UltronTool(text_me, "read"),
    # Memories go into every later conversation; you see and delete them in the memory panel.
    UltronTool(remember, "act"),
    UltronTool(forget, "act"),
    UltronTool(recall, "read"),
    # Your Obsidian notes: reading is free (never #private ones), a write asks only for notes you marked important.
    UltronTool(search_notes, "read"),
    UltronTool(read_note, "read"),
    UltronTool(write_note, "act"),
    # A standing job keeps running (and using your Pro limit) until you stop it.
    UltronTool(schedule_job, "act"),
    UltronTool(change_job, "act"),
    UltronTool(list_jobs, "read"),
    # Adding only adds protection; lifting it asks (see ASK_TOOLS).
    UltronTool(mark_important, "act"),
    UltronTool(unmark_important, "act"),
    # This Mac: reading is free. Changes stay on this Mac and inside Ultron's folder, so no card
    # (files you marked important still ask); scheduled jobs can't use them.
    UltronTool(mac_read, "read"),
    UltronTool(mac_change, "act"),
    # Sandboxed: no network or other programs, writes only in Ultron's Output folder.
    UltronTool(run_python, "act"),
    # Apple Maps: looking places and travel times up changes nothing.
    UltronTool(maps, "read"),
    # Google Flights: only searches, can't book.
    UltronTool(flights, "read"),
    # YouTube: only searches.
    UltronTool(youtube, "read"),
]

# In chat, an 'act' tool asks you first only when it reaches other people or touches
# something you marked important. These are the ones of Ultron's own that always ask.
ASK_TOOLS = {"whatsapp_send", "unmark_important"}
# Connector actions whose name has one of these words reach other people (send_message,
# reply, share, respond_to_event, publish_app, ...). Drafts don't: they wait for you.
PEOPLE_WORDS = {"send", "reply", "forward", "share", "invite", "respond", "broadcast",
                "publish", "post", "assign", "meeting"}
# Your everyday connectors, where everything else runs without a card. The rest (Supabase,
# Vercel, Shopify, ...) can delete live projects or spend money, so they always ask.
QUIET_CONNECTORS = {"Gmail", "Google_Calendar", "Google_Drive", "TickTick", "Spotify", "Claude_Docs",
                    "Canva"}

# Friendlier titles for confirmation cards.
TITLES = {
    "export_3d": "Build the final 3D file",
    "generate_video": "Make a video (takes a few minutes)",
    "whatsapp_send": "Send a WhatsApp message",
    "amazon_change": "Change your Amazon cart or list",
    "remember": "Remember this",
    "forget": "Forget this",
    "write_note": "Save to your notes",
    "schedule_job": "Schedule a job",
    "change_job": "Change a scheduled job",
    "unmark_important": "Stop protecting this",
    "mac_change": "Change something on this Mac",
}

# Claude Code's own built-in tools that Ultron may use (all 'read').
# ToolSearch lets Claude find connector tools on demand instead of loading
# hundreds of tool descriptions into every message.
BUILTIN_READ_TOOLS: list[str] = [*web.WEB_TOOLS, "ToolSearch"]


def builtin_tools() -> list[str]:
    return list(BUILTIN_READ_TOOLS)


def classify(name: str) -> str:
    """'read' (runs freely) or 'act' (asks you first) for any tool name Claude Code uses."""
    if name in BUILTIN_READ_TOOLS:
        return "read"
    for t in TOOLS:
        if t.full_name == name:
            return t.kind
    if connectors.is_read(name):
        return "read"
    return "act"


def needs_ok(name: str, tool_input: dict[str, Any]) -> bool:
    """Whether to show you an approval card in chat before this tool runs."""
    if classify(name) == "read":
        return False
    if _touches_important(tool_input):
        return True
    own = name.removeprefix(PREFIX)
    if name.startswith(PREFIX) and any(t.tool.name == own for t in TOOLS):
        return own in ASK_TOOLS
    parsed = connectors.parse(name)
    if parsed is None or parsed[0] not in QUIET_CONNECTORS:
        return True  # unknown tools still ask
    words = set(re.split(r"[_\-]", parsed[1].lower()))
    # ponytail: a calendar event is "with people" only if this call lists attendees, so
    # deleting an event others were invited to doesn't ask. Upgrade: look the event up first.
    return bool(words & PEOPLE_WORDS) or bool(tool_input.get("attendees"))


def _touches_important(value: Any) -> bool:
    """Any text in the call (or the file an id stands for) names an important entry."""
    if isinstance(value, dict):
        return any(_touches_important(v) for v in value.values())
    if isinstance(value, list):
        return any(_touches_important(v) for v in value)
    if isinstance(value, str):
        label = connectors.item_label(value)
        return important.matches(value) or bool(label and important.matches(label))
    return False


def hooks() -> dict[str, list[HookMatcher]]:
    """Checks that run before a tool does."""
    return {"PreToolUse": [HookMatcher(matcher="WebFetch", hooks=[web.block_private_urls])]}


@contextmanager
def _always_load():
    """Mark Ultron's own tools 'always load' so Tool Search doesn't hide them.

    Claude Code reads this from the tool's `_meta`; the SDK (0.2.x) only fills
    `_meta` from its own helper, so we wrap that helper while building our server.
    """
    original = claude_agent_sdk._build_meta

    def build_meta(tool_def):
        return {**(original(tool_def) or {}), "anthropic/alwaysLoad": True}

    claude_agent_sdk._build_meta = build_meta
    try:
        yield
    finally:
        claude_agent_sdk._build_meta = original


def mcp_servers() -> dict[str, Any]:
    """The in-process MCP server that exposes Ultron's tools to Claude Code."""
    with _always_load():
        server = create_sdk_mcp_server(SERVER_NAME, tools=[t.tool for t in TOOLS])
    return {SERVER_NAME: server}


def auto_allowed() -> list[str]:
    """Tools that run without asking: all 'read' tools."""
    return BUILTIN_READ_TOOLS + [t.full_name for t in TOOLS if t.kind == "read"]


def short_name(name: str) -> str:
    """'mcp__ultron__ask_expert' -> 'ask_expert'. Other names are unchanged."""
    return name.removeprefix(PREFIX)


def friendly_name(name: str) -> str:
    """A readable tool name for the confirmation card.

    'mcp__ultron__save_note'             -> 'Save note'
    'mcp__claude_ai_Gmail__send_message'  -> 'Gmail: Send message'
    'mcp__claude_ai_Canva__search-designs' -> 'Canva: Search designs'
    """
    if name.startswith("mcp__"):
        server, _, tool_name = name.removeprefix("mcp__").partition("__")
        if server == SERVER_NAME and tool_name in TITLES:
            return TITLES[tool_name]
        action = tool_name.replace("_", " ").replace("-", " ").strip().capitalize() or tool_name
        if server == SERVER_NAME:
            return action
        service = server.removeprefix("claude_ai_").replace("_", " ").strip()
        return f"{service}: {action}"
    return name


MAX_DETAIL_CHARS = 600
# Id arguments a card can name: the event or task Ultron saw earlier, a saved memory or a scheduled job.
ID_KEYS = {"eventId": "event", "task_id": "task", "memory_id": "memory", "job_id": "job"}


def describe_call(name: str, tool_input: dict[str, Any]) -> tuple[str, str, list[list[str]]]:
    """(title, summary, details) describing a tool call, for the confirmation card."""
    title = friendly_name(name)
    summary = f"Ultron wants to: {title}"
    details = []
    # One nested object (TickTick's create_task sends {"task": {...}}) becomes its own rows.
    items = []
    for key, value in tool_input.items():
        items += value.items() if isinstance(value, dict) else [(key, value)]
    for key, value in items:
        if isinstance(value, str):
            text = value
        elif isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
            text = ", ".join(str(v) for v in value)  # e.g. recipients
        else:
            text = json.dumps(value, ensure_ascii=False, indent=1)
        if len(text) > MAX_DETAIL_CHARS:
            text = text[:MAX_DETAIL_CHARS] + "…"
        details.append([key.replace("_", " "), text])
        if key in ID_KEYS and (label := connectors.item_label(text) or memory_store.label(text) or job_store.label(text)):
            details.append([ID_KEYS[key], label])
    return title, summary, details
