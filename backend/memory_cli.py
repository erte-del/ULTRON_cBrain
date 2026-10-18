"""Memory v2 from the command line (run in backend/ with the venv's python):

  python memory_cli.py dry-run [query ...]  try the whole migration on a COPY of your memory in a temp folder and
                                            print what it would do, plus recall before/after for the queries.
                                            Your real files are not touched (only the model-call cache and cost log).
  python memory_cli.py migrate              do it for real (copies memory.json to storage/backups/ first)
  python memory_cli.py cost [days]          model calls and tokens per day (local vs Claude)
  python memory_cli.py insights             what the pattern finder has found (and what is shown)
  python memory_cli.py nudges on|off|status switch the quiet proactive nudges (default: off)
  python memory_cli.py proposals            merges / archives waiting for your approval
  python memory_cli.py approve|reject ID    act on one proposal
  python memory_cli.py queue                answer the "check it tonight" queue now
"""

import shutil
import sys
import tempfile
from pathlib import Path

import config
import memory_ai
import memory_jobs
from storage import memory_aux, memory_store

SIDECARS = ("memory_embeddings.json", "memory_links.json", "memory_insights.json", "memory_state.json")
SAMPLE_QUERIES = ("EasyTV pricing", "Supabase", "exam", "birthday", "what does he like")


def dry_run(queries: tuple[str, ...]) -> str:
    real_file, real_vault = memory_store.MEMORY_FILE, config.VAULT_DIR
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / "memory.json"
        shutil.copy2(real_file, copy)
        for name in SIDECARS:
            if (real_file.parent / name).exists():
                shutil.copy2(real_file.parent / name, Path(folder) / name)
        memory_store.MEMORY_FILE, config.VAULT_DIR = copy, None  # the copy, and never the real vault
        try:
            old = memory_jobs.old_recall(queries)  # the old recall, before the copy is migrated
            report = memory_jobs.refresh(apply=True)
            report["applied"] = False  # it was applied to the copy only
            after = memory_jobs.compare_recall(queries, old)
            cache = memory_aux.state()
        finally:
            memory_store.MEMORY_FILE, config.VAULT_DIR = real_file, real_vault
        memory_aux.update_state(cache={**memory_aux.state()["cache"], **cache["cache"]},
                                cost=cache["cost"] or memory_aux.state()["cost"])  # keep what the model already answered
    return memory_jobs.format_report(report) + "\n\n" + after


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "dry-run"
    if command == "dry-run":
        print(dry_run(tuple(argv[1:]) or SAMPLE_QUERIES))
    elif command == "migrate":
        print(memory_jobs.format_report(memory_jobs.refresh(apply=True)))
    elif command == "cost":
        print(memory_ai.cost_report(int(argv[1]) if len(argv) > 1 else 7))
    elif command == "insights":
        import memory_insights
        shown = {i["id"] for i in memory_insights.visible()}
        for i in memory_aux.insights():
            print(f"{'*' if i['id'] in shown else ' '} {i['id']} [{i['kind']} {i['confidence']:.2f} {i['status']}] "
                  f"{i['text']}  <- {', '.join(i['evidence'])}")
        print("(* = may be shown; below 0.6 confidence is stored but never shown)")
    elif command == "nudges":
        import memory_surface
        if len(argv) > 1 and argv[1] in ("on", "off"):
            memory_surface.set_proactive(argv[1] == "on")
        print("proactive nudges:", "ON" if memory_surface.proactive() else "off")
    elif command in ("proposals", "approve", "reject"):
        import memory_decay
        if command == "approve":
            print(memory_decay.approve(argv[1]))
        elif command == "reject":
            memory_decay.reject(argv[1])
        for p in memory_aux.state()["proposals"]:
            print(p["status"], p["id"], p["kind"], p["ids"], p["reason"])
    elif command == "queue":
        import memory_write
        print(memory_write.process_queue())
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
