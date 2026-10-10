---
name: windows-check
description: Check the pending changes for Mac-only assumptions that would break Ultron on Windows (ULTRON_BUILD_PROMPT.md rule 1) and print the Windows setup list. Use before finishing any Ultron feature.
disable-model-invocation: true
---

Check the changes on this branch for Windows problems. Use `git diff --name-only HEAD` plus untracked files (`git ls-files --others --exclude-standard`). Only check the Python, TypeScript and script files among them.

Look for each of these, and report file and line:

- Mac-only paths: `/System/`, `/usr/local/`, `/opt/`, `/Applications/`, `~/Library`
- Mac-only tools: `osascript`, `.sh` scripts called from code, `open -a`, `pbcopy`, `mlx`, `terminal-notifier`
- POSIX-only calls: `os.fork`, `signal.SIGKILL`, `os.getuid`, hard-coded `/` path joins (use `pathlib`)
- File reads or writes without `encoding="utf-8"`: `open(`, `read_text(`, `write_text(`
- FFmpeg filter paths that don't go through `reel.filter_path`
- Backend binds to anything other than `127.0.0.1` (`0.0.0.0` is never allowed)

Then give the verdict:

- If nothing is found, say so.
- If something is found, list each item as `file:line — problem — fix`.
- If the feature can't run on Windows, say so plainly.

End with the **Windows setup** list: `winget` installs and `.env` lines the change needs, or "nothing to set up".

This skill only reports. Don't edit files unless the user asks.
