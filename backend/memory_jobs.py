"""The upkeep of Memory v2: the migration, the nightly pass and the loop that runs it.

`refresh()` is both. It is safe to run any number of times (idempotent): it fills in the v2 fields,
works out each memory's people, projects and topics with the local model (only the new or changed
ones; answers are cached), makes the vectors, rebuilds the automatic links and looks at memories that
were saved while the judge was down.

  - apply=False  computes everything and returns what it WOULD do; writes nothing
  - apply=True   writes memory.json (after a timestamped copy in storage/backups/ the first time),
                 the vectors, the links and the state file

The loop (modelled on watcher.py) runs `refresh` once a night, but only after the migration has been
applied once on purpose (`python memory_cli.py migrate`), and not at all when JARVIS_MEMORY_V2=0.
"""

import asyncio
import logging
import time
from datetime import datetime

import config
import memory_ai
import memory_graph
import memory_text
import memory_write
from storage import memory_aux, memory_store

log = logging.getLogger("ultron.memory")

CHECK_EVERY_S = 600
NIGHTLY_HOUR = 3          # local time after which the day's pass may run
MIN_GAP_S = 20 * 3600     # ... and at least this long after the last one


def _problems(memories: list[dict]) -> tuple[list[dict], list[dict]]:
    """(near duplicates, date conflicts) among the memories in use, for the report and the weekly list."""
    live = [m for m in memories if not m["archived"]]
    dups, conflicts = [], []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            subject = memory_write._same_subject(a["text"], b["text"])
            da, db = memory_write.date_of(a), memory_write.date_of(b)
            if subject >= 0.7 and da == db:
                dups.append({"a": a["id"], "b": b["id"], "score": round(subject, 2)})
            elif subject >= memory_write.MOVED_OVERLAP and da and db and da != db:
                conflicts.append({"a": a["id"], "b": b["id"], "dates": [da.isoformat(), db.isoformat()]})
    return dups, conflicts


def _similar_pairs(memories: list[dict], low: float = 0.4, high: float = 0.7, top: int = 10) -> list[dict]:
    """Pairs that say similar things without being copies (for you to look at; nothing is done with them)."""
    live = [m for m in memories if not m["archived"]]
    found = []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            score = memory_write._same_subject(a["text"], b["text"])
            if low <= score < high:
                found.append({"a": a["id"], "b": b["id"], "score": round(score, 2)})
    return sorted(found, key=lambda p: -p["score"])[:top]


def refresh(apply: bool = False) -> dict:
    """See the module docstring. Returns a report dict (see format_report)."""
    raw = memory_store._read_raw()
    old_schema = any("last_used_at" not in m for m in raw)
    memories = memory_store._read()
    state = memory_aux.state()
    report: dict = {"total": len(memories), "active": sum(not m["archived"] for m in memories),
                    "old_schema": old_schema, "applied": apply}

    # 1. sensitive flag and expiry date from the text alone (no model)
    changed_rules = []
    for m in memories:
        sens = m["sensitive"] or memory_text.sensitive_text(m["text"])
        expiry = m["expires_at"] if m["expires_at"] else memory_text.expiry_for(m["text"], memory_store._today(m["created"]))
        if (sens, expiry) != (m["sensitive"], m["expires_at"]):
            changed_rules.append(m["id"])
        m["sensitive"], m["expires_at"] = sens, expiry
    report["rule_changes"] = changed_rules

    # 2. people / projects / topics from the local model (new or changed memories only)
    todo = [m for m in memories if not m["archived"] and state["enriched"].get(m["id"]) != memory_aux.text_hash(m["text"])]
    found = memory_ai.enrich(todo) if todo and memory_ai.local_ready() else {}
    for m in todo:
        if m["id"] in found:
            m["entities"], m["topics"] = found[m["id"]]["entities"], found[m["id"]]["topics"]
            m["sensitive"] = m["sensitive"] or found[m["id"]]["sensitive"]
    report["enriched"] = len(found)
    report["enrich_missing"] = len(todo) - len(found)

    # 3. vectors (the local embedding model, if it's there)
    active = [m for m in memories if not m["archived"]]
    vectors_store, embedded, available = memory_ai.refresh_embeddings(active, save=apply)
    report["embedded"], report["embeddings_available"] = embedded, available
    vectors = {m["id"]: v for m in active if (v := memory_aux.vector_for(m, config.EMBED_MODEL, vectors_store))}

    # 4. links
    report["links"] = memory_graph.sync_auto_links(active, vectors, apply=apply)
    report["near_duplicates"], report["date_conflicts"] = _problems(memories)
    report["similar"] = _similar_pairs(memories)
    report["memories"] = memories

    if apply:
        _write_back(memories, found, report)
        done = memory_write.process_queue() if (memory_ai.local_ready() or memory_ai.claude_allowed()) else []
        report["queue_done"] = done
        import memory_decay, memory_insights  # after the labels and links they depend on
        report["decay"] = memory_decay.run(apply=True)
        report["insights"] = memory_insights.run(apply=True)
        memory_aux.update_state(migrated_at=state["migrated_at"] or time.time(), last_nightly=time.time())
    else:
        report["queue_done"] = []
    return report


