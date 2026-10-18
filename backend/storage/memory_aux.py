"""The files beside memory.json that Memory v2 keeps, so memory.json itself stays small and the
panel and the vault mirror keep reading it as before:

  memory_embeddings.json  one vector per memory (id -> model, text hash, numbers); local model only
  memory_links.json       how memories connect (a, b, kind, strength)
  memory_insights.json    patterns found by the nightly pass (later steps)
  memory_state.json       switches, caps, dismiss counts, the model-call cache and the daily cost log

They always sit in the same folder as memory.json (so a test that points memory.json at a temp
folder gets its own copies). Same pattern as memory_store: one lock, atomic write.
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

from storage import memory_store

log = logging.getLogger("ultron.memory")

_lock = threading.RLock()

LINK_KINDS = ("same_person", "same_project", "caused_by", "follow_up_of", "contradicts", "supersedes", "same_topic")
# a -> b means something (a supersedes b); the others read the same both ways.
DIRECTED = frozenset({"caused_by", "follow_up_of", "supersedes"})
CACHE_KEEP = 400


def path(name: str) -> Path:
    return memory_store.MEMORY_FILE.parent / name


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load(name: str, default):
    try:
        data = json.loads(path(name).read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save(name: str, data) -> None:
    target = path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")  # a crash mid-write mustn't lose the file
    compact = name == "memory_embeddings.json"  # vectors are big: no indenting
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":") if compact else None,
                              indent=None if compact else 1), encoding="utf-8")
    tmp.replace(target)


# --- state -----------------------------------------------------------------------------

def default_state() -> dict:
    return {
        "proactive": False,      # nudges out of the chat: off until you switch them on (step 7)
        "caps": {"per_day": 2, "per_topic_week": 1, "dismiss_limit": 2},
        "dismissed": {},         # insight id -> how many times you said "not useful"
        "cost": {},              # "2026-10-18" -> {"ollama": {"calls", "in", "out"}, "claude": {...}}
        "cache": {},             # hash of a model call's inputs -> its (validated) result
        "nudges": [],            # nudges sent: [{"ts", "insight", "topic"}]
        "proposals": [],         # weekly merge / archive suggestions waiting for you
        "last_decay": 0.0,
        "queue": [],             # remembered while the judge was down: [{"id", "at"}]
        "enriched": {},          # memory id -> hash of the text that entities/topics were made from
        "migrated_at": None,
        "last_nightly": 0.0,
    }


def state() -> dict:
    with _lock:
        return {**default_state(), **_load("memory_state.json", {})}


def save_state(data: dict) -> None:
    with _lock:
        cache = data.get("cache", {})
        if len(cache) > CACHE_KEEP:  # oldest first (dicts keep insertion order)
            data = {**data, "cache": dict(list(cache.items())[-CACHE_KEEP:])}
        _save("memory_state.json", data)


def update_state(**changes) -> dict:
    with _lock:
        data = state()
        data.update(changes)
        save_state(data)
        return data


def cached(key: str):
    return state()["cache"].get(key)


def remember_result(key: str, value) -> None:
    with _lock:
        data = state()
        data["cache"][key] = value
        save_state(data)


def log_cost(backend: str, calls: int = 1, tokens_in: int = 0, tokens_out: int = 0, what: str = "") -> None:
    """Count a model call under today's date: how many calls and tokens each backend used."""
    with _lock:
        data = state()
        day = data["cost"].setdefault(time.strftime("%Y-%m-%d"), {})
        entry = day.setdefault(backend, {"calls": 0, "in": 0, "out": 0, "by": {}})
        entry["calls"] += calls
        entry["in"] += tokens_in
        entry["out"] += tokens_out
        if what:
            entry["by"][what] = entry["by"].get(what, 0) + calls
        for old in sorted(data["cost"])[:-60]:  # two months is plenty
            del data["cost"][old]
        save_state(data)


# --- embeddings ------------------------------------------------------------------------

