"""Seeing and clicking WhatsApp's window, for sending to a group. Mac only.

WhatsApp's search results ignore the keyboard and its window hides its contents from the accessibility
tree, so Ultron looks at a screenshot instead: macOS's own text recognition (scripts/wa_ocr.swift,
nothing leaves this Mac) finds the row whose title is exactly the group's name, a real mouse click opens
it, and the chat's title is read again before anything is typed.

Needs Accessibility (key presses, clicks) and Screen Recording (screenshots) for the app that starts the
backend, and Xcode's command line tools (`swiftc`, once, to build the text reader).
"""

import asyncio
import re
from pathlib import Path

import config

OCR_SOURCE = config.ROOT_DIR / "scripts" / "wa_ocr.swift"
OCR_BIN = config.STORAGE_DIR / "bin" / "wa_ocr"
CLICK_SCRIPT = config.ROOT_DIR / "scripts" / "mouse_click.js"
SHOT = config.STORAGE_DIR / "bin" / "wa_window.png"

# WhatsApp's layout in points from the window's top-left: the chat list is the pane from LIST_X0 to LIST_X1;
# the open chat's title is at the top of the pane to its right.
LIST_X0, LIST_X1, TITLE_X0, TITLE_Y1 = 235, 610, 640, 85
SECTIONS = {"chats", "contacts", "groups", "media", "messages", "links", "documents", "photos"}

Line = tuple[float, float, float, float, str]  # x0, y0, x1, y1 in points from the window's top-left, text


def norm(text: str) -> str:
    """Letters and digits only, any case: how names are compared (OCR drops emoji and bends punctuation)."""
    return re.sub(r"[\W_]", "", text.casefold())


async def _exec(*cmd: str, timeout: float = 60) -> str:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"{Path(cmd[0]).name} took too long") from None
    if proc.returncode:
        msg = err.decode(errors="replace").strip()
        if "not allowed" in msg.lower() or "1002" in msg or "could not create image" in msg.lower():
            msg = ("macOS didn't allow Ultron to look at or click WhatsApp. Allow the app that starts the backend "
                   "under System Settings → Privacy & Security → Accessibility and Screen Recording.")
        raise RuntimeError(msg or f"{Path(cmd[0]).name} failed")
    return out.decode(errors="replace").strip()


UNMINIMIZE = ('tell application "System Events" to tell process "WhatsApp" to '
              'try\nset value of attribute "AXMinimized" of window 1 to false\nend try')
POSITION = 'tell application "System Events" to tell process "WhatsApp" to get (position of window 1) & (size of window 1)'


async def window() -> tuple[int, int, int, int]:
    """WhatsApp's window: x, y, width, height in screen points. Brings it back if it was minimized or
    closed (opening the app again makes a new window)."""
    for attempt in range(12):
        try:
            x, y, w, h = (int(float(n)) for n in (await _exec("osascript", "-e", POSITION)).split(","))
            if w > 400 and h > 300:
                return x, y, w, h
        except (RuntimeError, ValueError):
            pass
        if attempt in (0, 4):
            await _exec("osascript", "-e", UNMINIMIZE)
            await _exec("open", "-b", "net.whatsapp.WhatsApp")
        await asyncio.sleep(0.5)
    raise RuntimeError("couldn't find WhatsApp's window")


async def _ocr_binary() -> Path:
    if not OCR_BIN.exists() or OCR_BIN.stat().st_mtime < OCR_SOURCE.stat().st_mtime:
        OCR_BIN.parent.mkdir(parents=True, exist_ok=True)
        await _exec("swiftc", "-O", "-o", str(OCR_BIN), str(OCR_SOURCE), timeout=300)
    return OCR_BIN


def parse_ocr(output: str, width: int, height: int) -> list[Line]:
    lines = []
    for row in output.splitlines():
        box, _, text = row.partition("\t")
        try:
            x0, y0, x1, y1 = (float(n) for n in box.split())
        except ValueError:
            continue
        lines.append((x0 * width, y0 * height, x1 * width, y1 * height, text.strip()))
    return lines


