"""How memories connect (storage/memory_links.json): no model needed.

Automatic links come from what two memories share:
  - the same person            -> same_person  (strong)
  - the same project           -> same_project
  - the same organisation / place / thing -> same_topic
  - two or more topics         -> same_topic   (weaker)
  - nearly the same meaning    -> same_topic   (embedding similarity, when the local embedding model is there)
The judge (memory_write.py) adds the kinds that need reading: supersedes, contradicts, follow_up_of, caused_by.

Automatic links are recomputed by the nightly pass and when a memory is saved; links the judge or you made
are never removed by it, and a link you reject is not made again.
"""

import collections
import re

import numpy as np

import memory_text

from storage import memory_aux

MAX_PER_MEMORY = 8      # a memory keeps at most this many automatic links (the strongest)
GENERIC_ENTITY = 12     # a name in more memories than this ("Ultron") says nothing about any pair
SEMANTIC_MIN = 0.80     # cosine of nomic-embed-text vectors at which two notes are "about the same thing"
CONFIRM_MIN = 0.60      # a weak signal (a shared tool name, shared topic words) only counts if the meanings agree this much
NEAR_MISS_MIN = 1.0     # cosine band [this, SEMANTIC_MIN) linked on meaning alone; 1.0 = off (see README: measured, then decided)
# Topic words that say nothing about what a memory is about.
GENERIC_TOPICS = frozenset("projects project development code coding technology tech ai tools preferences general "
                           "integration features feature apps app".split())
RARE_WORD_MAX = 12      # a word in more memories than this is too common to connect two of them
RARE_WORD_COSINE = 0.65  # ... and a shared rare word only links when the meanings agree this much
# Tools and platforms: they appear in many unrelated notes, so they are never "the project" or "the person".
TOOLS = frozenset("""obsidian github android ios windows macos mac linux python javascript typescript html css kotlin
react node vite vercel claude chatgpt ollama whatsapp spotify telegram tailscale ticktick gmail google discord
instagram youtube steam""".split())
# Words that are rare enough but say nothing about the subject.
COMMON_WORDS = frozenset("""build building built plan planning free open created saved project feature code monday tuesday
wednesday thursday friday saturday sunday january february march april june july august september october
november december turkish english dubai note notes reel reels prompt prompts player ultron user wants plans using used working""".split())
KIND_FOR_TYPE = {"person": ("same_person", 0.9), "project": ("same_project", 0.8)}


_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")


def _proper_words(text: str) -> frozenset[str]:
    """Stems of the names and acronyms in a text: ALL-CAPS ("IPTV") or Capitalised ("Supabase") words that
    don't just start a sentence. Ordinary words ("want", "time") never count as a shared subject."""
    found = set()
    for m in _WORDS.finditer(text):
        word = m.group()
        starts = not text[:m.start()].rstrip().rstrip('"\'(') or text[:m.start()].rstrip()[-1:] in ".!?:;"
        if (word.isupper() and len(word) > 1) or (word[0].isupper() and not starts and not word.isupper()):
            found.add(memory_text.stem(word))
    return frozenset(found)


