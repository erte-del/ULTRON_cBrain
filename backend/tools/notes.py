"""search_notes / read_note / write_note: your Obsidian vault (JARVIS_VAULT in .env).

A vault is a folder of Markdown files, so these are plain file tools. Ultron only sees
.md files inside the vault, skips hidden folders (.obsidian, .trash) and never reads a
note tagged #private. Writing is an 'act' tool: it asks you first only for notes you marked important.
delete_note always asks, and moves to the vault's .trash (Obsidian's own trash), never erases.
"""

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config

MAX_CHARS = 100_000  # ~25K tokens, like read_upload
MAX_RESULTS = 30
SNIPPET_CHARS = 200

# Obsidian's own tag: "#private" in the text, or "private" in the frontmatter's tags.
_PRIVATE_TAG = re.compile(r"(?:^|\s)#private\b", re.I)
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.S)
_PRIVATE_IN_TAGS = re.compile(r"^tags:.*\bprivate\b|^\s*-\s*#?private\s*$", re.I | re.M)


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def is_private(text: str) -> bool:
    fm = _FRONTMATTER.match(text)
    return bool(_PRIVATE_TAG.search(text) or (fm and _PRIVATE_IN_TAGS.search(fm[1])))


def _vault() -> Path:
    if not config.VAULT_DIR:
        raise ValueError("No notes vault is set up: put JARVIS_VAULT=/path/to/vault in .env.")
    return config.VAULT_DIR


def _resolve(path: str) -> Path:
    """The vault file a relative path names. ValueError if it leaves the vault or is hidden."""
    vault = _vault().resolve()
    rel = path.strip().lstrip("/")
    if not rel.lower().endswith(".md"):
        rel += ".md"
    full = (vault / rel).resolve()
    if not full.is_relative_to(vault) or any(p.startswith(".") for p in full.relative_to(vault).parts):
        raise ValueError(f"{path!r} isn't a note in your vault.")
    return full


def _notes() -> list[tuple[str, str]]:
    """(relative path, text) of every note Ultron may read, newest first."""
    vault = _vault()
    found = []
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not is_private(text):
            found.append((p.stat().st_mtime, rel.as_posix(), text))
    return [(rel, text) for _, rel, text in sorted(found, reverse=True)]


