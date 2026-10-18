"""Saving a memory the smart way: look at the 5 most similar ones first, then add, merge, supersede
or flag a contradiction. Nothing is silently deleted: the old text of a merge stays in `history`, a
superseded memory is archived with its reason, and a contradiction is only flagged (a link of kind
`contradicts` you can see) - never resolved on its own when either side is something you said.

Order, cheapest first, so `remember` stays quick:
  1. checks (empty, too long, secret) - the same as before
  2. near-copy of one memory (same words, or nearly the same meaning)  -> merged without any model
  3. a dated plan that moved ("test moved to 19 Nov")                   -> superseded without any model
  4. candidates but no obvious answer -> the judge (local model; cheap Claude if it's down and allowed)
     with a short timeout. No answer in time: the memory is saved as it is and queued for the nightly pass.
  5. no candidates -> just added.
"""

import logging
import re
import time

import config
import memory_ai
import memory_graph
import memory_text
from storage import memory_aux, memory_store

log = logging.getLogger("ultron.memory")

CANDIDATES = 5
JUDGE_MIN_OVERLAP = 0.2   # words in common at which an older memory is worth showing the judge
JUDGE_MIN_COSINE = 0.72   # ... or meaning this close
NEAR_COSINE = 0.95        # meaning this close is the same memory
MOVED_OVERLAP = 0.5       # same subject (dates aside) for a "moved" plan


def _today():
    return memory_store._today(time.time())


def date_of(m: dict):
    """The calendar date a memory talks about, or None."""
    return memory_text.extract_date(m["text"], memory_store._today(m["created"]))


def similar(text: str, pool: list[dict], vectors: dict, query_vector) -> list[dict]:
    """The `CANDIDATES` most similar memories worth a look: [{"memory", "overlap", "cosine"}], best first."""
    found = []
    for m in pool:
        ov = memory_text.overlap(text, m["text"])
        cos = memory_ai.cosine(query_vector, vectors[m["id"]]) if query_vector and m["id"] in vectors else None
        if ov >= JUDGE_MIN_OVERLAP or (cos is not None and cos >= JUDGE_MIN_COSINE):
            found.append({"memory": m, "overlap": ov, "cosine": cos})
    found.sort(key=lambda c: -max(c["overlap"], c["cosine"] or 0.0))
    return found[:CANDIDATES]


def known_entities(text: str, pool: list[dict]) -> list[dict]:
    """People/projects other memories already know that this text names (no model needed)."""
    low, seen = text.casefold(), {}
    for m in pool:
        for e in m["entities"]:
            key = e["name"].casefold()
            if key not in seen and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", low):
                seen[key] = e
    return list(seen.values())


def _embed_one(memory: dict) -> None:
    """Best effort: keep this memory's vector up to date. Never raises."""
    try:
        store, _, _ = memory_ai.refresh_embeddings([memory])
    except Exception:
        log.info("Couldn't embed %s", memory["id"], exc_info=True)


def _after_add(memory: dict, pool: list[dict]) -> None:
    """Links for a fresh or changed memory (and its vector). Never raises: the memory is already saved."""
    try:
        _embed_one(memory)
        store = memory_aux.embeddings()
        vectors = {m["id"]: v for m in [memory, *pool] if (v := memory_aux.vector_for(m, config.EMBED_MODEL, store))}
        memory_graph.link_new(memory_store.get(memory["id"]) or memory, pool, vectors)
    except Exception:
        log.exception("Linking %s failed", memory["id"])


def _same_subject(a: str, b: str) -> float:
    return memory_text.overlap(memory_text.without_dates(a), memory_text.without_dates(b))


def _may_supersede(old: dict, new_source: str, new_text: str) -> bool:
    """Only a dated plan that moved, and never a guess over something the user said."""
    if new_source == "inferred" and old["source"] == "user_said":
        return False
    d_old, d_new = date_of(old), memory_text.extract_date(new_text, _today())
    return d_old is not None and d_new is not None and d_old != d_new


