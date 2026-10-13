# Mac mini setup

Goal: the Mac mini is Ultron's dedicated brain, with **every feature working**. The MacBook is
personal and stays out of this. Built from `README.md`, `.env.example` and the code. Tick things
off as you go.

> **Run Ultron on one machine only.** Once the mini works, stop and disable autostart on the
> MacBook. Two copies would double-run scheduled jobs and send duplicate Telegram messages.

---

## 1. Mac mini differences (read first)

The mini is not a laptop. These need a decision before the features work:

| Mac mini difference | Affects | What to do |
|---|---|---|
| **No built-in mic or speakers** | voice, "Hey Ultron", screen clip audio | Plug in a USB/Bluetooth mic and speakers (or a monitor with speakers and a mic). Pick them in System Settings → Sound. |
| **No camera** | screen share window, anything using Desk View | Nothing needed. Screen capture uses a display *name* (`JARVIS_CAPTURE_SCREEN`). |
| **No battery** | `mac_read` battery | Ultron will report no battery. Expected. |
| **No GPS; location comes from Wi-Fi** | `maps`, weather, "near me", leave-by times, `UltronLocation.app` | Keep Wi-Fi **on** (even if you use Ethernet) so macOS can locate it. If it is wrong, tell Ultron where you are. |
| **Needs a display (or a dummy HDMI plug)** | screen recording, Chrome automation, screen overlay | Headless Macs have no real screen. Use a monitor or a cheap HDMI dummy plug. |
| **Must never sleep** | scheduler, watchers, briefings | System Settings → Energy: prevent sleep, **start up automatically after a power failure**. |
| **Must start Ultron after a reboot** | everything | `scripts/autostart.sh`, and turn on automatic login (FileVault blocks auto-login: choose which you need). |
| **Apple Silicon needed** | FLUX images, Wan video | Check the model. Intel mini = those two features off. |
| **Disk space** | FLUX (~16 GB, keeps 8 GB), Wan (~17.6 GB, 5B ~34 GB), voice (~2 GB) | Make sure the internal disk has room before running the setup scripts. |

---

## 2. Apps to install

### Required
- [ ] **Homebrew** (brew.sh)
- [ ] **Xcode command line tools**: `xcode-select --install` (for `Ultron.app` and location)
- [ ] **Git**
- [ ] **uv** (astral-sh/uv): makes the Python 3.13 environment
- [ ] **Node.js 24**: builds the page
- [ ] **Claude Code**, signed in with your **Claude Pro** account
- [ ] **Google Chrome**: the page, voice, screen sharing, Teams, Amazon and flights use it
- [ ] **FFmpeg**: `brew install ffmpeg` (Reels, clipping, YouTube)
- [ ] **Tailscale**: phone, PC and remote terminal

### Needed for specific features
- [ ] **Blender** (blender.org): final 3D files. Set `BLENDER_PATH` in `.env`.
- [ ] **Tesseract**: `brew install tesseract` (scanned textbooks)
- [ ] **tmux**: `brew install tmux` (terminal tabs survive closing)
- [ ] **Spotify desktop app**: playing music
- [ ] **WhatsApp desktop app**: sending WhatsApp messages
- [ ] **Obsidian**: notes vault. Set `JARVIS_VAULT` in `.env`.
- [ ] **BlackHole**: game sound in screen clips (`JARVIS_CAPTURE_AUDIO`)
- [ ] **Ollama**: local model for scheduled jobs (`JARVIS_OLLAMA_URL`, localhost only)
- [ ] **OmniRoute**: second brain for other providers' models
- [ ] **GitHub CLI (`gh`)**: used by `backend/tools/github.py`

### On your Android phone
- [ ] **MacroDroid**: phone volume, Careem taxis and food
- [ ] **Telegram**: so Ultron can text you

---

## 3. Accounts to sign in to

- [ ] **Claude Pro**: the brain. **Never** set `ANTHROPIC_API_KEY`.
- [ ] **claude.ai connectors** (claude.ai/settings/connectors): Gmail, Google Calendar, Google Drive, TickTick, Canva, Spotify, Claude Docs
- [ ] **Chrome**: Microsoft Teams (homework), Amazon, Google Flights
  - Chrome → View → Developer → **Allow JavaScript from Apple Events**
