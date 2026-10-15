"""Compares local models on Ultron's real tool calling.

Each case is a message plus the tool call(s) a good model should make. The model gets Ultron's own
trimmed system prompt and the real tool schemas for the groups that message switches on (the same
way brain/capabilities.py does for the Ollama brain). Nothing is executed: we only look at which
tools the model asked for and whether the arguments are right.

  python scripts/bench_ollama_tools.py qwen3:14b gpt-oss:20b gemma4:e4b [--runs 2] [--json out.json]

Works on Mac and Windows. Ollama must be running (JARVIS_OLLAMA_URL, default localhost:11434).
Not covered: claude.ai connector tools (Gmail, Calendar, ...) and multi-step tool loops.
"""

import argparse
import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


@dataclass
class Case:
    name: str
    text: str
    expect: list[str]  # tool names that must all be called ([] = answer without any tool)
    check: dict = field(default_factory=dict)  # tool name -> function(args) -> bool


def _has(*words):
    return lambda a: all(w in json.dumps(a, ensure_ascii=False).lower() for w in words)


CASES = [
    Case("remember", "Remember that my sister's name is Lina.", ["remember"], {"remember": _has("lina")}),
    Case("recall", "What do you know about Lina?", ["recall"], {"recall": _has("lina")}),
    Case("jobs_list", "Which scheduled jobs do I have?", ["list_jobs"]),
    Case("job_create", "Every weekday at 7am give me a short briefing of my day.", ["schedule_job"],
         {"schedule_job": lambda a: a.get("at") == "07:00" and len(a.get("days") or []) == 5}),
    Case("canvas_table", "Put a table on the canvas with fruit and prices: apple 1.20, pear 1.50.", ["show_on_canvas"],
         {"show_on_canvas": lambda a: a.get("kind") == "table"}),
    Case("text_me", "Text me 'leaving now'.", ["text_me"], {"text_me": _has("leaving now")}),
    Case("new_chat", "Let's start a fresh chat.", ["new_chat"]),
    Case("notes", "Search my notes for chemistry.", ["search_notes"], {"search_notes": _has("chemistry")}),
    Case("mac_battery", "How much battery does my Mac have left?", ["mac_read"]),
    Case("maps", "How long does it take to drive to the airport?", ["maps"]),
    Case("music", "Play some jazz.", ["spotify_control"]),
    Case("two_tools", "Remember that I like oat milk, and tell me which jobs I have scheduled.",
         ["remember", "list_jobs"]),
    Case("chat_hi", "Hi, how are you?", []),
    Case("chat_math", "What is 12 times 12?", []),
    Case("no_tool_available", "Order me a pizza from the place on the corner.", []),
]


STRICT = False  # --strict: offer the raw schemas, as before tools/lenient.py


ORIGINAL: dict = {}  # tool name -> the real schema, which an answer must satisfy once tidied


def build(case: Case):
    """The system prompt and tool schemas the Ollama brain would give for this message."""
    from brain import capabilities
    from tools import registry

    groups = capabilities.match(case.text)
    names = capabilities.visible_tools(groups)
    by_name = {t.tool.name: t.tool for t in registry.TOOLS}
    from tools import lenient
    shown = {n: by_name[n] if STRICT else lenient.relax(by_name[n]) for n in names}
    tools = [{"type": "function", "function": {"name": n, "description": shown[n].description,
                                               "parameters": shown[n].input_schema}} for n in sorted(names)]
    ORIGINAL.update({n: by_name[n].input_schema for n in names})
    return capabilities.system_prompt(groups), tools, groups


def score(case: Case, calls: list[dict], valid: dict) -> dict:
    """calls: [{"name", "args"}]. valid: tool name -> True when the args match its JSON schema."""
    called = [c["name"] for c in calls]
    if not case.expect:
        return {"ok": not called, "picked": not called, "args": True, "extra": called}
    picked = all(e in called for e in case.expect)
    extra = [n for n in called if n not in case.expect]
    args = picked and all(
        valid.get(c["name"], False) and case.check.get(c["name"], lambda a: True)(c["args"])
        for c in calls if c["name"] in case.expect)
    return {"ok": picked and args and not extra, "picked": picked, "args": args, "extra": extra}