def _write_back(memories: list[dict], found: dict, report: dict) -> None:
    """Merge what was worked out into the file as it is now (it may have changed while the model worked)."""
    with memory_store._lock:
        current = memory_store._read()
        mine = {m["id"]: m for m in memories}
        changed = report["old_schema"]
        for m in current:
            new = mine.get(m["id"])
            if new is None or new["text"] != m["text"]:
                continue  # added or edited meanwhile: next time
            fields = {"sensitive": new["sensitive"], "expires_at": new["expires_at"]}
            if m["id"] in found:
                fields.update(entities=new["entities"], topics=new["topics"])
            for key, value in fields.items():
                if m[key] != value:
                    m[key], changed = value, True
        if changed:
            report["backup"] = memory_store.backup_old_schema()
            memory_store._write(current)
    enriched = memory_aux.state()["enriched"]
    memory_aux.update_state(enriched={**enriched, **{i: memory_aux.text_hash(mine[i]["text"]) for i in found}})


# --- the report you read before saying "go" ------------------------------------------------

def format_report(report: dict, queries: tuple[str, ...] = ()) -> str:
    """Plain text: what the pass found / did, with real examples."""
    by_id = {m["id"]: m for m in report["memories"]}
    short = lambda i, n=90: f"{i} {by_id[i]['text'][:n]}" if i in by_id else i  # noqa: E731
    lines = [f"MEMORY V2 - {'APPLIED' if report['applied'] else 'DRY RUN (nothing was written)'}",
             f"{report['total']} memories ({report['active']} in use). Old file format: {'yes' if report['old_schema'] else 'no'}."]
    if report.get("backup") and report["applied"]:
        lines.append(f"Backup of memory.json: storage/backups/{report['backup']}")
    elif report["old_schema"]:
        lines.append("A timestamped copy of memory.json goes to storage/backups/ before the first real write.")
    lines.append(f"Embedding model {config.EMBED_MODEL!r}: "
                 + ("answering" if report["embeddings_available"] else "NOT available (ollama pull it); recall uses word matching"))
    lines += ["", f"ENTITIES AND TOPICS (local model {config.OLLAMA_MODEL or '-'}): {report['enriched']} labelled, "
                  f"{report['enrich_missing']} not (model down or no answer)"]
    with_labels = [m for m in report["memories"] if m["entities"] or m["topics"]]
    for m in with_labels[:12]:
        ents = ", ".join(f"{e['name']} ({e['type']})" for e in m["entities"]) or "-"
        lines.append(f"  {m['id']}: {m['text'][:70]}\n      entities: {ents} | topics: {', '.join(m['topics']) or '-'}")
    people = sorted({e["name"] for m in report["memories"] for e in m["entities"] if e["type"] == "person"})
    projects = sorted({e["name"] for m in report["memories"] for e in m["entities"] if e["type"] == "project"})
    lines.append(f"  All people: {', '.join(people) or '-'}\n  All projects: {', '.join(projects) or '-'}")

    sens = [m for m in report["memories"] if m["sensitive"]]
    lines += ["", f"SENSITIVE (family / health / money; neutral wording in notifications, kept away from hosted models): {len(sens)}"]
    lines += [f"  {short(m['id'], 80)}" for m in sens[:8]]
    expiring = [m for m in report["memories"] if m["expires_at"]]
    lines += ["", f"EXPIRY DATES found in the text: {len(expiring)}"]
    lines += [f"  {datetime.fromtimestamp(m['expires_at']):%Y-%m-%d}  {short(m['id'], 80)}" for m in expiring]

    links = report["links"]
    lines += ["", f"LINKS: {len(links['added'])} to add, {len(links['removed'])} to remove, {links['kept']} unchanged"]
    for l in links["added"][:20]:
        lines.append(f"  {l['kind']} {l['strength']:.2f} ({l['why']})\n      {short(l['a'], 70)}\n      {short(l['b'], 70)}")
    if len(links["added"]) > 20:
        lines.append(f"  ... and {len(links['added']) - 20} more")

    lines += ["", f"NEAR-DUPLICATES: {len(report['near_duplicates'])}"]
    for d in report["near_duplicates"][:10]:
        lines.append(f"  {d['score']}\n      {short(d['a'], 80)}\n      {short(d['b'], 80)}")
    lines += ["", "SIMILAR BUT NOT COPIES (word overlap 0.4-0.7; nothing is merged automatically):"]
    for d in report.get("similar", []):
        lines.append(f"  {d['score']}\n      {short(d['a'], 80)}\n      {short(d['b'], 80)}")
    lines += ["", f"SAME SUBJECT, DIFFERENT DATES (possible moved plans / contradictions): {len(report['date_conflicts'])}"]
    for d in report["date_conflicts"][:10]:
        lines.append(f"  {d['dates']}\n      {short(d['a'], 80)}\n      {short(d['b'], 80)}")
    if report.get("decay"):
        d = report["decay"]
        lines += ["", f"DECAY: {len(d['expired'])} expired and archived, {len(d['faded'])} guesses faded, "
                      f"{len(d['proposals'])} proposals waiting for you"]
        lines += [f"  {p['kind']}: {', '.join(p['ids'])} - {p['reason']}" for p in d["proposals"][:8]]
    if report.get("insights"):
        found = report["insights"]["found"]
        lines += ["", f"INSIGHTS: {len(found)} found ({report['insights']['new']} new); shown only at confidence 0.6 or more"]
        lines += [f"  [{i['kind']} {i['confidence']:.2f}] {i['text']}  <- {', '.join(i['evidence'])}" for i in found[:12]]
    if report.get("queue_done"):
        lines += ["", f"QUEUED CHECKS DONE: {report['queue_done']}"]
    return "\n".join(lines)


