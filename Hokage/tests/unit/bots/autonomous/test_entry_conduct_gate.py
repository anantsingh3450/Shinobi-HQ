"""Entry conduct gates: time-of-day windows, bias alignment, IV premium guard.

Measured-evidence rules: midday and late-session NSE entries are net leaks;
longs only with a bullish tape; option premium not bought when India VIX sits
in the top quintile of its trailing range. Missing data skips a check.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot


@pytest.fixture
def bot():
    b = AutonomousTradingBot.__new__(AutonomousTradingBot)
    b._compute_underlying_bias = MagicMock(return_value=None)
    b._india_vix_percentile = MagicMock(return_value=None)
    b._now_ist = lambda: datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
    return b


def test_midday_is_open_to_the_league(bot):
    """Commander-approved 2026-07-16: the GLOBAL midday blackout is retired.
    It was cloned from the Malfoy benchmark and blocked every strategy for two
    hours a day, starving evolution of data. Malfoy keeps the blackout inside
    its own entry module (its identity); the shared gate no longer enforces it."""
    bot._now_ist = lambda: datetime(2026, 7, 14, 12, 15, tzinfo=timezone.utc)
    ok, _ = bot._entry_conduct_gate("NIFTY", "long")
    assert ok


def test_late_session_cutoff_blocks_nse_entries(bot):
    # Cutoff widened to 15:00 IST (commander-approved 2026-07-16); 15:10 is out.
    bot._now_ist = lambda: datetime(2026, 7, 14, 15, 10, tzinfo=timezone.utc)
    ok, reason = bot._entry_conduct_gate("NIFTY", "long")
    assert not ok and "cutoff" in reason.lower()


def test_afternoon_before_1500_is_open(bot):
    # 14:30 used to be blocked by the old 14:00 cutoff — now inside the window.
    bot._now_ist = lambda: datetime(2026, 7, 14, 14, 30, tzinfo=timezone.utc)
    ok, _ = bot._entry_conduct_gate("NIFTY", "long")
    assert ok


def test_mcx_symbols_exempt_from_nse_windows(bot):
    bot._now_ist = lambda: datetime(2026, 7, 14, 12, 15, tzinfo=timezone.utc)
    ok, _ = bot._entry_conduct_gate("CRUDE_OIL", "long")
    assert ok


def test_bias_mixed_stands_aside(bot):
    bot._compute_underlying_bias = MagicMock(return_value="MIXED")
    ok, reason = bot._entry_conduct_gate("NIFTY", "long")
    assert not ok and "MIXED" in reason


def test_bias_blocks_counter_trend_entries(bot):
    bot._compute_underlying_bias = MagicMock(return_value="BULLISH")
    ok, _ = bot._entry_conduct_gate("NIFTY", "long")
    assert ok
    ok, reason = bot._entry_conduct_gate("NIFTY", "short")
    assert not ok and "BULLISH" in reason

    bot._compute_underlying_bias = MagicMock(return_value="BEARISH")
    ok, _ = bot._entry_conduct_gate("NIFTY", "short")
    assert ok
    ok, reason = bot._entry_conduct_gate("NIFTY", "long")
    assert not ok and "BEARISH" in reason


def test_rich_vix_blocks_option_buying(bot):
    bot._india_vix_percentile = MagicMock(return_value=0.85)
    ok, reason = bot._entry_conduct_gate("NIFTY", "long")
    assert not ok and "premium too rich" in reason


def test_missing_data_skips_checks_not_fabricates(bot):
    # No bias data + no VIX data at a clean time of day: entry allowed.
    ok, reason = bot._entry_conduct_gate("NIFTY", "long")
    assert ok
    assert "passed" in reason
