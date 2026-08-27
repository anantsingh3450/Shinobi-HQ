# Is Hokage actually trading? Asked from OUTSIDE Hokage.
#
# 2026-08-27 07:44: he had been dead since 04:14 and his last line was
# "Overall Health Score: 100.0/100." A watchdog living inside the process
# cannot report that the process is gone. This one runs on the scheduler, so it
# survives him by construction.
#
# It checks BOTH ways of not-trading: the dashboard not answering (dead
# process) and an expired Zerodha session (living process, blind). The second
# is the more dangerous one — every dashboard stays green.
#
# All of the judgement lives in tools/ops/liveness_probe.py so it can be tested
# without a market, a broker, or a dead Hokage. This file only fires it.
#
# It reports and never restarts: reviving a crash-looping bot turns one outage
# into a hundred, and a bot the commander stopped on purpose must stay stopped.

$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Python = 'C:\Users\anant\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Root 'logs\liveness.log'

Push-Location $Root
try {
    $line = & $Python (Join-Path $Root 'tools\ops\liveness_probe.py') 2>&1
    # Out-File -Encoding utf8, NOT Tee-Object: Windows PowerShell 5.1's
    # Tee-Object has no -Encoding switch and writes UTF-16LE, which produced a
    # liveness.log full of NUL-separated characters on 2026-08-27 — unreadable
    # by grep and by any parser that reads it later. Same class of fault as the
    # BOM that broke the profile JSON readers.
    $line | Write-Output
    $line | Out-File -FilePath $Log -Append -Encoding utf8
    exit 0
} finally {
    Pop-Location
}
