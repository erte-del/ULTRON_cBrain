---
name: new-tool
description: Scaffold a new Ultron tool with the read/act label, registry entry, prompt line, test and README line, following ULTRON_BUILD_PROMPT.md section 5. Use when the user asks to add a tool to Ultron.
disable-model-invocation: true
argument-hint: <tool_name> <read|act> "<what it does>"
---

Add the Ultron tool described by: $ARGUMENTS

Work through these steps in order. Read each file before you change it.

1. **Check first.** Ultron prefers a claude.ai connector when one exists (see `backend/tools/connectors.py`). Search the existing tools for an overlap (`grep -rn "<keyword>" backend/tools`). If one fits, say so and stop.
2. **Write the tool** in its own file `backend/tools/<name>.py` with the SDK's `@tool` decorator, the same way the neighbouring tools do. Return results the same way the neighbouring tools do (look at `backend/tools/phone.py` for a short example). Use `encoding="utf-8"` on every file read or write. Use no Mac-only paths, no `osascript`, and no `.sh` scripts. Run any FFmpeg filter paths through `reel.filter_path`.
3. **Register it** in `backend/tools/registry.py`: add a `UltronTool(<fn>, "read" | "act")` line to `TOOLS`. For an act tool, add a friendly title to `TITLES`. Add it to `ASK_TOOLS` only if it must always ask.
4. **Mention it** in `backend/brain/prompts.py` (one line, same tone as the others).
5. **Add one small test** `backend/tests/test_<name>.py` using `unittest`. Cover the one branch that would break. Mock anything that touches the network or the user's machine.
6. **Add a line** for the tool to `README.md`.
7. **Run the tests:** `cd backend && .venv/bin/python -m unittest discover tests` (Windows: `.venv\Scripts\python.exe`). Report the result exactly.
8. **Finish with the Windows setup list:** what to install with `winget`, any `.env` lines, or "nothing to set up".

Don't commit. The user makes the git commits.
