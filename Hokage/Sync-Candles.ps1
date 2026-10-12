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
        # Out-File -Encoding utf8: PS 5.1's Tee-Object writes UTF-16LE.
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm') candle sync SKIPPED: session is $state" |
            Out-File -FilePath $Log -Append -Encoding utf8
        exit 1
    }

    & $Python (Join-Path $Root 'tools\research\candle_archive.py') sync 2>&1 |
        Out-File -FilePath $Log -Append -Encoding utf8
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm') candle sync FAILED: exit $code" |
            Out-File -FilePath $Log -Append -Encoding utf8
    }
    exit $code
} catch {
    # Without this a throw left no line at all and the archive simply stopped
    # growing, which is the quietest way for Hokage to stop learning.
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm') candle sync FAILED before completion: $($_.Exception.Message)" |
        Out-File -FilePath $Log -Append -Encoding utf8
    exit 1
} finally {
    Pop-Location
}
