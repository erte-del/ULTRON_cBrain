"""Brain protocol + BrainEvent types.

Everything in Ultron talks to a `Brain`, never to Claude Code or the API
directly. That way the brain can be swapped (Pro subscription today,
API key someday) without touching the rest of the app.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol

ModelAlias = Literal["haiku", "sonnet", "opus"]


@dataclass
class TextDelta:
    """A small piece of the reply text, streamed as it is generated."""
    text: str
    type: Literal["text_delta"] = "text_delta"


@dataclass
class ToolStart:
    """Claude started using a tool (e.g. a web search)."""
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool_start"] = "tool_start"


@dataclass
class ToolResult:
    """A tool finished. `data` is the tool's structured result, when there is one."""
    id: str
    is_error: bool = False
    data: Any = None
    type: Literal["tool_result"] = "tool_result"


@dataclass
class UIEvent:
    """Something for the frontend to show (canvas image, card, ...). Phase 4a+."""
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    type: Literal["ui_event"] = "ui_event"


@dataclass
class Done:
    """The reply is complete. `model` is the full model ID that answered."""
    model: str
    type: Literal["done"] = "done"


@dataclass
class Error:
    message: str
    type: Literal["error"] = "error"


BrainEvent = TextDelta | ToolStart | ToolResult | UIEvent | Done | Error


class Brain(Protocol):
    provider: str  # "claude" (Pro login) or "omniroute" (gateway)
    gateway_model: str  # the OmniRoute model picked in the app
    model: ModelAlias  # the model the conversation is on now
    context_tokens: int  # size of the conversation so far (switching models re-sends it)
    last_active: float  # time.time() of the last message, 0 if none yet
    session_id: str | None  # id to resume this conversation later (saved chats)

    async def send(
        self,
        text: str,
        images: list[bytes] | None = None,
        model: ModelAlias = "sonnet",
    ) -> AsyncIterator[BrainEvent]:
        """Send one user message and stream back events until `Done` or `Error`."""
        ...

    async def new_conversation(self, provider: str | None = None, resume: str | None = None) -> None:
        """Forget the conversation and start a fresh one (optionally on another provider),
        or continue the saved conversation `resume`."""
        ...

    async def restart_session(self) -> None:
        """Start a fresh session for the same chat (same model, same tool groups); the caller
        tells it what the chat was about in the next message."""
        ...

    async def close(self) -> None:
        """Release resources (e.g. stop the Claude Code process)."""
        ...
