"""Runs the watches (storage/watch_store.py): "notify me when X responds".

Every minute: one read-only look at the Gmail inbox (mail_text.headers, over IMAP) and/or WhatsApp
desktop's database (whatsapp_read.py) for the channels that have watches (no model, so
no Pro limit used and no 15-minute minimum), then each new mail that matches a watch goes to
notify.route: an open Ultron page if there is one, otherwise Telegram.

Only mail that arrived after the watch was made counts. Mail is other people's words: only its
sender and subject are shown, and nothing in it is ever followed as an instruction.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import mail_text
import notify
import whatsapp_read
from storage import watch_store

log = logging.getLogger("ultron.watcher")

CHECK_EVERY_S = 60


def hits(watch: dict, mails: list[dict]) -> list[dict]:
    """The mails that answer this watch: from `who`, with the thread words in the subject,
    sent after the watch was made, and not told before. Oldest first."""
    who, words = watch["who"].lower(), watch["subject"].lower()
    number = whatsapp_read.digits(watch["who"]) if watch.get("channel") == "whatsapp" else ""
    found = [m for m in mails
             if (who in m["from"].lower() or (len(number) >= 6 and number in whatsapp_read.digits(m["from"])))
             and words in m["subject"].lower()
             and m["sent"] >= watch["created"] and m["id"] not in watch["notified"]]
    return sorted(found, key=lambda m: m["sent"])


async def _source(channel: str, items: list[dict]) -> list[dict] | None:
    """New messages that could answer the watches on this channel; None if it can't be read right now."""
    mine = [w for w in items if w.get("channel", "email") == channel]
    if not mine:
        return None
    since = min(w["created"] for w in mine)
    if channel == "whatsapp":
        return await asyncio.to_thread(whatsapp_read.messages, since)
    if not mail_text.configured():
        return None
    return await asyncio.to_thread(mail_text.headers, datetime.fromtimestamp(since) - timedelta(days=1))


async def check() -> None:
    items = watch_store.watches()
    for channel in watch_store.CHANNELS:
        try:
            mails = await _source(channel, items)
        except RuntimeError as e:  # this channel can't be read now: the other still runs
            log.warning("Watch check (%s) failed: %s", channel, e)
            continue
        if mails is None:
            continue
        for watch in (w for w in items if w.get("channel", "email") == channel):
            await _tell(watch, hits(watch, mails))


async def _tell(watch: dict, found: list[dict]) -> None:
    if not found:
        return
    latest = found[-1]
    if watch.get("channel") == "whatsapp":  # who and how many; never the text
        text = f"New WhatsApp message from {latest['from']}" + (f" ({len(found)} new)" if len(found) > 1 else "")
    else:
        text = f"{latest['from']} wrote: {latest['subject'] or '(no subject)'}"
        if len(found) > 1:
            text += f" (and {len(found) - 1} more)"
    try:
        await notify.route(f"{watch['who']} responded", text)
    except RuntimeError as e:
        log.warning("Watch %s hit but couldn't tell you: %s", watch["id"], e)
        return  # not marked: it tries again next minute
    watch_store.mark_notified(watch["id"], [m["id"] for m in found], watch["once"])


async def loop() -> None:
    """Started with the server; runs until it's cancelled at shutdown."""
    while True:
        try:
            await check()
        except RuntimeError as e:  # Gmail unreachable: try again next time
            log.warning("Watch check failed: %s", e)
        except Exception:
            log.exception("Watch check failed")
        await asyncio.sleep(CHECK_EVERY_S)
