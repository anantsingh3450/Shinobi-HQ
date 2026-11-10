"""The weekly audit reported FAILED on three of the last four Fridays, and
had succeeded every one of them.

WHAT HAPPENED. `Run-WeeklyAudit.ps1` sets `$ErrorActionPreference = 'Stop'`
and runs the audit as `& $Python ... 2>&1 | Out-File`. PowerShell 5.1 wraps
every stderr LINE from a native command in a NativeCommandError ErrorRecord
when `2>&1` is used, and under 'Stop' the first one becomes a TERMINATING
error. The audit writes warnings to stderr and recovers from them - the
Telegram Markdown rejection falls back to plain text and the message goes out
- so the wrapper threw into its catch and exited 1 AFTER the snapshot had
already been written:

    2026-10-16, 2026-10-30, 2026-11-06   "Telegram rejected Markdown"
    2026-10-23                           exited 0, the only clean Friday

THE DAMAGE IS NOT THE LOST `END` LINE. It is that LastTaskResult=1 became the
normal weekly reading, so a week the audit genuinely fails is indistinguishable
from a week it succeeded - the same defect as a watchdog heartbeat that always
says OK. job_watch alarms on snapshot age rather than on the exit code, which
is the only reason this never surfaced as a false alarm; it also means nothing
was reading the exit code at all.

A line on stderr is where a process talks. Its exit code is its verdict.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "Run-WeeklyAudit.ps1"
SOURCE = SCRIPT.read_text(encoding="utf-8")


def test_the_wrapper_exists_where_the_scheduled_task_points():
    assert SCRIPT.is_file()


def test_the_file_has_no_bom():
    """A BOM makes PowerShell's first token unparseable and is how three
    earlier scripts in this repo failed to run at all."""
    assert SCRIPT.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_the_strict_preference_is_still_the_default():
    """The fix must not turn error handling off for the whole script. A
    throw before the audit starts still has to write a dated log."""
    assert "$ErrorActionPreference = 'Stop'" in SOURCE


def test_the_audit_call_runs_under_continue_not_stop():
    """Scoped, so one recovered warning cannot terminate the run."""
    call = SOURCE[SOURCE.index("START: running weekly_audit.py"):]
    relaxed = call.index("$ErrorActionPreference = 'Continue'")
    invoked = call.index("weekly_audit.py') --telegram")
    assert relaxed < invoked


def test_the_preference_is_restored_afterwards():
    """A leaked 'Continue' would silently disarm every check after it."""
    call = SOURCE[SOURCE.index("START: running weekly_audit.py"):]
    assert "finally {" in call
    assert "$ErrorActionPreference = $previousPreference" in call


def test_the_restore_cannot_be_skipped_by_a_throw():
    """It has to be `finally`, not a line after the call."""
    call = SOURCE[SOURCE.index("START: running weekly_audit.py"):]
    restore = call.index("$ErrorActionPreference = $previousPreference")
    final = call.index("} finally {")
    assert final < restore


def test_the_exit_code_is_still_what_decides():
    """Relaxing the preference must not also stop the script reporting a
    real failure: the process's own code is the verdict."""
    call = SOURCE[SOURCE.index("START: running weekly_audit.py"):]
    assert "$code = $LASTEXITCODE" in call
    assert "exit $code" in call


def test_the_end_line_is_written_outside_the_relaxed_block():
    """The END line is the evidence the run completed. It was the thing the
    throw skipped, so it must sit after the finally rather than inside the
    try that the throw escaped."""
    call = SOURCE[SOURCE.index("START: running weekly_audit.py"):]
    end = call.index('Write-AuditLog "END: weekly_audit.py exited')
    final = call.index("} finally {")
    assert end > final


def test_the_session_check_still_bails_before_measuring():
    """A dead token produces no candles, which reads as "every module lost
    its edge". That guard must survive this change."""
    assert "check_broker_session.py" in SOURCE
    assert "SKIPPED: broker session is" in SOURCE


def test_the_catch_still_records_a_real_failure():
    assert "FAILED before completion:" in SOURCE
    assert re.search(r"}\s*catch\s*{", SOURCE)


# ======================== the header describes the trigger it actually has
def test_the_header_does_not_claim_a_saturday_run():
    """It said "Scheduled for SATURDAY MORNING on purpose" while the trigger
    was Friday 23:45, and Saturday is the one slot this job cannot use: the
    Zerodha token dies overnight and Morning Start does not run at weekends,
    so a Saturday run would sit waiting for a login nothing asked for."""
    header = SOURCE[:SOURCE.index("$ErrorActionPreference")]
    assert "Scheduled for FRIDAY 23:45" in header
    assert "SATURDAY MORNING on purpose" not in header


def test_the_header_gives_the_binding_reason_not_only_the_convenient_ones():
    """Markets-are-closed and a-weekend-to-think are both true of Saturday
    too, so neither explains the slot. The token does."""
    header = SOURCE[:SOURCE.index("$ErrorActionPreference")]
    assert "token" in header.lower()
    assert "Morning Start" in header


def _trigger_days():
    """Friday-ness of the real scheduled task, or None when it is absent."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-ScheduledTask -TaskName 'Hokage Weekly Audit')"
             ".Triggers | ForEach-Object "
             "{ \"$($_.DaysOfWeek)|$($_.StartBoundary)\" }"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def test_the_registered_task_really_does_run_on_friday_at_2345():
    """Pins the comment to the machine. Skipped where the task is not
    registered, because a bare checkout has no scheduler to ask - a rail
    that cannot run anywhere is not a rail, and one that fails everywhere
    gets deleted."""
    trigger = _trigger_days()
    if trigger is None:
        pytest.skip("'Hokage Weekly Audit' is not registered on this machine")
    days, _, boundary = trigger.partition("|")
    # The Windows bitmask: Sun 1, Mon 2, Tue 4, Wed 8, Thu 16, Fri 32, Sat 64.
    assert days.strip() == "32", f"trigger is not Friday-only: {trigger}"
    assert "T23:45" in boundary, f"trigger is not 23:45: {trigger}"


def test_the_reason_is_written_down_where_the_next_reader_will_be():
    """A one-line fix with no explanation is how the same trap is walked
    back into six months later."""
    call = SOURCE[SOURCE.index("START: running weekly_audit.py"):]
    assert "NativeCommandError" in call
    assert "2026-11-06" in call
