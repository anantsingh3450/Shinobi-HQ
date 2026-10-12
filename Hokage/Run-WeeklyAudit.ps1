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

# 2026-10-09 23:45 this exited 1 and left NOTHING BEHIND -- no log file, no
# Telegram, no trace. By Monday the only evidence it had run at all was
# LastTaskResult=1 in the task scheduler, and the cause is still unknown
# because there was nothing to read. A job that fails silently is bad; one
# that fails without evidence cannot be diagnosed afterwards either.
#
# Everything below is now wrapped so ANY failure -- including one thrown by
# ErrorActionPreference='Stop' before the audit even starts -- writes a dated
# log saying what happened. tools/ops/job_watch.py is the alarm; this is the
# postmortem.
$ErrorActionPreference = 'Stop'

$Root = 'C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage'
$Python = 'C:\Users\anant\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Log = Join-Path $Root "logs\weekly_audit_$Stamp.log"

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'logs') | Out-Null

function Write-AuditLog {
    param([string]$Text)
    # Out-File -Encoding utf8, never Tee-Object: PS 5.1's Tee writes UTF-16LE,
    # which is why the one surviving older log reads as "W e e k l y".
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Text" |
        Out-File -FilePath $Log -Append -Encoding utf8
}

Push-Location $Root
try {
    # A dead token produces no candles, which would look like "every module
    # lost its edge". Check first and bail loudly instead.
    $state = & $Python (Join-Path $Root 'tools\check_broker_session.py') 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-AuditLog "SKIPPED: broker session is $state. Log in, then re-run."
        Write-Host "Weekly audit SKIPPED: broker session is $state."
        exit 1
    }

    Write-AuditLog "START: running weekly_audit.py --telegram"
    & $Python (Join-Path $Root 'tools\research\weekly_audit.py') --telegram 2>&1 |
        Out-File -FilePath $Log -Append -Encoding utf8
    $code = $LASTEXITCODE
    Write-AuditLog "END: weekly_audit.py exited $code"
    exit $code
} catch {
    # The branch that was missing. Any throw used to leave no file at all.
    Write-AuditLog "FAILED before completion: $($_.Exception.Message)"
    Write-AuditLog "  at: $($_.InvocationInfo.PositionMessage)"
    Write-Host "Weekly audit FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
