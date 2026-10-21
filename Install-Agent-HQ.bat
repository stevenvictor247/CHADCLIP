<# :
@echo off
rem Agent HQ installer for Windows. Double-click it. Safe to run again any time.
rem The PowerShell below this line does the work (this file is both a .bat and a PowerShell script).
title Agent HQ installer
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:HQ_INSTALLER='%~f0'; iex ([IO.File]::ReadAllText('%~f0'))"
echo.
pause
exit /b
#>

# Stop on mistakes. Git and pip print progress as "errors", so they're never redirected below.
$ErrorActionPreference = 'Stop'
$Repo = 'https://github.com/stevenvictor247/CHADCLIP.git'
$Target = Join-Path $HOME 'CHADCLIP'

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n!! $text" -ForegroundColor Red; exit 1 }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Install-App($id, $name) {
    if (-not (Have 'winget')) {
        Start-Process 'ms-windows-store://pdp/?productid=9NBLGGH4NNS1'
        Fail "Windows needs the free 'App Installer' from the Microsoft Store to install $name. The Store just opened on it: click Install (or Update), then run this installer again."
    }
    Say "Installing $name (a minute or two)"
    winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements | Out-Host
    Refresh-Path
}
function Find-Python {
    foreach ($try in 'py -3.12', 'py -3', 'python') {
        $cmd, $ver = $try -split ' '
        if (-not (Have $cmd)) { continue }
        try {
            $exe = & $cmd @($ver | Where-Object { $_ }) -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and $exe -notlike '*WindowsApps*') { return $exe.Trim() }
        } catch {}
    }
    return $null
}

Write-Host 'Agent HQ installer' -ForegroundColor Yellow
Write-Host "This sets up Agent HQ in $Target, keeps your old data, and puts an Agent HQ icon on your Desktop."

# 1. The tools HQ needs.
Refresh-Path
if (-not (Have 'git')) { Install-App 'Git.Git' 'Git' }
if (-not (Have 'git') -and (Test-Path 'C:\Program Files\Git\cmd\git.exe')) { $env:Path += ';C:\Program Files\Git\cmd' }
if (-not (Have 'git')) { Fail 'Git did not install. Restart the computer and run this again.' }
$Python = Find-Python
if (-not $Python) { Install-App 'Python.Python.3.12' 'Python'; $Python = Find-Python }
if (-not $Python) { Fail 'Python did not install. Restart the computer and run this again.' }
if (-not (Have 'ffmpeg')) { Install-App 'Gyan.FFmpeg' 'ffmpeg (video tools)' }
Say "Using Python at $Python"

# 2. Stop a running HQ so its files can be updated.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*-m hq*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 3. Get the code as a git copy, so HQ can update itself from now on.
$Old = @()
if ((Test-Path $Target) -and -not (Test-Path (Join-Path $Target '.git'))) {
    $moved = "$Target-old-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Say "$Target isn't an updatable copy. Moving it to $moved (your data comes along)."
    Rename-Item $Target $moved
    $Old += $moved
}
if (Test-Path (Join-Path $Target '.git')) {
    Say 'Getting the newest HQ code'
    git -C $Target pull --ff-only
} else {
    Say 'Downloading HQ from GitHub (if a GitHub sign-in window opens, sign in as stevenvictor247)'
    git clone $Repo $Target
    if (-not (Test-Path (Join-Path $Target 'hq'))) { Fail 'Download failed. Check the internet connection and that you signed in to GitHub, then run this again.' }
}

