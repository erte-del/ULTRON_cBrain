"""Compares local models on Ultron's real tool calling.

Each case is a message plus the tool call(s) a good model should make. The model gets Ultron's own
trimmed system prompt and the real tool schemas for the groups that message switches on (the same
way brain/capabilities.py does for the Ollama brain). Nothing is executed: we only look at which
tools the model asked for and whether the arguments are right.

  python scripts/bench_ollama_tools.py qwen3:14b gpt-oss:20b gemma4:e4b [--runs 2] [--json out.json]
  python scripts/bench_ollama_tools.py --routing        # no model: which tool groups each message switches on
  python scripts/bench_ollama_tools.py qwen3:14b -k recall   # only cases whose name contains "recall"

Works on Mac and Windows. Ollama must be running (JARVIS_OLLAMA_URL, default localhost:11434).
Cases that give `results` are multi-step: the canned tool result goes back to the model, which must then
answer from it (words in `reply_has`) without calling anything it shouldn't. Connector tools (Gmail,
Calendar, TickTick) are stand-ins: the names are the real ones, the arguments are simplified.
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
    results: dict = field(default_factory=dict)  # tool name -> canned result, fed back to the model (multi-step)
    later: list = field(default_factory=list)  # tools that may also be called after a result came back
    reply_has: list = field(default_factory=list)  # words the final answer must contain (multi-step)


def _has(*words):
    return lambda a: all(w in json.dumps(a, ensure_ascii=False).lower() for w in words)


GMAIL_SEARCH = "mcp__claude_ai_Gmail__search_threads"
CAL_LIST = "mcp__claude_ai_Google_Calendar__list_events"
TASK_ADD = "mcp__claude_ai_TickTick__create_task"
TASK_LIST = "mcp__claude_ai_TickTick__list_undone_tasks_by_date"


def _stand_in(name, description, props, required=()):
    return name, description, {"type": "object", "properties": props, "required": list(required)}


_str = {"type": "string"}
CONNECTOR_TOOLS = {  # group -> stand-ins for what its connector adds (real names, simplified arguments)
    "gmail": [_stand_in(GMAIL_SEARCH, "Search the user's Gmail threads with Gmail search syntax.", {"query": _str}, ["query"])],
    "calendar": [_stand_in(CAL_LIST, "List calendar events between two times.", {"startTime": _str, "endTime": _str})],
    "tasks": [
        _stand_in(TASK_ADD, "Create a task.", {"title": _str, "dueDate": _str}, ["title"]),
        _stand_in(TASK_LIST, "List the tasks that are not done, by due date.", {"startDate": _str, "endDate": _str}),
    ],
}

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
    # Things that sound like a tool but aren't: no tool, and no inventing one.
    Case("chat_code", "Explain what a Python decorator is.", []),
    Case("chat_leave", "I'll leave it for now, thanks.", []),
    Case("chat_unit_tests", "My unit tests all passed!", []),
    Case("no_tool_pay", "Pay my electricity bill.", []),
    Case("no_tool_call", "Phone my mum and tell her I'm late.", []),
    # Connector tools.
    Case("mail_search", "Any unread email from Sarah?", [GMAIL_SEARCH], {GMAIL_SEARCH: _has("sarah")}),
    Case("calendar_look", "What's on my calendar tomorrow?", [CAL_LIST]),
    Case("task_add", "Add a task: call the dentist.", [TASK_ADD], {TASK_ADD: _has("dentist")}),
    # Multi-step: the tool's result comes back and the model has to use it.
    Case("recall_answer", "What do you know about Lina?", ["recall"], {"recall": _has("lina")},
         results={"recall": "- [people] My sister's name is Lina."}, reply_has=["sister"]),
    Case("jobs_answer", "Which scheduled jobs do I have?", ["list_jobs"],
         results={"list_jobs": "1 job: Morning briefing, weekdays at 07:00."}, reply_has=["briefing"]),
    Case("remember_ack", "Remember that I like oat milk.", ["remember"], {"remember": _has("oat")},
         results={"remember": "Saved."}),
    Case("mail_answer", "Any unread email from Sarah?", [GMAIL_SEARCH],
         results={GMAIL_SEARCH: "1 unread thread: 'Lunch on Friday?' from Sarah <sarah@example.com>."},
         reply_has=["lunch"]),
    Case("two_sources", "What's on my calendar tomorrow, and what tasks are due?", [CAL_LIST, TASK_LIST],
         results={CAL_LIST: "Tomorrow: Dentist at 10:00.", TASK_LIST: "Due tomorrow: Hand in the essay."},
         reply_has=["dentist", "essay"]),
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
    for group in sorted(groups):  # the connectors those groups switch on
        for name, description, schema in CONNECTOR_TOOLS.get(group, []):
            tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": schema}})
            ORIGINAL[name] = schema
    return capabilities.system_prompt(groups), tools, groups


def score(case: Case, calls: list[dict], valid: dict, reply: str = "") -> dict:
    """calls: [{"name", "args"}] in every round. valid: tool name -> True when the args match its JSON schema.
    reply: the final answer, checked against case.reply_has when the case has canned results."""
    called = [c["name"] for c in calls]
    if not case.expect:
        return {"ok": not called, "picked": not called, "args": True, "extra": called}
    picked = all(e in called for e in case.expect)
    extra = [n for n in called if n not in case.expect and n not in case.later]
    args = picked and all(
        valid.get(c["name"], False) and case.check.get(c["name"], lambda a: True)(c["args"])
        for c in calls if c["name"] in case.expect)
    used = all(w.lower() in reply.lower() for w in case.reply_has) if case.results else True
    return {"ok": picked and args and not extra and used, "picked": picked, "args": args, "extra": extra, "used": used}


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


def ask(url: str, model: str, system: str, tools: list[dict], messages: list[dict], num_ctx: int) -> dict:
    body = {"model": model, "stream": False, "tools": tools, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}, *messages],
            "options": {"num_ctx": num_ctx, "temperature": 0.3}}
    if not model.startswith("gpt-oss"):
        body["think"] = False  # gpt-oss can't switch thinking off (only low/medium/high)
    else:
        body["think"] = "low"
    req = urllib.request.Request(url + "/api/chat", json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


# Which tool groups a message should switch on (brain/capabilities.py). Needs no model, runs in a blink.
ROUTES = [
    ("hi, who are you?", set()),
    ("Remember that my sister's name is Lina.", set()),
    ("Any unread email from Sarah?", {"gmail"}),
    ("What's on my calendar tomorrow?", {"calendar"}),
    ("Morning briefing", {"calendar", "tasks"}),
    ("Remind me to call mum at 5.", {"tasks"}),
    ("What tasks are due tomorrow?", {"tasks"}),
    ("Did my last deployment fail?", {"vercel"}),
    ("How many orders did my store get today?", {"shopify"}),
    ("When is my chemistry test?", {"school"}),
    ("Search my notes for chemistry.", {"notes"}),
    ("How much battery does my Mac have left?", {"mac"}),
    ("Is my PC on?", {"pc"}),
    ("How long does it take to drive to the airport?", {"travel"}),
    ("Draw me a cat.", {"images"}),
    ("Play some jazz.", {"music"}),
    ("Play Taylor Swift.", {"music"}),
    ("Message Sam that I'm late.", {"messages"}),
    ("What time should I leave?", {"travel"}),
    ("Send a message to Sam.", {"messages"}),
    ("I'm hungry.", {"phone"}),
    ("Put a table on the canvas.", {"canvas"}),
    ("Open the terminal.", {"terminal"}),
    # Words that sound like a group but aren't one:
    ("Unit tests all passed!", set()),
    ("I'll leave it for now.", set()),
    ("Let's play it safe.", set()),
    ("I got a message from Sarah.", set()),
    ("The shell company sold products.", set()),
    ("Take note that I like tea.", set()),
    ("Close the windows, it's cold.", set()),
    ("Order me a pizza from the corner.", set()),
    ("Explain what a Python decorator is.", set()),
    ("What's the model of growth in economics?", set()),
]


def check_routing() -> list[tuple[str, set, set]]:
    """The routes that go wrong: [(message, what it should switch on, what it did)]."""
    from brain import capabilities
    return [(text, want, got) for text, want in ROUTES if (got := capabilities.match(text)) != want]


MAX_ROUNDS = 4  # model -> tool results -> model ..., so a model that keeps calling tools ends


def converse(url, model, system, tools, case, num_ctx):
    """Send the case's message; while the model calls tools, feed back each canned result (or "ok").
    Returns (every call in order, the final reply, the last response)."""
    messages = [{"role": "user", "content": f"[Now: {datetime.now():%A %d %B %Y, %H:%M}]\n{case.text}"}]
    calls: list[dict] = []
    for _ in range(MAX_ROUNDS if case.results else 1):
        data = ask(url, model, system, tools, messages, num_ctx)
        msg = data.get("message", {})
        raw = msg.get("tool_calls") or []
        calls += [{"name": c["function"]["name"], "args": c["function"].get("arguments") or {}} for c in raw]
        if not raw or not case.results:
            return calls, msg.get("content") or "", data
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": raw})
        for c in raw:
            name = c["function"]["name"]
            messages.append({"role": "tool", "tool_name": name, "content": case.results.get(name, "ok")})
    return calls, "", data  # still calling tools after the last round: no answer


def run(url, model, runs, num_ctx, verbose, only=""):
    rows = []
    for case in [c for c in CASES if only in c.name]:
        system, tools, groups = build(case)
        for i in range(runs):
            t0 = time.time()
            try:
                calls, reply, data = converse(url, model, system, tools, case, num_ctx)
            except Exception as e:  # noqa: BLE001: a model that errors counts as a miss
                rows.append({"case": case.name, "ok": False, "error": str(e)[:200], "secs": time.time() - t0})
                print(f"  {case.name:18} ERROR {e}")
                continue
            valid = {c["name"]: schema_ok(tools, c) for c in calls}
            s = score(case, calls, valid, reply)
            row = {"case": case.name, "secs": round(time.time() - t0, 1), "tools_offered": len(tools),
                   "prompt_tokens": data.get("prompt_eval_count"), "out_tokens": data.get("eval_count"),
                   "calls": calls, "reply": reply[:120], **s}
            rows.append(row)
            mark = "ok  " if s["ok"] else "FAIL"
            print(f"  {case.name:18} {mark} {row['secs']:5.1f}s  tools={len(tools):2}  "
                  f"-> {[c['name'] for c in calls] or 'no tool'}" + (f"  extra={s['extra']}" if s["extra"] else "")
                  + ("  (answer ignores the result)" if s.get("used") is False else ""))
            if verbose and not s["ok"]:
                print(f"      args={json.dumps(calls)[:200]}  reply={row['reply']!r}")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("models", nargs="*", help="Ollama models to try (none with --routing)")
    p.add_argument("--routing", action="store_true", help="only check which groups messages switch on (no model needed)")
    p.add_argument("-k", default="", help="only the cases whose name contains this")
    p.add_argument("--runs", type=int, default=1, help="repeats per case (default 1)")
    p.add_argument("--num-ctx", type=int, default=32768)
    p.add_argument("--url", default="http://localhost:11434")
    p.add_argument("--strict", action="store_true", help="no lenient argument handling (the old behaviour)")
    p.add_argument("--json", help="write every result to this file")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    global STRICT
    STRICT = a.strict

    bad = check_routing()
    print(f"routing: {len(ROUTES) - len(bad)}/{len(ROUTES)} messages switch on the right groups")
    for text, want, got in bad:
        print(f"  WRONG  {text!r}: wanted {sorted(want) or 'nothing'}, got {sorted(got) or 'nothing'}")
    if a.routing:
        sys.exit(1 if bad else 0)
    if not a.models:
        p.error("name at least one model, or use --routing")

    results = {}
    for model in a.models:
        print(f"\n== {model}")
        run(a.url, model, 1, a.num_ctx, False, "chat_hi")  # warm-up (loads the model, not scored)
        results[model] = run(a.url, model, a.runs, a.num_ctx, a.verbose, a.k)

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