async def read_screen(rect: tuple[int, int, int, int]) -> list[Line]:
    """The text in WhatsApp's window right now, with where it is."""
    x, y, w, h = rect
    SHOT.parent.mkdir(parents=True, exist_ok=True)
    await _exec("screencapture", "-x", "-o", "-R", f"{x},{y},{w},{h}", str(SHOT))
    return parse_ocr(await _exec(str(await _ocr_binary()), str(SHOT)), w, h)


def chat_row(lines: list[Line], name: str) -> tuple[float, float] | None:
    """Where to click (points from the window's top-left) for the chat named exactly `name` under the
    "Chats" heading of the search results. None if it isn't there, or two rows have that name."""
    pane = [ln for ln in lines if LIST_X0 <= ln[0] < LIST_X1]
    heads = sorted((ln for ln in pane if ln[0] < 300 and ln[1] > 120 and norm(ln[4]) in SECTIONS), key=lambda ln: ln[1])
    start = next((ln for ln in heads if norm(ln[4]) == "chats"), None)
    if start is None:
        return None
    end = next((ln[1] for ln in heads if ln[1] > start[1]), float("inf"))
    want = norm(name)
    rows = [ln for ln in pane if start[3] < ln[1] < end and ln[0] >= 300 and want and norm(ln[4]) == want]
    if len(rows) != 1:
        return None
    ln = rows[0]
    return LIST_X0 + 100, ln[1] + 10


def chats_tab(lines: list[Line]) -> tuple[float, float] | None:
    """The "Chats" button in the sidebar (text recognition may put a stray character before the word)."""
    found = [ln for ln in lines if ln[0] < 225 and 30 < ln[1] < 120 and norm(ln[4]).endswith("chats")]
    return (60, (found[0][1] + found[0][3]) / 2) if found else None


def on_chat_list(lines: list[Line]) -> bool:
    """The Chats tab is showing: its title is at the top of the list pane."""
    return any(LIST_X0 <= ln[0] < LIST_X1 and ln[1] < 60 and norm(ln[4]) == "chats" for ln in lines)


async def show_chat_list(rect, press_escape, in_front) -> None:
    """Get WhatsApp to its chat list from wherever it is: a picture or video open full screen, a dialog,
    the Updates, Communities, Calls or Media tab, a chat with the search open. No sidebar on screen
    (a picture or call fills the window): Escape closes it. Otherwise click "Chats". `press_escape` and
    `in_front` are Ultron's own key press and "is WhatsApp in front?" check, so nothing goes to another app."""
    x, y = rect[:2]
    for _ in range(6):
        lines = await read_screen(rect)
        tab = chats_tab(lines)
        if tab is None:
            if not await in_front():
                raise RuntimeError("WhatsApp lost focus")
            await press_escape()
            await asyncio.sleep(1)
            continue
        if on_chat_list(lines) and not any(norm(ln[4]) in {"archived", "starredmessages"} for ln in lines if ln[1] < 60):
            return
        if not await in_front():
            raise RuntimeError("WhatsApp lost focus")
        await click(x + tab[0], y + tab[1])
        await asyncio.sleep(1)
        if on_chat_list(await read_screen(rect)):
            return
        await press_escape()  # something else is open over the list
        await asyncio.sleep(1)
    raise RuntimeError("couldn't get WhatsApp back to its chat list")


def chat_title(lines: list[Line]) -> str:
    """The title of the open chat: the top line of the pane right of the chat list."""
    header = sorted((ln for ln in lines if ln[0] >= TITLE_X0 and ln[1] < TITLE_Y1), key=lambda ln: ln[1])
    return header[0][4] if header else ""


def title_is(title: str, name: str) -> bool:
    """The header shows the group's name (a long one may be cut off with '…')."""
    have, want = norm(title), norm(name)
    return bool(want) and (have == want or (title.rstrip().endswith(("…", "...")) and want.startswith(have) and len(have) >= 4))


async def click(x: float, y: float) -> None:
    """A real mouse click at a screen point (WhatsApp ignores accessibility clicks)."""
    await _exec("osascript", "-l", "JavaScript", str(CLICK_SCRIPT), str(round(x)), str(round(y)))
