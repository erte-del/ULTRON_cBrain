"""PostToolUse hook for Edit/Write on backend Python files.

Runs only the test file that matches the edited module (backend/tools/mail.py -> tests/test_mail.py).
The full suite takes about 90 s, so run it by hand before finishing a change:
  backend/.venv/bin/python -m unittest discover tests
Exit 2 shows failing output to Claude so it can fix the change.
"""

import json
import os
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
BACKEND = os.path.join(ROOT, "backend")


def venv_python() -> str:
    # Mac/Linux: .venv/bin/python · Windows: .venv\Scripts\python.exe
    if os.name == "nt":
        return os.path.join(BACKEND, ".venv", "Scripts", "python.exe")
    return os.path.join(BACKEND, ".venv", "bin", "python")


def matching_test(path: str):
    rel = os.path.relpath(path, BACKEND).replace("\\", "/")
    if not rel.endswith(".py") or rel.startswith("..") or rel.startswith("."):
        return None
    base = os.path.basename(rel)
    if rel.startswith("tests/") and base.startswith("test_"):
        return base
    if rel.startswith("tests/"):
        return None
    candidate = f"test_{base}"
    return candidate if os.path.exists(os.path.join(BACKEND, "tests", candidate)) else None


def main() -> int:
    data = json.load(sys.stdin)
    path = data.get("tool_input", {}).get("file_path", "")
    test = matching_test(path)
    if not test:
        return 0
    result = subprocess.run(
        [venv_python(), "-m", "unittest", "discover", "-s", "tests", "-p", test],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", timeout=110,
    )
    if result.returncode != 0:
        print(f"tests/{test} failed after your edit:\n{result.stdout}{result.stderr}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
