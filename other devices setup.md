# Other devices setup: point everything at the Mac mini

Ultron now runs on the **Mac mini**. This is what to do on each other device so it uses the
mini instead of the old MacBook. The mini's address is:

```
https://<mini-name>.<your-tailnet>.ts.net
```

(Check any time on the mini: `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status`.)

Every device must be signed in to the **same Tailscale account** (your Tailscale login) and
Tailscale must be **connected**. The address only works inside your tailnet, never from the
open internet. Never use `tailscale funnel`.

---

## 1. Android phone (Galaxy S24)

1. Open the **Tailscale** app and make sure it says Connected.
2. In Chrome, open `https://<mini-name>.<your-tailnet>.ts.net`.
3. Bookmark it, or Chrome menu → **Add to Home screen** so it opens like an app.
4. Allow the **microphone** when Chrome asks (voice runs in the page).
5. Delete or replace the old MacBook bookmark.

Nothing else changes. MacroDroid and Telegram are cloud services.

## 2. Windows PC

The PC agent (`ultron_pc.py`, `JARVIS_PC_URL`) does **not** change. Only the "Hey Ultron" listener
needs the new address.

1. Open `windows\wake_pc.env` in the Ultron folder on the PC. If it doesn't exist, copy
   `wake_pc.env.example` to `wake_pc.env`.
2. Set this line (the only line you must change):
   ```
   ULTRON_URL=https://<mini-name>.<your-tailnet>.ts.net
   ```
3. Restart the listener in PowerShell, from the Ultron folder:
   ```powershell
   scripts\autostart.ps1 on
   ```
4. Test: say "Hey Ultron". The window that opens must be the **mini's** page.
5. Make sure Tailscale on the PC is connected.

If you set `ULTRON_OPEN` (a shortcut that opens Ultron), update that shortcut's address too.

### Later: game sound in clips on the PC

BlackHole is Mac only. On Windows use **Stereo Mix** or a loopback device (for example VB-Cable):

1. Sound settings → Recording → right-click → show disabled devices → enable **Stereo Mix**.
2. Install ffmpeg if needed: `winget install -e --id Gyan.FFmpeg`
3. Find the exact device name: `ffmpeg -list_devices true -f dshow -i dummy`
4. Put the name in the PC's Ultron `.env` as `JARVIS_CAPTURE_AUDIO=Stereo Mix (Realtek Audio)`
   (use your exact name).

## 3. MacBook (retire Ultron there)

Do this so Ultron doesn't run jobs twice (briefings, watchers, Telegram messages).

1. Quit `Ultron.app` (menu-bar orb).
2. In Terminal, from the MacBook's Ultron folder:
   ```bash
   scripts/autostart.sh off
   scripts/stop_ultron.sh
   tailscale serve reset
   ```
3. Confirm it's stopped: `curl -s http://127.0.0.1:8000/health` should fail on the MacBook.

**Optional:** the MacBook can open a terminal on the mini. This is already allowed for
your Tailscale login. Open the mini's address in the MacBook's browser and use the Terminal tab.

## 4. Check everything

- [ ] Phone opens the mini's address and chats
- [ ] PC "Hey Ultron" opens the mini's page
- [ ] MacBook's Ultron is off (`/health` fails there)
- [ ] `tailscale status` on the mini lists all three devices
