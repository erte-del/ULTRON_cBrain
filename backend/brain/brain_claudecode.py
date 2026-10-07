"""Brain backed by Claude Code via the Agent SDK, using the Pro login.

One Claude Code process stays running for the whole conversation
(`ClaudeSDKClient`), so each message doesn't pay the startup cost.
"""

import asyncio
import logging
import time
import warnings
from typing import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    CanUseTool,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

import usage
from config import CONNECTORS, EFFORT, GATEWAY_MODEL, PROVIDER, STORAGE_DIR, set_login
from storage import memory_store
from tools import registry

from .base import BrainEvent, Done, Error, ModelAlias, TextDelta, ToolResult, ToolStart, UIEvent
from .prompts import JARVIS_SYSTEM_PROMPT, PERSONA_REMINDER, school_block

log = logging.getLogger("ultron.brain")

# The SDK warns that 'read' tools in allowed_tools skip the confirmation gate.
# That's exactly what we want: only 'act' tools should ask you.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

# If Claude Code sends nothing for this long, give up on the turn
# (e.g. it is silently retrying while Anthropic's servers are overloaded).
IDLE_TIMEOUT_S = 120
# While one of Ultron's tools runs (e.g. ask_expert thinking on Opus), Claude Code
# stays quiet, so allow much longer.
TOOL_TIMEOUT_S = 600
# claude.ai connectors connect in the background; wait this long for them at startup.
CONNECTOR_WAIT_S = 15
# Ultron's own server can show up before the claude.ai ones; give those this long to appear
# (their list usually arrives after ~5 s).
CONNECTOR_LIST_WAIT_S = 10
# A session that still has no claude.ai connectors looks for them again this often.
CONNECTOR_RETRY_S = 300

# Claude Code tools Ultron must never have: it is an assistant, not a coding agent.
BLOCKED_TOOLS = [
    "Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Glob", "Grep", "Agent", "Task", "Skill",
]


