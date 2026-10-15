"""What the local model (Ollama) can use, loaded on demand.

Ultron's full prompt (~8k tokens) and its 76 tools (~14k) are too much for a 14B model: replies
took minutes and it grabbed tools nobody asked for. So the local brain starts with a small
core (memory, canvas, jobs, texting you) and no claude.ai connectors. Each *group* below adds
tools, a connector and the matching part of the prompt, and is switched on when the message
(or a scheduled job's text) mentions its words. A group stays on for the rest of the conversation.

Claude Code can't add Ultron's own tools to a running session, so a new group restarts it
(`resume` keeps the conversation). Claude itself doesn't use any of this: it has tool search.
"""

import re
from dataclasses import dataclass

import config
from tools import connectors, registry

PREFIX = registry.PREFIX

from .prompts import JARVIS_SYSTEM_PROMPT


@dataclass(frozen=True)
class Group:
    name: str
    words: str  # regex, matched case-insensitively against the message
    tools: tuple[str, ...] = ()  # Ultron's own tools
    connector: str = ""  # the claude.ai connector, as Claude Code lists it ("Google Calendar")
    prompt: tuple[str, ...] = ()  # beginnings of the system prompt paragraphs this group needs
    note: str = ""  # a hint a small model needs that the full prompt doesn't give


CORE_TOOLS = (
    "recall", "remember", "forget", "clear_canvas", "list_jobs", "schedule_job",
    "change_job", "text_me", "new_chat", "read_upload",
)
CORE_PROMPT = (
    "You are Ultron.", "About memory", "About confirmations", "About devices",
    "About uploaded files", "About chats", "About texting the user",
)

# show_on_canvas is not in the core: a model with nothing to show it makes things up (asked to order
# a pizza, Qwen3 drew a table of invented pizzerias). It comes with any group, or when the message asks for it.
CANVAS_TOOL = "show_on_canvas"
CANVAS_PROMPT = ("About the canvas",)

