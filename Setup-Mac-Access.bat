<# :
@echo off
rem Lets you open Agent HQ from your Mac (or phone) anywhere, through Tailscale. Double-click it. Safe to run again.
rem The PowerShell below this line does the work (this file is both a .bat and a PowerShell script).
title Agent HQ: set up Mac access
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:HQ_SETUP='%~f0'; iex ([IO.File]::ReadAllText('%~f0'))"
echo.
pause
exit /b
#>

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $env:HQ_SETUP
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Ts = 'C:\Program Files\Tailscale\tailscale.exe'
$Port = 8000

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n!! $text" -ForegroundColor Red; exit 1 }
# Native tools print notes on stderr; under 'Stop' Windows PowerShell would treat those as failures.
function Run { $ErrorActionPreference = 'Continue'; $exe, $rest = $args; & $exe @rest 2>$null }
function Port-Open {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $c.Close() }
}

Write-Host 'Agent HQ: set up Mac access' -ForegroundColor Yellow
Write-Host 'This keeps HQ running on this PC so your Mac can open it from anywhere.'
if (-not (Test-Path $Py)) { Fail "Agent HQ isn't installed in $Root yet. Run Install-Agent-HQ.bat first." }
Set-Location $Root

# 1. Tailscale: the private link between this PC and your Mac.
if (-not (Test-Path $Ts)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say 'Installing Tailscale (a minute or two)'
        winget install --id Tailscale.Tailscale -e --silent --accept-source-agreements --accept-package-agreements | Out-Host
    }
    if (-not (Test-Path $Ts)) {
        Start-Process 'https://tailscale.com/download/windows'
        Fail 'Install Tailscale from the page that just opened, then run this again.'
    }
}
$ip = Run $Ts ip -4 | Select-Object -First 1
if (-not $ip) {
    Say 'Sign in to Tailscale in the browser window that opens (use the same account you will use on your Mac)'
    $ErrorActionPreference = 'Continue'
    & $Ts up --unattended --timeout 300s
    $ErrorActionPreference = 'Stop'
    $ip = Run $Ts ip -4 | Select-Object -First 1
    if (-not $ip) { Fail "Tailscale isn't signed in yet. Click the Tailscale icon by the clock, sign in, then run this again." }
}
# The MagicDNS name, e.g. "gator-pc" from "gator-pc.tail1234.ts.net."
$name = ((Run $Ts status --json | Out-String | ConvertFrom-Json).Self.DNSName -split '\.')[0]
if (-not $name) { $name = $ip }
Say "Tailscale is on. This PC is '$name' ($ip)"

# 2. A password, so only you can open HQ.
$hasPassword = Run $Py -c "from hq.config import PASSWORD; print('yes' if PASSWORD else '')"
if (-not $hasPassword) {
    Say 'Choose a password for HQ. You will type it on your Mac.'
    do {
        $secure = Read-Host 'Password' -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    } while (-not $plain)
    $env:HQ_NEW_PASSWORD = $plain
    Run $Py -c "import os; from hq import settings; settings.save({'HQ_PASSWORD': os.environ['HQ_NEW_PASSWORD']})"
    $saved = $LASTEXITCODE
    Remove-Item Env:HQ_NEW_PASSWORD
    if ($saved -ne 0) { Fail 'Could not save the password. Set HQ_PASSWORD on the Settings page instead.' }
    Write-Host 'Saved. You can change it any time on the Settings page.'
} else {
    Say 'HQ already has a password (change it on the Settings page if you forgot it)'
}

# 3. Let your Tailscale devices (and only them) through the Windows firewall.
if (-not (Get-NetFirewallRule -DisplayName 'Agent HQ' -ErrorAction SilentlyContinue)) {
    Say 'Opening HQ to your Tailscale devices. Click Yes on the Windows prompt.'
    $rule = "New-NetFirewallRule -DisplayName 'Agent HQ' -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress 100.64.0.0/10 -Action Allow -Profile Any"
    try { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $rule }
    catch { Fail 'The firewall step needs you to click Yes. Run this again.' }
    if (-not (Get-NetFirewallRule -DisplayName 'Agent HQ' -ErrorAction SilentlyContinue)) { Fail 'The firewall rule was not added. Run this again and click Yes.' }
}
Say 'Firewall is set'

# 4. Never sleep while plugged in, or the Mac can't reach HQ.
Run powercfg /change standby-timeout-ac 0
Run powercfg /change hibernate-timeout-ac 0
Say 'This PC will stay awake while plugged in (the screen can still turn off)'

# 5. Run HQ in the background from now on, and every time you sign in.
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Agent HQ.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($startup)
$s.TargetPath = Join-Path $Root 'start-hq.bat'
$s.WorkingDirectory = $Root
$s.WindowStyle = 7  # minimized
$s.Save()
Say 'HQ will start by itself when you sign in to this PC'

Say 'Restarting HQ so the Mac can reach it'
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*-m hq*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Start-Process -FilePath $startup -WindowStyle Minimized
for ($i = 0; $i -lt 90 -and -not (Port-Open); $i++) { Start-Sleep -Seconds 2 }
if (-not (Port-Open)) { Fail "HQ didn't start. Open the minimized 'start-hq' window on the taskbar to see why." }

$url = "http://${name}:$Port"
$note = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Agent HQ on my Mac.txt'
@"
Open Agent HQ on your Mac (Tailscale must be on there too):

  $url

If that name doesn't work, use:  http://${ip}:$Port

Keep this PC plugged in and signed in. HQ runs in the minimized 'start-hq' window; don't close it.
The Agent HQ icon still opens HQ here, and closing that window no longer stops HQ.
"@ | Set-Content -Path $note -Encoding UTF8
try { Set-Clipboard -Value $url } catch {}

Write-Host "`nAll set!" -ForegroundColor Green
Write-Host "On your Mac, open:  $url" -ForegroundColor Yellow
Write-Host "(Also saved to 'Agent HQ on my Mac.txt' on your Desktop, and copied.)"
