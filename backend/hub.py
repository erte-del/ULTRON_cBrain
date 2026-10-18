"""Pushes events to every open browser tab.

Replies stream back on the tab that asked, but some events come from elsewhere:
a tool putting a card on the canvas, or the confirmation gate asking "Send this
email?". Those go through here, to all connected tabs.
"""

import logging
from typing import Awaitable, Callable

from events import Event

log = logging.getLogger("ultron.hub")

Sender = Callable[[Event], Awaitable[None]]

_clients: set[Sender] = set()


def connect(send: Sender) -> None:
    _clients.add(send)


def disconnect(send: Sender) -> None:
    _clients.discard(send)


def has_clients() -> bool:
    return bool(_clients)


async def emit(event: Event) -> int:
    """Send an event to every connected tab; how many received it (0 = nobody is looking)."""
    delivered = 0
    for send in list(_clients):
        try:
            await send(event)
            delivered += 1
        except Exception:
            log.debug("Dropping a tab that failed to receive", exc_info=True)
            _clients.discard(send)
    return delivered
