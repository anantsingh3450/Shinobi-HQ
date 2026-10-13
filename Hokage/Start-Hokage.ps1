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
# How long to let the running process pick up a new token on its own before
# resorting to a restart. The callback refreshes it in the same request, so
# this is normally satisfied on the first poll; the window only has to be wide
# enough for one slow Kite round trip.
$HealGraceSeconds = 45

# Shared with Stop-Hokage.ps1 so that "what counts as Hokage" has exactly one
# definition. Loud if it is missing, which is correct: without it this script
# cannot tell Hokage apart from any other python and must not guess.
. (Join-Path $Root 'tools\ops\HokageProcess.ps1')
function Get-DeliberateStop {
    # The reason recorded by Stop-Hokage.ps1, or $null.
    #
    # ASKED, NOT COMPUTED. This used to build the path itself from a hardcoded
    # $Root\hokage_brain. The brain is relocatable via HOKAGE_BRAIN_ROOT (it
    # moved off OneDrive on 2026-10-09), and a launcher that looks in the old
    # directory while Stop-Hokage.ps1 writes to the new one is a guard that has
    # silently stopped guarding. liveness_probe.py owns the path; ask it.
    #
    # A corrupt or missing marker counts as absent, matching the probe: a
    # launcher that refuses to run because of its own malformed state file is
    # worse than no guard.
    Push-Location $Root
    try {
        $out = & $Python (Join-Path $Root 'tools\ops\liveness_probe.py') --check-stopped 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        if ($out) { return ($out | Select-Object -Last 1).Trim() }
        return 'stopped on purpose'
    } catch {
        return $null
    } finally {
        Pop-Location
    }
}

function Clear-DeliberateStop {
    # Clearing it needs the path, so ask Python for that too rather than
    # rebuilding it here.
    Push-Location $Root
    try {
        & $Python -c @'
import sys
sys.path.insert(0, "tools/ops")
from liveness_probe import STOP_MARKER
STOP_MARKER.unlink(missing_ok=True)
'@ 2>$null
    } catch {
    } finally {
        Pop-Location
    }
}

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

function Test-ProcessSeesMarket {
    # Does the RUNNING process see the market?
    #
    # Get-BrokerState below answers a different question: is the token on disk
    # valid? A fresh token is valid the instant it is written and says nothing
    # about whether any running object has read it - that gap is the whole
    # reason this launcher restarts anything.
    #
    # $false on any doubt. This gates a restart, and an unnecessary restart is
    # recoverable while skipping a necessary one leaves Hokage blind all day.
    try {
        $r = Invoke-WebRequest -Uri "$Url/api/v1/broker/zerodha/status" -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -ne 200) { return $false }
        $j = $r.Content | ConvertFrom-Json
        return ($j.process_sees_market -eq $true)
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
    $ids = @(Get-HokageProcess)
    foreach ($id in $ids) {
        try { Stop-Process -Id $id -Force -ErrorAction Stop } catch { }
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
    # A DELIBERATE STOP MEANS STOPPED.
    #
    # 2026-10-09 18:36: Hokage was stopped on purpose to prune a 1.5 GB audit
    # table. Forty-three seconds later this script relaunched him, because the
    # weekday task repeats every 15 minutes and the logon trigger fires two
    # minutes after sign-in. The liveness probe then saw him up and cleared the
    # marker, so the restart left no trace at all.
    #
    # The two halves made each other worse: Stop-Hokage.ps1 writes the marker
    # to MUTE the "HOKAGE IS NOT TRADING" alarm, so the one thing that would
    # have reported the unwanted restart had been silenced by the stop itself.
    # The commander believes Hokage is down; Hokage is up and writing to the
    # files being edited. That is how the CRUDEOIL park got silently reverted
    # on 2026-08-26.
    #
    # An unattended trigger therefore never overrides a human decision. Only a
    # human does, by running this script interactively.
    $stopReason = Get-DeliberateStop
    if ($stopReason) {
        Write-Step "Hokage was stopped on purpose - NOT starting." 'Yellow'
        Write-Step "Reason: $stopReason" 'DarkGray'
        Write-Step 'Run this shortcut yourself to start him again.' 'DarkGray'
        exit 0
    }
    if (Test-Dashboard) {
        Write-Step 'Hokage already running; nothing to do.' 'Green'
        exit 0
    }
    if (@(Get-HokageProcess).Count -gt 0) {
        Write-Step 'Stray Hokage process with no dashboard - clearing.' 'Yellow'
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

# --- 0. a human overrides his own earlier stop, but is told about it ---------
# Running this script by hand IS the intent to start, so the marker is cleared
# rather than obeyed. It is still worth saying out loud: the reason shown here
# may be work that is only half finished.
$stopReason = Get-DeliberateStop
if ($stopReason) {
    Write-Step 'Hokage was stopped on purpose:' 'Yellow'
    Write-Step "  $stopReason" 'DarkGray'
    Write-Step 'Starting anyway - you asked for it directly.' 'Cyan'
    Write-Host ''
    Clear-DeliberateStop
}

# --- 1. make sure exactly one Hokage is serving -----------------------------
if (Test-Dashboard) {
    Write-Step 'Hokage is already running.' 'Green'
} else {
    if (@(Get-HokageProcess).Count -gt 0) {
        Write-Step 'Found a Hokage process but no dashboard - clearing it first.' 'Yellow'
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

# --- 5. THE RESTART IS A FALLBACK, NOT A STEP -------------------------------
# This used to restart unconditionally, and on 2026-10-13 06:22 that restart
# killed the very request that had just logged in. The dashboard callback
# writes the token, refreshes the live session in place and THEN answers the
# browser; this loop was polling for the token and shot the process in the
# 0.3s between those two. The commander got "Authentication failed" in red for
# a login that had entirely succeeded, and a Hokage that had been online for
# eleven seconds.
#
# Hokage heals himself now - the callback calls refresh_broker_session() and
# his own feed probe retries. So ask him, and only restart if he is still
# blind. The restart stays because the self-heal is a code path like any
# other: if it ever stops working, a blind Hokage all day is the cost.
$grace = (Get-Date).AddSeconds($HealGraceSeconds)
$healed = $false
while ((Get-Date) -lt $grace) {
    if (Test-ProcessSeesMarket) { $healed = $true; break }
    Start-Sleep -Seconds 3
}

if ($healed) {
    Write-Step 'Hokage picked the new token up himself - no restart needed.' 'Green'
} else {
    Write-Step "Still blind ${HealGraceSeconds}s after the login - restarting." 'Yellow'
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
}

Write-Host ''
Write-Step 'Hokage is online and connected. Hunting.' 'Green'
Write-Host ''
Write-Step 'Keep this laptop plugged in - a sleeping host suspends every stop.' 'DarkGray'
Write-Host ''
Start-Sleep -Seconds 8
exit 0
