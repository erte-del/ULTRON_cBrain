# Windows: set Ultron up in one go. Safe to run again; finished steps are skipped.
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
# Installs uv and Node 24 (winget) if missing, makes backend\.venv, installs the Python
# packages, builds the page, copies .env.example to .env if there's none, and turns on autostart.
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
Set-Location $root

# winget puts new programs on PATH only for new windows: reload it here instead.
function Update-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Install-IfMissing($command, $id) {
    if (Get-Command $command -ErrorAction SilentlyContinue) { return }
    Write-Host "Installing $id ..."
    winget install -e --id $id --accept-source-agreements --accept-package-agreements
    Update-Path
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is still not found. Close and reopen PowerShell, then run this script again."
    }
}
# Native programs don't stop the script on failure by themselves.
function Check($step) { if ($LASTEXITCODE -ne 0) { throw "$step failed (exit code $LASTEXITCODE)." } }

Install-IfMissing "uv" "astral-sh.uv"
Install-IfMissing "npm" "OpenJS.NodeJS"
$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 24) { Write-Warning "Node $(node --version) found; Ultron expects Node 24 (winget upgrade OpenJS.NodeJS)." }

Write-Host "`n== Backend (Python 3.13) =="
if (-not (Test-Path "backend\.venv\Scripts\python.exe")) {
    uv venv --python 3.13 backend\.venv; Check "uv venv"
}
uv pip install --python backend\.venv\Scripts\python.exe -r backend\requirements.txt; Check "uv pip install"

Write-Host "`n== Frontend (the page) =="
Push-Location frontend
try {
    npm install; Check "npm install"
    npm run build; Check "npm run build"
} finally { Pop-Location }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "`nMade .env from .env.example: open it to fill in the keys you want."
}

Write-Host "`n== Autostart =="
& "$PSScriptRoot\autostart.ps1" on

Write-Host "`nDone. Open http://127.0.0.1:8000"
