"""The nightly sync needs a token that is dead by the time it runs.

The candle sync fires at 23:40, after the MCX close, so the session is
complete. It needs a live broker session and exits without writing if the
token has expired - correct, because recording a short day as a real one is
worse than recording nothing. The commander logs in in the MORNING and Kite
expires a token daily, so the 23:40 run found the session unreachable on
2026-11-01, 11-04, 11-05, 11-07 and 11-08.

NOTHING WAS ACTUALLY LOST, and that matters for how hard to push on this:
`sync` re-fetches a ninety-day window, so a later success repairs the nights
before it, and the archive had no gaps at all when checked on 11-09. What was
lost is the GUARANTEE - a contract that rolls between the skip and the next
success takes its tape with it, which is exactly how three months of gas
history ceased to exist on 2026-08-27.

So Hokage tops the archive up himself, in the morning, when the token is
freshest. The rules this holds down:

  * only when the archive is actually BEHIND, or it hammers the broker daily
    for nothing
  * never on the trading thread, because exits are managed from that loop
  * holidays are not gaps, which is what the calendar is for
  * today is not a gap either: a session in progress has no close yet
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot  # noqa: E402

ASSETS = ("NATURALGAS", "CRUDEOIL", "GOLDM", "SILVERM",
          "NIFTY", "BANKNIFTY", "SENSEX")

#: Monday 2026-11-09 10:30 IST. The previous sessions are Friday the 6th and
#: the Muhurat Sunday the 8th; Saturday the 7th is shut.
NOW = dt.datetime(2026, 11, 9, 10, 30)


def _archive(tmp_path: Path, days: list[str], symbols=ASSETS) -> None:
    root = tmp_path / "brain"
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "candles.db")
    con.execute("CREATE TABLE candles (symbol TEXT, ts TEXT, close REAL)")
    con.executemany(
        "INSERT INTO candles VALUES (?, ?, 100.0)",
        [(s, f"{d} 10:00:00") for s in symbols for d in days])
    con.commit()
    con.close()


def _bot(tmp_path, monkeypatch, *, feed_ok=True, now=NOW):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    bot = SimpleNamespace(
        _now_ist=lambda: now,
        _feed_probe_ok=feed_ok,
        _archive_catchup_date=None,
        _archive_catchup_running=False,
    )
    bot._archive_assets = lambda: ASSETS
    bot._archive_sessions_missing = lambda: Bot._archive_sessions_missing(bot)
    bot._run_candle_catchup = MagicMock()
    return bot


#: Every weekday session in the fortnight before NOW, so there is no gap.
def _all_recent_sessions() -> list[str]:
    from hokage.memory import trading_calendar as tc

    out = []
    for n in range(1, 15):
        day = NOW.date() - dt.timedelta(days=n)
        if tc.session_kind(day, "NSE") not in (None, tc.CLOSED) or \
                tc.session_kind(day, "MCX") not in (None, tc.CLOSED):
            out.append(day.isoformat())
    return out


# ============================================================ finding a gap
def test_a_complete_archive_has_no_gaps(tmp_path, monkeypatch):
    _archive(tmp_path, _all_recent_sessions())
    bot = _bot(tmp_path, monkeypatch)
    assert bot._archive_sessions_missing() == set()


def test_a_missing_session_is_found(tmp_path, monkeypatch):
    days = _all_recent_sessions()
    assert "2026-11-06" in days
    days.remove("2026-11-06")
    _archive(tmp_path, days)
    bot = _bot(tmp_path, monkeypatch)
    assert "2026-11-06" in bot._archive_sessions_missing()


def test_the_muhurat_sunday_counts_as_a_session(tmp_path, monkeypatch):
    """The day this whole thread started. A Sunday that traded is a gap if it
    is missing, and the only thing that knows that is the calendar."""
    days = _all_recent_sessions()
    assert "2026-11-08" in days
    days.remove("2026-11-08")
    _archive(tmp_path, days)
    bot = _bot(tmp_path, monkeypatch)
    assert "2026-11-08" in bot._archive_sessions_missing()


def test_a_closed_saturday_is_not_a_gap(tmp_path, monkeypatch):
    _archive(tmp_path, _all_recent_sessions())
    bot = _bot(tmp_path, monkeypatch)
    missing = bot._archive_sessions_missing()
    assert "2026-11-07" not in missing          # Saturday
    assert "2026-11-14" not in missing          # outside the window anyway


def test_today_is_never_a_gap(tmp_path, monkeypatch):
    """A session in progress has no close, and Kite's bar for it is not one
    either. Asking for it would top up every single morning."""
    _archive(tmp_path, _all_recent_sessions())
    bot = _bot(tmp_path, monkeypatch)
    assert NOW.date().isoformat() not in bot._archive_sessions_missing()


def test_an_absent_archive_is_not_reported_as_fourteen_gaps(tmp_path,
                                                            monkeypatch):
    """No archive is missing data, not a fortnight of holes. Reporting it as
    gaps would start a full re-fetch on a machine that has never synced."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "nothing"))
    bot = _bot(tmp_path, monkeypatch)
    assert bot._archive_sessions_missing() == set()


# ================================================== when it decides to run
def _catchup(bot):
    return Bot._catch_up_candle_archive(bot)


def test_it_runs_when_the_archive_is_behind(tmp_path, monkeypatch):
    days = _all_recent_sessions()
    days.remove("2026-11-06")
    _archive(tmp_path, days)
    bot = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr("threading.Thread", MagicMock())
    _catchup(bot)
    assert bot._archive_catchup_running is True


