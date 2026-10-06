# Ultron's PC agent, once: dependencies, a token, Tailscale, start at logon.
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Run it again any time; it keeps the token. If the task step says "Access is denied",
# run it from an Administrator PowerShell.
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

py -m pip install --user -r "$here\requirements.txt"

$tokenFile = "$here\token.txt"
if (-not (Test-Path $tokenFile)) {
    py -c "import secrets; print(secrets.token_urlsafe(32))" | Set-Content -NoNewline $tokenFile
}

# Your tailnet only, over HTTPS, to 127.0.0.1:8765. Never "tailscale funnel".
tailscale serve --bg 8765
$name = (tailscale status --json | ConvertFrom-Json).Self.DNSName.TrimEnd(".")

# At logon, in your own session (a Windows service can't see your desktop, clipboard or speakers).
$pythonw = py -c "import os, sys; print(os.path.join(sys.exec_prefix, 'pythonw.exe'))"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$here\ultron_pc.py`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Ultron" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Stop-ScheduledTask "Ultron" -ErrorAction SilentlyContinue
Start-ScheduledTask "Ultron"

Write-Host "`nRunning. In the Mac's .env:"
Write-Host "JARVIS_PC_URL=https://$name"
Write-Host "JARVIS_PC_TOKEN=$(Get-Content $tokenFile)"
