"""Rebuild the two leaderboards from the notes' scores. Run from backend/:

    .venv/bin/python ../.claude/skills/saved-reels/rebuild_rankings.py [vault-folder]

Reads Saved reels/reels/*.md (frontmatter general_score and ultron_score, 1-100) and writes
Saved reels/ranking/general-claude-and-ai.md and ranking/ultron.md: the top 10, with equal
scores sharing a rank (1, 2, 2, 4 ...), so a tie at 10th place shows every tied reel.
Notes in other/<Topic>/ are never ranked. Files are written as UTF-8.
"""
import os
import re
import sys
from pathlib import Path

BOARDS = [("general_score", "general-claude-and-ai.md", "Leaderboard: Claude and AI usage in general",
           "Reels that help you use Claude, Claude Code and AI tools better."),
          ("ultron_score", "ultron.md", "Leaderboard: Ultron",
           "Reels with ideas, tools or fixes that could improve Ultron.")]


def vault_folder() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser()
    vault = os.getenv("JARVIS_VAULT", "")
    if not vault:
        for line in (Path(__file__).resolve().parents[3] / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("JARVIS_VAULT="):
                vault = line.split("=", 1)[1].strip()
    return Path(vault).expanduser() / "Saved reels"


BAD = re.compile(r'[\[\]#^|\\/:*?"<>]')   # characters that break an Obsidian link or a file name


def read(note: Path) -> dict:
    text = note.read_text(encoding="utf-8")
    front = text.split("---")[1] if text.startswith("---") else ""
    fields = dict(re.findall(r"^(\w+):\s*(.*)$", front, re.M))
    one = re.search(r"\*\*In one line:\*\*\s*(.*)", text)
    title = re.search(r"^# (.*)$", text, re.M)
    return {"name": note.stem, "title": title.group(1).strip() if title else note.stem,
            "one": one.group(1).strip() if one else "",
            "general_score": int(fields.get("general_score") or 0), "ultron_score": int(fields.get("ultron_score") or 0)}


def main() -> None:
    root = vault_folder()
    notes = [read(p) for p in sorted((root / "reels").glob("*.md"))]
    for n in notes:
        if BAD.search(n["name"]):
            print(f"WARNING: note name breaks links, rename it: {n['name']}", file=sys.stderr)
    notes = [n for n in notes if not BAD.search(n["name"])]
    (root / "ranking").mkdir(exist_ok=True)
    for key, filename, heading, blurb in BOARDS:
        ranked = sorted(notes, key=lambda n: -n[key])
        lines, rank, last = [], 0, None
        for i, n in enumerate(ranked, 1):
            if n[key] != last:
                rank, last = i, n[key]
            if rank > 10:
                break
            lines.append(f"| {rank} | [[{root.name}/reels/{n['name']}|{n['name']}]] | {n[key]} | {n['one']} |")
        body = (f"# {heading}\n\n{blurb} Top 10 of {len(notes)} ranked reels; equal scores share a rank. "
                "Score is 1-100. Rebuilt every night.\n\n| Rank | Reel | Score | What it is |\n|---|---|---|---|\n"
                + "\n".join(lines) + "\n")
        (root / "ranking" / filename).write_text(body, encoding="utf-8")
    print(f"ranked {len(notes)} reels into {root / 'ranking'}")


if __name__ == "__main__":
    main()