- [ ] **Spotify desktop app**
- [ ] **WhatsApp desktop app**
- [ ] **macOS Internet Accounts**: add your Google account with **Contacts** on
- [ ] **Tailscale**: same login on the mini, phone and PC

### Keys in `.env` (each optional, only that feature is off without it)
- [ ] `PEXELS_API_KEY`: images and stock video (free)
- [ ] `PIXABAY_API_KEY`: more stock video (free)
- [ ] `GROQ_API_KEY`: faster speech-to-text (audio goes to Groq)
- [ ] `ELEVENLABS_API_KEY` (+ `JARVIS_ELEVENLABS_VOICE`, `JARVIS_ELEVENLABS_MODEL`): ElevenLabs voice (falls back to Kokoro)
- [ ] `SPOTIFY_CLIENT_ID`: reading playlist songs. Redirect URI `http://127.0.0.1:8000/spotify/callback`
- [ ] `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: Ultron texting your phone
- [ ] `MACRODROID_WEBHOOK`: phone volume, taxis, food (Android)
- [ ] `INSTAGRAM_ACCESS_TOKEN`: posting Reels (Creator account + Meta app)
- [ ] `JARVIS_VAULT`: Obsidian vault path
- [ ] `JARVIS_FILES_DIR`: Ultron's file folder (`~/Jarvis Files`)
- [ ] `JARVIS_REMOTE_ORIGIN`: the `https://….ts.net` address from `tailscale serve` (**now the mini's**)
- [ ] `JARVIS_TERMINAL_USER`: your Tailscale login
- [ ] `JARVIS_PC_URL`, `JARVIS_PC_TOKEN`: Windows PC control (from `windows/install.ps1`)
- [ ] `JARVIS_HOMEWORK_URL`, `JARVIS_AMAZON_URL`: Teams and Amazon sites

---

## 4. Install order

