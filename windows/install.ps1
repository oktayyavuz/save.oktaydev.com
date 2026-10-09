<#
  Save - Windows VDS installer
  ----------------------------
  Run from an *Administrator* PowerShell in the project folder:

      # Cloudflare Tunnel (recommended): app listens on http://127.0.0.1:8000
      powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Tunnel
      # ...and also install cloudflared as a service with the token from the Cloudflare dashboard
      powershell -ExecutionPolicy Bypass -File windows\install.ps1 -TunnelToken eyJh...

      # Without Cloudflare: Caddy with automatic HTTPS (DNS A record -> this server)
      powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Domain save.oktaydev.com

  What it does:
    1. Installs Python 3.12 (if missing) and creates .venv with the requirements
    2. Downloads ffmpeg + deno into tools\ (needed for merging / MP3 / YouTube)
    3. Creates .env with a random SECRET_KEY
    4. Registers the app as a Windows service (auto start, auto restart)
    5. -Tunnel / -TunnelToken: no ports are opened; Cloudflare Tunnel points to http://127.0.0.1:8000
       -Domain: installs Caddy as a second service for automatic HTTPS (ports 80/443)
       none of them: plain HTTP on -Port (default 80)

  Re-running the script is safe; it updates what is already there.
#>
param(
    [switch]$Tunnel,
    [string]$TunnelToken = "",
    [string]$Domain = "",
    [int]$Port = 80,
    [string]$ServiceName = "SaveApp",
    [switch]$SkipPython
)

if ($TunnelToken) { $Tunnel = $true }
if ($Tunnel -and $Domain) { throw "Use either -Tunnel or -Domain, not both." }

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$Logs = Join-Path $Root "logs"
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $Tools, $Logs | Out-Null

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Please run this script from an Administrator PowerShell." }

function Download($url, $dest) {
    Write-Host "    downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

# ---------------------------------------------------------------- 1. Python
Step "Python"
function Find-Python {
    $candidates = @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"))
    foreach ($c in $candidates) {
        try {
            $cmdArgs = @()
            if ($c.Length -gt 1) { $cmdArgs += $c[1..($c.Length - 1)] }
            $cmdArgs += @("-c", "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')")
            $exe = & $c[0] @cmdArgs 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return ([string]$exe).Trim() }
        } catch { }
    }
    return $null
}
$Python = Find-Python
if (-not $Python -and -not $SkipPython) {
    $installer = Join-Path $env:TEMP "python-3.12-installer.exe"
    Download "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" $installer
    Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $Python = Find-Python
}
if (-not $Python) { throw "Python 3.11+ not found. Install it from python.org and re-run." }
Ok "using $Python"

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv $Venv
}
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt") --upgrade --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Ok "dependencies installed"

# ---------------------------------------------------------------- 2. ffmpeg + deno
Step "ffmpeg"
$ffmpegExe = Join-Path $Tools "ffmpeg\bin\ffmpeg.exe"
if (-not (Test-Path $ffmpegExe)) {
    $zip = Join-Path $env:TEMP "ffmpeg.zip"
    try {
        Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $zip
    } catch {
        Download "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $zip
    }
    $tmp = Join-Path $env:TEMP "ffmpeg-extract"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    Remove-Item -Recurse -Force (Join-Path $Tools "ffmpeg") -ErrorAction SilentlyContinue
    Move-Item $inner.FullName (Join-Path $Tools "ffmpeg")
    Remove-Item -Recurse -Force $tmp, $zip -ErrorAction SilentlyContinue
}
Ok (& $ffmpegExe -version | Select-Object -First 1)

Step "deno (JavaScript runtime required by yt-dlp for YouTube)"
$denoExe = Join-Path $Tools "deno.exe"
if (-not (Test-Path $denoExe)) {
    $zip = Join-Path $env:TEMP "deno.zip"
    Download "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" $zip
    Expand-Archive -Path $zip -DestinationPath $Tools -Force
    Remove-Item $zip -Force
}
Ok (& $denoExe --version | Select-Object -First 1)

# ---------------------------------------------------------------- 3. .env
Step ".env"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
    $cf = "BEHIND_CLOUDFLARE=0"
    if ($Tunnel) {
        $hostLine = "HOST=127.0.0.1"; $portLine = "PORT=8000"; $secure = "SECURE_COOKIES=1"; $cf = "BEHIND_CLOUDFLARE=1"
    } elseif ($Domain) {
        $hostLine = "HOST=127.0.0.1"; $portLine = "PORT=8000"; $secure = "SECURE_COOKIES=1"
    } else {
        $hostLine = "HOST=0.0.0.0"; $portLine = "PORT=$Port"; $secure = "SECURE_COOKIES=0"
    }
    @(
        "# Generated by windows\install.ps1",
        "SECRET_KEY=$secret",
        $hostLine,
        $portLine,
        $secure,
        $cf,
        "LOG_LEVEL=INFO"
    ) | Set-Content -Path $envFile -Encoding ASCII
    Ok "created .env (keep SECRET_KEY safe: it encrypts the saved tokens/cookies)"
} else {
    Ok ".env already exists, leaving it as is"
}

