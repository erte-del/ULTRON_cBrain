# Mac mini setup: everything, in order

Goal: the Mac mini becomes Ultron's dedicated brain with **every feature working**. The MacBook
stays personal and stops running Ultron.

This is a runbook. Do the parts in order. Each step says what to run, what to change, or what to
sign in to. Built from `README.md`, `.env.example`, the `scripts/`, and the code itself (checked
against this MacBook on 2026-10-13). Tick things off as you go.

**What I could verify from the repo, and what I couldn't:** commands, paths, file lists and
`.env` keys below come straight from the code. macOS menu names and permission prompts can differ
slightly between macOS versions, and nothing here has been run on the mini yet. Section 10 is the
test list that proves it.

---

## 0. Read first: the 10 things that will bite you

1. **`scripts/backup.sh` does NOT back up everything.** It misses your school folder, syllabus,
   textbooks, slides, lectures, the Instagram token, the ACC track info texts, your Obsidian
   vault and `~/Jarvis Files`. Section 3 lists each one with its size and where to copy it.
2. **`~/Desktop/school` is hardcoded in the code** (`backend/tools/textbook.py:28` and
   `backend/tools/slides.py:31`, which looks in `school/computing/class lectures`). The folder
   must exist at exactly that path on the mini, under the mini's user.
3. **The Obsidian vault path in `.env` points at this MacBook**
   (`JARVIS_VAULT=/Users/erselinankul/Desktop/Notes`). Change it on the mini.
4. **`make_slides` / `open_slides` use Keynote** (`tell application "Keynote"`). Install Keynote
   from the Mac App Store. It is not on the README's app list.
5. **No mic, speakers or battery on a Mac mini.** Voice needs real audio hardware you plug in.
6. **Location comes from Wi-Fi.** Keep Wi-Fi on even if you use Ethernet.
7. **Clone into your home folder, not Desktop or Documents.** macOS stops background programs
   (launchd autostart) reading those, per `README.md` §2.3. Because the code reads
   `~/Desktop/school`, test that after turning autostart on (section 6).
8. **Autostart only runs while a user is logged in** (it is a LaunchAgent). After a reboot nothing
   starts until someone logs in, unless you turn on automatic login (section 1).
9. **Run Ultron on one machine only.** Stop it on the MacBook before the mini goes live, or both
   will run your scheduled jobs and send duplicate Telegram messages.
10. **Never set `ANTHROPIC_API_KEY`**, and never use `tailscale funnel`.

---

## 1. The Mac mini itself (hardware and macOS settings)

| Thing | What to do |
|---|---|
| **Chip** | FLUX images and Wan video need Apple Silicon. Your MacBook is an M5, so the mini should be Apple Silicon too. An Intel mini would lose those two features. |
| **Disk** | Free space for: FLUX ~16 GB (keeps ~9 GB), Wan ~15 GB (Wan 5B ~34 GB), voice models ~5 GB, plus your data. Your MacBook currently uses `storage/flux` 9.1 GB, `storage/wan` 15 GB, `storage/voice` 5.1 GB. Budget **50 GB+ free**. |
| **Display** | Connect a monitor, or a cheap **HDMI dummy plug**. Screen recording, the screen overlay, Chrome automation and permission prompts all need a real desktop. |
| **Microphone and speakers** | Plug in a USB or Bluetooth mic and speakers (or a monitor with both). Pick them in System Settings → Sound. Voice, the wake word and screen-clip audio need them. |
| **Wi-Fi** | Turn Wi-Fi **on** (even if you use Ethernet). Location (`maps`, weather, leave-by times, `UltronLocation.app`) comes from Wi-Fi. |
| **Sleep** | System Settings → Energy: prevent automatic sleeping, and **Start up automatically after a power failure**. Or: `sudo pmset -a sleep 0 disksleep 0 autorestart 1` |
| **Automatic login** | System Settings → Users & Groups → Automatically log in as (this is greyed out while **FileVault** is on). Without it, nothing starts after a reboot until you log in. Your choice: FileVault off + auto-login (hands-free, but `.env` keys sit on an unencrypted disk), or FileVault on and you log in by hand after a reboot. |
| **Lock screen** | Keep the screen unlocked while Ultron works. Its WhatsApp, Chrome, Spotify and Keynote automation (AppleScript / System Events) needs an unlocked, logged-in desktop. |
| **Computer name** | System Settings → General → Sharing → Local hostname. Pick a short name; it becomes part of the Tailscale address (see section 7). |
| **Username** | If it is not `erselinankul`, remember to change the paths listed in section 5. |
| **Remote Login (optional)** | System Settings → General → Sharing → Remote Login, and Screen Sharing. Lets you copy files with `rsync` and fix things without walking to the mini. Use it over Tailscale only. |
| **Software Update** | Run it first; reboot. |