def old_recall(queries: tuple[str, ...]) -> dict[str, list[str]]:
    """What the old word-match recall finds for each query (ids)."""
    return {q: [m["id"] for m in memory_store.search(q)] for q in queries}


def compare_recall(queries: tuple[str, ...], old: dict[str, list[str]]) -> str:
    """The old recall's answers (taken before) next to the new recall on the memories as they are now."""
    lines = ["RECALL, BEFORE (old word match: every word must appear) vs AFTER (new)"]
    for q in queries:
        new = memory_search_results(q)
        lines.append(f'\n"{q}"')
        lines.append("  before: " + (" | ".join(old[q][:8]) or "nothing"))
        lines.append("  after:")
        for hit in new:
            lines.append(f"    {hit['id']}  {hit['text'][:80]}")
            for r in hit.get("related", []):
                lines.append(f"        -> {r['link']}: {r['id']} {r['text'][:70]} ({r['date']})")
        if not new:
            lines.append("    nothing")
    return "\n".join(lines)


def memory_search_results(query: str) -> list[dict]:
    import memory_search
    return memory_search.search(query, touch=False, limit=5)


# --- the nightly loop ----------------------------------------------------------------------

def due(now: datetime, state: dict) -> bool:
    """Time for the night's pass? Only after the migration was applied on purpose, never with the kill switch off."""
    if not config.MEMORY_V2 or not state["migrated_at"]:
        return False
    today_start = now.replace(hour=NIGHTLY_HOUR, minute=0, second=0, microsecond=0)
    return now >= today_start and state["last_nightly"] < today_start.timestamp() and now.timestamp() - state["last_nightly"] >= MIN_GAP_S


async def run_nightly() -> dict:
    """One pass (in a thread: it talks to Ollama). With JARVIS_MEMORY_DRY_RUN=1 it only computes."""
    report = await asyncio.to_thread(refresh, not config.MEMORY_DRY_RUN)
    log.info("Memory pass: %d labelled, %d links to add, %d to remove%s", report["enriched"], len(report["links"]["added"]),
             len(report["links"]["removed"]), " (dry run)" if config.MEMORY_DRY_RUN else "")
    if config.MEMORY_DRY_RUN:
        memory_aux.update_state(last_nightly=time.time())
    return report


async def loop() -> None:
    """Started with the server; runs until it's cancelled at shutdown."""
    while True:
        try:
            if due(datetime.now(), memory_aux.state()):
                await run_nightly()
        except Exception:
            log.exception("Memory pass failed")
        await asyncio.sleep(CHECK_EVERY_S)
