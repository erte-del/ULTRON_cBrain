"""The user's Android phone, through MacroDroid macros on it. (read: only their phone)

A web page can't touch the phone, so MacroDroid macros do it: Ultron calls a macro's webhook
(through MacroDroid's server) and the macro acts. Setup is in .env.example (MACRODROID_WEBHOOK).
  phone_volume  jarvis_volume?volume_level=N   sets the media volume to N.
  phone_taxi    jarvis_careem?taxi_to=<place>  copies the place and opens Careem. The user
                pastes it into "Where to?" and books: Careem has no API, and its deep links
                aren't documented, so Ultron never books or pays.
  phone_food    the same macro, with a restaurant or dish copied instead: they open Food and
                paste it into search. Careem Food has no website either, so Ultron finds the
                options with web search and maps first, and the user orders and pays.
"""

import asyncio
import subprocess
from typing import Any
from urllib.parse import urlencode

from claude_agent_sdk import tool

import config

BASE = "https://trigger.macrodroid.com/"


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def url_for(identifier: str, **params: Any) -> str:
    """The address of the macro whose webhook identifier this is. ValueError if MACRODROID_WEBHOOK
    isn't set up. Each query parameter sets the macro's variable of the same name."""
    device = config.MACRODROID_WEBHOOK.removeprefix(BASE).strip("/").split("/")[0]
    if not device:
        raise ValueError("MacroDroid isn't set up: MACRODROID_WEBHOOK in .env (steps in .env.example).")
    return f"{BASE}{device}/{identifier}?{urlencode(params)}"


def _call(url: str) -> None:
    # macOS's curl, not urllib: it trusts the Mac's keychain, so it works on networks that
    # re-sign HTTPS (see youtube.py). The address holds the phone's device id: errors never do.
    r = subprocess.run(["curl", "-sSf", "--max-time", "20", "-o", "/dev/null", url], capture_output=True, text=True)
    if r.returncode:
        why = r.stderr.strip().replace(url, "MacroDroid") or f"curl failed ({r.returncode})"
        raise RuntimeError(f"couldn't reach MacroDroid ({why})")


@tool(
    "phone_volume",
    "Set the media volume on the user's Android phone (0-100, 0 mutes), through a MacroDroid "
    "macro on the phone. It can't read the volume back. For the Mac's volume use mac_change.",
    {
        "type": "object",
        "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["volume"],
    },
)
async def phone_volume(args: dict[str, Any]) -> dict[str, Any]:
    try:
        level = max(0, min(100, int(args.get("volume"))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _text("phone_volume: volume must be 0-100.", True)
    try:
        await asyncio.to_thread(_call, url_for("jarvis_volume", volume_level=level))
    except ValueError as e:
        return _text(f"phone_volume: {e}", True)
    except RuntimeError as e:
        return _text(f"phone_volume: {e}. The phone may be offline or the macro off.", True)
    return _text(f"Sent: the phone's media volume to {level}%. (The phone sets it if it's online "
                 "and the macro is on; MacroDroid doesn't confirm.)")


@tool(
    "phone_taxi",
    "Get the user a Careem taxi: copies the destination on their Android phone and opens the "
    "Careem app there, so they paste it into \"Where to?\", check the price and book. It can't "
    "book or pay, see prices, or know whether they booked.",
    {
        "type": "object",
        "properties": {"destination": {"type": "string", "description": "Place name or address, e.g. 'Dubai Mall'. Empty just opens Careem."}},
    },
)
async def phone_taxi(args: dict[str, Any]) -> dict[str, Any]:
    destination = " ".join(str(args.get("destination") or "").split())[:200]
    try:
        await asyncio.to_thread(_call, url_for("jarvis_careem", taxi_to=destination))
    except ValueError as e:
        return _text(f"phone_taxi: {e}", True)
    except RuntimeError as e:
        return _text(f"phone_taxi: {e}. The phone may be offline or the macro off.", True)
    if not destination:
        return _text("Sent: Careem opens on the phone. (MacroDroid doesn't confirm.)")
    return _text(f"Sent: Careem opens on the phone with \"{destination}\" copied. They paste it into "
                 "\"Where to?\" and book it themselves. (MacroDroid doesn't confirm.)")


@tool(
    "phone_food",
    "Hand a food order over to Careem on the user's Android phone: copies the restaurant or "
    "dish and opens Careem there, so they tap Food, paste it into search, and order. It can't "
    "search Careem (app only), see menus or prices, order or pay. Find options first with web "
    "search (and maps near the user), then call this with the one they pick.",
    {
        "type": "object",
        "properties": {"search": {"type": "string", "description": "Restaurant or dish, e.g. 'Operation Falafel'. Empty just opens Careem."}},
    },
)
async def phone_food(args: dict[str, Any]) -> dict[str, Any]:
    search = " ".join(str(args.get("search") or "").split())[:200]
    try:
        # Reuses the taxi macro: it only copies its text and opens Careem.
        await asyncio.to_thread(_call, url_for("jarvis_careem", taxi_to=search))
    except ValueError as e:
        return _text(f"phone_food: {e}", True)
    except RuntimeError as e:
        return _text(f"phone_food: {e}. The phone may be offline or the macro off.", True)
    if not search:
        return _text("Sent: Careem opens on the phone. (MacroDroid doesn't confirm.)")
    return _text(f"Sent: Careem opens on the phone with \"{search}\" copied. They tap Food, paste it "
                 "into search and order themselves. (MacroDroid doesn't confirm.)")
