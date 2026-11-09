# Restart Hokage in one command, and PROVE it took.
#
# 2026-11-08. The commander was handed the same three commands twice and said
# both times that he had restarted. Both times the process was still the one
# that booted at 2026-11-07 13:16:38, the scheduled task's LastRunTime had not
# moved, and the broker was still disconnected - on a Sunday with a live
# Muhurat session at 14:20 and a calendar fix sitting unloaded on disk.
#
# Three separate commands pasted by hand is three places to lose one, and
# nothing in the sequence ever said "this worked". So: one command, and it
# does not finish quiet. It checks that the PID actually CHANGED, that the new
# process logged a line only the new code can write, and it prints the broker
# state so the next step is obvious.
#
# It does NOT flatten positions and it does NOT log in. Hokage should be flat
# before a stop - a stopped Hokage stops managing exits - and the login stays
# the commander's own, through the link Telegram sends him.

$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Marker = 'C:\Hokage\hokage_brain\state\stopped_deliberately.json'
$LogFile = 'C:\Hokage\hokage_brain\logs\hokage.log'
$TaskName = 'Hokage Morning Start'
$Reason = 'restart to load the session calendar'

. (Join-Path $Root 'tools\ops\HokageProcess.ps1')

function Say([string]$Text, [string]$Colour = 'Gray') {
    Write-Host $Text -ForegroundColor $Colour
}

Say ''
Say '=== RESTART HOKAGE ===' 'Cyan'

# ---------------------------------------------------------------- before
$before = @(Get-HokageProcess)
if ($before.Count -eq 0) {
    Say '  before: Hokage was not running.' 'Yellow'
} else {
    foreach ($id in $before) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
        $born = if ($p) { $p.CreationDate } else { 'unknown' }
        Say "  before: PID $id, booted $born"
    }
}

# ---------------------------------------------------------------- 1. stop
Say ''
Say '1. stopping' 'Cyan'
& (Join-Path $Root 'Stop-Hokage.ps1') -Reason $Reason
if ($LASTEXITCODE -ne 0) {
    Say '  STOP FAILED - a Hokage process is still alive. Nothing else was done.' 'Red'
    Say '  Find it with:  Get-CimInstance Win32_Process -Filter "Name=''python.exe''"' 'Red'
    exit 1
}

# ------------------------------------------------- 2. clear the stop marker
Say ''
Say '2. clearing the deliberate-stop marker' 'Cyan'
if (Test-Path $Marker) {
    Remove-Item $Marker -Force
    Say '  cleared.' 'Green'
} else {
    Say '  nothing to clear.' 'Gray'
}

# --------------------------------------------------------------- 3. start
Say ''
Say '3. starting' 'Cyan'
$taskBefore = (Get-ScheduledTaskInfo -TaskName $TaskName).LastRunTime
Start-ScheduledTask -TaskName $TaskName

# ------------------------------------------------------------- 4. verify
Say ''
Say '4. waiting for him to come up' 'Cyan'
$newPid = $null
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $now = @(Get-HokageProcess | Where-Object { $before -notcontains $_ })
    if ($now.Count -gt 0) { $newPid = $now[0]; break }
}

if (-not $newPid) {
    Say '  HE DID NOT COME UP within 120s, and the PID never changed.' 'Red'
    $taskAfter = (Get-ScheduledTaskInfo -TaskName $TaskName)
    Say "  task LastRunTime: $($taskAfter.LastRunTime)   result: $($taskAfter.LastTaskResult)" 'Red'
    if ($taskAfter.LastRunTime -eq $taskBefore) {
        Say '  The task never ran. That is the thing to fix, not Hokage.' 'Red'
    }
    exit 1
}

$p = Get-CimInstance Win32_Process -Filter "ProcessId = $newPid"
Say "  UP: PID $newPid, booted $($p.CreationDate)" 'Green'

