"""Hokage was awake for 23 of the last 48 market sessions.

On 2026-10-16 the question was why no trade had been taken since 09-22. The
gate tally said the entry modules were standing aside. The signal-rate lab
said those modules fire as often as they ever have. Both were careful answers
to a question whose premise nobody had checked.

The premise was false. The process before the gap died at 2026-09-23 06:27
and the next one started 2026-10-09 18:26: sixteen calendar days, eleven
market sessions, no process, no decisions, no log file. A second gap runs
09-07 to 09-18.

    window          2026-08-07 .. 2026-10-15
    sessions        48
      recorded      23   (48%)
      MISSED        24
    longest blackout  11 sessions, 2026-09-23 .. 2026-10-08

AND THE WATCH DID NOT CATCH IT. logs/liveness.log has no entries for those
days either. The external liveness probe exists because of a 3h39m death that
Hokage reported as "Health Score 100/100" — the lesson being that his own
watchdog dies with him. But the probe is a Windows scheduled task on the same
laptop, and every Hokage task runs as LogonType=Interactive. It is
independent of the PROCESS, not of the MACHINE, and the machine is what went
away. A probe inside the failure domain it watches cannot report that domain
failing.

SESSIONS COME FROM THE CANDLE ARCHIVE. Not a weekday calculation and not a
hardcoded holiday list, either of which would quietly count Diwali against
him. A day with archived index candles is a day the market traded; a day the
archive has never heard of is not counted at all, because missing is not the
same fact as missed.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sqlite3
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "session_coverage", ROOT / "tools" / "ops" / "session_coverage.py"
)
sc = importlib.util.module_from_spec(_spec)
sys.modules["session_coverage"] = sc
_spec.loader.exec_module(sc)


@pytest.fixture
def brain(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path))
    return tmp_path


def _archive(brain, days: list[str]) -> None:
    conn = sqlite3.connect(brain / "candles.db")
    conn.execute("CREATE TABLE IF NOT EXISTS candles (symbol TEXT, ts TEXT, "
                 "contract TEXT, open REAL, high REAL, low REAL, close REAL, "
                 "volume REAL, PRIMARY KEY (symbol, ts))")
    conn.executemany(
        "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?)",
        [(sc.SESSION_SYMBOL, f"{d} 09:15:00", "SPOT", 1, 1, 1, 1, 0)
         for d in days])
    conn.commit()
    conn.close()


def _journal(brain, counts: dict[str, int]) -> None:
    conn = sqlite3.connect(brain / "hokage.db")
    conn.execute("CREATE TABLE IF NOT EXISTS no_trade_decisions (asset TEXT, "
                 "timestamp TEXT, decision TEXT, confidence REAL, "
                 "reasons TEXT)")
    rows = []
    for day, n in counts.items():
        for i in range(n):
            rows.append(("NIFTY", f"{day}T0{4 + i % 5}:{i % 60:02d}:00+00:00",
                         "NO_TRADE", 0.0, "[]"))
    conn.executemany("INSERT INTO no_trade_decisions VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


WINDOW = (dt.date(2026, 9, 21), dt.date(2026, 9, 25))
WEEK = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]


# ------------------------------------------------- a session is a traded day
def test_sessions_come_from_the_archive_not_from_the_calendar(brain):
    """A weekday calculation counts Diwali against him, and a hardcoded
    holiday list is a table that rots. The archive already knows."""
    _archive(brain, ["2026-09-21", "2026-09-22", "2026-09-25"])
    assert sc.trading_days(*WINDOW) == [
        dt.date(2026, 9, 21), dt.date(2026, 9, 22), dt.date(2026, 9, 25)]


def test_a_day_the_archive_never_saw_is_not_held_against_him(brain):
    _archive(brain, ["2026-09-21", "2026-09-22"])
    _journal(brain, {"2026-09-21": 50, "2026-09-22": 50})
    out = sc.coverage(*WINDOW)
    assert out["sessions"] == 2
    assert out["missed"] == 0, "23, 24 and 25 are unknown, not missed"


def test_no_archive_reports_unmeasurable_rather_than_perfect(brain):
    out = sc.coverage(*WINDOW)
    assert out == {"sessions": 0}


# ------------------------------------------------------------ counting it
def test_a_session_with_no_decisions_is_missed(brain):
    _archive(brain, WEEK)
    _journal(brain, {"2026-09-21": 50, "2026-09-25": 50})
    out = sc.coverage(*WINDOW)
    assert out["sessions"] == 5
    assert out["covered"] == 2
    assert out["missed"] == 3
    assert out["missed_days"] == [dt.date(2026, 9, 22), dt.date(2026, 9, 23),
                                  dt.date(2026, 9, 24)]


def test_a_handful_of_decisions_is_partial_not_covered(brain):
    """A process that booted at 15:00 and wrote four rows was not awake for
    that session in any sense that produces learning."""
    _archive(brain, WEEK)
    _journal(brain, {d: 50 for d in WEEK} | {"2026-09-23": 4})
    out = sc.coverage(*WINDOW)
    assert out["partial"] == 1
    assert out["covered"] == 4
    assert out["missed"] == 0, "a partial session is not a missed one"


def test_an_empty_journal_is_zero_covered_and_not_no_data(brain):
    _archive(brain, WEEK)
    out = sc.coverage(*WINDOW)
    assert out["sessions"] == 5
    assert out["covered"] == 0
    assert out["missed"] == 5


# --------------------------------------------------------- the blackout run
def test_the_longest_blackout_is_reported_separately_from_the_percentage(brain):
    """One missed morning and eleven missed sessions in a row are different
    facts, and averaging them into a single percentage hides the one that
    matters."""
    _archive(brain, WEEK)
    _journal(brain, {"2026-09-21": 50, "2026-09-25": 50})
    out = sc.coverage(*WINDOW)
    assert out["longest_blackout"] == 3
    assert out["blackout_days"][0] == dt.date(2026, 9, 22)
    assert out["blackout_days"][-1] == dt.date(2026, 9, 24)


def test_scattered_misses_do_not_add_up_into_one_blackout(brain):
    _archive(brain, WEEK)
    _journal(brain, {"2026-09-22": 50, "2026-09-24": 50})
    out = sc.coverage(*WINDOW)
    assert out["missed"] == 3
    assert out["longest_blackout"] == 1


def test_a_fully_covered_window_has_no_blackout(brain):
    _archive(brain, WEEK)
    _journal(brain, {d: 50 for d in WEEK})
    out = sc.coverage(*WINDOW)
    assert out["missed"] == 0
    assert out["longest_blackout"] == 0
    assert out["blackout_days"] == []


def test_a_blackout_running_to_the_end_of_the_window_is_still_counted(brain):
    """The live case: the gap ran to the edge of the data, and a loop that
    only closed a run on a covered day would have reported none."""
    _archive(brain, WEEK)
    _journal(brain, {"2026-09-21": 50})
    out = sc.coverage(*WINDOW)
    assert out["longest_blackout"] == 4
    assert out["blackout_days"][-1] == dt.date(2026, 9, 25)


# ------------------------------------------------------- it does not alarm
def test_it_names_why_the_liveness_probe_cannot_catch_this():
    """The probe is a scheduled task on the same laptop under the same
    interactive logon. Independent of the process, not of the machine."""
    doc = sc.__doc__ or ""
    assert "failure domain" in doc
    assert "liveness" in doc.lower()