def schema_ok(tools: list[dict], call: dict) -> bool:
    spec = ORIGINAL.get(call["name"]) if call["name"] in {t["function"]["name"] for t in tools} else None
    if spec is None:
        return False  # invented tool
    if not STRICT:
        from tools import lenient
        call["args"] = lenient.clean(call["args"], spec)  # what the tool would really receive
    try:
        import jsonschema
        jsonschema.validate(call["args"], spec)
        return True
    except ImportError:
        return all(k in call["args"] for k in spec.get("required", []))
    except Exception:
        return False


def ask(url: str, model: str, system: str, tools: list[dict], text: str, num_ctx: int) -> dict:
    body = {"model": model, "stream": False, "tools": tools, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": f"[Now: {datetime.now():%A %d %B %Y, %H:%M}]\n{text}"}],
            "options": {"num_ctx": num_ctx, "temperature": 0.3}}
    if not model.startswith("gpt-oss"):
        body["think"] = False  # gpt-oss can't switch thinking off (only low/medium/high)
    else:
        body["think"] = "low"
    req = urllib.request.Request(url + "/api/chat", json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def run(url, model, runs, num_ctx, verbose):
    rows = []
    for case in CASES:
        system, tools, groups = build(case)
        for i in range(runs):
            t0 = time.time()
            try:
                data = ask(url, model, system, tools, case.text, num_ctx)
            except Exception as e:  # noqa: BLE001: a model that errors counts as a miss
                rows.append({"case": case.name, "ok": False, "error": str(e)[:200], "secs": time.time() - t0})
                print(f"  {case.name:18} ERROR {e}")
                continue
            msg = data.get("message", {})
            calls = [{"name": c["function"]["name"], "args": c["function"].get("arguments") or {}}
                     for c in msg.get("tool_calls") or []]
            valid = {c["name"]: schema_ok(tools, c) for c in calls}
            s = score(case, calls, valid)
            row = {"case": case.name, "secs": round(time.time() - t0, 1), "tools_offered": len(tools),
                   "prompt_tokens": data.get("prompt_eval_count"), "out_tokens": data.get("eval_count"),
                   "calls": calls, "reply": (msg.get("content") or "")[:120], **s}
            rows.append(row)
            mark = "ok  " if s["ok"] else "FAIL"
            print(f"  {case.name:18} {mark} {row['secs']:5.1f}s  tools={len(tools):2}  "
                  f"-> {[c['name'] for c in calls] or 'no tool'}" + (f"  extra={s['extra']}" if s["extra"] else ""))
            if verbose and not s["ok"]:
                print(f"      args={json.dumps(calls)[:200]}  reply={row['reply']!r}")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("models", nargs="+")
    p.add_argument("--runs", type=int, default=1, help="repeats per case (default 1)")
    p.add_argument("--num-ctx", type=int, default=32768)
    p.add_argument("--url", default="http://localhost:11434")
    p.add_argument("--strict", action="store_true", help="no lenient argument handling (the old behaviour)")
    p.add_argument("--json", help="write every result to this file")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    global STRICT
    STRICT = a.strict

    results = {}
    for model in a.models:
        print(f"\n== {model}")
        run(a.url, model, 1, a.num_ctx, False)  # warm-up (loads the model, not scored)
        results[model] = run(a.url, model, a.runs, a.num_ctx, a.verbose)

    print("\n" + f"{'model':22}{'pass':>8}{'tool':>7}{'args':>7}{'no-tool':>9}{'extra':>7}{'avg s':>8}{'p-tok':>8}")
    for model, rows in results.items():
        n = len(rows) or 1
        tool_rows = [r for r in rows if r.get("calls") is not None and r["case"] not in
                     {c.name for c in CASES if not c.expect}]
        chat_rows = [r for r in rows if r["case"] in {c.name for c in CASES if not c.expect}]
        ptok = [r["prompt_tokens"] for r in rows if r.get("prompt_tokens")]
        print(f"{model:22}{sum(r['ok'] for r in rows):>4}/{n:<3}"
              f"{sum(r.get('picked', False) for r in tool_rows):>4}/{len(tool_rows):<2}"
              f"{sum(r.get('args', False) for r in tool_rows):>4}/{len(tool_rows):<2}"
              f"{sum(r['ok'] for r in chat_rows):>5}/{len(chat_rows):<3}"
              f"{sum(bool(r.get('extra')) for r in rows):>7}"
              f"{sum(r['secs'] for r in rows) / n:>8.1f}{(sum(ptok) // len(ptok) if ptok else 0):>8}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
