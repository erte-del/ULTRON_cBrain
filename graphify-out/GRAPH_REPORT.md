# Graph Report - ULTRON_cBrain  (2026-10-06)

## Corpus Check
- 159 files · ~95,926 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 12 file(s) not represented in the graph (top: (none) 7, .css 2, .example 1)

## Summary
- 1946 nodes · 4211 edges · 139 communities (72 shown, 67 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 144 edges (avg confidence: 0.88)
- Token cost: 203,700 input · 0 output

## Community Hubs (Navigation)
- Canvas Events & Config
- Amazon & Flights Browsing
- Storage & Tool Test Suite
- Image Store & Generation
- 3D Shape Builder
- Image Ops Tests
- Blender Scripts
- Agent & Confirmation Gate
- Connectors & Important Files
- Scheduled Jobs
- OmniRoute Gateway
- Config & System Prompts
- Slides Builder
- HTTP Asset Endpoints
- Frontend Dependencies
- Screen Overlay App
- Brain Protocol & Events
- Mac Tool Tests
- Claude Code Brain Session
- Read-only Tool Tests
- Web Helper & URL Safety
- 3D Library Importer
- App Shell & Panels
- Chat UI
- Canvas Viewers
- Textbook & Syllabus
- Stage & Voice Orb
- 3D Model Store
- Confirm Card & WebSocket Client
- Ultron Conversation Loop
- Swift Location Types
- Swift Overlay Panel
- Memory Store
- 3D Preview & Export
- TS App Config
- 3D & Canvas Features (docs)
- Top Bar Menus
- Device Hub & Senders
- Library & Homework Tests
- YouTube Tool
- TS Node Config
- Obsidian Notes Tool
- Swift App Delegate
- Terminal UI
- Notifications & Telegram
- 3DAssets Download Tests
- Chat Store
- 3D Model Store Tests
- Briefing & Action Tools (docs)
- Connector Startup
- Device Tests
- Router Tests
- Slides Tests
- Upload Tests
- Confirmation Gate Tests
- Connector Retry Tests
- Idle Restart Tests
- Contacts Lookup
- Swift Overlay Errors
- Terminal Backend
- Contacts Tests
- Homework Tests
- Video Tests
- Memory Tools
- Phone Tools
- WhatsApp Tool
- Brain Design (docs)
- Image Gen Tests
- Memory Tests
- Notes Tests
- PC Tool Tests
- Expert Canvas Tests
- WhatsApp Tests
- Expert & Usage Tracking
- API Brain Placeholder
- Amazon Tests
- Flights Tests
- Tool Classification Tests
- Swift Locate Script
- Calendar & Time Note
- Tool Permission Callback
- Upload Store
- Needs-OK Tests
- Telegram Tests
- Memory Search
- Gateway Start Tests
- Login Switch Tests
- Shapes Tests
- Syllabus Tests
- Lint Config
- Floating Parts Tests
- New Shapes Tests
- Reminders Tests
- Scheduler Due Tests
- Terminal Tests
- Usage Numbers Tests
- Chat Store Tests
- 3D Small Changes Tests
- Textbook Tests
- Model Router
- Pending Confirmations
- WebSocket Protocol
- Job Tool Gate
- Gateway Error Tests
- Seed Library Tests
- Tool Hooks
- Favicon & Brand
- TS Root Config
- Autostart Script
- Start Script
- Local Image Gen (FLUX)
- SQLite DB Stub
- Voice Pipeline Stub
- Speech to Text
- Text to Speech
- Voice Activity Detection
- HTML Entry
- Backup Script
- App Bundle Script
- Image Setup Script
- Location Setup Script
- Video Setup Script
- Stop Script
- mapbox-earcut
- numpy
- openpyxl
- python-dotenv
- python-pptx
- rtree
- scipy
- shapely
- uvicorn
- Obsidian Vault
- Look at Screen
- Terminal Tab
- Local Video Gen (Wan)
- Safety & Trust
- Voice Phase

## God Nodes (most connected - your core abstractions)
1. `ClaudeCodeBrain` - 30 edges
2. `websocket_endpoint()` - 22 edges
3. `emit()` - 21 edges
4. `Ultron` - 19 edges
5. `_text()` - 19 edges
6. `react` - 19 edges
7. `compilerOptions` - 18 edges
8. `Done` - 17 edges
9. `EditError` - 17 edges
10. `Overlay` - 17 edges

## Surprising Connections (you probably didn't know these)
- `Claude Pro Login Brain` --semantically_similar_to--> `ClaudeCodeBrain`  [INFERRED] [semantically similar]
  README.md → ULTRON_BUILD_PROMPT.md
- `Confirmation Card Gate` --semantically_similar_to--> `Approval Policy (confirm.py, needs_ok)`  [INFERRED] [semantically similar]
  README.md → ULTRON_BUILD_PROMPT.md
- `Model Router` --semantically_similar_to--> `brain/router.py Model Routing`  [INFERRED] [semantically similar]
  README.md → ULTRON_BUILD_PROMPT.md
- `3D Builder (preview + Blender export)` --semantically_similar_to--> `3D Preview Mode`  [INFERRED] [semantically similar]
  README.md → ULTRON_BUILD_PROMPT.md
- `pycaw (Windows volume/mute)` --semantically_similar_to--> `mac_read / mac_change / run_python`  [INFERRED] [semantically similar]
  windows/requirements.txt → to_do_list.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Daily Briefing Flow** — to_do_list_daily_briefing, to_do_list_calendar, to_do_list_ticktick_reminders, backend_storage_memory_store, backend_scheduler, backend_notify [EXTRACTED 1.00]
- **Read/Act Approval Gate** — ultron_build_prompt_approval_policy, ultron_build_prompt_read_act_labels, ultron_build_prompt_tool_registry, readme_confirmation_gate [INFERRED 0.85]
- **3D Preview-to-Export Pipeline** — ultron_build_prompt_scene_spec, ultron_build_prompt_3d_preview_mode, ultron_build_prompt_blender_export, backend_requirements_trimesh [EXTRACTED 1.00]

## Communities (139 total, 67 thin omitted)

### Community 0 - "Canvas Events & Config"
Cohesion: 0.05
Nodes (67): For urlopen to HTTPS sites: Python's own certificates plus the Mac keychain's,…, ssl_context(), canvas_card(), emit(), has_clients(), Event, Send an event to every connected tab., A file from your computer (the raw bytes as the body). Images go on the canvas;… (+59 more)

### Community 1 - "Amazon & Flights Browsing"
Cohesion: 0.06
Nodes (69): amazon_change(), amazon_read(), _open(), page_url(), Any, tool, Amazon: browse the user's account in Chrome on this Mac, where they're signed…, The Amazon address for 'orders', 'cart', 'lists', an ASIN or a path. ValueError… (+61 more)

### Community 2 - "Storage & Tool Test Suite"
Cohesion: 0.09
Nodes (34): asyncio, Local storage: SQLite + assets/ folder., Amazon: which pages it opens, which buttons it presses, never checkout. Chrome…, Saved chats: the 5-chat limit. Run from the backend folder: .venv/bin/python -m…, Homework: what's new, read-only label, errors. Chrome itself isn't touched.…, AI images, with fake mflux commands instead of FLUX. Run from the backend…, Image editing and storage tests (no network). Run from the backend folder:…, 3D library tests. Run from the backend folder: .venv/bin/python -m unittest… (+26 more)

### Community 3 - "Image Store & Generation"
Cohesion: 0.09
Nodes (50): add_version(), card_data(), create(), _dir(), file_path(), ImageRecord, load(), open_version() (+42 more)

### Community 4 - "3D Shape Builder"
Cohesion: 0.08
Nodes (46): apply_changes(), build_scene(), _display_name(), floating_parts(), _gap(), _linear(), _loft(), _loft_sections() (+38 more)

### Community 5 - "Image Ops Tests"
Cohesion: 0.11
Nodes (30): OpsTest, Image, sample(), StoreTest, add_border(), add_text(), apply_all(), blur() (+22 more)

### Community 6 - "Blender Scripts"
Cohesion: 0.09
Nodes (38): Runs INSIDE Blender (never imported by Ultron). Fixed script: Claude never…, Runs INSIDE Blender (never imported by Ultron). Fixed script: Claude never…, BaseHTTPRequestHandler, bpy, ctypes, difflib, hmac, math (+30 more)

### Community 7 - "Agent & Confirmation Gate"
Cohesion: 0.08
Nodes (26): Ultron logic: router -> brain -> events., ConfirmationGate, Confirmation gate for 'act' tools. (Phase 4a) Claude Code runs 'read' tools…, Record your answer from the browser. False if nothing was waiting., Ultron's brain: talks to Claude., Pushes events to every open browser tab. Replies stream back on the tab that…, Reaching you when you're not looking at the chat. One notification goes three…, Notifications since the user's last message, for Ultron's conversation to know… (+18 more)

### Community 8 - "Connectors & Important Files"
Cohesion: 0.08
Nodes (38): _dicts(), is_read(), item_label(), parse(), Any, claude.ai connectors (Gmail, Supabase, Canva, ...): read/act labels. Claude…, mcp__claude_ai_Gmail__search_threads' -> ('Gmail', 'search_threads'). None if…, h5hdgf82...' -> 'Ultron test (2026-09-30T16:00:00+04:00)', if Ultron has seen… (+30 more)

### Community 9 - "Scheduled Jobs"
Cohesion: 0.11
Nodes (37): jobs_list(), change_job(), jobs_event(), Something you did in the schedule panel., loop(), Run one job now and tell the user the result. Never raises., Started with the server; runs until it's cancelled at shutdown., run_job() (+29 more)

### Community 10 - "OmniRoute Gateway"
Cohesion: 0.08
Nodes (34): explain_error(), _find_omniroute(), _is_local(), OmniRoute (the optional gateway brain): is it running, start it, explain its…, Does anything answer at the gateway's address? (Any HTTP reply counts.), The omniroute command. Ultron.app starts without your shell's PATH, so also…, Start OmniRoute in the background (on this Mac only). Returns None when it's…, OmniRoute's errors list every provider it tried. Say what to do about it. (+26 more)

### Community 11 - "Config & System Prompts"
Cohesion: 0.07
Nodes (29): Ultron system prompt(s)., Settings loaded from .env., Point Claude Code at the Pro login (provider "claude") or at the gateway. The…, set_login(), lifespan(), FastAPI app + /ws WebSocket, bound to 127.0.0.1. Run from the backend folder:…, /ws/terminal: a real shell in a canvas tab, for you to type in (e.g. to run…, Which device you're talking from reaches Ultron, so "play this" happens on that… (+21 more)

### Community 12 - "Slides Builder"
Cohesion: 0.09
Nodes (36): build(), _deck(), _figure(), _fill(), _free(), lectures(), make_slides(), open_slides() (+28 more)

### Community 13 - "HTTP Asset Endpoints"
Cohesion: 0.10
Nodes (34): asset(), health(), Finished videos. Names are checked strictly., Spotify sends you back here after the login link Ultron showed you., Image files for the canvas. Names are checked strictly, so only stored images…, spotify_callback(), video_file(), card_data() (+26 more)

### Community 14 - "Frontend Dependencies"
Cohesion: 0.06
Nodes (33): dependencies, react, react-dom, react-markdown, remark-gfm, @xterm/addon-fit, @xterm/xterm, devDependencies (+25 more)

### Community 15 - "Screen Overlay App"
Cohesion: 0.10
Nodes (15): errorText(), OverlayApp(), Bridge, NativeScreenSource, browserCanShareScreen(), BrowserScreenSource, ImageCaptureLike, ScreenSource (+7 more)

### Community 16 - "Brain Protocol & Events"
Cohesion: 0.12
Nodes (25): Done, Error, Brain protocol + BrainEvent types. Everything in Ultron talks to a `Brain`,…, A small piece of the reply text, streamed as it is generated., Claude started using a tool (e.g. a web search)., A tool finished. `data` is the tool's structured result, when there is one., Something for the frontend to show (canvas image, card, ...). Phase 4a+., The reply is complete. `model` is the full model ID that answered. (+17 more)

### Community 17 - "Mac Tool Tests"
Cohesion: 0.07
Nodes (8): call(), MacTest, fake_run(), fake_open(), run(), skipUnless, JobsTest, ask()

### Community 18 - "Claude Code Brain Session"
Cohesion: 0.11
Nodes (30): The model the conversation is on now., chats_list(), confirm_request(), confirm_resolved(), conversation_loaded(), conversation_new(), done(), error() (+22 more)

### Community 19 - "Read-only Tool Tests"
Cohesion: 0.11
Nodes (19): Contacts: relationship words, read-only label, errors. The Contacts app itself…, Flights: the search it opens, what it refuses. Chrome isn't touched.…, This Mac: labels, the folder fence, no overwrites, what may be opened, the…, YouTube: the search it fetches, how it reads the page, what it refuses. Nothing…, flights: search Google Flights in Chrome on this Mac. (read) Google Flights has…, Homework: read Microsoft Teams from Chrome on this Mac (read-only). The…, maps: places nearby and travel times, from Apple Maps on this Mac. (read) No…, search_notes / read_note / write_note: your Obsidian vault (JARVIS_VAULT in… (+11 more)

### Community 20 - "Web Helper & URL Safety"
Cohesion: 0.10
Nodes (21): PublicUrlTest, Web helper tests. Run from the backend folder: .venv/bin/python -m unittest…, SourcesTest, block_private_urls(), domain(), _is_public_ip(), is_public_url(), links_in_text() (+13 more)

### Community 21 - "3D Library Importer"
Cohesion: 0.13
Nodes (29): _allowed_host(), _describe(), _download(), _import_glb(), _import_spec(), Item, items(), _meaningful() (+21 more)

### Community 22 - "App Shell & Panels"
Cohesion: 0.13
Nodes (26): App(), PANE_IDS, PANES, Panel(), PanelProps, COMMANDS, countdown(), fmt() (+18 more)

### Community 23 - "Chat UI"
Cohesion: 0.13
Nodes (26): Chat(), ChatProps, CopyButton(), domain(), LongWait(), Message(), MicIcon(), ModelBadge() (+18 more)

### Community 24 - "Canvas Viewers"
Cohesion: 0.13
Nodes (25): three, CanvasProps, CardBody(), EmailList(), Events(), isUnread(), Item, MapCard() (+17 more)

### Community 25 - "Textbook & Syllabus"
Cohesion: 0.11
Nodes (22): Textbook: page lookup over saved OCR text. No PDF or tesseract needed.…, _download(), find(), Any, tool, Syllabus: what the user's A-level exam boards say is on each course. The…, Indexes of the pages to show: the course overview without a query, else the…, syllabus() (+14 more)

### Community 26 - "Stage & Voice Orb"
Cohesion: 0.13
Nodes (23): Canvas(), Core(), SAMPLE, Stage(), StageProps, Terminal, VOICE_PILL, VOICE_STATES (+15 more)

### Community 27 - "3D Model Store"
Cohesion: 0.20
Nodes (22): model_file(), 3D previews (.glb) and finished exports. Names are checked strictly., add_export(), add_version(), card_data(), create(), download_name(), Export (+14 more)

### Community 28 - "Confirm Card & WebSocket Client"
Cohesion: 0.12
Nodes (22): ConfirmCardProps, STATUS_LABEL, Action, baseReducer(), BatteryManager, ChatState, ClientEvent, clip() (+14 more)

### Community 29 - "Ultron Conversation Loop"
Cohesion: 0.11
Nodes (14): Event, A big conversation left alone for over an hour: Claude's cached copy has…, Answer one user message, yielding WebSocket events for the browser., Ultron, Brain, BrainEvent, Send one user message and stream back events until `Done` or `Error`., Forget the conversation and start a fresh one (optionally on another provider),… (+6 more)

### Community 30 - "Swift Location Types"
Cohesion: 0.23
Nodes (9): CLLocation, CLLocationCoordinate2D, CLLocationManager, CLLocationManagerDelegate, Double, MKMapItem, Locator, Any (+1 more)

### Community 31 - "Swift Overlay Panel"
Cohesion: 0.15
Nodes (14): AppKit, Bool, Carbon.HIToolbox, NSPanel, Overlay, .isVisible, OverlayPanel, .canBecomeKey (+6 more)

### Community 32 - "Memory Store"
Cohesion: 0.18
Nodes (19): change_memory(), An edit you made in the memory panel. ValueError with the reason if it can't be…, add(), _check(), delete(), label(), _luhn(), What Ultron remembers about you between chats, in storage/memory.json. Short… (+11 more)

### Community 33 - "3D Preview & Export"
Cohesion: 0.23
Nodes (19): _blender(), _build_preview(), _contact_sheet(), export_3d(), get_3d_spec(), _load(), preview_3d(), Any (+11 more)

### Community 34 - "TS App Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+11 more)

### Community 35 - "3D & Canvas Features (docs)"
Cohesion: 0.12
Nodes (19): pypdf, trimesh, 3D Builder (preview + Blender export), 3D Library (backend/library3d), 3DAssets.dev MCP, Canvas, claude.ai Connectors, Persistent Memory (remember/recall/forget) (+11 more)

### Community 36 - "Top Bar Menus"
Cohesion: 0.21
Nodes (18): jobWhen(), MemoryMenu(), MemoryProps, RUN_STATUS, SavedChats(), ScheduleMenu(), Settings(), TopBar() (+10 more)

### Community 37 - "Device Hub & Senders"
Cohesion: 0.15
Nodes (18): connect(), disconnect(), Sender, device_of(), make_sender(), send(), phone_location(), phone_status() (+10 more)

### Community 38 - "Library & Homework Tests"
Cohesion: 0.18
Nodes (5): fake_run(), fake_run(), LibraryTest, run(), text()

### Community 39 - "YouTube Tool"
Cohesion: 0.15
Nodes (11): YoutubeTest, _fetch(), Any, tool, YouTube's text objects: {'simpleText': ...} or {'runs': [{'text': ...}, ...]}., One line per video in the search page: link | title | channel | length | views…, _renderers(), search_url() (+3 more)

### Community 40 - "TS Node Config"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 41 - "Obsidian Notes Tool"
Cohesion: 0.22
Nodes (16): is_private(), _notes(), Any, Path, tool, Write a note; returns its path in the vault. ValueError when it can't., The vault file a relative path names. ValueError if it leaves the vault or is…, (relative path, text) of every note Ultron may read, newest first. (+8 more)

### Community 42 - "Swift App Delegate"
Cohesion: 0.17
Nodes (8): EventHotKeyRef, Notification, NSApplication, NSApplicationDelegate, NSImage, NSObject, NSStatusItem, App

### Community 43 - "Terminal UI"
Cohesion: 0.21
Nodes (8): snapshot(), Terminal(), TerminalProps, API_BASE, UltronSocket, useUltron(), @xterm/addon-fit, @xterm/xterm

### Community 44 - "Notifications & Telegram"
Cohesion: 0.21
Nodes (13): notification(), _mac(), push(), Tell the user something. A channel that fails is logged, never raised., _call(), configured(), Any, tool (+5 more)

### Community 46 - "Chat Store"
Cohesion: 0.23
Nodes (12): _clean(), _clean_cards(), delete(), load(), Saved chats (at most MAX_CHATS), in storage/chats.json. A saved chat is the…, Only what's needed to show the chat again; the browser sends the rest too., Newest first, without the messages., Save (or update) a chat. ValueError when it's new and MAX_CHATS are already… (+4 more)

### Community 48 - "Briefing & Action Tools (docs)"
Cohesion: 0.15
Nodes (13): Confirmation Card Gate, WhatsApp Send, Calendar Read/Write (Google Calendar), Daily Briefing Milestone, find_contact (macOS Contacts), mac_read / mac_change / run_python, TickTick Reminders, Ultron To-Do List (+5 more)

### Community 49 - "Connector Startup"
Cohesion: 0.20
Nodes (7): Give slow connectors a moment, so the first message can already use them., Switch claude.ai connectors on or off to match JARVIS_CONNECTORS (.env). Claude…, Start Claude Code ahead of the first message (called at server startup)., The school notes as a paragraph for the system prompt ("" when there are none)., school_block(), ClaudeAgentOptions, ClaudeSDKClient

### Community 50 - "Device Tests"
Cohesion: 0.17
Nodes (3): DeviceTest, tab(), SimpleNamespace

### Community 55 - "Connector Retry Tests"
Cohesion: 0.27
Nodes (3): FakeClient, A session that started without the claude.ai connectors looks for them again., RetryConnectors

### Community 57 - "Contacts Lookup"
Cohesion: 0.29
Nodes (10): find_contact(), Any, tool, Contacts: look people up in macOS Contacts (read-only). There's no claude.ai…, my mom' -> 'mother', 'Annem' -> 'mother'. None if it isn't a relationship word., What to search for a relation, in order: the user's own word, English, Turkish,…, relation_label(), _run() (+2 more)

### Community 58 - "Swift Overlay Errors"
Cohesion: 0.24
Nodes (8): LocalizedError, OverlayError, .errorDescription, Any, String, Void, WKScriptMessage, WKUserContentController

### Community 59 - "Terminal Backend"
Cohesion: 0.20
Nodes (8): terminal_endpoint(), WebSocket, Your normal environment, without the variables that point Ultron's own Claude…, In the shell's process, before it starts: make the pty its terminal, so Ctrl-C…, _resize(), serve(), _shell_env(), _take_terminal()

### Community 63 - "Memory Tools"
Cohesion: 0.42
Nodes (9): _changed(), forget(), Any, tool, remember / recall / forget: what Ultron knows about you between chats. The…, Keep the memory panel in every open tab up to date., recall(), remember() (+1 more)

### Community 64 - "Phone Tools"
Cohesion: 0.42
Nodes (9): _call(), phone_taxi(), phone_volume(), Any, tool, The user's Android phone, through MacroDroid macros on it. (read: only their…, The address of the macro whose webhook identifier this is. ValueError if…, _text() (+1 more)

### Community 65 - "WhatsApp Tool"
Cohesion: 0.33
Nodes (9): phone_digits(), Any, tool, WhatsApp: send a message from the WhatsApp app on this Mac. (act: asks you…, +90 532 138 20 11' -> '905321382011'. None without a country code or if it…, _run(), _text(), _whatsapp_in_front() (+1 more)

### Community 66 - "Brain Design (docs)"
Cohesion: 0.22
Nodes (9): Connector MCP Configs (fallback), No __init__.py in backend/mcp, claude-agent-sdk, Claude Pro Login Brain, brain_api.py Placeholder, Brain Protocol (brain/base.py), ClaudeCodeBrain, In-process SDK MCP Server (ultron) (+1 more)

### Community 72 - "WhatsApp Tests"
Cohesion: 0.28
Nodes (3): Run whatsapp_send with fake commands; front_apps is what's frontmost at each…, run(), WhatsAppTest

### Community 73 - "Expert & Usage Tracking"
Cohesion: 0.28
Nodes (9): consult_expert(), Any, From Claude Code's rate_limit_event. The numbers cover your whole Pro plan…, From a reply's ResultMessage.model_usage ({model: {inputTokens, ...}})., Everything the usage panel shows., record_limits(), record_turn(), _save() (+1 more)

### Community 74 - "API Brain Placeholder"
Cohesion: 0.25
Nodes (3): ApiBrain, BrainEvent, Placeholder: API-key brain. Not used. Ultron runs on the Claude Pro…

### Community 78 - "Swift Locate Script"
Cohesion: 0.32
Nodes (7): CoreLocation, Date, Foundation, MapKit, iso(), parseDate(), String

### Community 79 - "Calendar & Time Note"
Cohesion: 0.29
Nodes (3): now_note(), Tuesday 29 September 2026, 20:15 CEST (UTC+0200)': local time with its offset., CalendarTest

### Community 80 - "Tool Permission Callback"
Cohesion: 0.29
Nodes (6): _Pending, Any, Called by Claude Code before any tool that isn't auto-allowed., PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

### Community 81 - "Upload Store"
Cohesion: 0.29
Nodes (6): prune_screens(), Files you upload from your computer. storage/uploads/upl_001/report.pdf Images…, Store a file and return its id (upl_001, ...)., Delete all but the newest `keep` screen captures., save(), threading

### Community 84 - "Memory Search"
Cohesion: 0.33
Nodes (6): entries(), prompt_block(), Memories that contain every word of the query (any order, any case). No query:…, The newest memories as a paragraph for the system prompt ("" when there are…, Every memory, most recently changed first., search()

### Community 85 - "Gateway Start Tests"
Cohesion: 0.53
Nodes (3): dict, object, StartTest

### Community 86 - "Login Switch Tests"
Cohesion: 0.47
Nodes (3): LoginTest, dict, object

### Community 89 - "Lint Config"
Cohesion: 0.33
Nodes (5): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 99 - "Model Router"
Cohesion: 0.50
Nodes (4): ask_expert (Sonnet to Opus), Model Router, brain/router.py Model Routing, Sticky Routing

### Community 101 - "WebSocket Protocol"
Cohesion: 0.67
Nodes (3): fastapi, hub.py Event Push, WebSocket Protocol (events.py / ws.ts)

### Community 105 - "Tool Hooks"
Cohesion: 0.67
Nodes (3): hooks(), Checks that run before a tool does., HookMatcher

### Community 106 - "Favicon & Brand"
Cohesion: 0.67
Nodes (3): ULTRON cBrain Brand Identity (AI Orb), ULTRON Favicon (Purple Glowing Orb), Purple Radial Gradient (#e9d5ff -> #a855f7 -> #3b146e)

## Knowledge Gaps
- **150 isolated node(s):** `$schema`, `plugins`, `react/rules-of-hooks`, `react/only-export-components`, `name` (+145 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 729 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **67 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ClaudeCodeBrain` connect `Brain Protocol & Events` to `Storage & Tool Test Suite`, `Memory Tests`, `Agent & Confirmation Gate`, `Config & System Prompts`, `Connector Startup`, `Claude Code Brain Session`, `Connector Retry Tests`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Why does `JobsTest` connect `Mac Tool Tests` to `Agent & Confirmation Gate`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Why does `AssetsDevTest` connect `3DAssets Download Tests` to `Storage & Tool Test Suite`, `Library & Homework Tests`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._
- **What connects `$schema`, `plugins`, `react/rules-of-hooks` to the rest of the system?**
  _150 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Canvas Events & Config` be split into smaller, more focused modules?**
  _Cohesion score 0.054385964912280704 - nodes in this community are weakly interconnected._
- **Should `Amazon & Flights Browsing` be split into smaller, more focused modules?**
  _Cohesion score 0.060764587525150904 - nodes in this community are weakly interconnected._
- **Should `Storage & Tool Test Suite` be split into smaller, more focused modules?**
  _Cohesion score 0.09090909090909091 - nodes in this community are weakly interconnected._