---

## 2. On the MacBook, before you switch (prep)

- [ ] Run the backup: `cd ~/Desktop/ULTRON_cBrain && scripts/backup.sh` → `~/Ultron-backup-<date>.tgz` (it holds your keys: AirDrop or USB, never email).
- [ ] Copy the things the backup misses (section 3). Do this now while the MacBook still has them.
- [ ] Write down your **Tailscale login** (for `JARVIS_TERMINAL_USER`) and your current Ultron address (`JARVIS_REMOTE_ORIGIN` in `.env`).
- [ ] Optional shortcut to keep the same address: in the Tailscale admin console (login.tailscale.com/admin/machines) rename the MacBook to something else, so the mini can take its name later. The phone and PC then need no change.
- [ ] **Don't turn Ultron off yet.** Do it in section 7, once the mini works. (Autostart is already off on this MacBook. Quit `Ultron.app` / stop the backend then.)

---

## 3. Data that must be copied by hand (not in `backup.sh`)

`backup.sh` only saves: `.env`, `chats.json`, `memory.json`, `jobs.json`, `school.md`,
`homework_seen.json`, `usage.json`, `spotify_token.json`, and the `assets`, `models`, `uploads`
and `videos` folders, plus the Claude conversations your saved chats continue. Everything below
is **separate**. Sizes are from this MacBook.

| What | Size | Copy from (MacBook) | Copy to (mini) | Needed for |
|---|---|---|---|---|
| School folder (hardcoded path) | 72 MB | `~/Desktop/school` | `~/Desktop/school` (same path) | `textbook`, `lectures`, `make_slides` |
| Syllabus | 180 KB | `backend/storage/syllabus/` | same path in the mini's project | `syllabus` |
| Textbooks (scans index) | 612 KB | `backend/storage/textbooks/` | same | `textbook` |
| Slides | 3.8 MB | `backend/storage/slides/` | same | `make_slides`, `open_slides` |
| Lectures | 17 MB | `backend/storage/lectures/` | same | `lectures` |
| Instagram token | 4 KB | `backend/storage/instagram_token.json` | same | `instagram_*` (the token renews weekly into this file; the one in `.env` may be stale) |
| ACC track info texts | 96 KB | `backend/library_tracks/info/` | same | `track_info` (kept out of git on purpose) |
| Obsidian vault | 7.2 MB | `~/Desktop/Notes` | `~/Notes` (or anywhere), then set `JARVIS_VAULT` | `search_notes`, `read_note`, `write_note` |
| Ultron's file folder | 1.0 GB | `~/Jarvis Files` | `~/Jarvis Files` | `mac_*` file tools, Reels, stock downloads. Optional: skip if you don't need the old files. |

**Don't copy these; re-download them on the mini** (they are in no backup and no git):
`backend/storage/flux` (9.1 GB), `backend/storage/wan` (15 GB), `backend/storage/voice` (5.1 GB),
`backend/storage/f1cache`, and the Mac-built apps `Ultron.app` and `UltronLocation.app`.
(You can `rsync` the model folders instead of re-downloading if you prefer; it is just slow.)

