"""voice_usage: how much of the ElevenLabs voice is left, and how far it has gone (read only).

ElevenLabs counts characters, not Claude tokens. The plan's numbers come from ElevenLabs'
own account endpoint; the replies and average come from storage/voice/voice_usage.jsonl.
Ultron's own Claude tokens over the last 5 hours come from usage.py (the usage panel).
"""

import asyncio
import json
from typing import Any
import urllib.request

from claude_agent_sdk import tool

import config
import usage
from voice import tts


def account() -> dict[str, Any]:
    """The plan's characters: used, limit, and when they reset (unix seconds or None). OSError on failure."""
    req = urllib.request.Request(tts.ELEVEN_URL + "user/subscription", headers={"xi-api-key": config.ELEVEN_KEY})
    with urllib.request.urlopen(req, timeout=15, context=config.ssl_context()) as r:
        data = json.loads(r.read())
    return {"used": data["character_count"], "limit": data["character_limit"],
            "resets": data.get("next_character_count_reset_unix")}


def logged() -> dict[str, Any]:
    """Replies and characters Ultron has spoken through ElevenLabs, from the usage file."""
    try:
        rows = [json.loads(line) for line in tts.USAGE_FILE.read_text(encoding="utf-8").splitlines() if line]
    except OSError:
        rows = []
    replies = [r for r in rows if r["kind"] == "reply"]
    eleven = [r for r in replies if r["engine"] == "elevenlabs"]
    fallbacks = sum(1 for r in rows if r["engine"] == "kokoro-fallback")
    chars = sum(r["chars"] for r in eleven)
    return {"replies": len(replies), "eleven_replies": len(eleven), "eleven_chars": chars,
            "avg_chars": round(chars / len(eleven)) if eleven else 0, "fallbacks": fallbacks}


def _text() -> str:
    stats = logged()
    lines = [f"Voice: {'ElevenLabs' if tts.eleven_ready() else 'Kokoro (ElevenLabs is off)'}.",
             f"Replies spoken so far: {stats['replies']}, {stats['eleven_replies']} by ElevenLabs."]
    if stats["eleven_replies"]:
        lines.append(f"Average ElevenLabs reply: {stats['avg_chars']} characters.")
    if stats["fallbacks"]:
        lines.append(f"Sentences Kokoro said because ElevenLabs failed: {stats['fallbacks']}."
                     + (f" Last reason: {tts.last_error}" if tts.last_error else ""))
    if tts.eleven_ready():
        try:
            acc = account()
            left = acc["limit"] - acc["used"]
            lines.append(f"ElevenLabs plan: {acc['used']:,} of {acc['limit']:,} characters used, {left:,} left.")
            if stats["avg_chars"]:
                lines.append(f"About {left // stats['avg_chars']} more replies at that average.")
            if acc["resets"]:
                lines.append(f"Resets {acc['resets']}.")
        except (OSError, KeyError, ValueError) as e:
            lines.append(f"Couldn't read the ElevenLabs plan: {e}")
    tokens = usage.snapshot("claude", 0)["tokens"]
    lines.append("Ultron's Claude tokens in the last 5 hours: "
                 f"{tokens['input']:,} input, {tokens['output']:,} output, "
                 f"{tokens['cache_read']:,} read from cache.")
    return "\n".join(lines)


@tool(
    "voice_usage",
    "How much of Ultron's ElevenLabs voice is left: characters used and left on the plan, the "
    "replies spoken, the average reply, and roughly how many replies are left. Also Ultron's "
    "Claude tokens over the last 5 hours. Read only.",
    {"type": "object", "properties": {}},
)
async def voice_usage(args: dict[str, Any]) -> dict[str, Any]:
    text = await asyncio.to_thread(_text)
    return {"content": [{"type": "text", "text": text}]}