GROUPS: tuple[Group, ...] = (
    Group("canvas", r"\bcanvas\b|\btables?\b|\bcharts?\b|\bshow me\b|\bdisplay\b|\bon (the )?screen\b",
          (CANVAS_TOOL,), "", CANVAS_PROMPT),
    Group("gmail", r"\be-?mails?\b|\binbox\b|\bgmail\b|\bunread\b|\bmail from\b", ("find_contact",), "Gmail",
          ("About the user's accounts", "About people")),
    Group("calendar", r"\bcalendar\b|\bmeetings?\b|\bappointments?\b|\bagenda\b|\bbriefing\b|\bwrap-?up\b"
                      r"|\bweekly review\b|\bwhat'?s on\b|\bam i free\b|\bmy (day|schedule)\b|\bevents?\b|\bleave by\b",
          (), "Google Calendar", ("About the calendar",)),
    Group("tasks", r"\bremind\w*\b|\btasks?\b|\bto-?dos?\b|\bticktick\b|\bdue\b|\boverdue\b|\bdeadlines?\b"
                   r"|\bbriefing\b|\bwrap-?up\b|\bweekly review\b",
          (), "TickTick", ("About reminders and tasks",)),
    Group("drive", r"\bdrive\b|\bgoogle docs?\b|\bspreadsheets?\b|\bgoogle sheets?\b", (), "Google Drive", ()),
    Group("vercel", r"\bvercel\b|\bdeploy\w*\b|\bbuilds?\b|\bproduction\b|\bruntime (logs?|errors?)\b", (), "Vercel", (),
          "About Vercel: you can only look things up. For \"did my latest deployment work\" call list_deployments "
          "with limit 1 and no state filter, and say its state (READY, ERROR, BUILDING). Use list_projects for project names."),
    Group("shopify", r"\bshopify\b|\bmy store\b|\borders\b|\bmy orders?\b|\bproducts?\b|\binventory\b|\bsales\b", (), "Shopify", (),
          "About Shopify: you can only look things up (orders, products, stock, sales numbers)."),
    Group("school", r"\bhomework\b|\bassignments?\b|\bexams?\b|\btests?\b|\bquiz\w*\b|\brevis\w+\b|\bsyllabus\b"
                    r"|\btextbook\b|\blectures?\b|\bslides?\b|\bpowerpoint\b|\bteams\b|\ba-?levels?\b",
          ("check_homework", "exam_countdown", "syllabus", "textbook", "lectures", "make_slides", "open_slides"),
          "TickTick", ("About homework", "About revision", "About slides")),
    Group("notes", r"\bnotes?\b|\bobsidian\b|\bvault\b", ("search_notes", "read_note", "write_note", "delete_note"),
          "", ("About notes",)),
    Group("mac", r"\bmac\b|\bbattery\b|\bwi-?fi\b|\bdark mode\b|\bclipboard\b|\btrash\b|\bfolders?\b|\bpython\b"
                 r"|\bcsv\b|\bdisk\b|\bram\b|\bcpu\b",
          ("mac_read", "mac_change", "run_python"), "", ("About this Mac",)),
    Group("pc", r"\bpc\b|\bwindows\b", ("pc_read", "pc_change", "pc_run"), "", ("About the PC",)),
    Group("travel", r"\bmaps?\b|\broutes?\b|\bdirections?\b|\btravel\b|\bflights?\b|\bhow long\b|\bcommute\b|\bnearby\b"
                    r"|\bnear me\b|\bleave\b",
          ("maps", "flights"), "", ("About flights", "About maps and travel")),
    Group("images", r"\bimages?\b|\bpictures?\b|\bphotos?\b|\bdraw\b|\bgenerate\b",
          ("image_search", "image_edit", "image_undo", "image_versions", "generate_image", "image_ai_edit"),
          "", ("About images",)),
    Group("3d", r"\b3d\b|\bblender\b|\bstl\b|\bmodel of\b",
          ("search_3d_library", "show_from_3d_library", "show_3d_asset", "preview_3d", "revert_3d", "get_3d_spec",
           "export_3d"), "", ("About 3D objects",)),
    Group("video", r"\bvideos?\b|\bclips?\b|\bscreen ?record\w*\b", ("generate_video", "capture"), "",
          ("About videos", "About clipping")),
    Group("instagram", r"\binstagram\b|\breels?\b|\bcaption\b|\bstock (footage|clips?|music)\b",
          ("instagram_preview", "instagram_stats", "instagram_comments", "instagram_queue", "instagram_post",
           "instagram_reply", "instagram_schedule", "instagram_cancel", "reel_edit", "stock_search", "stock_download"),
          "", ("About Instagram",)),
    Group("music", r"\bplay\b|\bmusic\b|\bspotify\b|\bsongs?\b|\bplaylists?\b|\bvolume\b|\bpause\b|\bskip\b",
          ("spotify_control", "spotify_playlist_tracks", "phone_volume"), "Spotify", ("About music",)),
    Group("youtube", r"\byoutube\b|\bshorts?\b", ("youtube", "watch_short"), "", ("About YouTube",)),
    Group("amazon", r"\bamazon\b|\bwish ?list\b", ("amazon_read", "amazon_change"), "", ("About Amazon",)),
    Group("github", r"\bgithub\b|\brepos?\b|\bpull requests?\b", ("github",), "", ("About GitHub",)),
    Group("messages", r"\bwhatsapp\b|\bmessage\b", ("whatsapp_send", "find_contact"), "", ("About WhatsApp",)),
    Group("phone", r"\btaxi\b|\bcareem\b|\bfood\b|\bhungry\b", ("phone_taxi", "phone_food"), "", ()),
    Group("tracks", r"\bacc\b|\bassetto\b|\bbraking\b|\b(corner|turn) \d+", ("show_track", "track_info"), "",
          ("About ACC tracks",)),
    Group("voice", r"\bvoice\b|\beleven ?labs\b", ("voice_usage",), "", ('For "how much voice',)),
    Group("terminal", r"\bterminal\b|\bshell\b|\bcommand line\b", ("open_terminal", "read_terminal"), "", ()),
)
BY_NAME = {g.name: g for g in GROUPS}

# What a local model gets of connectors that have too many tools to list (Vercel alone has
# ~180): looking things up and checking status. Everything else of theirs stays hidden.
CONNECTOR_ALLOW: dict[str, set[str]] = {
    "Vercel": {"list_teams", "list_projects", "get_project", "list_deployments", "get_deployment",
               "list_deployment_events", "get_runtime_logs", "get_runtime_errors", "list_domains",
               "get_domain", "get_domain_config", "list_project_domains", "list_aliases",
               "get_active_attack_status", "search_vercel_documentation"},
    "Shopify": {"get-shop-info", "list-orders", "get-order", "get-product", "search_products",
                "get-inventory-levels", "list-customers", "run-analytics-query", "search_collections",
                "get-collection"},
}

