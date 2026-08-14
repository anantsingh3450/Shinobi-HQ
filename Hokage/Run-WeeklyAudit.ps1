# Hokage weekly self-audit.
#
# Runs every entry module against every asset, writes a dated snapshot to the
# brain, diffs it against the previous week, and Telegrams ONLY what changed.
#
# This is the job that stops Claude being Hokage's evolution loop. The
# ImprovementBot has written 430 autopsies and applied zero improvements; the
# labs measure correctly but had to be fired by hand. This fires them.
#
# Scheduled for SATURDAY MORNING on purpose:
#   - markets are closed, so it competes with nothing
#   - the week's tape is complete, so the measurement window is whole
#   - the commander gets the report with a weekend to think about it before
#     any lineup change lands on Monday
#
# It needs a LIVE broker session for candle history. If the token has expired
# the run exits non-zero without writing a snapshot rather than recording an
# empty week — a gap in the series is honest, a fabricated row is not.

$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Python = 'C:\Users\anant\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Log = Join-Path $Root "logs\weekly_audit_$Stamp.log"

Push-Location $Root
try {
    # A dead token produces no candles, which would look like "every module
    # lost its edge". Check first and bail loudly instead.
    $state = & $Python (Join-Path $Root 'tools\check_broker_session.py') 2>$null
    if ($LASTEXITCODE -ne 0) {
        "Weekly audit SKIPPED: broker session is $state. Log in, then re-run." |
            Tee-Object -FilePath $Log
        exit 1
    }

    & $Python (Join-Path $Root 'tools\research\weekly_audit.py') --telegram 2>&1 |
        Tee-Object -FilePath $Log
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
