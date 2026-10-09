"""github: read your GitHub repos, issues, pull requests and files with the gh tool. (read)

claude.ai's GitHub Integration doesn't reach Ultron, so this uses the GitHub CLI (`gh`)
that's already signed in on this computer. Read-only: only list and view commands and GET
requests for file contents. Nothing is created, commented on, merged or deleted.

Windows: install with `winget install GitHub.cli`, then run `gh auth login` once.
"""

import asyncio
import json
import re
import shutil
from typing import Any

from claude_agent_sdk import tool

from .homework import _text

MAX_CHARS = 20_000
TIMEOUT_S = 30
ACTIONS = ["repos", "repo", "issues", "pull_requests", "file"]
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
STATES = ["open", "closed", "all"]


def _gh() -> str | None:
    # Apps don't load the shell's PATH, so Homebrew's folders are checked too.
    return shutil.which("gh") or shutil.which("gh", path="/opt/homebrew/bin:/usr/local/bin")


def build_command(args: dict[str, Any]) -> list[str]:
    """The gh command for one read action. Raises ValueError for anything else."""
    action = args.get("action")
    repo = (args.get("repo") or "").strip()
    if action not in ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(ACTIONS)}")
    if action != "repos" and not REPO_RE.match(repo):
        raise ValueError("repo must look like owner/name, e.g. octocat/hello-world")
    limit = str(min(max(int(args.get("limit") or 30), 1), 100))
    state = args.get("state") or "open"
    if state not in STATES:
        raise ValueError(f"state must be one of: {', '.join(STATES)}")

    if action == "repos":
        return ["repo", "list", "--limit", limit, "--json", "nameWithOwner,description,isPrivate,updatedAt"]
    if action == "repo":
        return ["repo", "view", repo, "--json", "nameWithOwner,description,defaultBranchRef,isPrivate,url,updatedAt"]
    if action == "issues":
        return ["issue", "list", "-R", repo, "--state", state, "--limit", limit,
                "--json", "number,title,state,author,updatedAt,url"]
    if action == "pull_requests":
        return ["pr", "list", "-R", repo, "--state", state, "--limit", limit,
                "--json", "number,title,state,author,updatedAt,url"]
    # file: the raw text of one file (or the folder listing when the path is a folder)
    path = (args.get("path") or "").strip().strip("/")
    if not path or ".." in path.split("/"):
        raise ValueError("path must be a file or folder inside the repo, e.g. README.md")
    ref = (args.get("ref") or "").strip()
    endpoint = f"repos/{repo}/contents/{path}" + (f"?ref={ref}" if ref else "")
    return ["api", "-H", "Accept: application/vnd.github.raw", endpoint]


@tool(
    "github",
    "Read your GitHub account with the gh tool on this computer (read-only; never changes "
    "anything). action: repos (your repositories), repo (one repo's details), issues or "
    "pull_requests (lists for repo, filter with state: open, closed or all), file (text of "
    "one file in repo at path, optional ref = branch or tag; a folder path gives its listing). "
    "repo is owner/name.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTIONS},
            "repo": {"type": "string"},
            "path": {"type": "string"},
            "ref": {"type": "string"},
            "state": {"type": "string", "enum": STATES},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["action"],
    },
)
async def github(args: dict[str, Any]) -> dict[str, Any]:
    try:
        command = build_command(args)
    except (ValueError, TypeError) as e:
        return _text(f"github: {e}", True)
    gh = _gh()
    if gh is None:
        return _text("github: the gh tool isn't installed. Install it, then run `gh auth login`.", True)
    try:
        proc = await asyncio.create_subprocess_exec(
            gh, *command,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT_S)
    except asyncio.TimeoutError:
        return _text("github: gh took too long to answer.", True)
    except OSError as e:
        return _text(f"github: could not run gh: {e}", True)
    if proc.returncode != 0:
        return _text(f"github: {err.decode('utf-8', 'replace').strip() or 'gh failed'}", True)
    text = out.decode("utf-8", "replace")
    if args.get("action") in ("repos", "repo", "issues", "pull_requests"):
        text = _tidy(text)
    return _text(text[:MAX_CHARS])


def _tidy(text: str) -> str:
    """Turn gh's JSON into one line per item; anything else is passed on as it is."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    items = data if isinstance(data, list) else [data]
    lines = []
    for item in items:
        if isinstance(item.get("author"), dict):
            item["author"] = item["author"].get("login", "")
        bits = [str(v) for k, v in item.items() if v not in (None, "", False) and k not in ("url", "updatedAt")]
        lines.append(" | ".join(bits) + (f" ({item['url']})" if item.get("url") else ""))
    return "\n".join(lines) or "Nothing found."