def test_it_does_nothing_when_the_archive_is_complete(tmp_path, monkeypatch):
    _archive(tmp_path, _all_recent_sessions())
    bot = _bot(tmp_path, monkeypatch)
    started = MagicMock()
    monkeypatch.setattr("threading.Thread", started)
    _catchup(bot)
    started.assert_not_called()


def test_it_waits_for_a_working_feed(tmp_path, monkeypatch):
    """No token, no fetch - and no false alarm about an archive it could not
    have filled anyway."""
    days = _all_recent_sessions()
    days.remove("2026-11-06")
    _archive(tmp_path, days)
    bot = _bot(tmp_path, monkeypatch, feed_ok=False)
    started = MagicMock()
    monkeypatch.setattr("threading.Thread", started)
    _catchup(bot)
    started.assert_not_called()
    assert bot._archive_catchup_date is None       # not latched, so it retries


def test_it_latches_once_per_day(tmp_path, monkeypatch):
    days = _all_recent_sessions()
    days.remove("2026-11-06")
    _archive(tmp_path, days)
    bot = _bot(tmp_path, monkeypatch)
    started = MagicMock()
    monkeypatch.setattr("threading.Thread", started)
    _catchup(bot)
    bot._archive_catchup_running = False
    _catchup(bot)
    assert started.call_count == 1


def test_a_run_in_flight_is_not_started_twice(tmp_path, monkeypatch):
    days = _all_recent_sessions()
    days.remove("2026-11-06")
    _archive(tmp_path, days)
    bot = _bot(tmp_path, monkeypatch)
    bot._archive_catchup_running = True
    started = MagicMock()
    monkeypatch.setattr("threading.Thread", started)
    _catchup(bot)
    started.assert_not_called()


def test_a_missing_probe_flag_does_not_crash_the_loop(tmp_path, monkeypatch):
    """The flag is born on the first probe and this runs straight after it.
    An AttributeError here would be swallowed by the loop's shared except and
    the catch-up would silently never run."""
    _archive(tmp_path, _all_recent_sessions())
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    bot = SimpleNamespace(_now_ist=lambda: NOW)
    bot._archive_assets = lambda: ASSETS
    bot._archive_sessions_missing = lambda: set()
    _catchup(bot)       # must not raise


# ======================================================== how it is wired
def test_it_never_runs_on_the_trading_thread():
    """Exits are managed from the loop this is called in. A one-to-two-minute
    fetch in line with it is a position nobody is watching."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _catch_up_candle_archive")[1].split(
        "def _archive_sessions_missing")[0]
    assert "threading.Thread(" in body
    assert "daemon=True" in body
    # A THREAD join, not a string join: the log line above it formats the
    # missing dates with ", ".join(...), and a rail that cannot tell the two
    # apart fails on correct code.
    assert "join()" not in body
    assert "join(timeout" not in body
    assert ".start()" in body


def test_the_loop_calls_it_inside_its_own_guard():
    """A failing archive top-up must not take the trading iteration with it."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    call = src.split("self._catch_up_candle_archive()")[1][:200]
    assert "except Exception as exc:" in call
    assert "Candle archive catch-up failed" in call


def test_an_unknown_date_is_not_counted_as_a_gap(tmp_path, monkeypatch):
    """The 2027 case. This calendar's data ends 2026-12-31, and after that
    every answer is None - which must mean "skip", not "missing". Counted as
    gaps, the archive would look fourteen sessions behind every morning and
    start a full re-fetch of seven symbols, for ever."""
    far = dt.datetime(2027, 3, 2, 10, 30)       # a Tuesday outside the data
    from hokage.memory import trading_calendar as tc

    assert tc.session_kind(far.date(), "NSE") is None
    _archive(tmp_path, ["2027-02-01"])
    bot = _bot(tmp_path, monkeypatch, now=far)
    assert bot._archive_sessions_missing() == set()


def test_the_gap_check_asks_the_one_helper_that_answers_three_ways():
    """`segment_shut` collapses None and CLOSED, which is right for silencing
    a message and wrong here. `market_was_open` keeps them apart and already
    maps symbol to segment, so this file keeps no second list of which
    underlyings are MCX."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _archive_sessions_missing")[1].split(
        "def _run_candle_catchup")[0]
    assert "market_was_open(symbol, day) is not True" in body
    # CODE ONLY. The docstring names `session_kind` while explaining why it is
    # not used here, so the rail has to skip the docstring as well as the
    # comments - the fourth rail today to fire on its own explanation.
    code = body.split(chr(34) * 3, 2)[2]
    code = chr(10).join(line.split(chr(35))[0] for line in code.splitlines())
    assert "session_kind" not in code
    assert "CRUDEOIL" not in code


def test_the_asset_list_is_not_a_second_copy():
    """A symbol added to the archiver and not here would be silently exempt
    from the check that it is being archived."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _archive_assets")[1].split("def _catch_up")[0]
    assert "from candle_archive import ASSETS" in body


def test_the_real_archiver_still_exposes_what_is_read():
    """The import above is the seam. If candle_archive stops exporting ASSETS
    or sync, the catch-up degrades to doing nothing, silently."""
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import candle_archive

    assert isinstance(candle_archive.ASSETS, tuple)
    assert set(candle_archive.ASSETS) == set(ASSETS)
    assert callable(candle_archive.sync)
    import inspect

    assert "verbose" in inspect.signature(candle_archive.sync).parameters
