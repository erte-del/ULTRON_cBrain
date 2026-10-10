"""Confirmation gate for 'act' tools. (Phase 4a)

Claude Code runs 'read' tools freely (they're in `allowed_tools`). For any other
tool it asks us first, through `can_use_tool`. Simple ones (a reminder, a calendar
event just for you, a note) run straight away; for anything that reaches other people
or touches a file you marked important (registry.needs_ok) the gate shows a card in the
browser ("Send this email to X? [Approve] [Deny]") and waits for your answer.

Safe defaults:
  - a tool we've never seen always asks
  - no browser open  -> denied
  - no answer within CONFIRM_TIMEOUT_S -> denied
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

import events
import hub
from tools import registry

log = logging.getLogger("ultron.confirm")

CONFIRM_TIMEOUT_S = 300

# How each card ended, for the next message: a reply cut short (you talked over it, or said
# "stop") never shows Claude the answer or the action's result. Cleared when a reply finishes.
_outcomes: list[str] = []


def take_outcomes() -> list[str]:
    told = _outcomes[:]
    _outcomes.clear()
    return told


@dataclass
class _Pending:
    request: events.Event  # the confirm.request event, re-sent to tabs that open later
    answer: asyncio.Future[bool | None]  # None: the reply it belongs to was stopped


class ConfirmationGate:
    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    async def can_use_tool(
        self, tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Called by Claude Code before any tool that isn't auto-allowed."""
        if not registry.needs_ok(tool_name, tool_input):
            log.info("Allowed: %s", registry.friendly_name(tool_name))
            return PermissionResultAllow()

        if not hub.has_clients():
            log.warning("Denied %s: no browser open to confirm", tool_name)
            return PermissionResultDeny(message="The user isn't available to confirm this action.")

        request_id = context.tool_use_id or f"confirm-{id(tool_input)}"
        title, summary, details = registry.describe_call(tool_name, tool_input)
        request = events.confirm_request(request_id, title, summary, details)
        answer: asyncio.Future[bool | None] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _Pending(request, answer)
        log.info("Asking for confirmation: %s", title)

        status = "expired"
        try:
            await hub.emit(request)
            approved = await asyncio.wait_for(answer, CONFIRM_TIMEOUT_S)
            status = "stopped" if approved is None else "approved" if approved else "denied"
        except TimeoutError:
            pass
        finally:
            self._pending.pop(request_id, None)
            _outcomes.append(f'"{title}": ' + {
                "approved": "the user approved it, so it ran. If you never saw its result, the reply was cut off "
                            "while it ran: check with a read tool before saying it worked or trying again",
                "denied": "the user declined it, so it did not happen",
                "stopped": "the reply was stopped before the user answered, so it did not happen",
                "expired": "no answer in time, so it did not happen",
            }[status])
            await hub.emit(events.confirm_resolved(request_id, status))

        log.info("Confirmation %s: %s", status, title)
        if status == "approved":
            return PermissionResultAllow()
        if status == "denied":
            return PermissionResultDeny(
                message="The user declined this action. Don't retry it unless they ask again."
            )
        if status == "stopped":
            return PermissionResultDeny(message="The user stopped the reply before answering; the action was not performed.")
        return PermissionResultDeny(
            message=f"No answer from the user within {CONFIRM_TIMEOUT_S // 60} minutes; "
            "the action was not performed."
        )

    def resolve(self, request_id: str, approved: bool) -> bool:
        """Record your answer from the browser. False if nothing was waiting."""
        pending = self._pending.get(request_id)
        if pending is None or pending.answer.done():
            return False
        pending.answer.set_result(approved)
        return True

    def stop_waiting(self) -> None:
        """The reply was stopped: its cards end now (as not done), instead of lingering until
        the timeout where a later "yes" could answer a question Claude has moved past."""
        for pending in self._pending.values():
            if not pending.answer.done():
                pending.answer.set_result(None)

    def pending_requests(self) -> list[events.Event]:
        """Open questions, for a tab that connects while they're waiting."""
        return [p.request for p in self._pending.values()]