# 4. Bring over data, keys and settings from older copies (ZIP downloads, earlier folders).
$Old += Get-ChildItem -Directory -ErrorAction SilentlyContinue -Path `
    (Join-Path $HOME 'Downloads\CHADCLIP*'), (Join-Path $HOME 'Desktop\CHADCLIP*'), (Join-Path $HOME 'Documents\CHADCLIP*'), "$Target-old-*" |
    Where-Object { Test-Path (Join-Path $_.FullName 'hq') } | ForEach-Object { $_.FullName }
if ($env:HQ_INSTALLER) {
    $here = Split-Path $env:HQ_INSTALLER
    if ((Test-Path (Join-Path $here 'hq')) -and ($here -ne $Target)) { $Old += $here }
}
$Old = $Old | Select-Object -Unique
$TargetDb = Join-Path $Target 'data\hq.sqlite3'
$Newest = $Old | Where-Object { Test-Path (Join-Path $_ 'data\hq.sqlite3') } |
    Sort-Object { (Get-Item (Join-Path $_ 'data\hq.sqlite3')).LastWriteTime } -Descending | Select-Object -First 1
if ($Newest -and (-not (Test-Path $TargetDb) -or
        (Get-Item (Join-Path $Newest 'data\hq.sqlite3')).LastWriteTime -gt (Get-Item $TargetDb).LastWriteTime)) {
    Say "Bringing your clips, chats and history over from $Newest"
    if (Test-Path (Join-Path $Target 'data')) {
        Rename-Item (Join-Path $Target 'data') "data-before-move-$(Get-Date -Format yyyyMMdd-HHmmss)"
    }
    Copy-Item (Join-Path $Newest 'data') (Join-Path $Target 'data') -Recurse
}
foreach ($dir in @($Newest) + ($Old | Where-Object { $_ -ne $Newest })) {
    if (-not $dir) { continue }
    $envFile = Join-Path $dir '.env'
    if ((Test-Path $envFile) -and -not (Test-Path (Join-Path $Target '.env'))) {
        Say "Bringing your keys (.env) over from $dir"
        Copy-Item $envFile (Join-Path $Target '.env')
    }
    $secrets = Join-Path $dir 'config\secrets'
    if (Test-Path $secrets) {
        New-Item -ItemType Directory -Force (Join-Path $Target 'config\secrets') | Out-Null
        Get-ChildItem $secrets -File | Where-Object { -not (Test-Path (Join-Path $Target "config\secrets\$($_.Name)")) } |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $Target "config\secrets\$($_.Name)") }
    }
    # Config files you edited (not ones that just match an older version of HQ) come along too.
    Get-ChildItem (Join-Path $dir 'config') -File -ErrorAction SilentlyContinue | ForEach-Object {
        $file = $_
        $rel = "config/$($file.Name)"
        $mine = (git -C $Target hash-object "--path=$rel" $file.FullName).Trim()
        $known = git -C $Target log --all --format= --raw --no-abbrev -- $rel | ForEach-Object { ($_ -split '\s+')[3] }
        $now = if (Test-Path (Join-Path $Target $rel)) { (git -C $Target hash-object (Join-Path $Target $rel)).Trim() } else { '' }
        if ($mine -ne $now -and $known -notcontains $mine) {
            Say "Keeping your edited $rel from $dir"
            Copy-Item $file.FullName (Join-Path $Target $rel) -Force
        }
    }
}

# 5. HQ's own Python, with everything it needs.
Set-Location $Target
$VenvPy = Join-Path $Target '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    Say 'Setting up HQ''s Python'
    & $Python -m venv .venv
}
Say 'Installing what HQ needs (first time takes a few minutes)'
& $VenvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $VenvPy -m pip install -r requirements.txt --disable-pip-version-check | Where-Object { $_ -notlike 'Requirement already satisfied*' } | Out-Host
if ($LASTEXITCODE) { Fail 'Installing HQ''s packages failed. Run this again; if it keeps failing, send Claude a photo of this window.' }

# 6. Desktop icon, then open HQ.
Say 'Putting the Agent HQ icon on your Desktop'
& $VenvPy -m hq install-shortcut | Out-Host
Say 'Opening Agent HQ'
Start-Process (Join-Path $Target '.venv\Scripts\pythonw.exe') -ArgumentList '-m', 'hq', 'app', '--no-update' -WorkingDirectory $Target

Write-Host "`nAll done. From now on just double-click the Agent HQ icon on your Desktop." -ForegroundColor Green
Write-Host 'HQ keeps itself up to date, and your keys live on its Settings page.'
if ($Old) { Write-Host "Your old folders were left where they were. Once HQ looks right you can delete them:`n  $($Old -join "`n  ")" }
