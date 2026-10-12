"""47,457 incidents, every one of them the market being closed.

`market_data` publishes ONLY after a quote actually comes back, so outside
trading hours it correctly goes quiet. The staleness check had no idea it was
quiet for a good reason, and logged an ERROR every six seconds all night and
all weekend.

Measured on 2026-10-12:

    5,167 ERROR lines in one day's log, ~570 an hour from midnight to the
          open, every one "Subsystem 'market_data' has a stale heartbeat"
          with an age counting up through the weekend (189,341s by Monday)

    47,457 rows in watchdog_incidents -- 100% of them heartbeat_freshness

The forensic journal of things going wrong consisted entirely of one thing
that was not wrong. A real error in that log was effectively invisible, which
is the same alarm fatigue that put CRUDEOIL in PARKED_ASSETS rather than let
the orphan audit scream on every boot.

WHAT MUST NOT CHANGE. This check exists because Hokage once sat blind on an
expired token for seven days while the score read 100.0/100. That happened
DURING market hours and must still be caught. These tests pin both halves:
quiet outside the window, fully armed inside it.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from shared.watchdog.watchdog import Watchdog


# ----------------------------------------------------- inside trading hours
@pytest.mark.parametrize("when", [
    datetime(2026, 10, 12, 9, 0),    # MCX open, exactly
    datetime(2026, 10, 12, 9, 15),   # NSE open
    datetime(2026, 10, 12, 12, 30),
    datetime(2026, 10, 12, 15, 30),  # NSE closed, MCX still running
    datetime(2026, 10, 12, 20, 0),   # the US-overlap window SessionShift uses
    datetime(2026, 10, 12, 23, 29),  # one minute before MCX close
])
def test_a_quiet_feed_during_trading_hours_is_still_an_alarm(when):
    """The seven-days-blind case. Never suppress inside the window."""
    assert Watchdog.feed_expected_now(when) is True


@pytest.mark.parametrize("weekday", [0, 1, 2, 3, 4])
def test_every_weekday_is_armed(weekday):
    day = datetime(2026, 10, 12 + weekday, 11, 0)
    assert day.weekday() == weekday
    assert Watchdog.feed_expected_now(day) is True


# ---------------------------------------------------- outside trading hours
@pytest.mark.parametrize("when", [
    datetime(2026, 10, 12, 0, 0),    # midnight, where the flood started
    datetime(2026, 10, 12, 3, 0),
    datetime(2026, 10, 12, 8, 59),   # one minute before the open
    datetime(2026, 10, 12, 23, 30),  # MCX close, exactly
    datetime(2026, 10, 12, 23, 45),
])
def test_a_quiet_feed_outside_trading_hours_is_expected(when):
    assert Watchdog.feed_expected_now(when) is False


@pytest.mark.parametrize("when", [
    datetime(2026, 10, 10, 11, 0),   # Saturday, mid-session hour
    datetime(2026, 10, 11, 20, 0),   # Sunday, mid-session hour
])
def test_the_weekend_is_silent_even_at_a_session_hour(when):
    """The weekend produced the bulk of the 5,167. A clock-only check would
    have kept screaming right through it."""
    assert when.weekday() >= 5
    assert Watchdog.feed_expected_now(when) is False


# ------------------------------------------------------- the window itself
def test_the_window_covers_every_venue_hokage_trades():
    """MCX 09:00-23:30 IST; NSE/BSE 09:15-15:30 sits inside it. A narrower
    window would silence a real outage during a session."""
    assert Watchdog.FEED_WINDOW_START_IST.hour == 9
    assert Watchdog.FEED_WINDOW_START_IST.minute == 0
    assert Watchdog.FEED_WINDOW_END_IST.hour == 23
    assert Watchdog.FEED_WINDOW_END_IST.minute == 30


def test_a_market_holiday_still_alarms_which_is_the_safe_direction():
    """No holiday calendar at this layer. A holiday falls inside the window so
    the alarm still fires -- wrong, but wrong toward noticing, and a handful
    of days a year rather than every single night."""
    # 2026-10-12 is treated as a normal weekday here regardless of calendar.
    assert Watchdog.feed_expected_now(datetime(2026, 10, 12, 11, 0)) is True


# --------------------------------------- only market_data may be suppressed
def test_only_market_data_is_scoped_to_the_window():
    """strategy_engine beats whether or not the market is open -- that is why
    it stayed healthy all weekend while market_data did not. Suppressing it
    outside hours would hide a genuinely dead scan loop."""
    import ast
    import inspect
    import pathlib
    import textwrap

    src = pathlib.Path("src/shared/watchdog/watchdog.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    guards = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Name) and n.left.id == "sub"
        and any(isinstance(c, ast.Constant) and c.value == "market_data"
                for c in n.comparators)
    ]
    assert guards, "the suppression must be gated on sub == 'market_data'"

    assert "strategy_engine" not in src.split("feed_quiet_is_expected = ")[1][:200], (
        "strategy_engine must never be suppressed by the window"
    )


def test_the_default_argument_reads_the_clock_at_call_time():
    """A datetime captured as a default argument freezes at import, which
    would pin the answer to whenever the process booted."""
    import inspect

    sig = inspect.signature(Watchdog.feed_expected_now)
    assert sig.parameters["now_local"].default is None
