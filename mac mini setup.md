# Mac mini setup: a runbook a Claude Code session can execute

Goal: this Mac mini becomes Ultron's dedicated brain with **every feature working**. The
MacBook it came from is personal and stops running Ultron.

This file has two readers:
- **The user** (Part A): a short list of what to do before starting Claude.
- **A Claude Code session running on the Mac mini** (Parts B to F): everything it needs to do the
  setup, which steps it does itself, which steps only the user can do, and how to prove each
  step worked.

Written from `README.md`, `.env.example`, `scripts/` and the code, checked against the MacBook on
2026-10-13. Nothing here has been run on the mini yet; each phase has a check that proves it.

---

# Part A. For the user: get Claude started on the mini

1. **Set up macOS** on the mini (account, Wi-Fi, Software Update). Keep **Wi-Fi on** even if you use
   Ethernet: Ultron's location comes from Wi-Fi.
2. **Connect a display** (or a cheap HDMI dummy plug), plus a **mic and speakers**. A Mac mini has
   none built in, and voice, the screen overlay and screen recording need them.
3. **Install Homebrew and the Xcode command line tools yourself**; both need your admin password,
   which Claude can't type:
   ```bash
   xcode-select --install
   ```
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Then: `echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile && eval "$(/opt/homebrew/bin/brew shellenv)"`
4. **Install Claude Code and sign in with your Pro account** (code.claude.com/docs/en/setup).
5. **Get this repo onto the mini**, in your home folder (not Desktop):
   ```bash
   git clone https://github.com/erte-del/ULTRON_cBrain.git ~/ULTRON_cBrain
   ```
   If it asks you to sign in, run `brew install gh && gh auth login` first.
   **This file must be in the repo you clone.** On the MacBook you need to commit and push
   `mac mini setup.md` (and the README link) first. Or AirDrop the file into `~/ULTRON_cBrain/`.
6. **On the MacBook, before you start:** run `scripts/backup.sh` and AirDrop or USB the
   `~/Ultron-backup-<date>.tgz` to the mini. Then copy the extra items from **section E1** (the
   backup misses them). Don't email the backup: it contains your keys.
7. **Start Claude in the repo and paste this:**
   ```bash
   cd ~/ULTRON_cBrain && claude
   ```
   > Read "mac mini setup.md" in this folder and set up Ultron on this Mac mini by following it.
   > Do the steps you can, tell me exactly when you need me, and check each phase before moving on.

Claude will ask permission for commands as it goes. Approve the ones you're comfortable with.

---

# Part B. Rules for Claude (read these first, they override your habits)

You are setting up **Ultron**, a personal assistant that runs only for this one user, on this one
Mac. `CLAUDE.md` already loaded `ULTRON_BUILD_PROMPT.md`. Read `README.md` §2 too. Then:

**Hard rules**
1. **Never print or read secrets.** Don't `cat`, `Read` or `grep -n` values out of `.env`,
   `storage/*token*.json`, or the backup. List key **names** only:
   `grep -E '^[A-Z_]+=.+' .env | cut -d= -f1`. Edit single non-secret lines with the `setenv`
   helper in Phase 5.
2. **Never set `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_BASE_URL`**, anywhere
   (shell profiles, `.env`, launchd). Ultron runs on the user's Pro login.
3. **The backend stays on `127.0.0.1`.** Never `0.0.0.0`. **Never `tailscale funnel`**, only
   `tailscale serve`.
4. **Never `git commit` or `git push`.** The user makes the commits.
5. **You cannot enter passwords, sign in to accounts, pass 2FA, accept terms, or click macOS
   permission dialogs.** Those are `[USER]` steps. When you reach one, stop, tell the user the
   exact thing to do (and the command or `open` link that gets them to the right screen), and wait
   until they say it's done. Then verify it yourself.
6. **No `sudo`.** If a step needs it, give the user the exact command to run in their own terminal.
7. **Don't overwrite or delete the user's data.** Check before you write. Never run
   `scripts/backup.sh restore` over an existing `.env` without telling the user (it asks for `yes`).
