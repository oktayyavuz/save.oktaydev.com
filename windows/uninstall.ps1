<#
  Removes the Windows services created by install.ps1. Data (data\) is kept.

      powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1
#>
param([string]$ServiceName = "SaveApp")

$Root = Split-Path -Parent $PSScriptRoot
foreach ($id in @("${ServiceName}Caddy", $ServiceName)) {
    $exe = Join-Path $Root "tools\services\$id\$id.exe"
    if (Get-Service -Name $id -ErrorAction SilentlyContinue) {
        Stop-Service $id -Force -ErrorAction SilentlyContinue
        if (Test-Path $exe) { & $exe uninstall } else { sc.exe delete $id }
        Write-Host "removed $id"
    }
}
