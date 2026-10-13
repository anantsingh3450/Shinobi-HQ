# Which processes on this machine are Hokage?
#
# Dot-sourced by Start-Hokage.ps1 and Stop-Hokage.ps1. ONE definition, because
# two copies of "what counts as Hokage" drift, and the half that drifts is
# whichever one nobody ran that week.
#
# Both scripts used to say Get-Process python, which is every python on the
# machine: a candle sync mid-write, a sweep three hours into a run, a weekly
# audit, a lab, anything the commander happened to have open. "Stop hokage for
# today" would take all of them down with no mention that it had. A candle sync
# killed mid-write is how the archive loses a day that nobody notices until a
# lab answers n=3 - and the archive is the only evidence that can un-park an
# asset.
#
# TWO INDEPENDENT IDENTIFICATIONS, tried in order. Win32_Process.CommandLine
# needs privileges a script may not have and comes back empty when it lacks
# them - empty would read as "Hokage is not running" and leave a stray behind.
# So fall back to whoever actually holds the dashboard port.
#
# Failing to find him is the safer failure: a surviving stray blocks port 5000
# and the launcher says so out loud. Killing everything is silent.

function Get-HokageProcess {
    param([int]$DashboardPort = 5000)

    $byCmd = @(
        Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -match 'start\.py' } |
            ForEach-Object { $_.ProcessId }
    )
    if ($byCmd.Count -gt 0) { return @($byCmd | Sort-Object -Unique) }

    $owners = @(
        Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess }
    )
    return @($owners | Sort-Object -Unique)
}
