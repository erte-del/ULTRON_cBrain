# Dev mods

Claude Code mods that help with **developing** Ultron. They are not part of Ultron:
the backend, frontend and `Ultron.app` never read this folder.

| Mod | What it does |
|---|---|
| `restart-ultron-backend` | A live "Backend online/offline" dot (polls `/health` every 3 s), and a "Restart backend" button in a sidebar pane (and `/restart-backend`). Only active when the session folder is `ULTRON_cBrain`. |

## Using one

```
claude --plugin-dir .claude/dev-mods/restart-ultron-backend
```

Claude Code writes `.claude-plugin/types/` inside a mod when it loads it; that folder is git-ignored.
