# Stop Hokage on purpose, and tell the liveness watch that you meant it.
#
# 2026-08-28 21:22: the commander said "stop hokage for today". Three checks
# later, at 22:00, the liveness probe would have Telegrammed him "HOKAGE IS NOT
# TRADING" about a stop he had just ordered. An alarm that fires for a decision
# already made is how the alarm that matters gets ignored — the same reasoning
# that put CRUDEOIL in PARKED_ASSETS rather than letting the orphan audit
# scream on every boot.
#
# The marker is cleared automatically the moment Hokage is seen up again, so a
# deliberate stop can never leave the alarm permanently deaf.
#
# It does NOT flatten positions. Hokage should be flat before he is stopped;
# check the dashboard first, because a stopped Hokage stops managing exits.

param(
    [string]$Reason = "stopped on purpose"
)

$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Python = 'C:\Users\anant\AppData\Local\Python\pythoncore-3.14-64\python.exe'

Push-Location $Root
try {
    & $Python (Join-Path $Root 'tools\ops\liveness_probe.py') --stopped-on-purpose $Reason

    $procs = Get-Process python* -ErrorAction SilentlyContinue
    if (-not $procs) {
        Write-Host "  Hokage was not running." -ForegroundColor Yellow
        exit 0
    }
    foreach ($p in $procs) {
        Write-Host "  stopping PID $($p.Id)" -ForegroundColor Cyan
        Stop-Process -Id $p.Id -Force
    }
    Start-Sleep -Seconds 3
    if (Get-Process python* -ErrorAction SilentlyContinue) {
        Write-Host "  WARNING: a python process is still alive." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Hokage stopped at $(Get-Date -Format 'HH:mm:ss')." -ForegroundColor Green
    exit 0
} finally {
    Pop-Location
}