1. Create the user, join Wi-Fi, run Software Update.
2. Install the required apps (section 2).
3. **On the MacBook:** `scripts/backup.sh` (bundles Ultron's data and `.env`).
4. On the mini: clone the repo, then `scripts/backup.sh restore <backup>`.
5. Python deps: `VIRTUAL_ENV=backend/.venv uv pip install -r backend/requirements.txt`
6. Build the page: `cd frontend && npm install && npm run build`
7. Run the tests: `cd backend && .venv/bin/python -m unittest discover tests`
8. `claude` → sign in with Pro.
9. Setup scripts, only for what you use:
   - `scripts/setup_images.sh` (FLUX)
   - `scripts/setup_video.sh` (Wan, add `5b` for Wan 2.2)
   - `scripts/setup_voice.sh` (Kokoro, Piper Turkish, captions)
   - `scripts/setup_location.sh` (builds `UltronLocation.app`, asks for Location once)
10. `scripts/make_app.sh` → `Ultron.app`
11. `tailscale serve` (**never `funnel`**), copy the address into `JARVIS_REMOTE_ORIGIN`.
12. Update phone and PC to the mini: `windows/wake_pc.py` target, Tailscale name, `JARVIS_PC_URL`.
13. `scripts/autostart.sh`. Then **stop and disable autostart on the MacBook**.
14. Backend stays on `127.0.0.1`. Never `0.0.0.0`.

---

## 5. macOS permissions (allow once each)

- [ ] **Accessibility**: `Ultron.app`, plus WhatsApp automation
- [ ] **Screen Recording**: screen overlay, screen share, clipping
- [ ] **Location**: `UltronLocation.app`
- [ ] **Contacts**: contact lookup
- [ ] **Microphone**: Chrome / `Ultron.app` (voice)
- [ ] **Automation**: Chrome, Spotify, System Events (Ultron controlling apps)
- [ ] **Notifications**: job results

---

## 6. Feature checklist (try each one once)

**Core**
- [ ] Text chat on the Pro login, model badge shown
- [ ] Router and `ask_expert` (say "use opus")
- [ ] Web search with source chips
- [ ] Approval gate: a WhatsApp send asks first
- [ ] Canvas and saved chats
- [ ] Memory: "remember that…", then open the memory panel

**Connectors**
- [ ] Gmail ("any important unread email?")
- [ ] Google Calendar ("what's on today?")
- [ ] Google Drive
- [ ] TickTick ("remind me to… at…")
- [ ] Canva
- [ ] Spotify (connector) and Spotify (desktop playback via `spotify_control`)
- [ ] Claude Docs

**Voice** (needs mic and speakers)
- [ ] Listening, speaking, orb states
- [ ] Barge-in ("stop", "cancel", "wait", "never mind")
- [ ] "Go back to typing"
- [ ] "Hey Ultron" wake word on the mini
- [ ] Screen sharing ("look at my screen", ⌃⌥U)
- [ ] ElevenLabs voice, and Kokoro fallback with it off

**Media**
- [ ] `image_search` (Pexels), `image_edit`, `image_undo`
- [ ] `generate_image`, `image_ai_edit` (FLUX, Apple Silicon)
- [ ] `generate_video` (Wan, Apple Silicon)
- [ ] 3D: preview → approve → `export_3d` (needs Blender)
- [ ] Reels: `reel_edit`, `stock_search`, `stock_download`
- [ ] Instagram: preview, stats, comments, queue; post/reply/schedule always ask
- [ ] Screen clipping (`capture`): "start recording", "clip the last 30 seconds"
- [ ] YouTube, `watch_short`
- [ ] Track tools: `show_track`, `track_info`

**This Mac (now the mini)**
- [ ] `mac_read` (battery will say none, Wi-Fi, volume, location)
- [ ] `mac_change` (open app, clipboard, volume, dark mode, move/trash a file)
- [ ] `run_python` sandbox (no network, writes only to `Output/`)
- [ ] Terminal tab (with tmux, optionally Claude Code)
- [ ] `find_contact`, `whatsapp_send`
- [ ] `maps`, weather, leave-by times

**School, shopping, travel**
- [ ] `check_homework` (Teams in Chrome), exam countdown
- [ ] `syllabus`, `textbook` (needs Tesseract), `make_slides`, `open_slides`, `lectures`
- [ ] `amazon_read` / `amazon_change` (never checks out)
- [ ] `flights` (never books)

**Notes, files, jobs**
- [ ] `search_notes`, `read_note`, `write_note` (Obsidian, never `#private`)
- [ ] `read_upload` (drag a file into chat)
- [ ] `mark_important` / `unmark_important`
- [ ] Jobs: weekday briefing, watcher, run now, pause, delete
- [ ] Notifications: chat, macOS banner, Telegram

**Phone and PC**
- [ ] Ultron reachable from the phone at the Tailscale address
- [ ] Remote terminal only with your Tailscale login
- [ ] `text_me` (Telegram)
- [ ] `phone_volume`, `phone_taxi`, `phone_food` (MacroDroid, Android)
- [ ] `pc_read`, `pc_change`, `pc_run` (always asks)
- [ ] PC "Hey Ultron" opens the **mini's** page

**Other brains**
- [ ] Ollama for scheduled jobs
- [ ] OmniRoute (gear icon): connectors, web search and `ask_expert` are off in this mode

---

## 7. Known limits

- Mac tools (`mac_*`, contacts, WhatsApp, maps, Chrome automation, `Ultron.app`, FLUX/Wan, the
  sandboxed Python) are **Mac only**. They work because the brain is on the mini.
- `find_contact`, `whatsapp_send` and `maps` depend on the **mini's** Contacts, WhatsApp and
  location, not the MacBook's.
- Words said in the same breath as "Hey Ultron" on the PC are not passed on.
- Phone calls (Twilio) are not built.
- Notifications that open the related card need `terminal-notifier`; plain `osascript`
  notifications open Script Editor (next step 5 in `ULTRON_BUILD_PROMPT.md`).

**Windows setup:** nothing to set up (this file is only about the Mac mini).
