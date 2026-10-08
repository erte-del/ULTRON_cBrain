"""WebSocket event types — the shared protocol with frontend/src/ws.ts.

Every message is a JSON object with a "type" field.

Client -> server:
    user.text        {text, voice?}      voice = true when you said it (voice mode)
    user.voice       {mode}              "voice" (voice mode), "wake" (listening only for
                                         "Hey Ultron") or "off"; on loads the voice models
    user.greet       {}                  say "Awake and ready, sir." (a window "Hey Ultron" opened
                                         on the PC, windows/wake_pc.py)
    (binary frame)   your microphone in voice mode: 16 kHz, 16-bit mono PCM (voice/vad.py)
    user.confirm     {id, approved}       your answer to a confirm.request
    user.select_image {id, version} | {id: null}   you clicked an image on the canvas
    settings.update  {model_override: "haiku" | "sonnet" | "opus" | null}
    user.new_chat    {}                   start a fresh conversation
    settings.update  {provider: "claude" | "omniroute"}   switch brain (starts a new chat)
    settings.update  {gateway_model}      pick one of the OmniRoute models
    user.save_chat   {messages, cards}    save this chat (at most 5; see storage/chat_store.py)
    user.load_chat   {id}                 continue a saved chat
    user.delete_chat {id}
    user.memory_save {id?, text, category}   add a memory, or change the one with that id
    user.memory_delete {id}
    user.memory_wipe {}                  delete every memory
    user.job_update  {id, action: "pause" | "resume" | "delete" | "run"}   a scheduled job

Server -> client:
    status               {state: "idle" | "thinking"}
    assistant.text_delta {id, text}       id = the reply this text belongs to
    assistant.done       {id, model, routed_to, reason, expert, sources}
                         model = full model ID that answered
                         routed_to = the router's pick; reason = why
                         expert = true if Opus was consulted via ask_expert
                         sources = [{title, url}] web pages behind the answer
    tool.started         {id, name, detail, label}  detail = e.g. the search query;
                                                     label = readable name ("Gmail: Search threads")
    tool.finished        {id, is_error}
    error                {message, id?}
    notice               {message}        something to know that isn't an error
    confirm.request      {id, title, summary, details}   an 'act' tool wants to run
    confirm.resolved     {id, status}     status = approved | denied | expired
    conversation.new     {reason: "button" | "idle" | "provider"}   Ultron forgot the conversation
    conversation.loaded  {messages, cards}   a saved chat was loaded: show these messages and cards
    chats.list           {chats: [{id, title, provider, saved_at}], max}   saved chats, newest first
    memory.list          {memories: [{id, category, text, source, created, updated}], categories}
                         everything Ultron remembers, most recently changed first
    jobs.list            {jobs: [{id, title, prompt, at, days, every_min, once, enabled, last_run}],
                          runs: [{job_id, title, time, status, text}]}   scheduled jobs; runs newest first,
                         status = told | nothing | skipped | failed
    notification         {title, text, time}   a scheduled job is telling you something
    settings.state       {provider, gateway_url, gateway_model, gateway_models}   the brain in use
    usage.update         {provider, windows, tokens, context_tokens}   see usage.py
    canvas.card          {id, kind, title, data}  show (or replace) a canvas card;
                         kind "image": data = {image_id, current, credit, versions[]}
                         kind "model3d": data = {model_id, current, versions[], exports[]}
                         kind "video": data = {video_id, status, progress, url, ...} (video_store)
    terminal.open        {claude}  open a new terminal tab (a fresh shell at /ws/terminal);
                         claude = start Claude Code in it
    voice.speech         {active}         voice mode: you started (true) or stopped (false) talking
    voice.transcript     {text}           what you said ("" = nothing understood); the page
                                          sends it back as user.text {voice: true}
    voice.wake           {text}           wake word mode: you said "Hey Ultron" (text = what
                                          followed, "" if nothing): start voice mode
    voice.audio          {text, audio}    one sentence of a reply to something you said, to play
                                          in order; audio = base64 WAV, or null: the page says
                                          text with its own voice
"""

import base64
from typing import Any

