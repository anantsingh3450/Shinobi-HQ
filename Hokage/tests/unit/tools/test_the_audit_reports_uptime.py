"""Every number in the audit is an average over sessions Hokage was awake for.

He has seen about half of them. 23 of 48 when that was first measured; 22 of
39 over the eight weeks to 2026-11-09, with a longest blackout of 11 sessions
- and 20 of 21 over the last four, so the headline figure is dominated by one
old outage rather than by current behaviour. Both facts matter, and neither
was visible: `session_coverage.py` could answer it all along and was a
standalone tool nobody ran.

A per-cell n is as much a count of sessions ATTENDED as of setups found. An
audit that reports n without reporting coverage invites the wrong conclusion
from a thin sample - that the edge is absent rather than that nobody was
there to measure it.

This is context, never a verdict: it must not be able to take the audit down.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "research"))
sys.path.insert(0, str(ROOT / "tools" / "ops"))
sys.path.insert(0, str(ROOT / "src"))

import weekly_audit as audit  # noqa: E402


def _fake(monkeypatch, result):
    import session_coverage

    monkeypatch.setattr(session_coverage, "coverage", lambda s, e: result)


# =============================================================== the wording
def test_a_healthy_window_reads_plainly(monkeypatch):
    _fake(monkeypatch, {"sessions": 21, "covered": 20, "partial": 0,
                        "longest_blackout": 1})
    line = audit.coverage_line(weeks=4)
    assert "20 of 21" in line
    assert "95%" in line
    assert "ATTENDED" not in line           # no warning when coverage is fine


def test_a_poor_window_warns_that_n_counts_attendance(monkeypatch):
    """THE POINT OF THE LINE. At 56% the reader has to know that a thin n may
    mean nobody was watching, not that nothing happened."""
    _fake(monkeypatch, {"sessions": 39, "covered": 22, "partial": 1,
                        "longest_blackout": 11})
    line = audit.coverage_line(weeks=8)
    assert "22 of 39" in line
    assert "56%" in line
    assert "1 partial" in line
    assert "longest blackout 11 sessions" in line
    assert "ATTENDED" in line


def test_a_single_missed_day_is_not_called_a_blackout(monkeypatch):
    """One missed morning is a bad morning; twelve in a row is a system
    nobody is watching. They must not read the same."""
    _fake(monkeypatch, {"sessions": 20, "covered": 19, "partial": 0,
                        "longest_blackout": 1})
    assert "blackout" not in audit.coverage_line()


def test_an_empty_window_says_so_rather_than_dividing_by_zero(monkeypatch):
    _fake(monkeypatch, {"sessions": 0})
    line = audit.coverage_line()
    assert "no sessions" in line


# ===================================================== it cannot break the audit
def test_a_failure_degrades_to_a_line(monkeypatch):
    import session_coverage

    def boom(*a, **k):
        raise RuntimeError("archive unreadable")

    monkeypatch.setattr(session_coverage, "coverage", boom)
    line = audit.coverage_line()
    assert "could not be measured" in line
    assert "RuntimeError" in line


def test_it_is_rendered_into_the_report():
    src = (ROOT / "tools" / "research" / "weekly_audit.py").read_text(
        encoding="utf-8")
    assert "lines.append(coverage_line())" in src


def test_the_real_tool_still_answers(tmp_path, monkeypatch):
    """The seam, against a controlled archive.

    The first version of this read the machine's real brain: it passed alone
    and failed inside the suite, because another test had already repointed
    HOKAGE_BRAIN_ROOT. A test whose result depends on what ran before it is
    not evidence of anything.
    """
    import sqlite3

    import session_coverage

    root = tmp_path / "brain"
    root.mkdir(parents=True)
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))

    candles = sqlite3.connect(root / "candles.db")
    candles.execute("CREATE TABLE candles (symbol TEXT, ts TEXT)")
    days = ["2026-11-02", "2026-11-03", "2026-11-04"]
    candles.executemany(
        "INSERT INTO candles VALUES (?, ?)",
        [(session_coverage.SESSION_SYMBOL, f"{d} 10:00:00") for d in days])
    candles.commit()
    candles.close()

    ledger = sqlite3.connect(root / "hokage.db")
    ledger.execute("CREATE TABLE no_trade_decisions (timestamp TEXT)")
    # Two sessions fully attended, the third missed entirely.
    ledger.executemany(
        "INSERT INTO no_trade_decisions VALUES (?)",
        [(f"{d}T10:0{i % 10}:00Z",)
         for d in days[:2]
         for i in range(session_coverage.MIN_DECISIONS_FOR_A_FULL_SESSION)])
    ledger.commit()
    ledger.close()

    result = session_coverage.coverage(dt.date(2026, 11, 1),
                                       dt.date(2026, 11, 5))
    assert result["sessions"] == 3
    assert result["covered"] == 2
    assert result["missed"] == 1
    assert set(result) >= {"covered", "partial", "missed", "longest_blackout"}
    # Deliberately NOT asserting on coverage_line here: it derives its window
    # from date.today(), so a fixture pinned to November would quietly stop
    # testing anything in December. The rendering is covered above, against a
    # faked coverage() where the window is explicit.


def test_sessions_come_from_the_tape_not_a_holiday_list():
    """So no calendar can go stale underneath the uptime figure - the same
    reason confirmed_holidays_from_archive exists."""
    src = (ROOT / "tools" / "ops" / "session_coverage.py").read_text(
        encoding="utf-8")
    assert "candles.db" in src
