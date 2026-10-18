"""watch_for_reply / list_watches / stop_watch: "notify me when X responds".

A watch is a rule in storage/watch_store.py, checked every minute by watcher.py without a
model. When it hits, notify.route tells the user in an open Ultron page, or by Telegram when
none is open. Email and WhatsApp (new-message notices only) can be watched. Adding and
stopping are 'act' (a scheduled job can't add them); listing only reads.
"""

import json
from typing import Any

from claude_agent_sdk import tool

import mail_text
import whatsapp_read
from storage import watch_store


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


@tool(
    "watch_for_reply",
    "Notify the user when someone responds: 'tell me when Sarah replies', 'let me know when "
    "the landlord emails'. Watches incoming email from a person (name or address), optionally "
    "only a thread (words from its subject). Checked every minute without using any limit; the "
    "user is told in the open Ultron page, or by Telegram if none is open. channel 'email' "
    "(default) or 'whatsapp' (new WhatsApp messages from a contact's name or phone number; the "
    "message text is never read, only that one came). SMS/iMessage can't be read: say so if asked. "
    "Stops after the first hit unless once=false.",
    {
        "type": "object",
        "properties": {
            "who": {"type": "string", "description": "Name or email address of the sender to wait for."},
            "channel": {"type": "string", "enum": list(watch_store.CHANNELS), "description": "Where to wait. Default email."},
            "subject": {"type": "string", "description": "Words that must be in the subject (a thread). Optional."},
            "once": {"type": "boolean", "description": "Stop after the first notification (default true)."},
        },
        "required": ["who"],
    },
)
async def watch_for_reply(args: dict[str, Any]) -> dict[str, Any]:
    channel = str(args.get("channel") or "email")
    if channel == "whatsapp":
        if why := whatsapp_read.available():
            return _text(f"WhatsApp can't be watched yet: {why} Not set up.", True)
    elif not mail_text.configured():
        return _text("Email can't be watched yet: GMAIL_ADDRESS and GMAIL_APP_PASSWORD aren't set in .env "
                     "(steps in .env.example). Not set up.", True)
    try:
        watch = watch_store.add(args.get("who") or "", args.get("subject") or "", args.get("once") is not False, channel)
    except ValueError as e:
        return _text(str(e), True)
    return _text(f"Watching as {watch['id']}: {watch_store.describe(watch)}. "
                 "I'll tell you here if Ultron is open, otherwise by Telegram.")


@tool(
    "list_watches",
    "List what Ultron is watching for ('tell me when X replies') (read-only).",
    {"type": "object", "properties": {}},
)
async def list_watches(args: dict[str, Any]) -> dict[str, Any]:
    items = [{"id": w["id"], "watching": watch_store.describe(w)} for w in watch_store.watches()]
    return _text(json.dumps(items, ensure_ascii=False) if items else "Nothing is being watched.")


@tool(
    "stop_watch",
    "Stop a watch by its id (watch_2). Find the id with list_watches first.",
    {"type": "object", "properties": {"watch_id": {"type": "string", "description": "e.g. watch_2"}},
     "required": ["watch_id"]},
)
async def stop_watch(args: dict[str, Any]) -> dict[str, Any]:
    try:
        watch = watch_store.remove(str(args.get("watch_id") or ""))
    except KeyError:
        return _text(f"There's no watch {args.get('watch_id')!r}.", True)
    return _text(f"Stopped watching for {watch_store.describe(watch)}.")
