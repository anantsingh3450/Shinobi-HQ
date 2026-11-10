<#
    Hokage could only be STARTED on a weekday morning.

WHAT WAS WRONG
    "Hokage Morning Start" carried a WEEKLY trigger, DaysOfWeek = Mon..Fri,
    at 08:45 repeating every 15 minutes for 2 hours. So the only window in
    which anything would start him was 08:45-10:45, Monday to Friday.

    Two sessions are unreachable from that window:

      * A WEEKEND SPECIAL SESSION. 2026-11-08 was Diwali Muhurat trading on a
        SUNDAY, 14:20-15:40. It is the ONLY session missed since the October
        restart - 22 of 39 in the measured window, and 15 of the 16 misses are
        the September blackout. The calendar was taught about Muhurat on
        2026-11-07 and the senders were fixed; the SCHEDULER was not, so the
        one thing that could have put him there still could not fire.

      * ANY DEATH OUTSIDE THE WINDOW. He dies silently (2026-10-23: 3h39m
        while reporting "Health Score 100/100"). Die at 11:00 on a Monday and
        nothing retries until Tuesday 08:45. Die on a Friday evening and he is
        down until Monday - two MCX evening sessions and a whole weekend of
        recovery time lost to a trigger.

    The liveness probe runs DAILY, 09:00-23:30, so the alarm already covers
    hours the starter does not. An alarm nobody can act on until Monday is
    half a mechanism.

WHAT THIS CHANGES
    One trigger: daily at 08:00, repeating every 15 minutes for 15.5 hours
    (08:00 to 23:30), which spans the 09:15 equity open, a 14:20 Muhurat
    afternoon, and the 17:00 MCX evening on an equity holiday. The logon
    trigger is kept.

WHY A WIDE WINDOW IS SAFE, AND WHY NO CALENDAR CHECK IS NEEDED
    Start-Hokage.ps1 -Unattended is already idempotent and already refuses in
    every case that matters:

      * a deliberate stop marker means NOT STARTING (2026-10-09: a purposeful
        stop was undone 43 seconds later by this very task)
      * "Hokage already running; nothing to do" - the normal outcome of
        almost every one of these firings
      * a stray process with no dashboard is cleared first

    And there is deliberately no "is the market open today" gate here. Being
    up on a shut day costs nothing - every sender is calendar-gated and goes
    quiet - while being DOWN on a live day costs a session, which is the one
    thing this system cannot buy back. The asymmetry decides the direction.

WHY YOU HAVE TO RUN THIS AND I CANNOT
    Registering or editing a scheduled task is persistence, and my harness
    refuses it. That is the right rule and I am not going around it.

USAGE
    Right-click > Run with PowerShell, or:
        powershell -NoProfile -ExecutionPolicy Bypass -File tools\ops\Fix-StartTrigger.ps1

    It prints the triggers before and after. It changes nothing else: the
    action, the working directory and the principal are untouched.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "Hokage Morning Start",
    [switch]$WhatIfOnly
)

function Show-Triggers {
    param([string]$Label)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Host ""
    Write-Host "  $Label" -ForegroundColor Cyan
    foreach ($t in $task.Triggers) {
        $kind = $t.CimClass.CimClassName -replace 'MSFT_Task', '' -replace 'Trigger', ''
        $line = "    {0,-8} start={1}" -f $kind, $t.StartBoundary
        if ($t.PSObject.Properties.Name -contains 'DaysOfWeek' -and $t.DaysOfWeek) {
            $line += "  DaysOfWeek=$($t.DaysOfWeek)"
        }
        if ($t.Repetition -and $t.Repetition.Interval) {
            $line += "  every $($t.Repetition.Interval) for $($t.Repetition.Duration)"
        }
        Write-Host $line
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "    next run: $($info.NextRunTime)"
}

try {
    Show-Triggers "BEFORE"
} catch {
    Write-Host "  Could not read the task '$TaskName': $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if ($WhatIfOnly) {
    Write-Host ""
    Write-Host "  -WhatIfOnly: nothing changed." -ForegroundColor Yellow
    exit 0
}

# Daily, not weekly: a Sunday Muhurat session is a trading day.
$daily = New-ScheduledTaskTrigger -Daily -At 8:00am

# The repetition has to be borrowed from a -Once trigger; New-ScheduledTaskTrigger
# will not take -RepetitionInterval together with -Daily.
$pattern = New-ScheduledTaskTrigger -Once -At 8:00am `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Hours 15 -Minutes 30)
$daily.Repetition = $pattern.Repetition

# Kept: it is the fallback that would have started him on 2026-11-08 if he
# had signed in that afternoon.
$logon = New-ScheduledTaskTrigger -AtLogOn

try {
    Set-ScheduledTask -TaskName $TaskName -Trigger @($daily, $logon) | Out-Null
} catch {
    Write-Host ""
    Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  If this says access is denied, run PowerShell as Administrator." -ForegroundColor Yellow
    exit 1
}

Show-Triggers "AFTER"
Write-Host ""
Write-Host "  Done. He can now be started on any day, any hour from 08:00 to 23:30." -ForegroundColor Green
Write-Host "  Nothing starts a deliberately stopped Hokage - that marker still wins." -ForegroundColor DarkGray
exit 0