_PARAGRAPHS = JARVIS_SYSTEM_PROMPT.split("\n\n")
_COMPILED = {g.name: re.compile(g.words, re.IGNORECASE) for g in GROUPS}


def match(text: str) -> set[str]:
    """The groups whose words appear in this text."""
    return {g.name for g in GROUPS if _COMPILED[g.name].search(text)}


def groups_for_tools(full_names: tuple[str, ...]) -> set[str]:
    """The groups a job's "allow" list needs (the group of each tool it names)."""
    found = set()
    for full in full_names:
        parsed = connectors.parse(full)
        for g in GROUPS:
            if parsed and g.connector.replace(" ", "_") == parsed[0] or full.removeprefix(PREFIX) in g.tools:
                found.add(g.name)
    return found


def _groups(names: set[str]) -> list[Group]:
    return [BY_NAME[n] for n in sorted(names) if n in BY_NAME]


def connectors_for(names: set[str]) -> set[str]:
    """Connectors (lower case, as Claude Code lists them) to switch on. Only ones you allowed."""
    return {g.connector.lower() for g in _groups(names) if g.connector and g.connector.lower() in config.OLLAMA_CONNECTORS}


def tools_for(names: set[str]) -> set[str]:
    """Ultron's own tools (short names) these groups use, plus the core."""
    wanted = set(CORE_TOOLS).union(*(g.tools for g in _groups(names)))
    if names:  # any group may show its results on the canvas
        wanted.add(CANVAS_TOOL)
    return wanted


def visible_tools(names: set[str], background: bool = False, allow: tuple[str, ...] = ()) -> set[str]:
    """Short names of Ultron's tools the model gets. Never ask_expert (Claude Opus). In a
    scheduled job also none that change something, except the ones that job's "allow" list names."""
    wanted = tools_for(names) - {"ask_expert"}
    kinds = {t.tool.name: t for t in registry.TOOLS}
    return {n for n in wanted if n in kinds
            and (not background or kinds[n].kind == "read" or kinds[n].full_name in allow)}


def tool_visible(full_name: str, background: bool, allow: tuple[str, ...]) -> bool:
    """Whether a local model may see this connector tool."""
    if full_name in allow:
        return True
    parsed = connectors.parse(full_name)
    if parsed is None:
        return True
    connector, action = parsed
    if connector in {c.replace(" ", "_") for c in CONNECTOR_ALLOW}:
        return action in CONNECTOR_ALLOW[connector]
    if registry.classify(full_name) == "read":
        return True
    # Everyday connectors may change things in chat (the confirmation gate still asks for
    # anything that reaches other people); a scheduled job only looks.
    return not background and connector in registry.QUIET_CONNECTORS


def system_prompt(names: set[str]) -> str:
    """Ultron's prompt cut down to the core and the parts these groups need."""
    wanted = list(CORE_PROMPT)
    if names:
        wanted.extend(CANVAS_PROMPT)
    for g in _groups(names):
        wanted.extend(g.prompt)
    parts = []
    for p in _PARAGRAPHS:
        if p.startswith(tuple(wanted)):
            parts.append(p.replace("If a task needs deep reasoning, call ask_expert. ", ""))
    return "\n\n".join([
        *parts,
        *(g.note for g in _groups(names) if g.note),
        "About your own tools: you run on a model on the user's computer. You start with a few tools; "
        "more switch on when the user's message mentions what they're for (email, calendar, tasks, "
        "homework, Mac, ...). If you need something you don't have, say what to mention rather than guessing, "
        "and never invent a tool or an answer. Use a tool only when the request needs it. "
        "You cannot order food, book, buy, pay or phone anyone from here. If the request is one of those or "
        "none of your tools fits it, say so in one sentence and offer what you can do instead; do not call "
        "show_on_canvas or any other tool and never make up results. "
        "When a tool returns data, answer from it. Never say you lack access or permission unless the "
        "tool's own result says so.",
    ])