def search(query: str) -> list[dict[str, str]]:
    # ponytail: reads every note on each search; fine for thousands of notes, add an index if it gets slow
    words = query.lower().split()
    hits = []
    for rel, text in _notes():
        haystack = f"{rel}\n{text}".lower()
        if all(w in haystack for w in words):
            at = text.lower().find(words[0]) if words else 0
            start = max(at - SNIPPET_CHARS // 2, 0)
            hits.append({"path": rel, "snippet": " ".join(text[start:start + SNIPPET_CHARS].split())})
        if len(hits) == MAX_RESULTS:
            break
    return hits


@tool(
    "search_notes",
    "Search the user's Obsidian notes (read-only). Finds notes whose name or text contains "
    "every word of the query; use one or two key words. An empty query lists the newest "
    "notes. Returns each note's path and a snippet; open one with read_note.",
    {"type": "object", "properties": {"query": {"type": "string", "description": "e.g. 'chemistry test'"}}},
)
async def search_notes(args: dict[str, Any]) -> dict[str, Any]:
    try:
        hits = await asyncio.to_thread(search, str(args.get("query") or ""))
    except (ValueError, OSError) as e:
        return _text(str(e), True)
    if not hits:
        return _text("No notes match.")
    return _text("\n".join(f"- {h['path']}: {h['snippet']}" for h in hits))


@tool(
    "read_note",
    "Open one of the user's Obsidian notes by its path in the vault, e.g. "
    "'school Notes/Teams.md' (from search_notes).",
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)
async def read_note(args: dict[str, Any]) -> dict[str, Any]:
    try:
        path = _resolve(str(args.get("path") or ""))
        text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
    except (ValueError, OSError) as e:
        return _text(f"Couldn't open that note: {e}", True)
    if is_private(text):
        return _text("That note is tagged #private, so you can't read it.", True)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n\n[cut off: only the first {MAX_CHARS} of {len(text)} characters]"
    return _text(f"{path.relative_to(config.VAULT_DIR.resolve()).as_posix()}:\n\n{text}")


def write(path: str, content: str, mode: str) -> str:
    """Write a note; returns its path in the vault. ValueError when it can't."""
    full = _resolve(path)
    rel = full.relative_to(_vault().resolve()).as_posix()
    if full.exists():
        if mode == "create":
            raise ValueError(f"{rel} already exists: use mode append or replace.")
        if is_private(full.read_text(encoding="utf-8", errors="replace")):
            raise ValueError(f"{rel} is tagged #private, so Ultron doesn't change it.")
    elif mode == "append":
        mode = "create"  # appending to nothing is just a new note
    full.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        old = full.read_text(encoding="utf-8")
        full.write_text(old + ("" if old.endswith("\n") or not old else "\n") + content + "\n", encoding="utf-8")
    else:
        full.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
    return rel


@tool(
    "write_note",
    "Save to the user's Obsidian notes. mode create makes a "
    "new note (fails if it exists), append adds to the end of a note, replace rewrites a "
    "whole note (read it first). Write Markdown; link other notes with [[Note name]].",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path in the vault, e.g. 'Ultron/Chemistry test.md'"},
            "content": {"type": "string", "description": "Markdown"},
            "mode": {"type": "string", "enum": ["create", "append", "replace"]},
        },
        "required": ["path", "content", "mode"],
    },
)
async def write_note(args: dict[str, Any]) -> dict[str, Any]:
    try:
        rel = await asyncio.to_thread(
            write, str(args.get("path") or ""), str(args.get("content") or ""), str(args.get("mode") or "create"))
    except (ValueError, OSError) as e:
        return _text(f"Not saved: {e}", True)
    return _text(f"Saved to {rel}.")


def delete(path: str) -> str:
    """Move a note, or a folder with its notes, to the vault's .trash; returns what moved."""
    vault = _vault().resolve()
    rel = path.strip().lstrip("/")
    full = (vault / rel).resolve()
    if full.is_dir():
        notes = list(full.rglob("*.md"))
    else:
        full, notes = _resolve(path), [_resolve(path)]
    if full == vault or not full.is_relative_to(vault) or any(p.startswith(".") for p in full.relative_to(vault).parts):
        raise ValueError(f"{path!r} isn't a note or folder in your vault.")
    if not full.exists():
        raise ValueError(f"{path!r} doesn't exist.")
    if any(is_private(n.read_text(encoding="utf-8", errors="replace")) for n in notes):
        raise ValueError(f"{path!r} has a #private note, so Ultron doesn't delete it.")
    shown = full.relative_to(vault).as_posix()
    dest = vault / ".trash" / full.name
    for i in range(2, 1000):  # never overwrite something already in the trash
        if not dest.exists():
            break
        dest = vault / ".trash" / f"{full.stem} {i}{full.suffix}"
    dest.parent.mkdir(exist_ok=True)
    shutil.move(str(full), str(dest))
    return shown


@tool(
    "delete_note",
    "Delete one of the user's Obsidian notes, or a whole folder of notes, by its path in the "
    "vault. It goes to Obsidian's trash (.trash) so it can be put back. Always asks the user first.",
    {"type": "object", "properties": {"path": {"type": "string", "description": "Note or folder, e.g. 'Ultron/Old plan.md'"}},
     "required": ["path"]},
)
async def delete_note(args: dict[str, Any]) -> dict[str, Any]:
    try:
        shown = await asyncio.to_thread(delete, str(args.get("path") or ""))
    except (ValueError, OSError) as e:
        return _text(f"Not deleted: {e}", True)
    return _text(f"Moved {shown} to the vault's .trash (Obsidian can restore it).")
