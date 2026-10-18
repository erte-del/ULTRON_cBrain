"""Reaching you when you're not looking at the chat.

One notification goes three ways:
  - the open Ultron tabs (it appears in the chat),
  - a macOS notification on this Mac,
  - a text to your phone from Ultron's Telegram bot, if it's set up (.env.example).

Ultron's conversation didn't write these (a scheduled job did), so the next message you
send carries them along (`take_unseen`): "reply to that tonight" then means something.
"""

import asyncio
import logging
import time

import events
import hub
from tools import telegram

log = logging.getLogger("ultron.notify")

MAC_CHARS = 240  # a banner shows about this much
MAX_UNSEEN = 5

# The text reaches the script as arguments, never pasted into its source.
MAC_SCRIPT = 'on run argv\ndisplay notification (item 1 of argv) with title (item 2 of argv) sound name "Glass"\nend run'

_unseen: list[str] = []


async def _mac(title: str, text: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", MAC_SCRIPT, text[:MAC_CHARS], title,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    if await asyncio.wait_for(proc.wait(), timeout=10):
        raise OSError("osascript couldn't show the notification")


async def push(title: str, text: str) -> None:
    """Tell the user something. A channel that fails is logged, never raised."""
    _unseen.append(f"{title}: {text}")
    del _unseen[:-MAX_UNSEEN]
    await hub.emit(events.notification(title, text, time.time()))
    try:
        await _mac(title, text)
    except (OSError, TimeoutError):
        log.warning("macOS notification failed", exc_info=True)
    if telegram.configured():
        try:
            await asyncio.to_thread(telegram.send_text, f"{title}\n\n{text}")
        except RuntimeError as e:  # never includes the bot token
            log.warning("Telegram notification failed: %s", e)


async def route(title: str, text: str) -> str:
    """Tell the user something they asked to hear ("notify me when X replies"): in an open
    Ultron page if there is one (a toast and a chat message), otherwise by Telegram.
    Returns where it went: "ui", "telegram" or "mac" (no page open and no Telegram: a banner on
    this Mac, so it isn't lost). RuntimeError if nothing could carry it."""
    _unseen.append(f"{title}: {text}")
    del _unseen[:-MAX_UNSEEN]
    if await hub.emit(events.notification(title, text, time.time())):
        return "ui"
    if telegram.configured():
        try:
            await asyncio.to_thread(telegram.send_text, f"{title}\n\n{text}")
            return "telegram"
        except RuntimeError as e:  # never includes the bot token
            log.warning("Telegram notification failed: %s", e)
    try:
        await _mac(title, text)
        return "mac"
    except (OSError, TimeoutError):
        raise RuntimeError("no Ultron page is open, Telegram isn't working, and the Mac banner failed") from None


async def text_only(title: str, text: str) -> None:
    """Text the user's phone and nothing else (no banner, no chat card), for Ultron's own
    check-ins (initiative.py). Ultron still hears about it with the next message.
    RuntimeError (with the reason) if it didn't go."""
    if not telegram.configured():
        raise RuntimeError("Telegram isn't set up")
    await asyncio.to_thread(telegram.send_text, f"{title}\n\n{text}" if title else text)
    _unseen.append(f"{title}: {text}" if title else text)
    del _unseen[:-MAX_UNSEEN]


def take_unseen() -> list[str]:
    """Notifications since the user's last message, for Ultron's conversation to know about."""
    seen = _unseen[:]
    _unseen.clear()
    return seen
