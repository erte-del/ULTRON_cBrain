"""PostToolUse hook for Edit/Write on frontend TypeScript files.

Runs `tsc` on the app project (about 2 s). Exit 2 shows type errors to Claude.
"""

import json
import os
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
FRONTEND = os.path.join(ROOT, "frontend")


def main() -> int:
    data = json.load(sys.stdin)
    path = data.get("tool_input", {}).get("file_path", "")
    rel = os.path.relpath(path, FRONTEND).replace("\\", "/")
    if not (rel.startswith("src/") and rel.endswith((".ts", ".tsx"))):
        return 0
    # npx finds the local tsc on Mac/Linux (node_modules/.bin) and Windows (tsc.cmd) alike.
    result = subprocess.run(
        ["npx", "tsc", "-p", "tsconfig.app.json", "--noEmit"],
        cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=110, shell=os.name == "nt",
    )
    if result.returncode != 0:
        print(f"TypeScript errors after your edit:\n{result.stdout}{result.stderr}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
