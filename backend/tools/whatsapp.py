"""WhatsApp: send a message from the WhatsApp app on this Mac. (act: asks you first)

To a person (by number) or to a group chat (by name). A group has no link that opens it, so Ultron
searches for the group's name, finds the result by reading the screen, clicks it, checks the chat's title
and only then types the message (tools/whatsapp_ui.py).
A group with exactly the given name is used; otherwise the matches come back, nothing is
sent and the user is asked (never guessed). WhatsApp can be anywhere (a picture open, another tab):
Ultron first gets back to the chat list. After sending, the Mac's WhatsApp database is read (read-only) to confirm the message landed
in that group.

WhatsApp has no API for personal accounts, and unofficial "linked device" libraries can
get a number banned. So Ultron uses the app itself: WhatsApp's own whatsapp://send link
opens the chat with the message typed in (it only loads chats while it's in front, so it
can't be done in the background). Ultron waits for the chat to load, presses Enter, then
hides WhatsApp and switches back to the app you were in (the browser with Ultron). It only
presses Enter while WhatsApp is the frontmost app, so the key can't land anywhere else.

Pressing keys needs macOS Accessibility permission for Ultron (System Settings →
Privacy & Security → Accessibility). Reading is separate: tools/whatsapp_inbox.py.
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Callable
from typing import Any
import time
from urllib.parse import quote

from claude_agent_sdk import tool

import whatsapp_read
from tools import whatsapp_groups, whatsapp_ui

FRONT_APP = ('tell application "System Events" to get bundle identifier of first application process '
             'whose frontmost is true')
WHATSAPP_ID = "net.whatsapp.WhatsApp"
HIDE = 'tell application "System Events" to set visible of process "WhatsApp" to false'
PRESS_ENTER = 'tell application "System Events" to key code 36'
# ponytail: fixed wait for the chat to load once WhatsApp is in front (Ultron can't see when
# "Loading chat" is done); raise it if messages stay typed but unsent.
CHAT_LOAD_S = 2.5
SENT_S = 1.0  # after Enter, so the send goes out before WhatsApp is hidden
OPEN_TIMEOUT_S = 15
# Group chats (tried on the live app): Cmd+F focuses WhatsApp's chat search, Cmd+A replaces what it kept.
SEARCH = 'tell application "System Events" to keystroke "f" using command down'
ESCAPE = 'tell application "System Events" to key code 53'
SELECT_ALL = 'tell application "System Events" to keystroke "a" using command down'
TYPE_TEXT = 'on run argv\ntell application "System Events" to keystroke (item 1 of argv)\nend run'
SEARCH_S = 2.0  # for the search results to appear, and for the chat to open after the click
CONFIRM_S = 6  # how long to look for the sent message in WhatsApp's database
MAX_GROUP_MESSAGE = 1000


def phone_digits(phone: str) -> str | None:
    """'+90 532 138 20 11' -> '905321382011'. None without a country code or if it isn't a number."""
    raw = phone.strip()
    digits = re.sub(r"[\s\-().]", "", raw)
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    else:
        return None  # "0532…" or "532…": WhatsApp needs the country code
    return digits if re.fullmatch(r"[1-9]\d{6,14}", digits) else None


