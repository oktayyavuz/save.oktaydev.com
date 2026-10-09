<#
  Updates the code (git pull, if this is a git checkout), the Python packages
  (including yt-dlp, which should be updated often) and restarts the service.

      powershell -ExecutionPolicy Bypass -File windows\update.ps1
#>
param([string]$ServiceName = "SaveApp")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (Test-Path (Join-Path $Root ".git")) {
    Write-Host "==> git pull" -ForegroundColor Cyan
    git -C $Root pull --ff-only
}

Write-Host "==> pip install -U" -ForegroundColor Cyan
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt") --upgrade --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $VenvPython -c "import yt_dlp; print('yt-dlp', yt_dlp.version.__version__)"

Write-Host "==> restart $ServiceName" -ForegroundColor Cyan
Restart-Service $ServiceName
Write-Host "Done." -ForegroundColor Green