8. **Only touch this Mac mini.** The MacBook, the phone and the Windows PC are `[USER]` steps.
9. **Verify before claiming.** A step is done only when its **Check** command shows it. If a check
   fails or a test fails, report the real output. Don't hide it, don't change application code to
   make it pass, and don't go on to the next phase unless the user says to.
10. **Windows rule:** you are on a Mac, so this doesn't change the code, but keep new commands
    free of hardcoded user paths. Use `$HOME`.

**How to work**
- The user is learning. Explain each phase in one or two simple sentences before you do it.
- Each Bash call is a fresh shell. Re-load `PATH` where needed:
  `eval "$(/opt/homebrew/bin/brew shellenv)"` and, for Node,
  `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"`.
- Make every step safe to re-run: check first (`brew list --formula X`, `ls`, `command -v`).
- Run long jobs (model downloads) in the background and tell the user it will take a while.
- Keep a task list of the phases. At the end of each phase print one status line:
  `Phase N: DONE | NEEDS USER: <what> | FAILED: <why>`.
- Don't ask what you can find out. Ask only the questions in Part C, in **one** message.

---

# Part C. Ask the user these first (one message), then continue

| # | Question | Why | Default if they don't care |
|---|---|---|---|
| 1 | Where is the backup file (`Ultron-backup-<date>.tgz`)? | Phase 4 | stop and wait for it |
| 2 | Are the extra items from section E1 copied? Where is the Obsidian vault now? | Phase 4, 5 | ask again at Phase 4 |
| 3 | Do you want **FLUX images** and **Wan video** (needs Apple Silicon and ~35 GB or more of free disk)? Wan 2.1 only, or also `5b` (Wan 2.2, +~34 GB)? | Phase 6 | FLUX yes, Wan 2.1 yes, 5b no |
| 4 | Do you want **Ollama** (local model for scheduled jobs) and/or **OmniRoute** (other providers' models)? | Phase 2, 5 | no, no |
| 5 | Do you want **game sound in screen clips** (installs BlackHole and needs setup in Audio MIDI Setup)? | Phase 2, 5 | no |
| 6 | Your **Tailscale login** (an email) so the MacBook may open a terminal on the mini? | `JARVIS_TERMINAL_USER` | skip |
| 7 | Automatic login after a reboot? (Needs FileVault **off**: hands-free, but `.env` keys sit on an unencrypted disk.) | Phase 7 | explain the trade-off, leave it to the user |

Don't ask the macOS username or machine name: read them (`whoami`, `scutil --get LocalHostName`).

---

# Part D. The phases

## Phase 0. Preflight [CLAUDE]

Run, and show the user a summary:
```bash
uname -m; sw_vers -productVersion; whoami; echo "$HOME"; scutil --get LocalHostName; df -h /
```
```bash
eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null; for c in brew git uv node npm claude gh ffmpeg tesseract tmux; do printf '%-10s %s\n' "$c" "$(command -v $c || echo MISSING)"; done
```
```bash
ls /Applications | grep -iE 'chrome|blender|keynote|spotify|whatsapp|obsidian|tailscale|ollama|blackhole'; pwd; git -C . rev-parse --show-toplevel
```
```bash
claude auth status; env | grep -c '^ANTHROPIC_' || true
```

**Stop and tell the user if:**
- `uname -m` is not `arm64`: FLUX and Wan can't run here. Skip those two (Phase 6) and say so.
- Free disk is under ~50 GB: ask whether to skip FLUX/Wan.
- `claude auth status` doesn't show `"subscriptionType": "pro"` (or `max`): the brain won't work.
- Any `ANTHROPIC_*` variable is set: tell the user to remove it from their shell profile.
- `brew` is MISSING: the user hasn't done Part A step 3.
- The working folder isn't `~/ULTRON_cBrain` (e.g. it's under Desktop or Documents): macOS blocks
  background programs from reading those. Tell the user to move it, then run `scripts/make_app.sh`
  and `scripts/autostart.sh on` from the new place.

**Check:** the summary is printed, no stop condition fired.

## Phase 1. Things only the user can do [USER]