**How to copy** (pick one):
- AirDrop or a USB stick for the small items.
- Or, with Remote Login on the mini, from the MacBook (replace `miniuser` and `mini-name`):
  ```bash
  rsync -avh --progress ~/Desktop/school/ miniuser@mini-name.local:~/Desktop/school/
  ```
  ```bash
  rsync -avh --progress ~/Desktop/Notes/ miniuser@mini-name.local:~/Notes/
  ```
  ```bash
  rsync -avh --progress ~/Desktop/ULTRON_cBrain/backend/storage/{syllabus,textbooks,slides,lectures} miniuser@mini-name.local:~/ULTRON_cBrain/backend/storage/
  ```
  ```bash
  rsync -avh ~/Desktop/ULTRON_cBrain/backend/storage/instagram_token.json miniuser@mini-name.local:~/ULTRON_cBrain/backend/storage/
  ```
  ```bash
  rsync -avh ~/Desktop/ULTRON_cBrain/backend/library_tracks/info/ miniuser@mini-name.local:~/ULTRON_cBrain/backend/library_tracks/info/
  ```
  Run the `backend/...` copies after the project is cloned on the mini (step 4.3).

---

## 4. Install, in order

### 4.1 Developer basics
- [ ] `xcode-select --install` (needed to build `Ultron.app` and `UltronLocation.app`)
- [ ] Install Homebrew (brew.sh), then add it to your shell:
  ```bash
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile && eval "$(/opt/homebrew/bin/brew shellenv)"
  ```
- [ ] CLI tools:
  ```bash
  brew install git uv ffmpeg tesseract tmux gh
  ```
  (ffmpeg: Reels, clipping, YouTube. tesseract: scanned textbooks. tmux: terminal tabs survive a closed tab. gh: the `github` tool.)
- [ ] **Node.js 24**, the way your MacBook has it (via nvm; `start_ultron.sh` and `youtube.py` look for it there):
  ```bash
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  ```
  Open a new terminal, then `nvm install 24`.
- [ ] `gh auth login` (also lets you clone the repo if it is private, and lets the `github` tool work).

