"""The look of the page for this chat: Ultron's own CSS on top of the standard look.

Ultron changes it with the change_ui tool; the page applies it (ui.layout event). It lives
only as long as the chat: a new chat, a loaded chat or a brain switch put the standard look
back (agent.new_conversation), and so does the reset button in the top bar.
"""

import re

MAX_CSS = 30_000

css = ""  # the custom style sheet for this chat; "" = the standard look

# What a style sheet may not do. Plain CSS can restyle and move anything on the page; it must not
# load things from elsewhere or run code. (The page also keeps the top bar and the approval cards
# on screen whatever this says.)
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_BANNED = [
    (re.compile(r"@import", re.I), "@import"),
    (re.compile(r"url\s*\(\s*(?!['\"]?data:image/)", re.I), "url() (only data:image/ is allowed)"),
    (re.compile(r"expression\s*\(|javascript:|behaviou?r\s*:|-moz-binding", re.I), "scripts"),
    (re.compile(r"<"), "'<'"),
]


def check(sheet: str) -> str | None:
    """Why this style sheet can't be used, or None if it can."""
    bare = _COMMENT.sub("", sheet)
    for pattern, what in _BANNED:
        if pattern.search(bare):
            return f"Style sheets may not use {what}."
    if bare.count("{") != bare.count("}"):
        return "Unbalanced braces: every { needs a }."
    return None


def apply(sheet: str, replace: bool = False) -> str | None:
    """Add to the custom look (or replace it). Returns the problem, or None if it is applied."""
    sheet = _COMMENT.sub("", sheet).strip()
    if problem := check(sheet):
        return problem
    global css
    new = sheet if replace else f"{css}\n{sheet}".strip()
    if len(new) > MAX_CSS:
        return f"The style sheet would be {len(new)} characters; the limit is {MAX_CSS}. Use replace to start it again, shorter."
    css = new
    return None


def reset() -> bool:
    """Back to the standard look. True if there was a custom look to remove."""
    global css
    was, css = bool(css), ""
    return was


def layout(width: int, height: int, voice: bool = False) -> str:
    """Which of the page's layouts a window that size gets (the breakpoints in App.css)."""
    if width <= 800 or height <= 500:
        kind = "phone layout: one pane at a time (chat, canvas or status), switched by the bar at the bottom"
    elif width <= 1200:
        kind = "narrow desktop layout: chat and canvas side by side, the status panels underneath"
    else:
        kind = "wide desktop layout: chat | core and canvas | status"
    return kind + (", in voice mode" if voice else "")


def screen_note(raw: object) -> str:
    """What the page said about its window, as a short note for the [Device: ...] line,
    or "" if it sent nothing usable."""
    if not isinstance(raw, dict):
        return ""
    try:
        w, h = int(raw["w"]), int(raw["h"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not (100 <= w <= 20_000 and 100 <= h <= 20_000):
        return ""
    note = f"; page window {w}x{h} px, {layout(w, h, raw.get('voice') is True)}"
    try:
        sw, sh, ratio = int(raw["sw"]), int(raw["sh"]), float(raw["dpr"])
        if 100 <= sw <= 20_000 and 100 <= sh <= 20_000 and 0.5 <= ratio <= 8:
            note += f"; display {sw}x{sh}, pixel ratio {ratio:g}"
    except (KeyError, TypeError, ValueError):
        pass
    return note
