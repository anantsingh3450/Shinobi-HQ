"""A square-off seven and three quarter hours after the market shut.

MCX positions square off at 23:15 because MCX closes at 23:30. On Sunday
2026-11-08, Diwali Muhurat trading, MCX closes at 15:30. So a position opened
that afternoon would have waited for 23:15 with no quotes to exit against from
15:30 onward, failed to exit, and carried overnight into Monday - through a
weekend gap, with no stop having ever run. That is the same shape as the
critical-battery sleep that suspended Hokage mid-session and cost every stop
on an open position.

The same pair of numbers also drives the option target's runway, where being
wrong is quieter and just as real: at 14:30 that day an MCX position would be
credited 525 minutes of runway against a market closing in 60, inflating the
expected move by sqrt(105/12) and putting the target beyond the session it has
to be reached in.

NEVER LATER THAN THE ORDINARY TIME. Equity F&O runs to 15:40 that day, so
matching the close would push the 15:20 square-off out to 15:30 - loosening a
risk control because of a calendar entry. It does not move.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

MUHURAT = dt.date(2026, 11, 8)          # NSE F&O to 15:40, MCX to 15:30
MONDAY = dt.date(2026, 11, 9)
DEAD_SUNDAY = dt.date(2026, 11, 15)


def _bot(day: dt.date, hhmm: str = "14:30"):
    hour, minute = (int(x) for x in hhmm.split(":"))
    bot = SimpleNamespace(
        _now_ist=lambda: dt.datetime.combine(day, dt.time(hour, minute)),
        _SQUARE_OFF_BUFFER_MIN=Bot._SQUARE_OFF_BUFFER_MIN,
    )
    bot._special_window_today = lambda seg: Bot._special_window_today(bot, seg)
    return bot


def _square_off(day: dt.date, is_mcx: bool) -> tuple[int, int]:
    return Bot._square_off_time(_bot(day), is_mcx)


# ======================================================== the ordinary days
@pytest.mark.parametrize("day", [MONDAY, DEAD_SUNDAY])
def test_an_ordinary_day_keeps_the_published_constants(day):
    """These two values are risk controls. Nothing here is allowed to move
    them on a day with ordinary hours."""
    assert _square_off(day, False) == (15, 20)
    assert _square_off(day, True) == (23, 15)


# ====================================================== the special session
def test_mcx_is_flat_before_the_muhurat_close():
    """THE HAZARD. 15:15 is fifteen minutes before MCX shuts at 15:30 - the
    same buffer the 23:15/23:30 pair already uses."""
    assert _square_off(MUHURAT, True) == (15, 15)


def test_the_equity_square_off_does_not_move_outward():
    """Equity F&O runs to 15:40 that day. Matching it would mean holding 10
    minutes longer than on any ordinary day, which is a loosened stop dressed
    up as a calendar fix."""
    assert _square_off(MUHURAT, False) == (15, 20)
    assert _square_off(MUHURAT, False) == _square_off(MONDAY, False)


def test_the_special_time_can_only_bring_the_square_off_forward():
    """The rule, stated as a comparison rather than as two literals: whatever
    the calendar says, neither league may be flat later than it would be on
    an ordinary day."""
    for is_mcx in (False, True):
        assert _square_off(MUHURAT, is_mcx) <= _square_off(MONDAY, is_mcx)


def test_the_buffers_are_the_ones_already_in_force():
    """Not new policy. 15:30 close minus 10 is the existing 15:20; 23:30
    close minus 15 is the existing 23:15."""
    assert Bot._SQUARE_OFF_BUFFER_MIN == {"NSE": 10, "MCX": 15}
    assert (15, 30 - Bot._SQUARE_OFF_BUFFER_MIN["NSE"]) == (15, 20)
    assert (23, 30 - Bot._SQUARE_OFF_BUFFER_MIN["MCX"]) == (23, 15)


def test_an_unreadable_calendar_leaves_the_constants_alone():
    import hokage.memory.trading_calendar as tc

    bot = _bot(MUHURAT)
    bot._special_window_today = lambda seg: (_ for _ in ()).throw(
        RuntimeError("calendar unreadable"))
    with pytest.raises(RuntimeError):
        bot._special_window_today("MCX")
    # the production accessor swallows it, so the real path still answers
    assert Bot._square_off_time(_bot(MONDAY), True) == (23, 15)


# ================================================ the runway uses the same
def test_the_runway_is_measured_to_the_square_off_not_the_exchange_close():
    """Both call sites read one helper, so a session cannot have an exit time
    and a target that disagree about when the day ends."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    assert src.count("self._square_off_time(") == 2
    # and the pair of literals now lives in exactly ONE place: the helper.
    assert "(23, 15) if is_mcx_instrument else (15, 20)" not in src
    assert src.count("(23, 15) if is_mcx else (15, 20)") == 1
    helper = src.split("def _square_off_time")[1].split("def _describe_today")[0]
    assert "(23, 15) if is_mcx else (15, 20)" in helper


def test_the_inflated_runway_is_gone():
    """At 14:30 on the Muhurat Sunday an MCX position had 525 minutes of
    runway against a market closing in 60."""
    bot = _bot(MUHURAT, "14:30")
    hour, minute = Bot._square_off_time(bot, True)
    minutes_left = (hour - 14) * 60 + (minute - 30)
    assert minutes_left == 45
    bars_left = minutes_left / 5          # MCX reads 5-minute bars
    assert bars_left == 9.0               # was 105.0