class ClaudeCodeBrain:
    def __init__(self, model: ModelAlias = "sonnet", can_use_tool: CanUseTool | None = None) -> None:
        self.provider = PROVIDER  # "claude" (Pro login) or "omniroute" (gateway)
        self.gateway_model = GATEWAY_MODEL  # picked in the app (OmniRoute only)
        # A Claude alias (haiku / sonnet / opus), or a gateway model on OmniRoute.
        self._model: str = model if self.provider == "claude" else self.gateway_model
        self._can_use_tool = can_use_tool  # the confirmation gate for 'act' tools
        self._client: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()  # one turn at a time
        self.auth_source: str | None = None  # reported by Claude Code at startup
        self._session_id: str | None = None  # lets a restarted process resume the conversation
        # How many tokens the conversation takes up now (from Claude's last reply).
        # Switching models means sending all of it again, so the router uses this.
        self.context_tokens = 0
        # Wall-clock time of the last message (keeps counting while the Mac sleeps).
        self.last_active = 0.0
        # False when Claude Code started without the claude.ai connectors (Gmail, ...).
        self._has_connectors = True
        self._connector_retry_at = 0.0

    @property
    def session_id(self) -> str | None:
        """The Claude Code session of this conversation, once it has one (for saved chats)."""
        return self._session_id

    @property
    def model(self) -> str:
        """The model the conversation is on now."""
        return self._model

    def _options(self) -> ClaudeAgentOptions:
        on_claude = self.provider == "claude"
        return ClaudeAgentOptions(
            # Replaces Claude Code's coding prompt. Your school notes and what Ultron remembers
            # about you are added each time a conversation starts.
            system_prompt=JARVIS_SYSTEM_PROMPT + school_block() + memory_store.prompt_block() + memory_store.conversations_block() + PERSONA_REMINDER,
            model=self._model,
            # Thinking was the biggest use of the Pro limit (see .env). Gateway models
            # may not understand the setting, so it's only sent to Claude.
            effort=EFFORT if on_claude else None,
            # Only WebSearch / WebFetch / ToolSearch. Through a gateway only WebFetch:
            # WebSearch runs on Anthropic's servers, and there are no connectors to search.
            tools=registry.builtin_tools() if on_claude else ["WebFetch"],
            # belt and braces; ask_expert calls Claude Opus, which a gateway doesn't have
            disallowed_tools=BLOCKED_TOOLS if on_claude else [*BLOCKED_TOOLS, registry.PREFIX + "ask_expert"],
            hooks=registry.hooks(),  # e.g. WebFetch may not reach local addresses
            mcp_servers=registry.mcp_servers(),  # Ultron's own tools (ask_expert, ...)
            allowed_tools=registry.auto_allowed(),  # 'read' tools run without asking
            can_use_tool=self._can_use_tool,  # every other tool goes through the gate
            env={
                "MCP_TOOL_TIMEOUT": str(TOOL_TIMEOUT_S * 1000),
                # Connector tools stay hidden until Claude searches for one. Without
                # this, ~300 tool descriptions went into every message (~220K tokens).
                "ENABLE_TOOL_SEARCH": "true" if on_claude else "false",
                # A gateway that's down or broken: give up after a few seconds, not minutes.
                **({} if on_claude else {"CLAUDE_CODE_MAX_RETRIES": "2"}),
            },
            include_partial_messages=True,  # stream text word by word
            # Tool results with pictures (slides, photos) come as one JSON line; the SDK's
            # default 1 MB cap failed on 6 lecture slides ("CLIJSONDecodeError").
            max_buffer_size=32 * 1024 * 1024,
            setting_sources=[],  # ignore ~/.claude settings, CLAUDE.md files, plugins
            # False = also load the claude.ai connectors (Gmail, ...) of the Pro account.
            # Their tools are labelled read/act in tools/connectors.py. Never through a
            # gateway: your emails would go to other providers' models.
            strict_mcp_config=not on_claude,
            skills=[],
            cwd=STORAGE_DIR,
            resume=self._session_id,
        )

    async def _connect(self) -> ClaudeSDKClient:
        if self._client is None:
            set_login(self.provider)
            client = ClaudeSDKClient(self._options())
            await client.connect()
            self._client = client
            log.info("Claude Code session started (provider=%s, model=%s)", self.provider, self._model)
            await self._wait_for_connectors(client)
        return self._client

    async def _wait_for_connectors(self, client: ClaudeSDKClient) -> None:
        """Give slow connectors a moment, so the first message can already use them."""
        started = asyncio.get_running_loop().time()
        servers: list = []
        while True:
            try:
                servers = (await client.get_mcp_status()).get("mcpServers", [])
            except Exception:
                log.debug("Could not read connector status", exc_info=True)
                return
            # Wait until the claude.ai connectors are listed (or clearly aren't coming)
            # and none is still connecting.
            waited = asyncio.get_running_loop().time() - started
            listed = any(s["name"].startswith("claude.ai ") for s in servers)
            pending = [s["name"] for s in servers if s.get("status") == "pending"]
            if ((listed or waited > CONNECTOR_LIST_WAIT_S) and not pending) or waited > CONNECTOR_WAIT_S:
                break
            await asyncio.sleep(0.5)
        await self._apply_connector_choice(client, servers)
        self._has_connectors = self.provider != "claude" or any(
            s["name"].startswith("claude.ai ") for s in servers
        )
        self._connector_retry_at = time.time() + CONNECTOR_RETRY_S
        by_status: dict[str, list[str]] = {}
        for s in servers:
            by_status.setdefault(s.get("status", "?"), []).append(s["name"].removeprefix("claude.ai "))
        log.info("Connectors: %s", "; ".join(f"{k}: {', '.join(v)}" for k, v in by_status.items()) or "none")

    async def _retry_connectors(self) -> None:
        """Claude Code sometimes starts without the claude.ai connectors (their list comes
        late or not at all), and then Ultron says Gmail isn't connected. Look again, and
        if they're still missing restart Claude Code; `resume` keeps the conversation."""
        if self._client is None or self._has_connectors or time.time() < self._connector_retry_at:
            return
        self._connector_retry_at = time.time() + CONNECTOR_RETRY_S
        try:
            servers = (await self._client.get_mcp_status()).get("mcpServers", [])
        except Exception:
            servers = []
        if any(s["name"].startswith("claude.ai ") for s in servers):  # they arrived late
            await self._apply_connector_choice(self._client, servers)
            self._has_connectors = True
            return
        log.warning("No claude.ai connectors in this session; restarting Claude Code")
        await self.close()

    async def _apply_connector_choice(self, client: ClaudeSDKClient, servers: list) -> None:
        """Switch claude.ai connectors on or off to match JARVIS_CONNECTORS (.env).
        Claude Code remembers the switch, so both directions are needed."""
        for server in servers:
            name = server.get("name", "")
            if not name.startswith("claude.ai "):
                continue
            wanted = "all" in CONNECTORS or name.removeprefix("claude.ai ").lower() in CONNECTORS
            is_off = server.get("status") == "disabled"
            if wanted == is_off:
                try:
                    await client.toggle_mcp_server(name, wanted)
                    server["status"] = "switched on" if wanted else "disabled"
                except Exception:
                    log.warning("Could not switch %s %s", name, "on" if wanted else "off", exc_info=True)

    async def start(self) -> None:
        """Start Claude Code ahead of the first message (called at server startup)."""
        async with self._lock:
            try:
                await self._connect()
            except Exception:
                log.exception("Could not start Claude Code; will retry on the first message")
                await self.close()

    async def send(
        self,
        text: str,
        images: list[bytes] | None = None,
        model: str = "sonnet",
    ) -> AsyncIterator[BrainEvent]:
        if images:
            raise NotImplementedError("Image input arrives in Phase 4c")

        async with self._lock:
            finished = False
            try:
                if model != self._model and self.provider == "omniroute":
                    # Switching model in a running Claude Code asks the gateway to confirm
                    # the name, and OmniRoute keeps its model list behind its own key. So
                    # restart with the new model instead; `resume` keeps the conversation.
                    await self.close()
                    self._model = model
                await self._retry_connectors()
                client = await self._connect()
                if model != self._model:
                    await client.set_model(model)
                    self._model = model

                await client.query(text)

                answered_by = self._model
                running_tools: set[str] = set()
                messages = client.receive_response()
                while True:
                    timeout = TOOL_TIMEOUT_S if running_tools else IDLE_TIMEOUT_S
                    try:
                        msg = await asyncio.wait_for(anext(messages), timeout)
                    except StopAsyncIteration:
                        break
                    # Skip anything from sub-agents; Ultron only shows its own reply.
                    if getattr(msg, "parent_tool_use_id", None):
                        continue

                    if isinstance(msg, StreamEvent):
                        ev = msg.event
                        if ev.get("type") == "content_block_delta":
                            delta = ev.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield TextDelta(delta["text"])

                    elif isinstance(msg, AssistantMessage):
                        answered_by = msg.model
                        if msg.usage:
                            u = msg.usage
                            self.context_tokens = sum(
                                int(u.get(k) or 0)
                                for k in ("input_tokens", "cache_read_input_tokens",
                                          "cache_creation_input_tokens", "output_tokens")
                            )
                        if msg.error:  # reported to the UI via the ResultMessage below
                            log.warning("Claude error on %s: %s", msg.model, msg.error)
                        for block in msg.content:
                            if isinstance(block, ToolUseBlock):
                                running_tools.add(block.id)
                                yield ToolStart(block.id, block.name, block.input)

                    elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                        for block in msg.content:
                            if isinstance(block, ToolResultBlock):
                                running_tools.discard(block.tool_use_id)
                                yield ToolResult(
                                    block.tool_use_id, bool(block.is_error), msg.tool_use_result
                                )

                    elif isinstance(msg, SystemMessage) and msg.subtype == "init":
                        self.auth_source = msg.data.get("apiKeySource")
                        self._session_id = msg.data.get("session_id")
                        log.info("Claude Code auth: apiKeySource=%s", self.auth_source)

                    elif isinstance(msg, SystemMessage) and msg.subtype == "api_retry":
                        # Claude Code retries quietly (e.g. 529 overloaded); show the count.
                        d = msg.data
                        log.warning("Claude API retry %s/%s: %s", d.get("attempt"), d.get("max_retries"), d.get("error"))
                        yield UIEvent("assistant.retry", {
                            "attempt": d.get("attempt"), "max": d.get("max_retries"), "error": d.get("error"),
                        })

                    elif isinstance(msg, RateLimitEvent):
                        usage.record_limits(msg.rate_limit_info.raw)

                    elif isinstance(msg, ResultMessage):
                        finished = True
                        usage.record_turn(msg.model_usage)
                        if msg.is_error:
                            detail = "; ".join(msg.errors or []) or msg.result or msg.subtype
                            yield Error(detail)
                        else:
                            yield Done(answered_by)
            except TimeoutError:
                log.error("No response from Claude Code; restarting session")
                yield Error("No response from Claude for too long. It may be overloaded; try again.")
            except Exception as e:  # keep the app alive; report to the UI
                log.exception("Brain turn failed")
                yield Error(f"{type(e).__name__}: {e}")
            finally:
                self.last_active = time.time()
                # If the turn was cut short (error, timeout, browser closed mid-reply),
                # Claude Code may still be sending the old reply. Restart it so the next
                # turn starts clean; `resume` keeps the conversation.
                if not finished:
                    await self.close()

    async def new_conversation(self, provider: str | None = None, resume: str | None = None) -> None:
        """Forget the conversation: the next message starts a fresh Claude Code session,
        or continues the saved session `resume`.
        Switching provider always does this (the other side can't continue it)."""
        if self._lock.locked() and self._client is not None:
            try:  # a reply in progress: stop it rather than wait for it
                await self._client.interrupt()
            except Exception:
                log.debug("Could not interrupt the reply in progress", exc_info=True)
        async with self._lock:  # the interrupted reply ends first
            await self.close()
            if provider:
                self.provider = provider
            self._session_id = resume
            self._model = "sonnet" if self.provider == "claude" else self.gateway_model
            self.context_tokens = 0
            self.last_active = 0.0
        log.info("Started a %s conversation (provider=%s)", "saved" if resume else "new", self.provider)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None
