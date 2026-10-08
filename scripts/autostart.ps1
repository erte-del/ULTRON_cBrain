# Windows: start Ultron in the background when you log in, with no window (a scheduled task).
#   powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 on    turn it on
#   powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 off   turn it off and stop Ultron
# Then "Hey Ultron" opens him (JARVIS_BACKGROUND_WAKE). Log: backend\storage\ultron.log.
# Run "on" again after changing .env or moving the project folder.
param([ValidateSet("on", "off")][string]$mode = "on")
$ErrorActionPreference = "Stop"
$backend = Resolve-Path "$PSScriptRoot\..\backend"

Stop-ScheduledTask "Ultron Backend" -ErrorAction SilentlyContinue
if ($mode -eq "off") {
    Unregister-ScheduledTask "Ultron Backend" -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Autostart off."
    exit
}
if (-not (Test-Path "$backend\..\frontend\dist\index.html")) {
    throw "Build the page first: cd frontend; npm run build"
}

# conhost --headless: no console window, for Ultron or anything he starts (Claude Code, ffmpeg).
$run = "set PYTHONUTF8=1&& .venv\Scripts\python.exe main.py >> storage\ultron.log 2>&1"
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd /c `"$run`"" -WorkingDirectory $backend
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Ultron Backend" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask "Ultron Backend"
Write-Host "Autostart on: Ultron is starting in the background. Say `"Hey Ultron`"."
