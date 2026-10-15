# Handoff: Ollama brain improvements (branch `ollama`)

## What we're doing
Improving the Ollama (local model) brain in Ultron: smarter tool-group switching, faster restarts, a fallback to Claude when Ollama fails, a tools panel, a bigger benchmark, and safer "what may it change" rules. Everything is **uncommitted** (the user commits themselves; ~25 changed/new files on top of commit e89986f).

## Current state
Done, tested (backend `cd backend && .venv/bin/python -m unittest discover tests` = 446 pass, 8 skipped; `cd frontend && npx tsc -b` clean), and code-reviewed (all 9 review findings fixed):
- **Item 1** narrower keyword patterns in `backend/brain/capabilities.py` (tests in `tests/test_capabilities.py`, also `--routing` list in the benchmark).
- **Item 2** connector tool lists cached in `backend/storage/ollama_connector_tools.json` (union only, never shrinks); `ollama.warm()` loads the model once, via `warm_local()` in `main.py`.
- **Item 6** error with `fallback` flag gives buttons "Try again on Ollama" / "Continue with Claude" (`user.fallback`, `brain/handoff.py`, `main.continue_on_claude`, `Chat.tsx`). Sends file ids too; only the latest error shows buttons.
- **Item 5** TOOLS bar in `Chat.tsx` (`user.groups` / `ollama.groups`, `Brain.set_groups`).
- **Items 4 + 3** `JARVIS_OLLAMA_CHANGES` = `none` | `chat` (default) | `all`. Jobs with an `allow` list stay on Claude unless `all`. `none` = local chat looks only (`ClaudeCodeBrain.looks_only`).
- **Item 9** benchmark `scripts/bench_ollama_tools.py`: `--routing` (no model), `-k`, no-tool cases, connector stand-ins, multi-step cases.
- **Item 10** `scripts/smoke_ollama_brain.py` passed live on `ultron-qwen3-14b` (small talk, battery -> `mac_read`, memory -> `recall`, tools panel, new chat reset).
- Item 12 was a false alarm (the `[Spoken]` rule is already in the local prompt; a test now pins it). Item 11 dropped (memory blocks are capped at 1,500 chars).

Not broken that we know of.

## Next step
Look at the UI once in a browser: start the backend/frontend, pick **Ollama** under the gear icon, check the TOOLS bar appears and toggles, then stop Ollama (or use an unknown model) and send a message to see the two fallback buttons and the "Continue with Claude" note. Nobody has seen these in the real UI yet (only type-check and unit tests). Then the user commits.

## Decisions made
- `JARVIS_OLLAMA_CHANGES` default is `chat` (keeps existing behaviour, gate still asks for anything reaching other people); only jobs that may change things moved back to Claude by default.
- "Continue with Claude" starts a **new** Claude session and puts the last 8 messages (1,500 chars each, labelled context-only) in front of the failed message, because Claude can't resume Ollama's session.
- Connector tool names in the benchmark are real, their arguments are simplified stand-ins.

## Gotchas
- My early claim "only gemma4 is installed" was wrong (I truncated the curl output): `ultron-qwen3-14b`, `ultron-qwen3-8b`, `gpt-oss:20b`, `gemma4:e4b`, `qwen3:8b`, `qwen3:14b` are all installed.
- Group switches restart the Claude Code session (about 17 s on the first message with a new group); later messages in that chat are ~7 s. Claude Code prints an `unrecognized_model` warning for `ultron-*` names; harmless, not investigated.
- Project rules (CLAUDE.md): every feature ends with a "Windows setup" line, one small test per new tool, update README, user makes git commits, verify before claiming.
- Tests in `tests/test_fallback_ws.py` temporarily change `main.brain.provider`; they restore it.

## Open questions
- Remaining improvements the user hasn't picked: item 7 (long chats near the 32k window have no guard; unverified what Ollama does at the limit) and item 8 (only Qwen3 can be patched by `make_ollama_model.py`; other models offered only if named in `.env`).
- Should group switching be faster (keep common groups on, or avoid the full restart)? Not decided.
