# Remote terminals: setup

"Open a terminal on the PC" gives you a live shell on that device in a canvas tab (optionally running
Claude Code), which you can type in from your phone, MacBook or PC. Ultron uses plain `ssh` over
Tailscale, key login only, to the machines listed in `backend/devices.json`. Nothing new listens
anywhere except each device's own SSH server, which should only be reachable through Tailscale.

**Ultron's host must be the Mac** (the terminal needs Unix ptys); the *targets* can be Mac, Linux or Windows.

### 1 On the Mac mini (once)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/ultron_remote -N "" -C ultron-remote
cp backend/devices.example.json backend/devices.json   # skip if it already exists
tailscale ip -4                                          # the mini's 100.x address, for step 4
```

Edit `backend/devices.json`: one entry per device. `host` is its Tailscale name (MagicDNS) or
`100.x` address, `user` the account to log in as, `key` the file above. Names and `aliases` are what
you say ("the pc"). Ultron refuses any host that isn't a Tailscale address.

The key has no passphrase (Ultron can't type one), so whoever gets the file gets a shell on every
device below: keep it `chmod 600`, and lock each target's copy to the mini (step 4).

### 2 A Mac or Linux target (e.g. the MacBook)

1. Mac: System Settings → General → Sharing → **Remote Login** on, allowed for your user only.
   Linux: `sudo apt install openssh-server`.
2. Add the mini's public key (`cat ~/.ssh/ultron_remote.pub` on the mini) to `~/.ssh/authorized_keys` on the target.
3. Turn passwords off: create `/etc/ssh/sshd_config.d/ultron.conf` containing
   `PasswordAuthentication no` and `KbdInteractiveAuthentication no`, then on Mac
   `sudo launchctl kickstart -k system/com.openssh.sshd` (Linux: `sudo systemctl restart ssh`).
4. Install Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`), run `claude` once there to sign in.
5. Optional: `brew install tmux` (Mac) / `sudo apt install tmux`: a closed tab or dropped Wi-Fi then only
   detaches, and Claude keeps running.

macOS starts sshd through launchd, so you can't bind it to the Tailscale address only: it also answers on
your Wi-Fi. Keys-only login (step 3) and the Tailscale rule in step 5 are what protect it.

### 3 A Windows target (the PC), in an admin PowerShell

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service sshd -StartupType Automatic; Start-Service sshd
# Only Tailscale addresses may reach it:
Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -RemoteAddress 100.64.0.0/10
# Open in PowerShell, not cmd:
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force
winget install Anthropic.ClaudeCode   # then run `claude` once to sign in
```

Add the mini's public key line: if your Windows user is an administrator (usual), append it to
`C:\ProgramData\ssh\administrators_authorized_keys` and run
`icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`;
otherwise use `C:\Users\<you>\.ssh\authorized_keys`. Then in `C:\ProgramData\ssh\sshd_config` set
`PasswordAuthentication no` and `Restart-Service sshd`. (Windows has no tmux: closing the tab ends that session.)

### 4 Lock the key to the mini (every target)

Put `from="<the mini's 100.x address>"` in front of its line in `authorized_keys`, e.g.
`from="100.64.0.5" ssh-ed25519 AAAA… ultron-remote`. Tailscale gives each device a stable address, and
the key is then useless from anywhere else.

### 5 Tailscale access rule (optional, recommended)

SSH is already limited to the tailnet. To also stop other tailnet devices (a shared one, a guest) from
reaching port 22, in the Tailscale admin console → Access controls, tag the mini `tag:ultron-host`
and each target `tag:ssh-target` (add both under `tagOwners`), and allow
`{"action": "accept", "src": ["tag:ultron-host"], "dst": ["tag:ssh-target:22"]}`. Keep a rule that
still lets your own devices reach the mini (its page), then test before removing any broad allow rule.
Tailscale's own SSH feature isn't used: Windows (and the standard Mac app) can't be its server.

### 6 Try it

On the mini: `ssh -i ~/.ssh/ultron_remote you@<device host>` should log in with no prompt. Then ask Ultron
"open a terminal on the PC with Claude". The first open in a while shows an approval card
(`JARVIS_REMOTE_TRUST_MIN`, default 4 hours); typing for you with `remote_terminal_type` always asks.