def _merge_into(target: dict, new_text: str, merged_text: str | None, new_source: str, by: str) -> dict:
    """Fold the new wording into an existing memory. The old text is kept in its history."""
    text = merged_text
    if text is None:  # no model: keep whichever says more, if the other adds nothing
        a, b = memory_text.token_set(target["text"]), memory_text.token_set(new_text)
        text = new_text if (b > a and len(new_text) >= len(target["text"])) else target["text"]
    changes = {}
    if new_source == "user_said" and target["source"] != "user_said":
        changes.update(source="user_said", confidence=1.0)  # the user just said it themself
    if changes:
        memory_store.patch(target["id"], **changes)
    if text != target["text"]:
        return memory_store.update(target["id"], text, target["category"], by=by, reason=f"merged with: {new_text}"[:300])
    memory_store.patch(target["id"], updated=time.time())
    return memory_store.get(target["id"])


def _supersede(old: dict, new: dict, why: str, by: str) -> None:
    memory_store.archive(old["id"], f"superseded by {new['id']}: {why}"[:200])
    memory_aux.add_link(new["id"], old["id"], "supersedes", 1.0, by, why[:200])


def _flag_contradiction(new: dict, other: dict, by: str) -> str:
    memory_aux.add_link(new["id"], other["id"], "contradicts", 0.9, by, "disagree")
    return f"{new['id']} disagrees with {other['id']} ('{other['text'][:90]}'). Both are kept: ask the user which is right."


def smart_add(text: str, category: str, source: str = "user_said") -> dict:
    """Save a memory after looking at the most similar ones. ValueError as memory_store.add.
    Returns {"action": added|merged|duplicate|superseded|flagged, "memory", "target", "flags": [...], "by"}."""
    text = memory_store._check(text, category)
    source = memory_store.normalize_source(source)
    if not config.MEMORY_V2:  # kill switch: the old behaviour
        return {"action": "added", "memory": memory_store.add(text, category, source), "target": None, "flags": [], "by": "off"}

    pool = memory_store.entries()
    got = memory_ai.embed([text])
    store = memory_aux.embeddings()
    vectors = {m["id"]: v for m in pool if (v := memory_aux.vector_for(m, config.EMBED_MODEL, store))}
    candidates = similar(text, pool, vectors, got[0] if got else None)

    # 2. a near-copy
    if candidates:
        top = candidates[0]
        same_date = (date_of(top["memory"]) == memory_text.extract_date(text, _today()))
        if same_date and (_same_subject(text, top["memory"]["text"]) >= memory_store.NEAR_DUPLICATE
                          or (top["cosine"] or 0) >= NEAR_COSINE):
            before = top["memory"]["text"]
            merged = _merge_into(top["memory"], text, None, source, "merge")
            _after_add(merged, pool)
            return {"action": "merged" if merged["text"] != before else "duplicate", "memory": merged,
                    "target": top["memory"]["id"], "flags": [], "by": "rule"}
        # 3. a plan that moved
        for c in candidates:
            old = c["memory"]
            if (_same_subject(text, old["text"]) >= MOVED_OVERLAP and memory_text.CHANGE_CUE.search(text)
                    and _may_supersede(old, source, text)):
                new = memory_store.add(text, category, source)
                _supersede(old, new, "the date moved", "rule")
                _after_add(new, pool)
                return {"action": "superseded", "memory": new, "target": old["id"], "flags": [], "by": "rule"}

    # 4. the judge
    verdict, by = None, "none"
    if candidates:
        private = memory_ai.is_private({"text": text, "sensitive": memory_text.sensitive_text(text)}) or any(
            memory_ai.is_private(c["memory"]) for c in candidates)
        try:
            verdict, by = memory_ai.judge(text, category, [c["memory"] for c in candidates], private,
                                          config.MEMORY_JUDGE_TIMEOUT_S)
        except memory_ai.Unavailable as e:
            log.info("Judge unavailable (%s): saving as it is, checking tonight", e)
    return _apply(text, category, source, candidates, verdict, by, pool)