Ask the user to do these now, one list, and wait. Offer the `open` command for each pane (if one
doesn't open on this macOS version, they navigate manually).

- [ ] **Sleep:** System Settings → Energy: prevent automatic sleeping, and **start up automatically
  after a power failure**. Or in their terminal: `sudo pmset -a sleep 0 disksleep 0 autorestart 1`
- [ ] **Sound:** pick the mic and speakers (`open "x-apple.systempreferences:com.apple.Sound-Settings.extension"`).
- [ ] **Automatic login** (only if they said yes to Question 7): Users & Groups → Automatically log
  in as. Without it, nothing starts after a reboot until someone logs in (autostart is a LaunchAgent).
- [ ] **Screen:** set the screen lock so it doesn't lock while Ultron works. WhatsApp, Chrome,
  Spotify and Keynote automation needs an unlocked, logged-in desktop.
- [ ] **Keynote** from the Mac App Store (free). `make_slides` / `open_slides` use it. Open it once.
- [ ] **Tailscale:** install the Mac app (tailscale.com/download) and sign in. Phone, PC and
  MacBook must be on the same account.
- [ ] **Google account for Contacts:** System Settings → Internet Accounts → add Google, with
  **Contacts** on (`open "x-apple.systempreferences:com.apple.Internet-Accounts-Settings.extension"`).
- [ ] **Remote Login** (optional, for copying files from the MacBook): General → Sharing.

**Check [CLAUDE]:** `ls /Applications | grep -iE 'keynote|tailscale'`;
`pmset -g | grep -E ' sleep |autorestart'`.

## Phase 2. Install tools and apps [CLAUDE]

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
for f in git uv ffmpeg tesseract tmux gh; do brew list --formula "$f" >/dev/null 2>&1 || brew install "$f"; done
for c in google-chrome blender spotify whatsapp obsidian; do brew list --cask "$c" >/dev/null 2>&1 || brew install --cask "$c"; done
```
If a cask is refused, tell the user to download that app from its own website and continue.

Node 24 via nvm (this is what `start_ultron.sh` and `tools/youtube.py` look for):
```bash
[ -s "$HOME/.nvm/nvm.sh" ] || curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm install 24; node --version
```

Only if the user said yes in Part C:
- **Ollama:** the user downloads it from ollama.com/download (no verified cask name).
- **OmniRoute:** `npm i -g omniroute` (with nvm loaded).
- **BlackHole:** `brew install blackhole-2ch`.

**Check:** `command -v git uv ffmpeg tesseract tmux gh node` all print a path;
`ls /Applications | grep -iE 'chrome|blender|spotify|whatsapp|obsidian'` shows all five;
`/Applications/Blender.app/Contents/MacOS/Blender --version` prints a version.

## Phase 3. The code and its environment [CLAUDE]

You should already be in `~/ULTRON_cBrain`. If not, tell the user (Part A step 5).
```bash
cd ~/ULTRON_cBrain && git status --short | head
```
Then:
```bash
eval "$(/opt/homebrew/bin/brew shellenv)"; cd ~/ULTRON_cBrain
uv venv --python 3.13 backend/.venv
VIRTUAL_ENV=backend/.venv uv pip install -r backend/requirements.txt
```
```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; cd ~/ULTRON_cBrain/frontend && npm install && npm run build
```
There is no `pip` inside this environment: always `uv pip install`.

**Check:** `ls frontend/dist/index.html`; `backend/.venv/bin/python --version` shows 3.13.x;
`backend/.venv/bin/python -c "import fastapi, claude_agent_sdk"`.

## Phase 4. Restore the data [CLAUDE, needs the user's files]

1. Confirm the backup file exists (`ls -lh <path from Question 1>`). If there's already a `.env`
   here, tell the user restore will replace it and wait for a yes.
2. ```bash
   cd ~/ULTRON_cBrain && scripts/backup.sh restore <path to Ultron-backup-<date>.tgz>
   ```
   It restores `.env`, memory, saved chats, jobs, school notes, Spotify token, images, 3D models,
   videos and uploads, plus the Claude conversations the saved chats continue.
3. Check the items from section E1 arrived (the user copies them; you only check):
   ```bash
   ls -d ~/Desktop/school ~/Jarvis\ Files backend/storage/{syllabus,textbooks,slides,lectures} backend/storage/instagram_token.json backend/library_tracks/info 2>&1
   ```
   Anything missing: say which feature it breaks (table E1) and ask whether to continue.

**Check:** `.env` exists and `grep -E '^[A-Z_]+=.+' .env | cut -d= -f1` lists key names
(PEXELS_API_KEY, TELEGRAM_BOT_TOKEN, etc.; never values).

## Phase 5. Edit `.env` for this machine [CLAUDE]

Use only this helper, only for non-secret values (paths, addresses):
```bash
cd ~/ULTRON_cBrain
setenv() { if grep -q "^$1=" .env; then sed -i '' "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }
```
Re-define it in each Bash call that uses it.

| Key | Set it to | Notes |
|---|---|---|
| `JARVIS_VAULT` | the vault's path **on this Mac** (ask the user), e.g. `$HOME/Notes` | The restored value is `/Users/erselinankul/Desktop/Notes`, which is the MacBook. Check the folder exists. |
| `JARVIS_HOST` | leave `127.0.0.1` | Must never be `0.0.0.0`. |
| `JARVIS_REMOTE_ORIGIN` | set in Phase 8 | After Tailscale is serving. |
| `JARVIS_PC_URL`, `JARVIS_PC_TOKEN` | **don't touch** | These belong to the Windows PC. |
| `JARVIS_TERMINAL_USER` | their Tailscale login | Only if they gave one (Question 6). |
| `JARVIS_CAPTURE_SCREEN` | the display's name | After the display is connected: `ffmpeg -f avfoundation -list_devices true -i "" 2>&1 \| grep -i -A8 'video devices'`. Default `Capture screen 0`. Use the name, not a number. |
| `JARVIS_CAPTURE_AUDIO` | BlackHole's index | Only if Question 5 was yes and the user made the Multi-Output Device in Audio MIDI Setup. |
| `JARVIS_OLLAMA_MODEL` | `ultron-qwen3-14b` | Only if Question 4 was yes, after Phase 6's Ollama step. |
| `INSTAGRAM_ACCESS_TOKEN` | leave | The renewed token lives in `storage/instagram_token.json` (copied in E1). |

Other files tied to the MacBook (tell the user, don't fix unless asked): `.claude/launch.json`
(tracked) has `/Users/erselinankul/...` paths and an nvm node path. It only matters if they open
the project in the Claude desktop app on the mini.

**Check:** `ls -d "$(grep '^JARVIS_VAULT=' .env | cut -d= -f2-)"` succeeds;
`grep -c '^JARVIS_HOST=127.0.0.1' .env` is 1 (or the key is absent: default is `127.0.0.1`);
`grep -c '^ANTHROPIC_' .env` is 0.

## Phase 6. Build the Mac pieces and download models [CLAUDE, with the user clicking Allow]

Order matters. The certificate comes first so macOS keeps Screen Recording permission after rebuilds.
```bash
cd ~/ULTRON_cBrain && scripts/make_cert.sh && scripts/make_app.sh
```
```bash
scripts/setup_location.sh
```
This last one makes macOS ask for **Location**. Tell the user to click **Allow** on the mini.

Downloads (check `df -h /` first; run in the background; tell the user they take a while):
```bash
scripts/setup_voice.sh      # ~2 GB: Kokoro fallback voice, Piper Turkish, captions
scripts/setup_images.sh     # ~16 GB, keeps ~9 GB: FLUX.2 Klein (Apple Silicon only)
scripts/setup_video.sh      # ~17.6 GB: Wan 2.1 (add `5b` for Wan 2.2, ~34 GB more)
```
Only run images and video if the user wanted them (Question 3) and Phase 0 said `arm64`.
Each script is safe to re-run.

If Ollama (Question 4):
```bash
ollama pull qwen3:14b && python3 scripts/make_ollama_model.py
```
then `setenv JARVIS_OLLAMA_MODEL ultron-qwen3-14b` (the script patches qwen3:14b: 32k window, no thinking; fits 24 GB RAM).

**Check:** `ls -d Ultron.app backend/storage/UltronLocation.app`;
`codesign --verify Ultron.app` (no output = good); `ls backend/storage/flux backend/storage/wan backend/storage/voice`
as applicable; `ollama list | grep ultron` if Ollama.

## Phase 7. Start it and run the tests [CLAUDE]

```bash
cd ~/ULTRON_cBrain/backend && .venv/bin/python -m unittest discover tests 2>&1 | tail -20
```
Report the real result. Skips for missing optional tools are fine; failures are not. Don't edit
code to silence them.
```bash
cd ~/ULTRON_cBrain && scripts/start_ultron.sh --no-open && curl -s http://127.0.0.1:8000/health
```
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```
The listener must be `127.0.0.1:8000` (or `localhost`), **never** `*:8000`. Then turn on always-on:
```bash
scripts/autostart.sh on
```
It writes the LaunchAgent `com.ultron.backend`, starts Ultron at login, and restarts it if it
crashes. Log: `~/Library/Logs/Ultron.log`.

**Check:** `curl -s http://127.0.0.1:8000/health` answers;
`launchctl print gui/$(id -u)/com.ultron.backend | head -5` shows it loaded;
`tail -20 ~/Library/Logs/Ultron.log` has no tracebacks.

**School-folder check:** with autostart on, macOS may block the background process from reading
`~/Desktop/school` (the code hardcodes that path in `tools/textbook.py:28` and `tools/slides.py:31`).
Test it from the running backend: ask the user to say "what's in my textbook folder?" in the page.
If it fails with a permission error, the fix is **Full Disk Access** for
`~/ULTRON_cBrain/backend/.venv/bin/python` (user, in System Settings), or moving the folder and
changing those two paths. Ask before changing code.

## Phase 8. Tailscale and the switch-over [CLAUDE for the Mac, USER for everything else]

1. [CLAUDE] The Mac app's CLI: `TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale`
   (use plain `tailscale` if it's on PATH). `$TS status` must show the mini logged in.
2. [CLAUDE] `$TS serve --bg 8000`, then read the mini's address:
   `$TS status --json | python3 -c "import sys,json; print('https://'+json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))"`
3. [CLAUDE] `setenv JARVIS_REMOTE_ORIGIN <that address>` then restart:
   `launchctl kickstart -k gui/$(id -u)/com.ultron.backend`
4. [USER] **Phone:** open the new address (new bookmark / home-screen shortcut). MacroDroid and
   Telegram are cloud services and need no change.
5. [USER] **Windows PC:** edit `windows/wake_pc.env` on the PC: `ULTRON_URL=<mini's address>`, then
   restart its "Hey Ultron" listener (`scripts\autostart.ps1 on`). `JARVIS_PC_URL` and the PC agent
   don't change.
6. [USER] **Retire Ultron on the MacBook** so it doesn't run jobs twice: quit `Ultron.app`, run
   `scripts/autostart.sh off` and `scripts/stop_ultron.sh` there, and `tailscale serve reset`.
   (Optional shortcut to keep the old address: rename the MacBook in the Tailscale admin console
   first, then rename the mini to the old name. Phone and PC then need no change.)

**Never** `tailscale funnel`.

**Check:** `$TS serve status` shows `https://<name>.ts.net` → `127.0.0.1:8000`; from the user's
phone the address loads the Ultron page.

## Phase 9. Sign-ins and permissions [USER, Claude guides and verifies]

Walk the user through these one at a time. Claude can't click any of them.

**Sign-ins**
- [ ] **Chrome:** Microsoft Teams (homework), Amazon (default `amazon.ae`; `JARVIS_AMAZON_URL` changes it), Google Flights.
- [ ] **Chrome menu bar → View → Developer → Allow JavaScript from Apple Events.** Homework, Amazon and flights read Chrome this way.
- [ ] **Chrome:** allow the **microphone** for `http://127.0.0.1:8000` and the Tailscale address (voice runs in the page).
- [ ] **Spotify** desktop app. **WhatsApp** desktop app (scan the QR with their phone). **Obsidian:** open the vault once.
- [ ] **GitHub CLI:** `gh auth login` (the `github` tool is read-only).
- [ ] **claude.ai connectors** (belong to the account, so they should already be there): Gmail, Google Calendar, Google Drive, TickTick, Canva, Spotify, Claude Docs. They confirm at claude.ai/settings/connectors.

**macOS permissions** (System Settings → Privacy & Security; deep links may vary by macOS version)
- [ ] Accessibility (`Ultron.app`, WhatsApp automation): `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"`
- [ ] Screen Recording (`Ultron.app` overlay and screen share; clipping): `...?Privacy_ScreenCapture`
- [ ] Location Services → Ultron Location: `...?Privacy_LocationServices`
- [ ] Contacts: `...?Privacy_Contacts`
- [ ] Microphone: `...?Privacy_Microphone`
- [ ] Automation (Ultron controlling Chrome, Spotify, System Events, Finder, Keynote): `...?Privacy_Automation`. These prompts appear the first time each feature runs; tell the user to click Allow.
- [ ] Notifications for job results.
- [ ] Full Disk Access only if Phase 7's school-folder check failed.

**Check [CLAUDE]:** `gh auth status`; `claude auth status`. The rest is proved by the feature
tests in Phase 10.

## Phase 10. Prove every feature works [CLAUDE runs what it can; USER does the rest]

**Claude can verify these itself (no human needed):**
```bash
curl -s http://127.0.0.1:8000/health
cd ~/ULTRON_cBrain/backend && .venv/bin/python -m unittest discover tests 2>&1 | tail -5
ffmpeg -version | head -1; tesseract --version | head -1; tmux -V; gh --version | head -1
/Applications/Blender.app/Contents/MacOS/Blender --version | head -1
ls ~/Desktop/school ~/Jarvis\ Files | head
launchctl print gui/$(id -u)/com.ultron.backend | grep -E 'state|pid'
```

**The user tests these in the page** (Claude reads the log after each with
`tail -30 ~/Library/Logs/Ultron.log` and reports problems). Tick each:

*Core*
- [ ] Text chat answers on the Pro login and shows a model badge
- [ ] "use opus" switches the model (`ask_expert`); web search shows source chips
- [ ] A WhatsApp send **asks first** (the approval card)
- [ ] Canvas cards; save a chat and reload it; "remember that…" then the memory panel

*Connectors*
- [ ] Gmail ("any important unread email?"), Google Calendar ("what's on today?"), Google Drive, TickTick ("remind me to… at…"), Canva, Claude Docs
- [ ] Spotify connector, and `spotify_control` playing on the desktop app

*Voice* (mic and speakers connected)
- [ ] Listening, speaking, orb states, barge-in; "stop", "cancel", "wait", "never mind"; "go back to typing"
- [ ] "Hey Ultron" wake word; screen sharing ("look at my screen", ⌃⌥U)
- [ ] ElevenLabs voice works; Kokoro takes over if `JARVIS_TTS=kokoro`; "how much voice is left?"

*Images, video, 3D*
- [ ] `image_search`, `image_edit`, `image_undo`; `generate_image` and `image_ai_edit` (FLUX); `generate_video` (Wan, takes minutes)
- [ ] 3D: preview, change, approve, then `export_3d` (Blender)

*Reels, Instagram, clips*
- [ ] `reel_edit`, `stock_search`, `stock_download`, `watch_short`
- [ ] Instagram preview, stats, comments, queue; post, reply and schedule must always ask
- [ ] "start recording", "clip the last 30 seconds"; the library at `http://127.0.0.1:8000/?captures=1`

*This Mac (now the mini)*
- [ ] `mac_read`: status (battery will say none), Wi-Fi, volume, location, clipboard, Shortcuts (the mini won't have the MacBook's Shortcuts)
- [ ] `mac_change`: open an app, clipboard, volume, dark mode, move and trash a file inside `~/Jarvis Files`
- [ ] `run_python` on a CSV (sandbox: no network, writes only to `Output/`)
- [ ] Terminal tab (and from the MacBook with `JARVIS_TERMINAL_USER`)
- [ ] `find_contact`, `whatsapp_send`; `maps`, weather, "when should I leave for my next meeting"

*School, shopping, travel*
- [ ] `check_homework` (Teams) and the exam countdown
- [ ] `syllabus`, `textbook` (needs Tesseract and `~/Desktop/school`), `make_slides` and `open_slides` (Keynote), `lectures`
- [ ] `amazon_read` / `amazon_change` (never checks out); `flights` (never books)

*Notes, files, jobs*
- [ ] `search_notes`, `read_note`, `write_note` (the vault at its new path; `#private` never read)
- [ ] `read_upload` (drag a file into chat); `mark_important` / `unmark_important`; `github`
- [ ] Jobs: a weekday briefing, a watcher, run now, pause, delete; results reach chat, a macOS banner and Telegram

*Phone and PC*
- [ ] The phone opens the Tailscale address and chats
- [ ] `text_me` (Telegram), `phone_volume`, `phone_taxi`, `phone_food` (MacroDroid, Android)
- [ ] `pc_read`, `pc_change`, `pc_run` (always asks); "record my PC screen"; the PC's "Hey Ultron" opens the **mini's** page

*Other brains* (only if set up)
- [ ] Ollama runs a scheduled job; OmniRoute works from the gear icon

---

## Final report [CLAUDE]

When the phases are done, give the user one short report: each phase's status line; what you
verified yourself and how; what is still the user's to test (unticked boxes in Phase 10); anything
that failed and the real output; and the one-line "Windows setup" (nothing to set up, except
`ULTRON_URL` on the PC if the address changed). Then say plainly whether the mini is ready.
Remind the user to commit the repo changes themselves.

---

# Part E. Reference

## E1. What `scripts/backup.sh` does not back up (copy these by hand, from the MacBook)

`backup.sh` saves only: `.env`, `chats.json`, `memory.json`, `jobs.json`, `school.md`,
`homework_seen.json`, `usage.json`, `spotify_token.json`, and the `assets`, `models`, `uploads`
and `videos` folders, plus the Claude conversations saved chats continue. Everything below is
**separate**. Sizes are from the MacBook.

| What | Size | MacBook path | Mini path | Breaks without it |
|---|---|---|---|---|
| School folder (**path hardcoded**) | 72 MB | `~/Desktop/school` | `~/Desktop/school` (same) | `textbook`, `lectures`, `make_slides` |
| Syllabus | 180 KB | `backend/storage/syllabus/` | same, in the mini's repo | `syllabus` |
| Textbooks index | 612 KB | `backend/storage/textbooks/` | same | `textbook` |
| Slides | 3.8 MB | `backend/storage/slides/` | same | `make_slides`, `open_slides` |
| Lectures | 17 MB | `backend/storage/lectures/` | same | `lectures` |
| Instagram token | 4 KB | `backend/storage/instagram_token.json` | same | `instagram_*` (renews weekly into this file) |
| ACC track info texts | 96 KB | `backend/library_tracks/info/` | same | `track_info` (kept out of git on purpose) |
| Obsidian vault | 7.2 MB | `~/Desktop/Notes` | e.g. `~/Notes`, then set `JARVIS_VAULT` | all notes tools |
| Ultron's file folder | 1.0 GB | `~/Jarvis Files` | `~/Jarvis Files` | old Reels, stock, outputs (optional) |

**Re-download on the mini, don't copy** (in no backup and no git): `storage/flux` (9.1 GB),
`storage/wan` (15 GB), `storage/voice` (5.1 GB), `storage/f1cache`, and the Mac-built apps
`Ultron.app` and `UltronLocation.app`.

**Copy methods:** AirDrop or USB; or with Remote Login on the mini, from the MacBook:
```bash
rsync -avh --progress ~/Desktop/school/ miniuser@mini-name.local:~/Desktop/school/
rsync -avh --progress ~/Desktop/Notes/ miniuser@mini-name.local:~/Notes/
rsync -avh --progress ~/Desktop/ULTRON_cBrain/backend/storage/{syllabus,textbooks,slides,lectures} miniuser@mini-name.local:~/ULTRON_cBrain/backend/storage/
rsync -avh ~/Desktop/ULTRON_cBrain/backend/storage/instagram_token.json miniuser@mini-name.local:~/ULTRON_cBrain/backend/storage/
rsync -avh ~/Desktop/ULTRON_cBrain/backend/library_tracks/info/ miniuser@mini-name.local:~/ULTRON_cBrain/backend/library_tracks/info/
```
Run the `backend/...` ones after the repo is cloned on the mini.

## E2. Mac mini differences

| Difference | Effect | Handled in |
|---|---|---|
| No mic or speakers | voice, wake word, clip audio | Part A step 2, Phase 1 |
| No camera, no battery | `mac_read` battery says none; Desk View device names don't apply | nothing to do |
| No GPS, location from Wi-Fi | `maps`, weather, leave-by times | keep Wi-Fi on; Phase 6 |
| Needs a real or dummy display | screen recording, overlay, Chrome automation | Part A step 2 |
| Must not sleep; start after power loss | scheduler, watchers, briefings | Phase 1 |
| Must be logged in | autostart is a LaunchAgent | Phase 1 |
| Apple Silicon required | FLUX, Wan | Phase 0 |
| Disk space | FLUX ~16 GB, Wan ~15 GB (5B ~34 GB), voice ~5 GB | Phase 0, 6 |

## E3. Accounts and keys in use (names only, from the MacBook's `.env`)

`PEXELS_API_KEY`, `PIXABAY_API_KEY`, `GROQ_API_KEY`, `ELEVENLABS_API_KEY`, `JARVIS_ELEVENLABS_VOICE`,
`JARVIS_TTS` (`elevenlabs`), `SPOTIFY_CLIENT_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`MACRODROID_WEBHOOK`, `INSTAGRAM_ACCESS_TOKEN`, `JARVIS_VAULT`, `JARVIS_REMOTE_ORIGIN`, `JARVIS_PC_URL`,
`JARVIS_PC_TOKEN`, `JARVIS_HOST`, `JARVIS_PORT`. They all come across with the backup. Blank today
and therefore optional: Ollama, OmniRoute, `JARVIS_TERMINAL_USER`, `JARVIS_CAPTURE_*`, `BLENDER_PATH`
(the default is right).

## E4. If something doesn't work

| Symptom | Check |
|---|---|
| Ultron won't start | `tail -50 ~/Library/Logs/Ultron.log`; `curl -s http://127.0.0.1:8000/health` |
| Nothing starts after a reboot | nobody is logged in: automatic login (Phase 1) |
| Not loaded in launchd | `launchctl print gui/$(id -u)/com.ultron.backend`; re-run `scripts/autostart.sh on` |
| Pro login not used | `claude auth status`; `env \| grep ANTHROPIC` must be empty |
| Phone can't reach it | `$TS status`; `$TS serve status`; `JARVIS_REMOTE_ORIGIN` must match exactly |
| Voice silent or deaf | mic and speakers selected in Sound; Chrome mic permission for the address |
| "near me" or weather empty | Wi-Fi on; re-run `scripts/setup_location.sh`; Location Services → Ultron Location |
| Clips empty / "no footage" | Screen Recording permission; set `JARVIS_CAPTURE_SCREEN` to the display's name |
| School tools find nothing | `~/Desktop/school` exists; Full Disk Access note in Phase 7 |
| Homework, Amazon, flights fail | Chrome signed in; **Allow JavaScript from Apple Events** is on |
| Notes not found | `JARVIS_VAULT` points at the mini's vault |
| Slides don't open | Keynote installed and opened once |
| Screen Recording asked again after a rebuild | run `scripts/make_cert.sh` once, then `scripts/make_app.sh` |

## E5. Known limits

- Mac tools (`mac_*`, contacts, WhatsApp, maps, Chrome automation, `Ultron.app`, the sandboxed
  Python, FLUX, Wan) are **Mac only**. They act on the **mini's** Contacts, WhatsApp, location,
  Shortcuts and files, not the MacBook's.
- `scripts/backup.sh` is missing the items in E1. Adding them to its `DATA` list would fix the next move.
- Words said in the same breath as "Hey Ultron" on the PC are not passed on. Phone calls (Twilio) are not built.
- Notifications that open the related card need `terminal-notifier`; plain ones open Script Editor
  (next step 5 in `ULTRON_BUILD_PROMPT.md`).

**Windows setup:** nothing to set up. The one Windows action is `ULTRON_URL` in
`windows/wake_pc.env` on the PC if the address changes (Phase 8).