from brain.base import BrainEvent, Done, Error, TextDelta, ToolResult, ToolStart, UIEvent
from storage import memory_store

Event = dict[str, Any]


def status(state: str) -> Event:
    return {"type": "status", "state": state}


def error(message: str, reply_id: str | None = None) -> Event:
    ev: Event = {"type": "error", "message": message}
    if reply_id:
        ev["id"] = reply_id
    return ev


def notice(message: str) -> Event:
    return {"type": "notice", "message": message}


def done(
    reply_id: str,
    model: str,
    routed_to: str,
    reason: str,
    expert: bool,
    sources: list[dict[str, str]],
) -> Event:
    return {
        "type": "assistant.done",
        "id": reply_id,
        "model": model,
        "routed_to": routed_to,
        "reason": reason,
        "expert": expert,
        "sources": sources,
    }


def tool_started(tool_id: str, name: str, detail: str = "", label: str = "") -> Event:
    return {"type": "tool.started", "id": tool_id, "name": name, "detail": detail, "label": label or name}


def confirm_request(request_id: str, title: str, summary: str, details: list[list[str]]) -> Event:
    return {
        "type": "confirm.request",
        "id": request_id,
        "title": title,
        "summary": summary,
        "details": details,  # [[label, value], ...]
    }


def confirm_resolved(request_id: str, status: str) -> Event:
    return {"type": "confirm.resolved", "id": request_id, "status": status}


def settings_state(provider: str, gateway_url: str, gateway_model: str, gateway_models: list[str]) -> Event:
    return {
        "type": "settings.state",
        "provider": provider,
        "gateway_url": gateway_url,
        "gateway_model": gateway_model,
        "gateway_models": gateway_models,
    }


def usage_update(snapshot: dict[str, Any]) -> Event:
    return {"type": "usage.update", **snapshot}


def conversation_new(reason: str) -> Event:
    return {"type": "conversation.new", "reason": reason}


def conversation_loaded(messages: list[dict], cards: list[Event]) -> Event:
    return {"type": "conversation.loaded", "messages": messages, "cards": cards}


def chats_list(chats: list[dict], max_chats: int) -> Event:
    return {"type": "chats.list", "chats": chats, "max": max_chats}


def memory_list(memories: list[dict]) -> Event:
    return {"type": "memory.list", "memories": memories, "categories": list(memory_store.CATEGORIES)}


def jobs_list(jobs: list[dict], runs: list[dict]) -> Event:
    return {"type": "jobs.list", "jobs": jobs, "runs": runs}


def notification(title: str, text: str, when: float) -> Event:
    return {"type": "notification", "title": title, "text": text, "time": when}


def terminal_open(claude: bool) -> Event:
    return {"type": "terminal.open", "claude": claude}


def voice_speech(active: bool) -> Event:
    return {"type": "voice.speech", "active": active}


def voice_transcript(text: str) -> Event:
    return {"type": "voice.transcript", "text": text}


def voice_wake(text: str) -> Event:
    return {"type": "voice.wake", "text": text}


def voice_audio(text: str, wav: bytes | None) -> Event:
    return {"type": "voice.audio", "text": text, "audio": base64.b64encode(wav).decode() if wav else None}


def canvas_card(card_id: str, kind: str, title: str, data: dict[str, Any]) -> Event:
    return {"type": "canvas.card", "id": card_id, "kind": kind, "title": title, "data": data}


def from_brain(ev: BrainEvent, reply_id: str) -> Event:
    """Translate a brain event into the WebSocket event the frontend understands."""
    match ev:
        case TextDelta(text=text):
            return {"type": "assistant.text_delta", "id": reply_id, "text": text}
        case Done(model=model):
            return {"type": "assistant.done", "id": reply_id, "model": model}
        case ToolStart(id=tool_id, name=name):
            return tool_started(tool_id, name)
        case ToolResult(id=tool_id, is_error=is_error):
            return {"type": "tool.finished", "id": tool_id, "is_error": is_error}
        case UIEvent(name=name, data=data):
            return {"type": name, **data}
        case Error(message=message):
            return error(message, reply_id)
    raise ValueError(f"Unknown brain event: {ev!r}")
