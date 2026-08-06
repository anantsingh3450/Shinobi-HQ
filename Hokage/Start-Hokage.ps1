# Hokage launcher.
#
# Double-click the desktop shortcut and this does the right thing in every case:
#   - not running          -> start it, then open the dashboard
#   - running + logged in  -> just open the live dashboard
#   - running + token dead -> open the dashboard so you can log in, wait for the
#                             login to land, then RESTART so the new token is
#                             actually picked up
#
# That last step is not optional and is the whole reason this script exists.
# KiteConnectionManager reads the access token once, inside connect(). If Hokage
# boots with a dead token, connect() fails, the client is left null, and every
# later call raises "Venue is not connected." forever. Logging in afterwards
# updates the .env and the vault but NOT the running process, so Hokage stays
# blind while looking perfectly healthy. On 2026-08-05 that cost a restart the
# commander had no way of knowing he needed. Order matters: log in, THEN restart.
#
# -Unattended is for the weekday scheduled task: ensure exactly one Hokage is
# running, then exit. No browser, no waiting for a human. Safe now ONLY because
# the reconnect fix shipped the same day — a process that boots on the expired
# overnight token picks the new one up within a minute of the commander logging
# in, without a restart. Before that fix an unattended start would have produced
# a bot that looked healthy and was blind all day.

param(
    [switch]$Unattended
)

$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Python = 'C:\Users\anant\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Url = 'http://127.0.0.1:5000'
$LoginWaitMinutes = 15

function Write-Step {
    param([string]$Text, [string]$Colour = 'Gray')
    Write-Host "  $Text" -ForegroundColor $Colour
}

function Test-Dashboard {
    # The HTTP probe is the honest test: it proves the app is SERVING, not
    # merely that some python.exe exists.
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Get-BrokerState {
    # Returns LIVE / EXPIRED / UNREACHABLE / NO_CREDENTIALS
    Push-Location $Root
    try {
        $out = & $Python (Join-Path $Root 'tools\check_broker_session.py') 2>$null
        if ($LASTEXITCODE -eq 0) { return 'LIVE' }
        if ($out) { return ($out | Select-Object -Last 1).Trim() }
        return 'UNREACHABLE'
    } catch {
        return 'UNREACHABLE'
    } finally {
        Pop-Location
    }
}

function Stop-Hokage {
    # Two instances would both trade the same paper account, so never leave a
    # stray behind.
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch { }
    }
    Start-Sleep -Seconds 4
}

function Start-Hokage {
    $stamp = [int][double]::Parse((Get-Date -UFormat %s))
    $out = Join-Path $Root "logs\hokage_$stamp.log"
    $err = Join-Path $Root "logs\hokage_${stamp}_err.log"
    $proc = Start-Process -FilePath $Python -ArgumentList 'start.py' `
        -WorkingDirectory $Root -RedirectStandardOutput $out `
        -RedirectStandardError $err -PassThru -WindowStyle Hidden
    Write-Step "Started Hokage (PID $($proc.Id)). Log: $err" 'DarkGray'
    return $proc
}

function Wait-Dashboard {
    param([int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Dashboard) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

if ($Unattended) {
    if (Test-Dashboard) {
        Write-Step 'Hokage already running; nothing to do.' 'Green'
        exit 0
    }
    if (Get-Process python -ErrorAction SilentlyContinue) {
        Write-Step 'Stray python process with no dashboard - clearing.' 'Yellow'
        Stop-Hokage
    }
    [void](Start-Hokage)
    if (Wait-Dashboard) {
        $state = Get-BrokerState
        Write-Step "Hokage up. Broker session: $state" 'Green'
        if ($state -ne 'LIVE') {
            # Deliberately NOT an error. The commander logs in when he logs in,
            # and the running process now picks the token up on its own.
            Write-Step 'Awaiting login; the feed will heal itself once it lands.' 'DarkGray'
        }
        exit 0
    }
    Write-Step 'Hokage failed to come up. Check the newest *_err.log.' 'Red'
    exit 1
}

Clear-Host
Write-Host ''
Write-Host '  HOKAGE' -ForegroundColor Green
Write-Host '  ------' -ForegroundColor DarkGray
Write-Host ''

# --- 1. make sure exactly one Hokage is serving -----------------------------
if (Test-Dashboard) {
    Write-Step 'Hokage is already running.' 'Green'
} else {
    if (Get-Process python -ErrorAction SilentlyContinue) {
        Write-Step 'Found a python process but no dashboard - clearing it first.' 'Yellow'
        Stop-Hokage
    }
    Write-Step 'Starting Hokage...' 'Cyan'
    [void](Start-Hokage)
    if (-not (Wait-Dashboard)) {
        Write-Host ''
        Write-Step 'Hokage did not come up within 2 minutes.' 'Red'
        Write-Step "Check the newest *_err.log in $Root\logs" 'Red'
        Write-Host ''
        Read-Host '  Press Enter to close'
        exit 1
    }
    Write-Step 'Hokage is up.' 'Green'
}

# --- 2. open the dashboard --------------------------------------------------
Write-Step "Opening $Url" 'Cyan'
Start-Process $Url

# --- 3. is he actually able to see the market? ------------------------------
$state = Get-BrokerState
if ($state -eq 'LIVE') {
    Write-Host ''
    Write-Step 'Zerodha session is live. Hokage can see the market.' 'Green'
    Write-Host ''
    Write-Step 'Keep this laptop plugged in - a sleeping host suspends every stop.' 'DarkGray'
    Write-Host ''
    Start-Sleep -Seconds 6
    exit 0
}

if ($state -eq 'UNREACHABLE') {
    Write-Host ''
    Write-Step 'Cannot reach Zerodha - check your internet, not your login.' 'Yellow'
    Write-Host ''
    Read-Host '  Press Enter to close'
    exit 1
}

# --- 4. token is dead: wait for the login, then restart ---------------------
Write-Host ''
Write-Step 'Zerodha session has EXPIRED. Hokage is blind until you log in.' 'Yellow'
Write-Host ''
Write-Step 'In the dashboard that just opened: click Login to Zerodha.' 'White'
Write-Step 'Leave this window open - it will finish the job automatically.' 'White'
Write-Host ''
Write-Step "Waiting for your login (up to $LoginWaitMinutes minutes)..." 'DarkGray'

$deadline = (Get-Date).AddMinutes($LoginWaitMinutes)
$loggedIn = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if ((Get-BrokerState) -eq 'LIVE') { $loggedIn = $true; break }
}

if (-not $loggedIn) {
    Write-Host ''
    Write-Step 'No login detected. Hokage is running but cannot trade.' 'Red'
    Write-Step 'Log in, then run this shortcut again.' 'Red'
    Write-Host ''
    Read-Host '  Press Enter to close'
    exit 1
}

Write-Host ''
Write-Step 'Login detected.' 'Green'
Write-Step 'Restarting so Hokage picks up the new token (it only reads it at boot)...' 'Cyan'
Stop-Hokage
[void](Start-Hokage)
if (-not (Wait-Dashboard)) {
    Write-Host ''
    Write-Step 'Restart failed to come up. Check the newest *_err.log.' 'Red'
    Write-Host ''
    Read-Host '  Press Enter to close'
    exit 1
}

Start-Process $Url
Write-Host ''
Write-Step 'Hokage is online and connected. Hunting.' 'Green'
Write-Host ''
Write-Step 'Keep this laptop plugged in - a sleeping host suspends every stop.' 'DarkGray'
Write-Host ''
Start-Sleep -Seconds 8
exit 0
