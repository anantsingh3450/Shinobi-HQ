# Keep every candle Hokage has ever been able to see, and the India VIX
# and the option chain alongside them.
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

    # India VIX, the other half of the same corpus. The candle archive holds
    # what the index DID; this holds what the market CHARGED for it, and the
    # IV premium guard - the gate that can refuse every signal of the day -
    # reads nothing else. Hokage writes it through himself whenever the guard
    # runs, so on a normal day this adds nothing; it covers the days he is
    # down. Its exit code is kept SEPARATE: a failed VIX top-up must not be
    # reported as a failed candle sync, and a failed candle sync must not
    # hide a VIX archive that is quietly going stale.
    & $Python (Join-Path $Root 'tools\ops\archive_vix.py') 2>&1 |
        Out-File -FilePath $Log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm') VIX archive FAILED: exit $LASTEXITCODE" |
            Out-File -FilePath $Log -Append -Encoding utf8
    }

    # The option chain around the money. A spread CANNOT be backtested:
    # an option carries history only from its listing and an expired one
    # is delisted with its token, so the premium history of the past does
    # not exist and never will. The only corpus that can exist is the one
    # that starts being written down - the candle lesson and the VIX
    # lesson, for a third time. This runs after 15:30 IST so the rows are
    # closes rather than intraday marks. Its exit code is kept separate
    # so one archive failing is never reported as another.
    & $Python (Join-Path $Root 'tools\ops\archive_options.py') 2>&1 |
        Out-File -FilePath $Log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm') option chain archive FAILED: exit $LASTEXITCODE" |
            Out-File -FilePath $Log -Append -Encoding utf8
    }
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
