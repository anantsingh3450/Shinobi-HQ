# Keep every candle Hokage has ever been able to see.
#
# 2026-08-27: the gas front-month contract rolled overnight and three months of
# training tape ceased to exist. A futures contract carries no history from
# before it listed, and an expired one is delisted along with its token, so what
# Kite will serve SHRINKS on every roll. RangeFade/NATURALGAS measured
# +2.35/+2.67 on 08-26 and +2.44/+1.08 on 08-27 — same code, same market, less
# evidence.
#
# For a system whose entire method is measurement, evidence that evaporates on a
# schedule is the deepest possible fault. This runs daily AFTER the MCX close so
# the session is complete, and from here the corpus only grows.
#
# It needs a live broker session. If the token has expired it exits non-zero
# without writing rather than recording a short day as a real one.

$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Python = 'C:\Users\anant\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Root 'logs\candle_sync.log'

Push-Location $Root
try {
    $state = & $Python (Join-Path $Root 'tools\check_broker_session.py') 2>$null
    if ($LASTEXITCODE -ne 0) {
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm') candle sync SKIPPED: session is $state" |
            Tee-Object -FilePath $Log -Append
        exit 1
    }

    & $Python (Join-Path $Root 'tools\research\candle_archive.py') sync 2>&1 |
        Tee-Object -FilePath $Log -Append
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
