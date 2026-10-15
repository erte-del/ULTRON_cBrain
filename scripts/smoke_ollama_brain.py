"""Live check of the Ollama brain, end to end: Claude Code -> Ollama -> Ultron's tools.

  python scripts/smoke_ollama_brain.py [model]      (default: JARVIS_OLLAMA_MODEL, else the first ultron-* model)

Sends a few read-only messages and checks which tool groups switch on and which tools get called. It
only looks (battery level, memories); nothing is changed or sent. Needs Ollama running with a model made by
scripts/make_ollama_model.py. Works on Mac and Windows. Exit code 1 if a check failed.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config  # noqa: E402
import ollama  # noqa: E402
from brain.base import Done, Error, TextDelta, ToolStart  # noqa: E402
from brain.brain_claudecode import ClaudeCodeBrain  # noqa: E402
from brain import capabilities  # noqa: E402

PFX = "mcp__ultron__"

# (message, groups that must be on afterwards, tools that must have been called)
CHECKS = [
    ("Hi, who are you?", set(), set()),
    ("How much battery does my Mac have left?", {"mac"}, {"mac_read"}),
    ("What do you know about Lina?", set(), {"recall"}),
]


async def ask(brain: ClaudeCodeBrain, text: str):
    """Send one message the way the app does; returns (tools called, reply, seconds, error)."""
    brain.said = text
    tools, reply, error = [], "", ""
    t0 = time.time()
    async for ev in brain.send(text, model=brain.local_model):
        if isinstance(ev, ToolStart):
            tools.append(ev.name.removeprefix(PFX))
        elif isinstance(ev, TextDelta):
            reply += ev.text
        elif isinstance(ev, Error):
            error = ev.message
        elif isinstance(ev, Done):
            break
    return tools, reply.strip(), time.time() - t0, error


async def main() -> int:
    installed = ollama.installed()
    if installed is None:
        print("Ollama isn't running.")
        return 1
    model = sys.argv[1] if len(sys.argv) > 1 else (ollama.default_model(installed) or "")
    if not model or not ollama.has(installed, model):
        print(f"No such model: {model!r}. Make one with scripts/make_ollama_model.py")
        return 1
    print(f"model {model}   changes={config.OLLAMA_CHANGES}")
    brain = ClaudeCodeBrain(model="sonnet")
    brain.provider, brain.local_model = "ollama", model
    brain._model = model
    seen: list[list[str]] = []
    brain.on_groups = lambda: seen.append(sorted(brain.groups))
    failed = 0
    try:
        for text, want_groups, want_tools in CHECKS:
            tools, reply, secs, error = await ask(brain, text)
            ok = not error and want_groups <= brain.groups and want_tools <= set(tools)
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {secs:5.1f}s  {text!r}\n       groups={sorted(brain.groups)}  tools={tools}"
                  f"\n       reply={reply[:160]!r}" + (f"\n       ERROR {error}" if error else ""))
        # A hand switch (the tools panel) takes effect on the next message.
        await brain.set_groups({"notes"})
        ok = brain.groups == {"notes"} and "search_notes" in capabilities.visible_tools(brain.groups)
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} tools panel: groups={sorted(brain.groups)}")
        await brain.new_conversation("ollama")
        ok = brain.groups == set() and seen and seen[-1] == []
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} a new chat starts with the basics; the page was told {seen}")
    finally:
        await brain.close()
    print("\nall checks passed" if not failed else f"\n{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