async def _run(*cmd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
    if proc.returncode:
        msg = err.decode().strip()
        if "1002" in msg or "-1719" in msg or "not allowed" in msg.lower():
            msg = ("macOS didn't allow Ultron to press keys. Allow it in System Settings → "
                   "Privacy & Security → Accessibility.")
        raise RuntimeError(msg or f"{cmd[0]} failed")
    return out.decode().strip()


async def _whatsapp_in_front() -> bool:
    return await _run("osascript", "-e", FRONT_APP) == WHATSAPP_ID


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _find_group(group_id: str, name: str) -> tuple[dict | None, str]:
    """(the group to send to, '') or (None, why not / the question to ask the user). The group must be
    exactly the one the approval card names: an id has to match its name, a bare name has to be the only
    group containing it."""
    try:
        found = whatsapp_read.groups("" if group_id else name)
    except RuntimeError as e:
        return None, f"Couldn't look up WhatsApp groups: {e}."
    if group_id:
        group = next((g for g in found if g["id"] == group_id), None)
        if group is None:
            return None, "No WhatsApp group has that id; not sent. Look it up again by name."
        if not _same(group["name"], name):
            return None, (f"That id is the group {group['name']!r}, not {name!r}; not sent. "
                          "Pass the group's exact name with its id.")
        return group, ""
    if not found:
        return None, f"No WhatsApp group has {name!r} in its name; not sent."
    exact = [g for g in found if _same(g["name"], name)]
    if len(exact) == 1:  # "Rain" is the group called Rain, whatever else has "Rain" in its name
        return exact[0], ""
    options = "; ".join(f"{g['name']!r} (group_id {g['id']})" for g in found[:10])
    return None, (f"NOT SENT. {len(found)} group(s) match {name!r}: {options}. Don't guess: ask the user which "
                  "one, then call whatsapp_send again with that group's exact name and its group_id.")


async def _send_to_group(group: dict, message: str, said: str = "") -> dict[str, Any]:
    if "\n" in message or len(message) > MAX_GROUP_MESSAGE:
        return _text(f"A group message must be one line of at most {MAX_GROUP_MESSAGE} characters; not sent.", True)
    started = time.time()
    try:
        back_to = await _run("osascript", "-e", FRONT_APP)
        await _run("open", "-b", WHATSAPP_ID)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + OPEN_TIMEOUT_S
        while not await _whatsapp_in_front():
            if loop.time() > deadline:
                return _text("WhatsApp didn't open; the message was not sent.", True)
            await asyncio.sleep(0.5)
        await asyncio.sleep(CHAT_LOAD_S)
        async def key(*script: str) -> None:
            # Every key press only goes ahead while WhatsApp is in front, so none lands in another app.
            if not await _whatsapp_in_front():
                raise RuntimeError("WhatsApp lost focus; stopped before sending")
            await _run("osascript", "-e", *script)

        # WhatsApp's search results ignore the keyboard: look at the screen, click the row whose title is
        # exactly the group's name, and read the chat's title before typing anything.
        x, y, w, h = await whatsapp_ui.window()

        async def escape() -> None:
            await key(ESCAPE)

        await whatsapp_ui.show_chat_list((x, y, w, h), escape, _whatsapp_in_front)  # from anywhere in the app
        await key(SEARCH)
        await key(SELECT_ALL)  # the search box keeps the last search
        await key(TYPE_TEXT, group["name"])
        await asyncio.sleep(SEARCH_S)
        row = whatsapp_ui.chat_row(await whatsapp_ui.read_screen((x, y, w, h)), group["name"])
        if row is None:
            return _text(f"Searched WhatsApp but didn't see a chat named exactly {group['name']!r} in the results; "
                         "nothing was sent.", True)
        if not await _whatsapp_in_front():
            raise RuntimeError("WhatsApp lost focus; stopped before sending")
        await whatsapp_ui.click(x + row[0], y + row[1])
        await asyncio.sleep(SEARCH_S)
        title = whatsapp_ui.chat_title(await whatsapp_ui.read_screen((x, y, w, h)))
        if not whatsapp_ui.title_is(title, group["name"]):
            return _text(f"Clicked a chat but its title reads {title!r}, not {group['name']!r}; nothing was typed or sent.", True)
        await key(TYPE_TEXT, message)  # the message box has focus once the chat opens
        await key(PRESS_ENTER)
        confirmed = False
        for _ in range(int(CONFIRM_S / 0.5) + 1):
            if confirmed := whatsapp_read.sent_after(group["id"], message, started):
                break
            await asyncio.sleep(0.5)
        if back_to != WHATSAPP_ID:
            await _return_to(back_to)
    except (RuntimeError, OSError, TimeoutError) as e:
        return _text(f"WhatsApp: {e}. The message may be typed somewhere but not sent.", True)
    if confirmed:
        note = whatsapp_groups.remember_alias(said, group["name"]) if said else ""
        if note:
            try:  # keep the memory panel in open tabs up to date
                import hub
                import memory_panel
                await hub.emit(memory_panel.event())
            except Exception:
                pass
        return _text(f"Sent to the group {group['name']!r} (confirmed in WhatsApp).{note}")
    return _text(f"Pressed Send for the group {group['name']!r}, but the message did not show up in that group's chat. "
                 "Tell the user to check WhatsApp: it may be unsent, or have gone to a different chat.", True)


async def _return_to(back_to: str) -> None:
    await asyncio.sleep(SENT_S)
    await _run("osascript", "-e", HIDE)
    if re.fullmatch(r"[\w.-]+", back_to):
        await _run("open", "-b", back_to)


@tool(
    "whatsapp_send",
    "Send a WhatsApp message from the WhatsApp app on this Mac, to a person or to a group chat. "
    "For a person: look them up with find_contact first and pass their mobile number with the country "
    "code. For a group: call whatsapp_groups first with the user's words (they don't have to say the exact "
    "name), then pass the group's exact name and group_id it gives, plus said = the user's words. "
    "Without a group_id the name must be exactly one group's name or nothing is sent. The user approves the exact message and the target before it's sent. "
    "Can't read messages (use whatsapp_messages).",
    {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Who it's for, as the user knows them (e.g. 'Mom'). Not for groups."},
            "phone": {"type": "string", "description": "Their number with country code, e.g. +90 532 138 20 11."},
            "group": {"type": "string", "description": "A group chat's name, e.g. 'Rain'. Instead of phone."},
            "group_id": {"type": "string", "description": "The group's id, from whatsapp_groups."},
            "said": {"type": "string", "description": "The user's own words for the group, if not its exact name ('the boys'): remembered after sending."},
            "message": {"type": "string", "description": "The exact text to send."},
        },
        "required": ["message"],
    },
)
async def whatsapp_send(args: dict[str, Any]) -> dict[str, Any]:
    message = str(args.get("message") or "").strip()
    phone, group = str(args.get("phone") or "").strip(), " ".join(str(args.get("group") or "").split())
    if not message:
        return _text("The message is empty; not sent.", True)
    if bool(phone) == bool(group):
        return _text("Say who it's for: either a phone number or a group name, not both; not sent.", True)
    if group:
        target, why = _find_group(str(args.get("group_id") or "").strip(), group)
        return await _send_to_group(target, message, str(args.get("said") or "")) if target else _text(why, not why.startswith("NOT SENT"))
    digits = phone_digits(phone)
    if not digits:
        return _text("That number has no country code (e.g. +90 or +971); not sent.", True)
    try:
        back_to = await _run("osascript", "-e", FRONT_APP)  # usually the browser with Ultron
        await _run("open", f"whatsapp://send?phone={digits}&text={quote(message)}")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + OPEN_TIMEOUT_S
        while not await _whatsapp_in_front():
            if loop.time() > deadline:
                return _text("WhatsApp didn't open; the message was not sent.", True)
            await asyncio.sleep(0.5)
        await asyncio.sleep(CHAT_LOAD_S)
        if not await _whatsapp_in_front():
            return _text("WhatsApp lost focus before sending; the message was not sent. "
                         "It may still be typed in the chat.", True)
        await _run("osascript", "-e", PRESS_ENTER)
        if back_to != WHATSAPP_ID:
            await _return_to(back_to)
    except (RuntimeError, OSError, TimeoutError) as e:
        return _text(f"WhatsApp: {e}. The message may be typed in the chat but not sent.", True)
    return _text(f"Pressed Send in WhatsApp for {args.get('to') or digits}. "
                 "Ultron can't read the chat, so it can't confirm delivery.")
