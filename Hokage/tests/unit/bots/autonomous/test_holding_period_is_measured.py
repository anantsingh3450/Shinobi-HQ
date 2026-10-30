"""Every exit-path consumer was told the trade had been held for three days.

Five call sites, all hardcoded, one of them labelled in the source:

    holding_time_seconds=3 * 86400, # Mocked holding time based on holding_days=3

On 2026-10-30 GOLDM26NOV141000PE was held 71 minutes and SILVERM26NOV184000PE
six, and both were recorded as three-day holds. The generated lessons, which
are forwarded to long-term memory, each said "3d hold".

THE QUIET CASUALTY was the calibration engine. It compares actual holding
time against an expected 3 days — and the actual was also a constant 3, so it
reported perfect agreement about a number nobody had measured. Same shape as
the promotion loop that ran on win rate: a number that always looked right
because nothing fed it. With real values it will now show the true gap, which
is large, and that gap is a finding, not a regression.

Found while fixing R:R (test_rr_uses_entry_stop.py) — adjacent in the same
call, same root: post-trade measurement trusting a value nobody set.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.autonomous.position_review import PositionReviewEngine, _format_hold


def _bot():
    return object.__new__(Bot)


def _stamp(**ago):
    return (datetime.now(timezone.utc) - timedelta(**ago)).isoformat()


# ------------------------------------------------------- it reads the clock
def test_it_measures_from_the_records_own_entry_stamp():
    held = _bot()._holding_seconds({"entry_timestamp": _stamp(minutes=71)})
    assert held == pytest.approx(71 * 60, abs=5)


def test_a_naive_stamp_is_read_as_utc_not_local():
    """Hokage writes UTC. Reading a naive stamp as local time would shift the
    hold by the IST offset and make a 71-minute trade look like 5h 41m."""
    naive = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(tzinfo=None)
    held = _bot()._holding_seconds({"entry_timestamp": naive.isoformat()})
    assert held == pytest.approx(30 * 60, abs=5)


def test_unreadable_is_zero_and_zero_cannot_pass_for_a_hold():
    bot = _bot()
    for meta in ({}, None, {"entry_timestamp": ""},
                 {"entry_timestamp": "not a date"},
                 {"entry_timestamp": None}, {"entry_timestamp": 12345}):
        assert bot._holding_seconds(meta) == 0.0


def test_a_future_stamp_never_goes_negative():
    assert _bot()._holding_seconds(
        {"entry_timestamp": (datetime.now(timezone.utc)
                             + timedelta(hours=2)).isoformat()}) == 0.0


# ------------------------------------------------- it reports what it holds
@pytest.mark.parametrize("seconds,expected", [
    (71 * 60, "1.2h"),           # the real GOLDM hold
    (6 * 60, "6m"),              # the real SILVERM hold
    (90 * 60, "1.5h"),
    (3 * 86400, "3.0d"),
    (None, "0d"),                # unknown falls back to the int field
    (0, "0d"),
])
def test_the_hold_reads_the_way_it_was_held(seconds, expected):
    assert _format_hold(0, seconds) == expected


def test_the_lesson_no_longer_claims_three_days(tmp_path):
    r = PositionReviewEngine(brain_root=tmp_path).review_trade(
        symbol="GOLDM26NOV141000PE", entry_price=3152.50, exit_price=3586.00,
        stop_price=2994.875, target_price=3539.28, conviction_score=59,
        position_size_pct=2.0, holding_days=0, exit_reason="TARGET_HIT",
        pnl=4335.0, holding_seconds=71 * 60,
    )
    assert "1.2h hold" in r.lesson
    assert "3d hold" not in r.lesson


def test_an_old_caller_without_seconds_still_works(tmp_path):
    """The parameter is optional on purpose — nothing else had to change."""
    r = PositionReviewEngine(brain_root=tmp_path).review_trade(
        symbol="X", entry_price=100.0, exit_price=110.0, stop_price=90.0,
        target_price=120.0, conviction_score=50, position_size_pct=2.0,
        holding_days=4, exit_reason="Take Profit", pnl=100.0,
    )
    assert "4d hold" in r.lesson


# --------------------------------------------- nothing assumes three days now
def test_no_hardcoded_holding_period_survives_in_the_exit_path():
    src = Path(__import__("bots.autonomous.autonomous_bot",
                          fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "holding_days=3" not in src
    assert "holding_period_days=3" not in src
    assert "Mocked holding time" not in src
    assert "holding_time_seconds=_held_seconds" in src
