# Ultron PC setup prompt

Paste everything below the line into Claude Code (or any coding agent with a terminal) on the
Windows PC. It installs what Ultron needs, starts the PC agent, and prints the two lines for the
Mac's `.env`.

---

Set up this Windows PC so Ultron (an assistant running on my Mac) can control it over Tailscale.
The PC side is `windows/ultron_pc.py` in https://github.com/erte-del/ULTRON_cBrain, started by
`windows/install.ps1`. Work in PowerShell, one step at a time, and check each step worked before
moving on. Don't change any settings I didn't ask for.

1. **Check what's already there.** Report the Windows version and whether these exist:
   `winget`, `py` (Python 3.11 or newer), `git`, `tailscale`, `wt` (Windows Terminal).

2. **Install what's missing with winget** (`--accept-source-agreements --accept-package-agreements`
   is fine for these four only):
   - Python: `winget install -e --id Python.Python.3.12` (it includes the `py` launcher)
   - Git: `winget install -e --id Git.Git`
   - Tailscale: `winget install -e --id Tailscale.Tailscale`
   - Windows Terminal (optional, for `open_terminal`): `winget install -e --id Microsoft.WindowsTerminal`

   After installing, reload PATH in this shell
   (`$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")`)
   and confirm `py --version`, `git --version` and `tailscale version` work.

3. **Tailscale sign-in: I do this myself.** Stop and ask me to sign in to Tailscale on this PC with
   the **same account as my Mac**. Don't type any password. When I say done, check that
   `tailscale status` shows this PC and my Mac.
   Then tell me to make sure **MagicDNS** and **HTTPS Certificates** are on in the Tailscale admin
   console (https://login.tailscale.com/admin/dns), because `tailscale serve` needs them. Wait for me.

4. **Get the code.** Clone into my home folder:
   `git clone https://github.com/erte-del/ULTRON_cBrain "$HOME\ULTRON_cBrain"`.
   If it's already there, `git pull` instead. If GitHub asks me to sign in, let me do that myself.

5. **Run the installer.** `powershell -ExecutionPolicy Bypass -File "$HOME\ULTRON_cBrain\windows\install.ps1"`.
   It installs `pycaw`, makes `windows\token.txt`, runs `tailscale serve --bg 8765`, and registers a
   scheduled task called "Ultron" that starts the agent at logon. If the task step says
   "Access is denied", ask me to rerun it from an Administrator PowerShell.

6. **Check it actually works**, locally:
   ```powershell
   $t = Get-Content "$HOME\ULTRON_cBrain\windows\token.txt"
   Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/read -Headers @{Authorization="Bearer $t"} -ContentType application/json -Body '{"what":"status"}'
   ```
   It should return battery, sound, appearance and Wi-Fi. If it fails, read
   `windows\ultron_pc.log` and `Get-ScheduledTask Ultron | Get-ScheduledTaskInfo`, fix the cause, and
   retry. Also check `tailscale serve status` shows `https://<this-pc>.ts.net` → `127.0.0.1:8765`.
   **Never run `tailscale funnel`**: that would put the agent on the public internet.

7. **Ask before changing these** (each is optional; explain the trade-off in one line):
   - Sleep: Ultron can't reach a sleeping PC. Offer `powercfg /change standby-timeout-ac 0` (when
     plugged in only).
   - Wi-Fi name in status: Windows 11 hides it unless Location is on for desktop apps
     (Settings → Privacy & security → Location). Just tell me; don't change it.

8. **Finish** by printing exactly these two lines for me to paste into the Mac's `.env`, then tell
   me to restart Ultron on the Mac:
   ```
   JARVIS_PC_URL=https://<this PC's tailscale name>.ts.net
   JARVIS_PC_TOKEN=<contents of windows\token.txt>
   ```
   Don't put the token anywhere else (no files, commits or messages).

Ultron's files on this PC live in `%USERPROFILE%\Ultron Files` (set `ULTRON_PC_FOLDER` to change it).
Updates are automatic: every time the agent starts (each logon) it pulls the latest code from
GitHub. To update right away: `Stop-ScheduledTask Ultron; Start-ScheduledTask Ultron`.