def _entity_map(memories: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """{entity name (lowercase): [(memory id, type), ...]}"""
    found: dict[str, list[tuple[str, str]]] = {}
    for m in memories:
        for e in m["entities"]:
            found.setdefault(e["name"].casefold(), []).append((m["id"], e["type"]))
    # One type per name: the model labels the same name differently from note to note, and a link's kind
    # must not depend on which note happened to call it a "project". Tools are never a project or a person.
    for name, owners in found.items():
        if name in TOOLS:
            kind = "other"
        else:
            kind = max(collections.Counter(t for _, t in owners).items(), key=lambda kv: (kv[1], kv[0] == "other"))[0]
        found[name] = [(i, kind) for i, _ in owners]
    return found


def proposed_links(memories: list[dict], vectors: dict[str, list[float]] | None = None) -> list[dict]:
    """The automatic links these (active) memories justify, strongest first:
    [{"a", "b", "kind", "strength", "why"}].

    A shared person or project name is enough. A shared organisation / place / tool name ("GitHub") or shared
    topic words are only a hint: with vectors they must also be close in meaning (CONFIRM_MIN); without vectors
    they can't be checked, so they make no link."""
    memories = [m for m in memories if not m.get("archived")]
    best: dict[tuple[str, str], dict] = {}
    vectors = vectors or {}

    def agree_at(a: str, b: str, minimum: float) -> bool:
        if a not in vectors or b not in vectors:
            return False
        x, y = np.array(vectors[a], dtype=np.float32), np.array(vectors[b], dtype=np.float32)
        return float(x @ y / max(np.linalg.norm(x) * np.linalg.norm(y), 1e-9)) >= minimum

    def agree(a: str, b: str) -> bool:
        return agree_at(a, b, CONFIRM_MIN)

    def offer(a: str, b: str, kind: str, strength: float, why: str) -> None:
        key = tuple(sorted((a, b)))
        if key not in best or strength > best[key]["strength"]:
            best[key] = {"a": key[0], "b": key[1], "kind": kind, "strength": round(strength, 3), "why": why}

    limit = max(GENERIC_ENTITY, len(memories) * 0.15)
    for name, owners in _entity_map(memories).items():
        if len(owners) < 2 or len(owners) > limit:
            continue
        for i, (a, ta) in enumerate(owners):
            for b, tb in owners[i + 1:]:
                kind, strength = KIND_FOR_TYPE.get(ta if ta in KIND_FOR_TYPE else tb, ("same_topic", 0.55))
                if kind == "same_topic" and not agree(a, b):
                    continue  # a shared tool or platform name alone is not a connection
                offer(a, b, kind, strength, f"both mention {name}")

    by_topic: dict[str, list[str]] = {}
    for m in memories:
        for t in m["topics"]:
            if t in GENERIC_TOPICS:
                continue
            by_topic.setdefault(t, []).append(m["id"])
    shared: dict[tuple[str, str], list[str]] = {}
    for topic, ids in by_topic.items():
        if len(ids) > max(GENERIC_ENTITY, len(memories) * 0.2):
            continue
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                shared.setdefault(tuple(sorted((a, b))), []).append(topic)
    for (a, b), topics in shared.items():
        if len(topics) >= 2 and agree(a, b):
            offer(a, b, "same_topic", min(0.6, 0.35 + 0.1 * (len(topics) - 2)), "both about " + ", ".join(topics[:3]))

    # A distinctive word two memories both use ("iptv"), when their meanings agree too.
    df = collections.Counter(w for m in memories for w in memory_text.token_set(m["text"]))
    rare = {w for w, n in df.items() if 2 <= n <= RARE_WORD_MAX and len(w) > 3 and w not in COMMON_WORDS and w not in TOOLS}
    words = {m["id"]: _proper_words(m["text"]) & rare for m in memories}
    for i, a in enumerate(memories):
        for b in memories[i + 1:]:
            shared = words[a["id"]] & words[b["id"]]
            if shared and agree_at(a["id"], b["id"], RARE_WORD_COSINE):
                offer(a["id"], b["id"], "same_topic", 0.5, "both about " + ", ".join(sorted(shared)[:3]))

    ids = [m["id"] for m in memories if m["id"] in vectors]
    if len(ids) > 1:
        matrix = np.array([vectors[i] for i in ids], dtype=np.float32)
        matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
        sims = matrix @ matrix.T
        for i, j in zip(*np.where(np.triu(sims, 1) >= min(SEMANTIC_MIN, NEAR_MISS_MIN))):
            weak = sims[i, j] < SEMANTIC_MIN
            offer(ids[i], ids[j], "same_topic", float(sims[i, j]) * (0.8 if weak else 1.0),
                  f"{'somewhat ' if weak else ''}similar meaning ({sims[i, j]:.2f})")

    kept, count = [], {}
    for link in sorted(best.values(), key=lambda l: -l["strength"]):
        if count.get(link["a"], 0) < MAX_PER_MEMORY and count.get(link["b"], 0) < MAX_PER_MEMORY:
            kept.append(link)
            for end in (link["a"], link["b"]):
                count[end] = count.get(end, 0) + 1
    return kept


def sync_auto_links(memories: list[dict], vectors: dict | None, apply: bool = True) -> dict:
    """Make the automatic links match what the memories justify now. Returns what changed:
    {"added": [...], "removed": [...], "kept": n} (nothing is written when apply is False)."""
    wanted = proposed_links(memories, vectors)
    wanted_keys = {memory_aux.link_key(l["a"], l["b"], l["kind"]): l for l in wanted}
    existing = memory_aux.links(include_rejected=True)
    have = {memory_aux.link_key(l["a"], l["b"], l["kind"]): l for l in existing}
    added = [l for k, l in wanted_keys.items() if k not in have]
    stale = [l for k, l in have.items() if l["source"] == "auto" and k not in wanted_keys and l.get("status") != "rejected"]
    if apply:
        for l in added:
            memory_aux.add_link(l["a"], l["b"], l["kind"], l["strength"], "auto", l["why"])
        if stale:
            drop = {memory_aux.link_key(l["a"], l["b"], l["kind"]) for l in stale}
            memory_aux.save_links([l for l in memory_aux.links(include_rejected=True)
                                   if memory_aux.link_key(l["a"], l["b"], l["kind"]) not in drop])
    return {"added": added, "removed": stale, "kept": len(wanted) - len(added)}


def link_new(memory: dict, others: list[dict], vectors: dict | None) -> list[dict]:
    """Links for one fresh memory against the rest (when it is saved). Returns the ones made."""
    pool = [m for m in others if not m.get("archived") and m["id"] != memory["id"]]
    made = []
    for l in proposed_links([memory, *pool], vectors):
        if memory["id"] in (l["a"], l["b"]):
            if memory_aux.add_link(l["a"], l["b"], l["kind"], l["strength"], "auto", l["why"]):
                made.append(l)
    return made
