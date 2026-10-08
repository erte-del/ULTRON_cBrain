# "Hey Ultron" on the PC → the Mac's Ultron

Paste everything below the line into Claude Code on the Windows PC.

---

Build a small "Hey Ultron" listener for this Windows PC. Work in PowerShell, one step at a time,
check each step works before the next, and explain what you're doing in simple terms (I'm learning).

**The idea.** Ultron (my AI assistant, repo `$HOME\ULTRON_cBrain`, https://github.com/erte-del/ULTRON_cBrain)
has **one brain, and it runs only on my Mac**. This PC must never run its own Ultron backend or
Claude Code for Ultron. The PC only listens for "Hey Ultron" and then opens the Mac's Ultron page,
which I reach over Tailscale (same as on my phone).

**What to build** (`windows\wake_pc.py`, plus a scheduled task):

1. **Turn off the full Ultron on this PC first:**
   `powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 off`. Check the task
   "Ultron Backend" is gone and nothing listens on 127.0.0.1:8000. Don't delete the repo.
   (The "Ultron" task from `windows\install.ps1`, the PC agent the Mac controls, is separate: leave it alone if it exists.)

2. **Find how I open the Mac's Ultron.** Ask me for the script or shortcut I already use to open
   it through Tailscale, and read it. If I don't have one, the address is the Mac's Tailscale URL
   (`https://<mac-name>.<tailnet>.ts.net`; `tailscale status` lists the Mac). Put the URL (or
   my script's path) in `windows\wake_pc.env` (git-ignored: add it to `.gitignore`), never hardcoded.
   Check the page actually loads from this PC before going on. If it doesn't, tell me what
   to check on the Mac: `tailscale serve --bg 8000` running, and `JARVIS_REMOTE_ORIGIN` in the
   Mac's `.env` set to that same https address (then restart Ultron on the Mac).

3. **The listener, `windows\wake_pc.py`.** Reuse the code that already does this, don't reinvent it:
   - `backend\voice\wake.py`: the mic loop (sounddevice `RawInputStream`, reopen the default mic
     every 60 s, retry after 10 s if there's no mic, skip while the window is opening).
   - `backend\voice\vad.py`: `Endpointer` cuts the audio into utterances (Silero VAD from faster-whisper).
   - `backend\voice\stt.py`: `after_wake()` and the `WAKE_HINT` prompt decide whether an utterance
     starts with "Hey Ultron". Use faster-whisper `small.en` on the CPU, int8.
   `stt.py` imports `config` (the full backend's settings): don't import it. Copy the few small
   functions you need into `wake_pc.py`, or import `voice.vad` only if it doesn't pull in `config`.
   Use the existing `backend\.venv` (it already has faster-whisper, sounddevice and numpy) so
   nothing new is installed. Store the whisper model under `windows\` (git-ignored), not in
   the backend's storage.
   - **On "Hey Ultron":** run my script from step 2, or by default open the URL in its own Edge window:
     `msedge --app=<URL> --start-fullscreen --autoplay-policy=no-user-gesture-required --user-data-dir=<windows\edge-profile>`.
     Its own profile means Edge remembers the mic permission and the page's "Hey Ultron · ON"
     setting just for this window.
   - **While that window is open, don't listen** (the page does its own listening and the two
     would both react). Check for an `msedge.exe` process whose command line contains that
     profile folder; start listening again once it's closed.
   - Audio never leaves this PC: wake-word checking is local, nothing is sent anywhere.
   - Log to `windows\wake_pc.log` (keep it small, e.g. a rotating handler), with
     `encoding="utf-8"` on every file read/write.

4. **Start it at logon, with no window:** a scheduled task "Ultron Wake" (at logon of my user, restart
   on failure, no time limit, runs on battery), started with `conhost.exe --headless`, like
   `scripts\autostart.ps1` does. Write it as `windows\wake_pc.ps1 on|off` so I can turn it off.

5. **Test with me:** start the task, check the log shows it listening, then I'll say
   "Hey Ultron" with no window open. The Mac's Ultron should open within a few seconds and I
   should be able to talk to it. Then ask me to restart the PC and try once more.

**Rules:** no new open ports, never `tailscale funnel`, never set `ANTHROPIC_API_KEY`, don't
change the Mac-side code, add one small test in `backend\tests\` (e.g. that "hey ultron, what's
up" is detected and "hey there" isn't), and add a short section to `README.md` (section 2.7).
I make the git commits myself.

**Known limit:** words said in the same breath ("Hey Ultron, play music") aren't passed to the
Mac's page yet, because the page has no way to receive them from the URL. After the window opens,
just say the request again. (That would need a small Mac-side change later.)
