# ULTRON_cBrain

A personal AI assistant with Claude as its brain. It runs on your own Mac, for one user,
in a browser page with a chat on the left, a canvas in the middle and status panels on
the right. The backend only listens on 127.0.0.1, so nothing outside this machine can
reach it.

See `ULTRON_BUILD_PROMPT.md` for the original plan.

## What Ultron can do

Looking things up and everyday actions (reminders, events just for you, notes, memory,
music, your Amazon cart) run straight away. Anything that reaches other people (emails,
WhatsApp, calendar invites, sharing, publishing), touches a file or folder you told
Ultron is important, or uses a developer connector (Supabase, Vercel, ...) shows a
confirmation card first, and nothing happens until you approve it. Scheduled jobs can
only look things up.

### Talking and thinking

- **Chat.** Replies stream in word by word. Each reply shows a badge with the model
  that answered and why it was picked (see [The brains](#the-brains)).
- **Talk to it.** The mic button (or a click on the orb) starts voice mode: Ultron listens,
  hears when you've stopped talking, writes down what you said and answers out loud, sentence
  by sentence while it's still writing (about 2 s to the first word). With `GROQ_API_KEY`
  set, your speech is written down by Groq's Whisper (more accurate, ~0.3 s; the audio goes
  to Groq); without it, or if Groq fails, by faster-whisper on this computer
  (`JARVIS_STT_MODEL`, default `small.en`, ~250 MB, downloads the first time). The voice is
  Kokoro's `bm_lewis` on this computer (`JARVIS_VOICE`, ~350 MB, downloads the first time);
  code, tables and links aren't read out. Spoken questions get spoken answers: 1-3 short
  sentences, with anything longer (lists, tables, drafts) on the canvas. When an action
  needs your OK, Ultron asks out loud and shows the card under the orb; say "yes" or "no".
  You can talk over it: what you say stops the reply and Ultron carries on from where it
  was cut off; "stop" or "never mind" on its own just stops it, and so does a click on the
  orb. Its own voice coming back through the mic is recognised and ignored.
  Works in Chrome on this Mac and on your phone through Tailscale; Esc or "back to typing"
  ends it.
- **"Hey Ultron".** The switch under the orb ("HEY ULTRON · ON") keeps the mic listening
  while the page is open: say "Hey Ultron" (or "Hey Ultron, what's on tomorrow?") and voice
  mode starts with a soft chime, with your question if you asked one. It checks for the
  name on this computer (local Whisper), so nothing you say leaves it until you've said
  "Hey Ultron". After 20 seconds of quiet it goes back to waiting. The browser remembers the
  switch; if the page was opened without a click, it may need one click before it hears you.
- **Consult an expert.** For hard problems (multi-step reasoning, tricky maths, complex
  code, long writing) Sonnet hands the task to Opus with `ask_expert`. Long answers go
  straight onto the canvas.
- **Search the web.** Uses Claude's built-in WebSearch and WebFetch tools. Answers end
  with the pages they came from, shown as clickable source chips. WebFetch can't reach
  this machine or your local network.
- **Show things on the canvas.** Tables, comparisons, drafts, plans, email lists and
  calendar events go on cards next to the chat, so the chat reply stays short.

### Knowing you

- **Remember you.** Ultron keeps short notes about you between chats: preferences, who
  people are ("Sarah" = Sarah K. from work), projects, decisions. You see or delete them all with the memory button in the top bar. Passwords, card
  numbers and keys are always refused.
- **Use your Obsidian notes.** Set `ULTRON_VAULT` to your vault folder and Ultron
  searches and reads your notes when you ask about something you wrote down, before
  searching the web. It saves research, plans and lists as new notes (in a `Ultron`
  folder unless you say otherwise) or adds to an existing one. Tell Ultron a note or folder is important and it asks
  before changing it. Tag a
  note `#private` and Ultron never reads or changes it, and it can't reach anything
  outside the vault.
- **Use this Mac.** It runs your Shortcuts, opens apps, web pages and documents, reads
  and sets the clipboard, knows where the Mac is (after `scripts/setup_location.sh`, for
  weather and "near me"), and reads the battery, volume, dark mode and Wi-Fi (it can
  set volume, mute and dark mode). It finds, moves, renames and trashes files in one
  folder only (`ULTRON_FILES_DIR`, default `~/ULTRON Files`), never overwrites, and
  runs Python for data work in a macOS sandbox: no internet, no other programs, reads
  only that folder, writes only to its `Output` subfolder.
- **Maps and travel.** Places near you ("coffee near me"), travel times by car (with
  traffic), on foot or by transit, when to leave for a meeting, and travel time blocked in
  your calendar. Uses Apple Maps on this Mac, no API key (needs `scripts/setup_location.sh`).
  On your phone, "near me" uses the phone's GPS (allow location when the page asks).
  Routes and places show as a live map on the canvas (Google Maps' embed), with a
  satellite view.
- **Look at your screen.** Click the eye in the top bar (or type "look at my screen"),
  pick **Entire Screen** in the browser's share window, and a small always-on-top window
  opens in the bottom-left corner. Type a question in its box and the answer appears above
  it. Ultron gets a fresh picture of your screen with each question, so it keeps seeing
  your screen when you switch tabs or apps. Drag the window anywhere (box and answer move
  together) or resize it. Closing it, or "Stop sharing" in the browser, ends it. Needs
  Chrome or Edge. Only the newest 10 captures are kept in `backend/storage/uploads/`.
  In the Mac app (below) the same overlay is a native window instead: press **⌃⌥U** from
  anywhere (or "Look at my screen" in the orb's menu) to show or hide it. It floats over every
  app and desktop, remembers where you put it, and Ultron captures the screen the mouse is
  on, without the overlay in the picture. Needs Screen Recording permission
  (System Settings > Privacy & Security; macOS asks the first time). Rebuilding the app with
  `scripts/make_app.sh` can make macOS ask for that permission again. The overlay has its own
  connection to Ultron, so what you ask there shows in its box, not in the main page's chat.
- **Read your files.** Click 📎 in the chat box or drop files onto it. Images go on
  the canvas, where they can be edited. Text, code, CSV, JSON and PDF files are read
  as text (up to about 100K characters each). Files are kept in
  `backend/storage/uploads/`.

### Your accounts

- **Use your claude.ai connectors** (Gmail, Google Calendar, Drive, TickTick, Canva,
  Spotify, …), the same ones enabled on your Claude account. Reminders go to TickTick,
  so they reach your phone.
- **Check your homework.** It reads your school's Microsoft Teams activity feed
  from Chrome on this Mac, where you're already signed in, and can tell you when a
  teacher sets something new. It also reads a class's posts, for assessment dates and
  topic lists. School accounts don't let apps read assignments, so
  this needs one Chrome setting (see `.env.example`).
- **Browse Amazon.** It searches Amazon and reads your orders, cart and wish lists in
  Chrome on this Mac, where you're already signed in (no password is stored). It can
  add to or remove from your cart, or add to your wish list. It
  can't place an order: you check out in Chrome yourself. Uses the same Chrome setting
  as homework; set `ULTRON_AMAZON_URL` if you don't shop on amazon.ae.
- **Find flights.** It searches Google Flights in Chrome on this Mac and lists the
  options with price, airline, stops and times, plus the link to book. It can't buy a
  ticket: you pick one from the link and pay yourself. Uses the same Chrome setting as homework.
- **Find videos.** It searches YouTube and plays the best match right on the canvas, with
  the other results listed underneath (click one to play it). No API key or setup.
- **Play music.** It plays songs, albums and playlists in the Spotify app on this Mac
  and controls playback (pause, next, volume, …). It can also list the songs in your own
  playlists, which needs a Spotify developer app (see `.env.example`).

### Messages

- **Text people on WhatsApp.** It finds the number in your Contacts (synced from your
  Google account) and sends the message from the WhatsApp app on this Mac, after you
  approve. It can't read your messages. Needs Accessibility permission for Ultron.
- **Your phone's volume.** On your phone, "turn it down" or "mute" sets the phone's media
  volume through a MacroDroid macro (free Android app; setup in `.env.example`).
- **Taxis.** "Get me a Careem to Dubai Mall" opens Careem on your phone with the
  destination copied: paste it into "Where to?", check the price and book. Ultron never
  books or pays (Careem has no API). A second MacroDroid macro; setup in `.env.example`.
- **Text you.** Ultron's own Telegram bot sends things to your phone ("send that list to
  my phone"). It can only ever reach your own chat. Setup is in `.env.example`.

### Doing things on its own

- **Scheduled jobs.** A job at a time of day ("a briefing every weekday at 7") or a
  watcher that checks every so often and only speaks up when there's news ("tell me when
  Sarah replies", "tell me when new homework is set"). Results reach you in the chat, as
  a notification on this Mac, and on your phone through Telegram. Watchers pause during
  quiet hours, and jobs stop when most of your 5-hour Pro limit is used, so they never
  lock you out.

### Making things

- **Find and edit images.** It finds photos on Pexels and edits them locally: crop,
  resize, rotate, flip, brightness, contrast, saturation, sharpen, blur, grayscale,
  sepia, text and borders. Every edit is a new version, so you can always go back.
  Click an image to select it, and "this one" in your next message means that image.
- **Make images with AI.** Describe a picture and Ultron paints it with FLUX.2 Klein
  running on this Mac (about 20 seconds, free, nothing leaves the machine). It can also
  change an image with AI ("make it snowy", "turn it into a watercolour", "put a hat on
  the dog"), each change as a new version. Set it up once with `scripts/setup_images.sh`
  (downloads about 16 GB, keeps 8 GB).
- **Make videos.** Describe a shot and Ultron makes a short clip (up to 5 seconds,
  832×480, no sound) with Wan 2.1 running on this Mac: free, and nothing leaves the
  machine. It's slow (about 13 minutes for 5 seconds on an M5) and runs in the
  background, with progress on the canvas. Set it up once with
  `scripts/setup_video.sh` (downloads about 17.6 GB, keeps 14 GB). Text only for
  now: animating an existing image needs a bigger model.
- **3D library.** Ask for a 3D object and Ultron looks in `backend/library3d/` first. If
  a ready-made model of that thing is there it shows it in the 3D panel and builds nothing.
  Only when it isn't there (or only something similar is), or when you ask for a change,
  does Ultron use its own 3D builder (below). If your own folder doesn't have it, Ultron
  next searches [3DAssets.dev](https://3dassets.dev), a free online library of CC0 `.glb`
  models (no key needed), through its public MCP server, and downloads the one you want.
  Downloads only come from the hosts in `JARVIS_3DASSETS_HOSTS` (default `3dassets.dev`);
  set `JARVIS_3DASSETS_MCP` empty to turn the online library off. Downloaded models are
  finished files, so a change to one is rebuilt by Ultron from simple shapes. Add models by dropping a `.glb` file into the
  folder; an optional `name.json` next to it adds a title, `aliases` and `tags` for
  searching. A `.json` with a `spec` (Ultron's shape format) works without any file, and
  those models can be changed part by part. A plain `.glb` can't be edited, so a change
  to one is rebuilt by Ultron from simple shapes. Point `JARVIS_3D_LIBRARY` at another
  folder to move the library.
- **Build 3D objects.** Ultron makes a quick preview you can spin around, then checks
  4 rendered views of its own work and fixes mistakes. When you're happy, Blender builds
  the final file (.blend, .fbx, .obj, .stl, .gltf or .glb), never before you say so.

### On this Mac

- **Open a terminal.** Ask for a terminal ("open a terminal", or "open Claude Code")
  and a real shell on this Mac opens as a tab on the canvas, optionally with Claude Code
  already started. It's for you to type in: Ultron opens it but can't see or type in it.
  Each request opens another tab; closing the tab or reloading the page ends its shell.
  It only works on the Mac itself, never on your phone.
- **Use it from your phone.** Through Tailscale, Ultron opens on your phone from
  anywhere, one section at a time: swipe sideways between chat, canvas and panels (see
  [Run](#run)).
- **Track your usage.** The right-hand panel shows how much of your Pro plan's 5-hour and
  weekly limits is used, when they reset, and how many tokens Ultron itself used.

## The brains

Ultron has two brains. Switch between them with the gear icon at the top right.
Switching starts a new chat.

### Claude on your Pro login (the default)

Ultron talks to Claude through Claude Code (the Claude Agent SDK), signed in with your
Claude Pro account. **No API key is used**: if an `ANTHROPIC_API_KEY` were set, Claude
Code would bill that key instead, so Ultron removes it from its environment.

A router picks the model for each message:

1. A model you pick in the usage panel always wins.
2. Words in the message: "use opus" or "think hard" → **Opus**; "quick" or "use haiku" → **Haiku**.
3. Small talk stays on the current model.
4. Everything else → **Sonnet**, which can call `ask_expert` to consult Opus.

Switching models means sending the whole conversation to the new model again, so once a
conversation is big, the router won't move it to a cheaper model by itself. A big
conversation left alone for an hour starts over fresh, because Claude's cached copy of
it has expired (`ULTRON_NEW_CHAT_AFTER_IDLE_MIN`).

Ultron is an assistant, not a coding agent: Claude Code's file, shell and sub-agent tools
are switched off. Ultron only gets web search, tool search (so connector tools load on
demand) and its own tools.

### OmniRoute (optional)

[OmniRoute](https://github.com/diegosouzapw/OmniRoute) is a local gateway to other
providers' models (Gemini, Groq, …). It doesn't use your Pro limit. Install it with
`npm i -g omniroute`, then pick it with the gear icon: Ultron starts it if it isn't
running (on 127.0.0.1 only). Connect at least one provider in its dashboard
(http://localhost:20128 → Providers). Its keyless free providers mostly refuse
requests from outside their own apps.

The models you can switch between are set in `ULTRON_GATEWAY_MODELS` and appear as
buttons in the usage panel. In OmniRoute mode:
- the claude.ai connectors are off, so your emails never go to other providers' models
- web search and `ask_expert` are off (web page reading still works)
- other models may use Ultron's tools less reliably

## Setup

Requirements: Claude Code signed in with your Pro account (`claude auth status` shows
`"subscriptionType": "pro"`), [uv](https://docs.astral.sh/uv/), and Node 24.
Optional: Blender (for final 3D files) and the Spotify desktop app.

Backend (Python 3.13):

    uv venv --python 3.13 backend/.venv
    VIRTUAL_ENV=backend/.venv uv pip install -r backend/requirements.txt

On Windows (PowerShell, in the project folder; get uv with `winget install -e --id astral-sh.uv`):

    uv venv --python 3.13 backend\.venv
    uv pip install --python backend\.venv\Scripts\python.exe -r backend\requirements.txt

There's no `pip` inside this environment (uv makes it without one): always install with
`uv pip install`, as above.

Frontend:

    cd frontend && npm install

Copy `.env.example` to `.env` and fill in what you need. Every setting is explained
there: the Pexels key for images, Spotify, the Blender path, how hard Claude thinks
(`ULTRON_EFFORT`), which connectors to load (`ULTTRON_CONNECTORS`) and the OmniRoute
settings. Never add an `ANTHROPIC_API_KEY`.

## Run

**The easy way: Ultron.app.** Build it once:

    scripts/make_app.sh

Then double-click `Ultron.app` (drag it to Applications if you like). It puts an orb in
the menu bar, starts Ultron and opens it in your browser at http://127.0.0.1:8000.
Click the orb to open the page again, or choose Quit Ultron to stop Ultron. For the orb
at every login, add Ultron.app in System Settings → General → Login Items. Logs go to `backend/storage/ultron.log`. Run `make_app.sh` again
if you move the project folder.

**Always on (optional).** `scripts/autostart.sh on` starts Ultron when you log in and
starts him again if he crashes; `scripts/autostart.sh off` undoes it. While it's on,
quitting `Ultron.app` restarts Ultron instead of stopping him (do that after changing
`.env`), and the log is `~/Library/Logs/Ultron.log`. If macOS asks whether Python may
access your Desktop folder, allow it; a project kept outside Desktop and Documents is
never asked.

**On your phone (optional).** Ultron has no password, so it never listens on your Wi-Fi.
Instead, [Tailscale](https://tailscale.com) connects your own devices privately: install
it on this Mac and your phone, run `tailscale serve --bg 8000` on the Mac, and put the
address it prints in `.env` as `ULTRON_REMOTE_ORIGIN` (see `.env.example`). Then open
that address on your phone, from anywhere, while this Mac is awake and Ultron is running.

**Back up.** `scripts/backup.sh` writes everything of yours that isn't on GitHub (`.env`,
memory, saved chats, scheduled jobs, school notes, images, 3D models, videos, uploads) to
`~/Ultron-backup-<date>.tgz`. `scripts/backup.sh restore FILE` puts it back, in this
project or in a fresh clone on another Mac. The file holds your keys: keep it to yourself.

**For development**, in two terminals (the page reloads as you edit):

    cd backend && .venv/bin/python main.py      # API on http://127.0.0.1:8000
    cd frontend && npm run dev                   # UI on http://127.0.0.1:5173

Then open http://127.0.0.1:5173.

To test the brain without the UI (`/haiku`, `/sonnet`, `/opus` switch models):

    cd backend && .venv/bin/python chat_cli.py

Tests:

    cd backend && .venv/bin/python -m unittest discover tests

## Move to a new Mac

**On the old Mac**

1. `scripts/backup.sh`, then copy `~/Ultron-backup-<date>.tgz` to the new Mac (AirDrop or
   a USB stick; it holds your keys, so not by email).
2. `scripts/autostart.sh off` if autostart is on. Two running Ultrones would both run
   your scheduled jobs and text you twice.

**On the new Mac**

1. Install Claude Code and sign in with your Pro account, plus uv and Node 24 (see
   [Setup](#setup)). Install the apps you use Ultron with: Google Chrome, Spotify,
   WhatsApp, Blender, Tailscale.
2. Clone the project into your home folder, not Desktop or Documents (macOS restricts
   those for background programs):

       git clone https://github.com/erte-del/Jarvis_cBrain.git ~/Jarvis_cBrain

3. Run the backend and frontend commands from [Setup](#setup). Skip copying
   `.env.example`: the backup brings your `.env`.
4. `scripts/backup.sh restore ~/Ultron-backup-<date>.tgz`
5. `scripts/setup_images.sh` and `scripts/setup_video.sh`, if you want images and videos
   made on this Mac (about 34 GB of downloads, 22 GB kept).
6. `scripts/make_app.sh`, then open `Ultron.app` once. It builds the page and starts Ultron.

**Sign-ins and switches only you can do**

- **Chrome:** sign in to Teams and Amazon, then View → Developer → Allow JavaScript from
  Apple Events.
- **Spotify and WhatsApp:** sign in to the apps. WhatsApp also needs Ultron allowed under
  System Settings → Privacy & Security → Accessibility.
- **Contacts:** add your Google account under System Settings → Internet Accounts, with
  Contacts on.
- **Tailscale:** sign in to the same account and run `tailscale serve --bg 8000`. The new
  Mac gets its own address: put that one in `.env` as `JARVIS_REMOTE_ORIGIN`.
- **Permission prompts:** the first time Ultron uses Chrome, Spotify, Contacts or
  notifications, macOS asks. Allow each once.

Nothing to do for the claude.ai connectors (Gmail, Calendar, TickTick, …) and Telegram:
they come with your Claude login and your `.env`.

**If the new Mac should stay on all the time** (a Mac mini)

1. `scripts/autostart.sh on`
2. System Settings → Energy: turn on "Prevent automatic sleeping when the display is
   off" and "Start up automatically after a power failure".
3. System Settings → Users & Groups: set "Automatically log in as" to your user, so
   Ultron comes back after a restart without anyone typing a password. This needs
   FileVault off, which means anyone who takes the Mac can read its disk.

**Check it worked.** Ask Ultron what he remembers about you, open a saved chat and
continue it, ask for your homework, play a song, and open the page on your phone.

## How it fits together

    frontend/          React + Vite page: chat, canvas, 3D viewer, usage / log panels
    backend/main.py    FastAPI server: the /ws WebSocket, image, 3D and upload endpoints
    backend/brain/     the brain (Claude Code via the Agent SDK), router, prompts,
                       confirmation gate
    backend/scheduler.py, notify.py   jobs Ultron runs on its own, and how their results reach you
    backend/tools/     Ultron's own tools, served to Claude as an in-process MCP server,
                       each labelled read (runs freely) or act (asks only for other
                       people or important files)
    backend/library3d/ ready-made 3D models Ultron shows before building its own
    backend/storage/   images, 3D models, uploads, usage numbers, memory, scheduled jobs (all local files)
    scripts/           builds and runs Ultron.app

## Status

- [x] Phase 1: text chat on the Pro subscription
- [x] Phase 2: model router (Haiku / Sonnet / Opus, `ask_expert`)
- [x] Phase 3: web search
- [x] Phase 4: abilities
  - [x] confirmation gate + canvas
  - [x] claude.ai connectors (Gmail, Calendar, Drive, …)
  - [x] images (search + edit)
  - [x] 3D objects
  - [x] Spotify
  - [x] OmniRoute as a second brain
  - [x] file uploads
- [x] Phase 5: voice (listening, speaking, spoken answers, yes/no out loud, talking over it)
- [x] Phase 6: memory (`remember` / `recall` / `forget`, and the memory button in the top bar)
- [x] Phase 7: polish (wake word "Hey Ultron", talking over Ultron)
