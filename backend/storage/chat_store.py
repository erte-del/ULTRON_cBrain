"""Saved chats (at most MAX_CHATS), in storage/chats.json.

A saved chat is the Claude Code session id (so Ultron can resume the conversation)
plus the messages and canvas cards the browser showed (so you can see them again).
Image, 3D and video cards are kept as ids only: main.load_chat rebuilds them from
their own stores, which still hold the files.
"""

import json
import threading
import time

from config import STORAGE_DIR

CHATS_FILE = STORAGE_DIR / "chats.json"
MAX_CHATS = 5

_lock = threading.Lock()


def _read() -> dict[str, dict]:
    try:
        return json.loads(CHATS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _clean(messages: list) -> list[dict]:
    """Only what's needed to show the chat again; the browser sends the rest too."""
    keep = []
    for m in messages if isinstance(messages, list) else []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("text"), str):
            files = m.get("files")
            keep.append({
                **({"turn": m["turn"]} if m["role"] == "user" and isinstance(m.get("turn"), int) else {}),
                "role": m["role"],
                "text": m["text"],
                "files": [f for f in files if isinstance(f, str)] if isinstance(files, list) else [],
                "model": m["model"] if isinstance(m.get("model"), str) else "",
            })
    return keep


FILE_CARDS = ("image", "model3d", "video")


def _clean_cards(cards: list) -> list[dict]:
    keep = []
    for c in cards if isinstance(cards, list) else []:
        if not (isinstance(c, dict) and all(isinstance(c.get(k), str) for k in ("id", "kind", "title"))):
            continue
        card = {"id": c["id"], "kind": c["kind"], "title": c["title"]}
        if isinstance(c.get("turn"), int):  # the turn that last touched it, so a trim knows what it belonged to
            card["turn"] = c["turn"]
        if c["kind"] not in FILE_CARDS:
            card["data"] = c["data"] if isinstance(c.get("data"), dict) else {}
        keep.append(card)
    return keep


def summaries() -> list[dict]:
    """Newest first, without the messages."""
    chats = sorted(_read().values(), key=lambda c: c["saved_at"], reverse=True)
    return [{k: c[k] for k in ("id", "title", "provider", "saved_at")} for c in chats]


def save(session_id: str, provider: str, messages: list, cards: list) -> None:
    """Save (or update) a chat. ValueError when it's new and MAX_CHATS are already saved."""
    messages = _clean(messages)
    first = next((m["text"] for m in messages if m["role"] == "user" and m["text"]), "Chat")
    title = " ".join(first.split())
    with _lock:
        chats = _read()
        if session_id not in chats and len(chats) >= MAX_CHATS:
            raise ValueError(f"You already have {MAX_CHATS} saved chats. Delete one first.")
        chats[session_id] = {
            "id": session_id,
            "title": title[:60] + ("…" if len(title) > 60 else ""),
            "provider": provider,
            "saved_at": time.time(),
            "messages": messages,
            "cards": _clean_cards(cards),
        }
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        CHATS_FILE.write_text(json.dumps(chats), encoding="utf-8")


def load(chat_id: str) -> dict:
    """KeyError if there's no such chat."""
    return _read()[chat_id]


def delete(chat_id: str) -> None:
    with _lock:
        chats = _read()
        if chats.pop(chat_id, None) is not None:
            CHATS_FILE.write_text(json.dumps(chats), encoding="utf-8")