def embeddings() -> dict:
    with _lock:
        return _load("memory_embeddings.json", {})


def save_embeddings(data: dict) -> None:
    with _lock:
        _save("memory_embeddings.json", data)


def vector_for(memory: dict, model: str, store: dict | None = None):
    """The stored vector if it was made by this model from this exact text, else None."""
    item = (store if store is not None else embeddings()).get(memory["id"])
    if item and item.get("model") == model and item.get("hash") == text_hash(memory["text"]):
        return item["v"]
    return None


# --- links -----------------------------------------------------------------------------

def links(include_rejected: bool = False) -> list[dict]:
    with _lock:
        found = _load("memory_links.json", [])
    return found if include_rejected else [l for l in found if l.get("status", "active") == "active"]


def save_links(items: list[dict]) -> None:
    with _lock:
        _save("memory_links.json", items)


def link_key(a: str, b: str, kind: str) -> tuple:
    return (a, b, kind) if kind in DIRECTED else (*sorted((a, b)), kind)


def add_link(a: str, b: str, kind: str, strength: float, source: str = "auto", note: str = "") -> dict | None:
    """Add (or strengthen) a link. None if it's a link to itself, the kind is unknown, or you removed it
    earlier. Links you or the judge made are never overwritten by the automatic pass."""
    if a == b or kind not in LINK_KINDS:
        return None
    with _lock:
        items = _load("memory_links.json", [])
        key = link_key(a, b, kind)
        for item in items:
            if link_key(item["a"], item["b"], item["kind"]) == key:
                if item.get("status") == "rejected":
                    return None
                if item["source"] == "auto":
                    item["strength"] = round(max(item["strength"], strength), 3)
                _save("memory_links.json", items)
                return item
        item = {"a": a, "b": b, "kind": kind, "strength": round(float(strength), 3), "source": source,
                "status": "active", "created": time.time(), "note": note}
        items.append(item)
        _save("memory_links.json", items)
        return item


def reject_link(a: str, b: str, kind: str) -> bool:
    """Take a link away for good: the nightly pass won't make it again."""
    with _lock:
        items = _load("memory_links.json", [])
        key = link_key(a, b, kind)
        hit = False
        for item in items:
            if link_key(item["a"], item["b"], item["kind"]) == key:
                item["status"] = "rejected"
                hit = True
        if hit:
            _save("memory_links.json", items)
        return hit


def drop_memory(memory_id: str) -> None:
    """You deleted a memory: its vector and its links go too."""
    with _lock:
        store = _load("memory_embeddings.json", {})
        if store.pop(memory_id, None) is not None:
            _save("memory_embeddings.json", store)
        items = _load("memory_links.json", [])
        kept = [l for l in items if memory_id not in (l["a"], l["b"])]
        if len(kept) != len(items):
            _save("memory_links.json", kept)
        data = state()
        if memory_id in data["enriched"] or any(q["id"] == memory_id for q in data["queue"]):
            data["enriched"].pop(memory_id, None)
            data["queue"] = [q for q in data["queue"] if q["id"] != memory_id]
            save_state(data)


def neighbours(memory_id: str) -> list[dict]:
    """Active links touching this memory, strongest first: [{"other", "kind", "strength", "direction"}]."""
    out = []
    for l in links():
        if memory_id in (l["a"], l["b"]):
            other = l["b"] if l["a"] == memory_id else l["a"]
            direction = "" if l["kind"] not in DIRECTED else ("out" if l["a"] == memory_id else "in")
            out.append({"other": other, "kind": l["kind"], "strength": l["strength"], "direction": direction,
                        "source": l["source"]})
    return sorted(out, key=lambda n: -n["strength"])


# --- insights --------------------------------------------------------------------------

def insights() -> list[dict]:
    with _lock:
        return _load("memory_insights.json", [])


def save_insights(items: list[dict]) -> None:
    with _lock:
        _save("memory_insights.json", items)
