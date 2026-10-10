"""PreToolUse hook for Edit/Write: block edits to secret and personal-data files.

Reads the hook JSON from stdin. Exit 2 blocks the edit and shows the message to Claude.
"""

import json
import os
import re
import sys

# Secrets live in .env (git-ignored); .env.example is the safe template.
SECRET_FILE = re.compile(r"(^|[\\/])\.env(\.[^\\/]+)?$")
ALLOWED = re.compile(r"\.env\.example$")
# Personal data written by Ultron at runtime (memory, chats, jobs, tokens, usage).
DATA_FILE = re.compile(r"backend[\\/]storage[\\/][^\\/]+\.json$")
PC_ENV = re.compile(r"windows[\\/]wake_pc\.env$")
# A real Anthropic key pasted into code or config. config.py only *removes* ANTHROPIC_API_KEY.
REAL_KEY = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")


def main() -> int:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input", {})
    path = tool_input.get("file_path", "")
    name = os.path.basename(path)
    new_text = tool_input.get("content") or tool_input.get("new_string") or ""

    if ALLOWED.search(path):
        pass
    elif SECRET_FILE.search(path) or PC_ENV.search(path):
        return block(f"{path} holds secrets. Ask the user to edit it themselves, and only touch .env.example.")
    elif DATA_FILE.search(path):
        return block(f"{path} is Ultron's personal data (memory, chats, jobs, tokens). Don't edit it by hand.")

    if REAL_KEY.search(new_text):
        return block(f"The new text contains a real Anthropic key (sk-ant-…) in {name}. Keys never go in code.")
    return 0


def block(message: str) -> int:
    print(f"Blocked by guard_edits: {message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
