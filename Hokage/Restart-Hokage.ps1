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
Say ''
Say '5. is it the new code?' 'Cyan'
$calendar = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Path $LogFile) {
        $calendar = Get-Content $LogFile -Tail 400 |
            Select-String -SimpleMatch 'Session calendar:' |
            Select-Object -Last 1
    }
    if ($calendar) { break }
}
if ($calendar) {
    Say "  $($calendar.Line.Trim())" 'Green'
} else {
    Say '  No "Session calendar:" line yet. Either the code is older than' 'Yellow'
    Say '  2026-11-08 or the loop has not reached it. Check:' 'Yellow'
    Say "    git -C `"$Root`" log --oneline -1" 'Yellow'
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
