# "Hey Ultron" on this PC opens the Mac's Ultron: start wake_pc.py at logon, with no window.
#   powershell -ExecutionPolicy Bypass -File windows\wake_pc.ps1 on    turn it on (and start it now)
#   powershell -ExecutionPolicy Bypass -File windows\wake_pc.ps1 off   turn it off and stop it
# Log: windows\wake_pc.log. Run "on" again after moving the project folder.
param([ValidateSet("on", "off")][string]$mode = "on")
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$python = Resolve-Path "$here\..\backend\.venv\Scripts\python.exe"

Stop-ScheduledTask "Ultron Wake" -ErrorAction SilentlyContinue
# Stopping the task doesn't always end Python itself: end any wake_pc.py still running.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains("wake_pc.py") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if ($mode -eq "off") {
    Unregister-ScheduledTask "Ultron Wake" -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Ultron Wake off."
    exit
}
if (-not (Test-Path "$here\wake_pc.env")) {
    throw "Create windows\wake_pc.env first (copy wake_pc.env.example and fill in ULTRON_URL)."
}
if (Get-ScheduledTask "Ultron Backend" -ErrorAction SilentlyContinue) {
    Write-Warning "The full Ultron still starts on this PC: run scripts\autostart.ps1 off"
}

# conhost --headless: no console window. wake_pc.py writes its own (small) log.
$run = "set PYTHONUTF8=1&& `"$python`" wake_pc.py"
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd /c `"$run`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Ultron Wake" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask "Ultron Wake"
Write-Host "Ultron Wake on. Watch it start: Get-Content windows\wake_pc.log -Wait -Tail 20"
