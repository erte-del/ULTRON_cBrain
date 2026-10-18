"""Letting memory age gracefully. Nothing here deletes anything.

  - A memory whose expiry date has passed is ARCHIVED (reason "expired"), unless it is pinned. Archived
    memories leave the prompt, recall and the vault but stay in memory.json (`memory_store.restore` undoes it).
  - Guesses (source "inferred") that nobody used for 30 days lose 0.1 confidence a week; below 0.3 they are
    PROPOSED for archiving.
  - Once a week a list of proposals is made for you to approve or reject: near-duplicates to merge and weak
    guesses to archive. They are only applied when you approve (`approve` / `reject`).
"""

import logging
import time

import memory_jobs
import memory_write
from storage import memory_aux, memory_store

log = logging.getLogger("ultron.memory")

UNUSED_DAYS = 30
WEEK_S = 7 * 86400
DECAY_STEP = 0.1
ARCHIVE_BELOW = 0.3


def expire(now: float | None = None, apply: bool = True) -> list[str]:
    """Archive memories past their expiry date. Returns their ids."""
    now = now or time.time()
    due = [m["id"] for m in memory_store.entries() if m["expires_at"] and m["expires_at"] < now and not m["pinned"]]
    if apply:
        for memory_id in due:
            memory_store.archive(memory_id, "expired")
    return due


def fade(now: float | None = None, apply: bool = True) -> list[str]:
    """Weekly: unused guesses lose confidence. Returns the ids that changed."""
    now = now or time.time()
    state = memory_aux.state()
    if now - state["last_decay"] < WEEK_S:
        return []
    changed = []
    for m in memory_store.entries():
        last = m["last_used_at"] or m["created"]
        if m["source"] == "inferred" and not m["pinned"] and now - last > UNUSED_DAYS * 86400 and m["confidence"] > 0.1:
            changed.append(m["id"])
            if apply:
                memory_store.patch(m["id"], confidence=round(max(0.1, m["confidence"] - DECAY_STEP), 2), mirror_too=False)
    if apply:
        memory_aux.update_state(last_decay=now)
    return changed


def propose(now: float | None = None, apply: bool = True) -> list[dict]:
    """This week's suggestions (replaces the ones still waiting): merges and archives. Needs your approval."""
    memories = memory_store._read()
    dups, _ = memory_jobs._problems(memories)
    by_id = {m["id"]: m for m in memories}
    items = [{"id": f"prop_{d['a']}_{d['b']}", "kind": "merge", "ids": [d["a"], d["b"]], "status": "waiting",
              "reason": f"near-identical wording ({d['score']})"} for d in dups]
    items += [{"id": f"prop_{m['id']}", "kind": "archive", "ids": [m["id"]], "status": "waiting",
               "reason": f"a guess nobody used, confidence {m['confidence']:.1f}"}
              for m in memories if m["source"] == "inferred" and not m["archived"] and not m["pinned"] and m["confidence"] < ARCHIVE_BELOW]
    kept = [p for p in memory_aux.state()["proposals"] if p["status"] in ("approved", "rejected")]
    rejected = {p["id"] for p in kept if p["status"] == "rejected"}  # asked once: not again
    items = [p for p in items if p["id"] not in rejected and all(i in by_id for i in p["ids"])]
    if apply:
        memory_aux.update_state(proposals=[*kept, *items])
    return items


def approve(proposal_id: str) -> str:
    """Do what a proposal says. KeyError if there's no such waiting proposal."""
    state = memory_aux.state()
    prop = next((p for p in state["proposals"] if p["id"] == proposal_id and p["status"] == "waiting"), None)
    if prop is None:
        raise KeyError(proposal_id)
    if prop["kind"] == "archive":
        memory_store.archive(prop["ids"][0], "approved: " + prop["reason"])
    else:  # merge the newer into the older; the newer is archived with its text kept
        keep, other = sorted((memory_store.get(i) for i in prop["ids"]), key=lambda m: m["created"])
        memory_write._merge_into(keep, other["text"], None, other["source"], "merge")
        memory_store.archive(other["id"], f"merged into {keep['id']} (approved)")
    prop["status"] = "approved"
    memory_aux.update_state(proposals=state["proposals"])
    return prop["reason"]


def reject(proposal_id: str) -> None:
    state = memory_aux.state()
    for p in state["proposals"]:
        if p["id"] == proposal_id:
            p["status"] = "rejected"
    memory_aux.update_state(proposals=state["proposals"])


def run(apply: bool = True, now: float | None = None) -> dict:
    expired = expire(now, apply)
    faded = fade(now, apply)
    proposals = propose(now, apply)
    return {"expired": expired, "faded": faded, "proposals": proposals}