# A line only the new code can write. A new PID alone proves a process
# started; it does not prove WHICH code it is running.
#
# 2026-11-09: this step printed a GREEN "Session calendar: normal session"
# stamped 18:59:30 for a process that booted at 22:40:46 - the previous
# boot's line, still sitting in the tail. It matched the last occurrence and
# never looked at the clock, so the one check written to prove WHICH code is
# running was satisfied by code that had already been replaced. Stale
# evidence reads exactly like fresh evidence. Every line below must now be
# timestamped AT OR AFTER the new process started.
Say ''
Say '5. is it the new code?' 'Cyan'

function Get-FreshLines([string]$Needle, [datetime]$NotBefore) {
    if (-not (Test-Path $LogFile)) { return @() }
    Get-Content $LogFile -Tail 800 |
        Select-String -SimpleMatch $Needle |
        Where-Object {
            $stamp = $null
            if ($_.Line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
                $stamp = [datetime]::ParseExact($Matches[1],
                    'yyyy-MM-dd HH:mm:ss', $null)
            }
            $stamp -ne $null -and $stamp -ge $NotBefore
        }
}

# One second of slack: the log stamp and the process creation time come from
# different clocks and the version line is written within a second of boot.
$bootedAt = ([datetime]$p.CreationDate).AddSeconds(-1)
$calendar = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $calendar = @(Get-FreshLines 'Session calendar:' $bootedAt) |
        Select-Object -Last 1
    if ($calendar) { break }
}
if ($calendar) {
    Say "  $($calendar.Line.Trim())" 'Green'
    $version = @(Get-FreshLines 'Code version:' $bootedAt) | Select-Object -Last 1
    if ($version) { Say "  $($version.Line.Trim())" 'Green' }
} else {
    Say "  No `"Session calendar:`" line stamped at or after $($p.CreationDate)." 'Red'
    Say '  An OLD line may be in the log; that is not evidence. Either the' 'Red'
    Say '  loop has not reached it yet or the new process failed early.' 'Red'
    Say "    git -C `"$Root`" log --oneline -1" 'Yellow'
}

# -------------------------------------------- 5b. did the risk rails load?
# A rail that cannot measure fails CLOSED, which is the right direction and
# completely silent from outside: on 2026-11-09 the account exposure rail
# raised NameError on its first run and blocked every entry for the rest of
# the session, while the restart reported success. Fail-closed hides a bug
# exactly as well as it stops a trade, so the restart now reads the rail.
Say ''
Say '5b. risk rails' 'Cyan'
$rail = @(Get-FreshLines 'account exposure rail:' $bootedAt) | Select-Object -Last 1
if ($rail) {
    Say "  $($rail.Line.Trim())" 'Green'
} else {
    Say '  No account-exposure rail line from this boot.' 'Yellow'
}
$railBroken = @(Get-FreshLines 'could not be measured' $bootedAt)
if ($railBroken.Count -gt 0) {
    Say '  A RISK RAIL CANNOT MEASURE, SO IT IS BLOCKING EVERY TRADE:' 'Red'
    foreach ($line in $railBroken) { Say "    $($line.Line.Trim())" 'Red' }
    Say '  He is up but he will not enter anything. Report this.' 'Red'
}

# ------------------------------------------------------------- 6. broker
Say ''
Say '6. broker' 'Cyan'
try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/v1/broker/zerodha/status' -TimeoutSec 15
    if ($status.connected) {
        Say '  CONNECTED. Nothing further needed.' 'Green'
    } else {
        Say "  NOT connected: $($status.message)" 'Yellow'
        Say '  Send /login to the Telegram bot, or open:' 'Yellow'
        Say '    http://127.0.0.1:5000/api/v1/broker/zerodha/login' 'Yellow'
    }
} catch {
    Say "  Dashboard did not answer yet: $($_.Exception.Message)" 'Yellow'
    Say '  Give it a minute, then re-check the URL above.' 'Yellow'
}

Say ''
Say '=== DONE ===' 'Cyan'
Say ''
exit 0