def _apply(text, category, source, candidates, verdict, by, pool) -> dict:
    by_id = {c["memory"]["id"]: c["memory"] for c in candidates}
    flags: list[str] = []
    if verdict and verdict["decision"] in ("duplicate", "merge"):
        target = by_id[verdict["target"]]
        merged = _merge_into(target, text, verdict["merged_text"] or None, source, "merge")
        _after_add(merged, pool)
        return {"action": "merged" if verdict["decision"] == "merge" else "duplicate", "memory": merged,
                "target": target["id"], "flags": flags, "by": by}
    extra = {"entities": known_entities(text, pool), "topics": []}
    if verdict:
        names = {e["name"].casefold() for e in extra["entities"]}
        extra["entities"] += [e for e in verdict["entities"] if e["name"].casefold() not in names]
        extra["topics"] = verdict["topics"]
    new = memory_store.add(text, category, source, **extra)
    if extra["entities"] or extra["topics"]:
        memory_aux.update_state(enriched={**memory_aux.state()["enriched"], new["id"]: memory_aux.text_hash(text)})
    action, target = "added", None
    if verdict and verdict["decision"] == "supersede":
        old = by_id[verdict["target"]]
        if _may_supersede(old, source, text):
            _supersede(old, new, verdict["reason"] or "replaced by a newer plan", by)
            action, target = "superseded", old["id"]
        else:  # not a dated plan, or it would overwrite what the user said: flag it, don't decide
            flags.append(_flag_contradiction(new, old, by))
            action, target = "flagged", old["id"]
    elif verdict and verdict["decision"] == "contradict":
        old = by_id[verdict["target"]]
        flags.append(_flag_contradiction(new, old, by))
        action, target = "flagged", old["id"]
    elif verdict is None and candidates:
        # no judge: still flag the one thing code can see - the same subject with a different date
        for c in candidates:
            if _same_subject(text, c["memory"]["text"]) >= MOVED_OVERLAP and _may_supersede(c["memory"], source, text):
                flags.append(_flag_contradiction(new, c["memory"], "rule"))
                action, target = "flagged", c["memory"]["id"]
                break
        queue = memory_aux.state()["queue"]
        memory_aux.update_state(queue=[*queue, {"id": new["id"], "at": time.time()}])
        flags.append("saved without the duplicate check; Ultron will check it tonight")
    _after_add(new, pool)
    return {"action": action, "memory": memory_store.get(new["id"]) or new, "target": target, "flags": flags, "by": by}


def learn(text: str) -> list[dict]:
    """Like memory_store.learn (the "- [category] fact" lines of a conversation note), but each fact goes
    through smart_add. Returns the memories that were added or changed."""
    saved = []
    for match in map(memory_store.LEARNED.match, text.splitlines()):
        if not match or len(saved) >= memory_store.MAX_LEARNED:
            continue
        try:
            result = smart_add(" ".join(match[2].split()), match[1].lower(), source="conversation_summary")
        except ValueError:
            continue  # a secret, too long or a made-up category
        if result["action"] != "duplicate":
            saved.append(result["memory"])
    return saved


def process_queue(timeout: float = 60.0) -> list[dict]:
    """Memories saved while the judge was down: look at each now. Returns what was done:
    [{"id", "action"}]. Memories that are gone or already archived are dropped from the queue."""
    state = memory_aux.state()
    left, done = [], []
    for item in state["queue"]:
        new = memory_store.get(item["id"])
        if new is None or new["archived"]:
            continue
        pool = [m for m in memory_store.entries() if m["id"] != new["id"]]
        store = memory_aux.embeddings()
        vectors = {m["id"]: v for m in [new, *pool] if (v := memory_aux.vector_for(m, config.EMBED_MODEL, store))}
        candidates = similar(new["text"], pool, vectors, vectors.get(new["id"]))
        if not candidates:
            continue
        private = memory_ai.is_private(new) or any(memory_ai.is_private(c["memory"]) for c in candidates)
        try:
            verdict, by = memory_ai.judge(new["text"], new["category"], [c["memory"] for c in candidates], private, timeout)
        except memory_ai.Unavailable:
            left.append(item)
            continue
        by_id = {c["memory"]["id"]: c["memory"] for c in candidates}
        target = by_id.get(verdict["target"])
        action = "kept"
        if target and verdict["decision"] in ("duplicate", "merge"):
            _merge_into(target, new["text"], verdict["merged_text"] or None, new["source"], "merge")
            memory_store.archive(new["id"], f"merged into {target['id']}")
            action = "merged"
        elif target and verdict["decision"] == "supersede" and _may_supersede(target, new["source"], new["text"]):
            _supersede(target, new, verdict["reason"] or "replaced by a newer plan", by)
            action = "superseded"
        elif target and verdict["decision"] in ("supersede", "contradict"):
            _flag_contradiction(new, target, by)
            action = "flagged"
        done.append({"id": new["id"], "action": action})
    memory_aux.update_state(queue=left)
    return done
