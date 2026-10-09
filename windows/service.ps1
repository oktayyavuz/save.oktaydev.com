<#
  Control the Save services. Run from an Administrator PowerShell:

      powershell -ExecutionPolicy Bypass -File windows\service.ps1 stop      # stop now
      powershell -ExecutionPolicy Bypass -File windows\service.ps1 start
      powershell -ExecutionPolicy Bypass -File windows\service.ps1 restart
      powershell -ExecutionPolicy Bypass -File windows\service.ps1 status
      powershell -ExecutionPolicy Bypass -File windows\service.ps1 disable   # stop + don't start with Windows
      powershell -ExecutionPolicy Bypass -File windows\service.ps1 enable    # start with Windows again
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet("start", "stop", "restart", "status", "disable", "enable")][string]$Action,
    [string]$ServiceName = "SaveApp"
)

$names = @($ServiceName, "${ServiceName}Caddy") | Where-Object { Get-Service -Name $_ -ErrorAction SilentlyContinue }
if (-not $names) { Write-Host "No $ServiceName service installed."; exit 1 }

foreach ($n in $names) {
    switch ($Action) {
        "start"   { Start-Service $n }
        "stop"    { Stop-Service $n -Force }
        "restart" { Restart-Service $n -Force }
        "disable" { Stop-Service $n -Force; Set-Service $n -StartupType Disabled }
        "enable"  { Set-Service $n -StartupType Automatic; Start-Service $n }
    }
}
Get-Service -Name $names | Format-Table Name, Status, StartType -AutoSize