### 4.2 Apps
- [ ] **Google Chrome** (the page, voice, screen sharing, Teams, Amazon, flights all use it): `brew install --cask google-chrome`
- [ ] **Blender** (3D export; default path `/Applications/Blender.app/Contents/MacOS/Blender` matches `.env`): `brew install --cask blender`
- [ ] **Keynote** (`make_slides` / `open_slides`): Mac App Store, free
- [ ] **Spotify desktop**: `brew install --cask spotify`
- [ ] **WhatsApp desktop**: `brew install --cask whatsapp`
- [ ] **Obsidian**: `brew install --cask obsidian`
- [ ] **Tailscale**: install the Mac app from tailscale.com/download (needed for phone, PC and remote terminal)
- [ ] Optional: **BlackHole** for game sound in screen clips: `brew install blackhole-2ch`
- [ ] Optional: **Ollama** (local model for scheduled jobs): ollama.com/download
- [ ] Optional: **OmniRoute** (second brain for other providers' models): `npm i -g omniroute`
- [ ] Optional: **Telegram** on your phone, **MacroDroid** on your Android phone (not on the mini)

If a `brew install --cask` name is rejected, download that app from its own website instead.

### 4.3 Ultron's code
- [ ] Clone into your **home folder**, not Desktop:
  ```bash
  git clone https://github.com/erte-del/ULTRON_cBrain.git ~/ULTRON_cBrain && cd ~/ULTRON_cBrain
  ```
- [ ] Python 3.13 environment and backend dependencies (always `uv pip`, never plain `pip`):
  ```bash
  uv venv --python 3.13 backend/.venv
  ```
  ```bash
  VIRTUAL_ENV=backend/.venv uv pip install -r backend/requirements.txt
  ```
- [ ] Build the page:
  ```bash
  cd frontend && npm install && npm run build && cd ..
  ```

### 4.4 Claude Code (the brain)
- [ ] Install Claude Code (code.claude.com/docs/en/setup), run `claude`, sign in with your **Pro** account.
- [ ] Check: `claude auth status` must show `"subscriptionType": "pro"` (or `max`).
- [ ] Check no API key leaked into the shell: `env | grep ANTHROPIC` must print nothing.
- [ ] The claude.ai **connectors** (Gmail, Google Calendar, Google Drive, TickTick, Canva, Spotify, Claude Docs) belong to your claude.ai account, not the machine, so they appear once you are signed in. Confirm at claude.ai/settings/connectors that each is still connected.

### 4.5 Restore your data
- [ ] Put `Ultron-backup-<date>.tgz` on the mini, then:
  ```bash
  cd ~/ULTRON_cBrain && scripts/backup.sh restore ~/Ultron-backup-<date>.tgz
  ```
  This restores `.env`, memory, chats, jobs, school notes, tokens, images, 3D models, videos and uploads.
- [ ] Now do the manual copies from section 3.
- [ ] Run the tests:
  ```bash
  cd backend && .venv/bin/python -m unittest discover tests
  ```

---

## 5. Edit `.env` and the other MacBook-tied files

Your MacBook's `.env` currently sets these (names only, from this machine): `PEXELS_API_KEY`,
`PIXABAY_API_KEY`, `GROQ_API_KEY`, `ELEVENLABS_API_KEY`, `JARVIS_ELEVENLABS_VOICE`, `JARVIS_TTS`
(`elevenlabs`), `SPOTIFY_CLIENT_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `MACRODROID_WEBHOOK`,
`INSTAGRAM_ACCESS_TOKEN`, `JARVIS_VAULT`, `JARVIS_REMOTE_ORIGIN`, `JARVIS_PC_URL`, `JARVIS_PC_TOKEN`,
`JARVIS_HOST`, `JARVIS_PORT`. The restore brings them all across. Then change:

| Setting | What to do on the mini |
|---|---|
| `JARVIS_VAULT` | Currently `/Users/erselinankul/Desktop/Notes`. Set it to the vault's new path on the mini, e.g. `/Users/<miniuser>/Notes`. |
| `JARVIS_REMOTE_ORIGIN` | Set to the **mini's** `https://….ts.net` address from `tailscale serve` (section 7). Same address if you renamed the MacBook and reused its name. |
| `JARVIS_PC_URL`, `JARVIS_PC_TOKEN` | **No change.** These are the Windows PC's own address and token. |
| `JARVIS_HOST` | Must stay `127.0.0.1`. Never `0.0.0.0`. |
| `JARVIS_TERMINAL_USER` | Optional. Your Tailscale login, e.g. `you@gmail.com`, so your MacBook can open a terminal on the mini. |
| `JARVIS_CAPTURE_SCREEN` | Optional. Find the display's name with `ffmpeg -f avfoundation -list_devices true -i ""` and set it (default `Capture screen 0`). Do this once the monitor or dummy plug is connected. |
| `JARVIS_CAPTURE_AUDIO` | Optional. BlackHole's index from the same ffmpeg command (audio list). See `.env.example`. |
| `JARVIS_OLLAMA_MODEL` | Optional, blank today. See section 8. |
| `JARVIS_PROVIDER`, `JARVIS_GATEWAY_*` | Blank today. Only for OmniRoute. |
| `BLENDER_PATH` | Default is right if Blender is in `/Applications`. |
| `INSTAGRAM_ACCESS_TOKEN` | If the `.env` one has expired, copy `storage/instagram_token.json` (section 3), which holds the renewed token. |

Other files that mention this MacBook:
- [ ] `.claude/launch.json` (tracked in git) has `/Users/erselinankul/Desktop/ULTRON_cBrain/...`
  and `/Users/erselinankul/.nvm/versions/node/v24.21.0/bin/node`. It only matters if you open the
  project in the Claude desktop app on the mini (for its preview). Fix the paths if you do.
- [ ] `windows/wake_pc.env` (on the Windows PC, git-ignored) has `ULTRON_URL=https://<mac>.ts.net`.
  Change it to the mini's address if the address changed (section 7).

---

## 6. Build the Mac pieces, then run it

Order matters: certificate first, so macOS keeps its Screen Recording permission after rebuilds.

- [ ] `scripts/make_cert.sh` (once; makes the "Ultron Local Signing" certificate in your login keychain)
- [ ] `scripts/make_app.sh` (builds `Ultron.app`, the menu-bar orb and screen overlay)
- [ ] `scripts/setup_location.sh` (builds `UltronLocation.app`, asks macOS for Location once; click Allow)
- [ ] `scripts/setup_voice.sh` (Reel voice-overs, Kokoro fallback voice, Piper Turkish, captions; ~2 GB)
- [ ] `scripts/setup_images.sh` (FLUX.2 Klein; ~16 GB download, keeps ~9 GB)
- [ ] `scripts/setup_video.sh` (Wan 2.1; add `5b` for Wan 2.2 at 720p and image to video; ~17.6 GB, 5B ~34 GB)

Each script is safe to run again; finished steps are skipped.

- [ ] Double-click `Ultron.app` once. An orb appears in the menu bar; the page opens at `http://127.0.0.1:8000`.
- [ ] Check it is up: `curl -s http://127.0.0.1:8000/health`
- [ ] Turn on always-on:
  ```bash
  scripts/autostart.sh on
  ```
  It writes a LaunchAgent `com.ultron.backend`, starts Ultron at login, and restarts it if it
  crashes. Log: `~/Library/Logs/Ultron.log`. With autostart on, quitting `Ultron.app` restarts
  Ultron instead of stopping it.
- [ ] **After autostart is on, re-test the school tools** ("what's in my textbook folder?"). If
  macOS blocks the background process from reading `~/Desktop/school`, grant **Full Disk Access**
  to `backend/.venv/bin/python` (System Settings → Privacy & Security), or move the folder and
  change the two hardcoded paths in the code.

---

## 7. Switch over: phone, PC, Tailscale, retire the MacBook

- [ ] Tailscale on the mini: sign in to the **same account** as your phone, PC and MacBook.
- [ ] On the mini: `tailscale serve --bg 8000` (the Mac app's CLI is at `/Applications/Tailscale.app/Contents/MacOS/Tailscale` if `tailscale` isn't on your PATH). It prints `https://<name>.<tailnet>.ts.net`.
  **Never `tailscale funnel`**: that would put Ultron on the public internet with no password.
- [ ] Put that address in `.env` as `JARVIS_REMOTE_ORIGIN`, then restart Ultron:
  ```bash
  launchctl kickstart -k gui/$(id -u)/com.ultron.backend
  ```
- [ ] **Phone:** open the new address (update your bookmark or home-screen shortcut). MacroDroid and the Telegram bot are cloud services, so they need no change.
- [ ] **Windows PC:** edit `windows/wake_pc.env` on the PC: `ULTRON_URL=<the mini's address>`, then restart the "Hey Ultron" listener (`scripts\autostart.ps1 on` there, or re-run `windows\wake_pc.ps1`). The PC agent (`ultron_pc.py`) and `JARVIS_PC_URL` stay as they are.
- [ ] **Retire the MacBook's Ultron:**
  - Quit `Ultron.app`, run `scripts/autostart.sh off` and `scripts/stop_ultron.sh` there.
  - `tailscale serve reset` on the MacBook, so its old address stops answering.
  - Keep the MacBook's copy as a backup for a week, then delete its `.env` and `backend/storage/` if you want the keys off a personal machine.
- [ ] Your MacBook is now just a client: open Ultron in a browser at the mini's address, or open a terminal on the mini from the MacBook (needs `JARVIS_TERMINAL_USER`).

---

## 8. Optional extras

**Local model for scheduled jobs (Ollama).** Blank on your MacBook today, so jobs run on Claude.
To turn it on:
```bash
ollama pull qwen3:8b && ollama create ultron-qwen3-8b -f scripts/Modelfile.ultron
```
Then in `.env`: `JARVIS_OLLAMA_MODEL=ultron-qwen3-8b` (keep `JARVIS_OLLAMA_URL=http://localhost:11434`).
(`.env.example` mentions a 14b name, but `scripts/Modelfile.ultron` is based on `qwen3:8b`; use
whatever name you give `ollama create`.) Restart Ultron.

**OmniRoute (other providers' models).** `npm i -g omniroute`, then Ultron starts it as
`omniroute serve --daemon` on `127.0.0.1:20128`. Connect each provider in its dashboard at
`http://localhost:20128`. In that mode connectors, web search and `ask_expert` are **off**.

**Game sound in clips.** Install BlackHole, make a Multi-Output Device (BlackHole + your speakers)
in Audio MIDI Setup, play sound through it, and put BlackHole's index in `JARVIS_CAPTURE_AUDIO`.

---

## 9. Sign-ins and permissions, all in one place

### Accounts and sign-ins
- [ ] **Claude Pro** in Claude Code (`claude`). Never an API key.
- [ ] **claude.ai connectors** (still connected): Gmail, Google Calendar, Google Drive, TickTick, Canva, Spotify, Claude Docs
- [ ] **Chrome:** Microsoft Teams (homework), Amazon (default `amazon.ae`, change with `JARVIS_AMAZON_URL`), Google Flights
  - Chrome menu bar → **View → Developer → Allow JavaScript from Apple Events** (homework, Amazon and flights read Chrome this way)
  - Allow the **microphone** for `http://127.0.0.1:8000` (voice runs in the Chrome page) and for your Tailscale address
- [ ] **Spotify desktop app**
- [ ] **WhatsApp desktop app** (sign in by scanning the QR code with your phone)
- [ ] **macOS Internet Accounts:** add your **Google** account with **Contacts** on (for `find_contact` and WhatsApp). Give it a few minutes to sync.
- [ ] **Tailscale:** same account everywhere
- [ ] **GitHub CLI:** `gh auth login` (the `github` tool is read-only)
- [ ] **Obsidian:** open the vault once so it registers
- [ ] **Keynote:** open once, accept its first-run prompts

### Keys already in your `.env` (restored from the backup)
Pexels, Pixabay, Groq, ElevenLabs, Spotify Client ID, Telegram bot, MacroDroid webhook, Instagram
token, PC token. Nothing to re-create unless one is rejected.

### macOS permissions (allow once each; System Settings → Privacy & Security)
- [ ] **Accessibility:** `Ultron.app` and whatever runs WhatsApp automation
- [ ] **Screen Recording:** `Ultron.app` (overlay, screen share). For clipping, also whatever runs `ffmpeg`.
- [ ] **Location Services:** Ultron Location
- [ ] **Contacts**
- [ ] **Microphone:** Chrome (and `Ultron.app` if it asks)
- [ ] **Automation:** Ultron controlling Chrome, Spotify, System Events, Finder, Keynote
- [ ] **Notifications:** job results
- [ ] **Files and Folders / Full Disk Access:** only if the school folder or vault is blocked (section 6)

---

## 10. Test every feature on the mini

**Core**
- [ ] Text chat on the Pro login; the reply shows a model badge
- [ ] Router and `ask_expert` ("use opus")
- [ ] Web search with source chips
- [ ] A WhatsApp send **asks first** (the approval card)
- [ ] Canvas cards; save a chat and reload it
- [ ] Memory: "remember that…", then open the memory panel

**Connectors**
- [ ] Gmail ("any important unread email?"), Google Calendar ("what's on today?"), Google Drive, TickTick ("remind me to… at…"), Canva, Claude Docs
- [ ] Spotify connector, and `spotify_control` playing on the desktop app

**Voice** (mic and speakers connected)
- [ ] Listening, speaking, orb states
- [ ] Barge-in; "stop", "cancel", "wait", "never mind"
- [ ] "Go back to typing"
- [ ] "Hey Ultron" wake word
- [ ] Screen sharing ("look at my screen", ⌃⌥U)
- [ ] ElevenLabs voice works, and Kokoro takes over if you set `JARVIS_TTS=kokoro`
- [ ] Say "how much voice is left?" (ElevenLabs characters)

**Images, video, 3D**
- [ ] `image_search`, `image_edit`, `image_undo`
- [ ] `generate_image` and `image_ai_edit` (FLUX)
- [ ] `generate_video` (Wan, takes minutes)
- [ ] 3D: preview, change, approve, then `export_3d` with Blender

**Reels, Instagram, clips**
- [ ] `reel_edit`, `stock_search`, `stock_download`, `watch_short`
- [ ] Instagram preview, stats, comments, queue; post, reply and schedule must always ask
- [ ] Screen clipping: "start recording", "clip the last 30 seconds"; the library at `http://127.0.0.1:8000/?captures=1`

**This Mac (now the mini)**
- [ ] `mac_read`: status (battery will say none), Wi-Fi, volume, location, clipboard, **Shortcuts** (your personal Shortcuts will not exist on the mini; recreate any you rely on)
- [ ] `mac_change`: open an app, clipboard, volume, dark mode, move and trash a file inside `~/Jarvis Files`
- [ ] `run_python` sandbox on a CSV (no network; writes only to `Output/`)
- [ ] Terminal tab (and with `JARVIS_TERMINAL_USER`, from the MacBook)
- [ ] `find_contact`, `whatsapp_send`
- [ ] `maps`, weather, "when should I leave for my next meeting"

**School, shopping, travel**
- [ ] `check_homework` (Teams in Chrome) and the exam countdown
- [ ] `syllabus`, `textbook` (needs Tesseract and `~/Desktop/school`), `make_slides` and `open_slides` (Keynote), `lectures`
- [ ] `amazon_read` / `amazon_change` (never checks out), `flights` (never books)

**Notes, files, jobs**
- [ ] `search_notes`, `read_note`, `write_note` (Obsidian vault at the new path; `#private` never read)
- [ ] `read_upload` (drag a file into chat)
- [ ] `mark_important` / `unmark_important`
- [ ] `github` (list repos and issues)
- [ ] Jobs: weekday briefing, a watcher, run now, pause, delete; results reach the chat, a macOS banner and Telegram

**Phone and PC**
- [ ] The phone opens the Tailscale address and chats
- [ ] `text_me` (Telegram), `phone_volume`, `phone_taxi`, `phone_food` (MacroDroid, Android)
- [ ] `pc_read`, `pc_change`, `pc_run` (always asks); "record my PC screen"
- [ ] The PC's "Hey Ultron" opens the **mini's** page

**Other brains**
- [ ] Ollama for scheduled jobs (if you set it up)
- [ ] OmniRoute from the gear icon (if you set it up)

---

## 11. If something doesn't work

| Symptom | Check |
|---|---|
| Ultron won't start | `tail -50 ~/Library/Logs/Ultron.log`; `curl -s http://127.0.0.1:8000/health` |
| Nothing starts after a reboot | Nobody is logged in. Turn on automatic login (section 1). |
| `launchctl` shows it isn't loaded | `launchctl print gui/$(id -u)/com.ultron.backend`; re-run `scripts/autostart.sh on` |
| Pro login not used / billing worries | `claude auth status`; `env | grep ANTHROPIC` must be empty |
| Phone can't reach it | `tailscale status`; `tailscale serve status`; `JARVIS_REMOTE_ORIGIN` must match exactly |
| Voice silent or deaf | Mic and speakers selected in System Settings → Sound; Chrome mic permission for the address |
| "near me" or weather is wrong or empty | Wi-Fi on; `scripts/setup_location.sh`; Location Services → Ultron Location |
| Clips are empty / "no footage" | Screen Recording permission; set `JARVIS_CAPTURE_SCREEN` to the display's name |
| School tools find nothing | `~/Desktop/school` exists; if autostart is on, see the Full Disk Access note in section 6 |
| Homework, Amazon or flights fail | Chrome signed in; **Allow JavaScript from Apple Events** is on |
| Notes not found | `JARVIS_VAULT` points at the mini's vault path |
| Slides don't open | Keynote is installed and has been opened once |
| Screen Recording asked again after a rebuild | Run `scripts/make_cert.sh` once, then `scripts/make_app.sh` |

---

## 12. Known limits

- Mac tools (`mac_*`, contacts, WhatsApp, maps, Chrome automation, `Ultron.app`, the sandboxed Python, FLUX and Wan) are **Mac only**. They work because the brain now runs on the mini.
- `find_contact`, `whatsapp_send`, `maps` and `mac_*` act on the **mini's** Contacts, WhatsApp, location, Shortcuts and files, not the MacBook's.
- A Mac mini has no battery, built-in mic, speakers or camera.
- `scripts/backup.sh` is missing the items in section 3. (Adding them to its `DATA` list would fix that for the next move.)
- Words said in the same breath as "Hey Ultron" on the PC are not passed on.
- Phone calls (Twilio) are not built.
- Notifications that open the related card need `terminal-notifier`; plain notifications open Script Editor (next step 5 in `ULTRON_BUILD_PROMPT.md`).

**Windows setup:** nothing to set up (this file is only about the Mac mini). The one Windows
action is editing `ULTRON_URL` in `windows/wake_pc.env` if the address changes (section 7).