# ---------------------------------------------------------------- 4. services (WinSW)
$WinSW = Join-Path $Tools "winsw.exe"
if (-not (Test-Path $WinSW)) {
    Download "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe" $WinSW
}

function Install-WinSWService($id, $display, $description, $exe, $arguments, $envVars) {
    $dir = Join-Path $Tools "services\$id"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $svcExe = Join-Path $dir "$id.exe"
    $svcXml = Join-Path $dir "$id.xml"
    $existing = Get-Service -Name $id -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Status -ne "Stopped") { Stop-Service $id -Force; Start-Sleep 2 }
        & $svcExe uninstall | Out-Null
        Start-Sleep 2
    }
    Copy-Item $WinSW $svcExe -Force
    $envXml = ""
    foreach ($k in $envVars.Keys) { $envXml += "  <env name=`"$k`" value=`"$($envVars[$k])`"/>`n" }
    @"
<service>
  <id>$id</id>
  <name>$display</name>
  <description>$description</description>
  <executable>$exe</executable>
  <arguments>$arguments</arguments>
  <workingdirectory>$Root</workingdirectory>
$envXml  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <onfailure action="restart" delay="5 sec"/>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>20 sec</stoptimeout>
  <logpath>$Logs</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
</service>
"@ | Set-Content -Path $svcXml -Encoding UTF8
    & $svcExe install | Out-Null
    Start-Service $id
    Ok "$id service installed and started"
}

Step "Windows service: $ServiceName"
Install-WinSWService $ServiceName "Save video downloader" "Save web site + Telegram bot" `
    $VenvPython "`"$(Join-Path $Root 'run.py')`"" @{ RUNNING_AS_SERVICE = "1"; PYTHONUNBUFFERED = "1"; PYTHONIOENCODING = "utf-8" }

$ports = @()
if ($Tunnel) {
    if ($TunnelToken) {
        Step "cloudflared (Cloudflare Tunnel)"
        $cloudflared = Join-Path $Tools "cloudflared.exe"
        if (-not (Test-Path $cloudflared)) {
            Download "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" $cloudflared
        }
        if (Get-Service -Name "Cloudflared" -ErrorAction SilentlyContinue) {
            & $cloudflared service uninstall | Out-Null
            Start-Sleep 2
        }
        & $cloudflared service install $TunnelToken
        Ok "cloudflared service installed"
    }
    Ok "Cloudflare Tunnel -> Public hostname service: HTTP  localhost:8000"
} elseif ($Domain) {
    Step "Caddy (automatic HTTPS for $Domain)"
    $caddyExe = Join-Path $Tools "caddy.exe"
    if (-not (Test-Path $caddyExe)) {
        Download "https://caddyserver.com/api/download?os=windows&arch=amd64" $caddyExe
    }
    $caddyfile = Join-Path $Root "Caddyfile"
    @"
$Domain {
    encode zstd gzip
    request_body {
        max_size 2MB
    }
    reverse_proxy 127.0.0.1:8000 {
        transport http {
            read_timeout 30m
            write_timeout 30m
        }
    }
}
"@ | Set-Content -Path $caddyfile -Encoding ASCII
    Install-WinSWService "${ServiceName}Caddy" "Save HTTPS proxy (Caddy)" "Reverse proxy with automatic Let's Encrypt certificates" `
        $caddyExe "run --config `"$caddyfile`" --adapter caddyfile" @{ XDG_DATA_HOME = (Join-Path $Root "data\caddy") }
    $ports = @(80, 443)
} else {
    $ports = @($Port)
}

if ($ports.Count -gt 0) { Step "Firewall" }
foreach ($p in $ports) {
    $name = "Save HTTP $p"
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow | Out-Null
    }
    Ok "port $p open"
}

Write-Host ""
if ($Tunnel) { $url = "https://<your-tunnel-hostname>" } elseif ($Domain) { $url = "https://$Domain" } elseif ($Port -eq 80) { $url = "http://<server-ip>" } else { $url = "http://<server-ip>:$Port" }
Write-Host "Done! Open $url/admin to create the admin account." -ForegroundColor Green
Write-Host "Logs: $Logs"
