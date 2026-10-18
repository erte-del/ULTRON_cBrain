"""WhatsApp: send a message from the WhatsApp app on this Mac. (act: asks you first)

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
from urllib.parse import quote

from claude_agent_sdk import tool

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


@tool(
    "whatsapp_send",
    "Send a WhatsApp message from the WhatsApp app on this Mac. Look the person up with "
    "find_contact first and use their mobile number with the country code. The user "
    "approves the exact message before it's sent. Can't read messages.",
    {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Who it's for, as the user knows them (e.g. 'Mom')."},
            "phone": {"type": "string", "description": "Their number with country code, e.g. +90 532 138 20 11."},
            "message": {"type": "string", "description": "The exact text to send."},
        },
        "required": ["to", "phone", "message"],
    },
)
async def whatsapp_send(args: dict[str, Any]) -> dict[str, Any]:
    digits = phone_digits(str(args.get("phone") or ""))
    message = str(args.get("message") or "").strip()
    if not digits:
        return _text("That number has no country code (e.g. +90 or +971); not sent.", True)
    if not message:
        return _text("The message is empty; not sent.", True)
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
            await asyncio.sleep(SENT_S)
            await _run("osascript", "-e", HIDE)
            if re.fullmatch(r"[\w.-]+", back_to):
                await _run("open", "-b", back_to)
    except (RuntimeError, OSError, TimeoutError) as e:
        return _text(f"WhatsApp: {e}. The message may be typed in the chat but not sent.", True)
    return _text(f"Pressed Send in WhatsApp for {args.get('to') or digits}. "
                 "Ultron can't read the chat, so it can't confirm delivery.")
