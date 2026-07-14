"""Option exit ladder: ordered, premium-aware, loss protection first.

Ladder (after kill-switch and EOD square-off): tiered premium hard backstop,
underlying ATR thesis stop, adaptive TARGET_HIT, TRAIL_LOCK. Missing data
skips a rung; nothing is fabricated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from integrations.brokers.models import OrderSide


@pytest.fixture
def bot(mock_orchestrator=None):
    b = AutonomousTradingBot.__new__(AutonomousTradingBot)
    b.intraday_override = {}
    b._get_validated_live_price = MagicMock(return_value=(None, "no data"))
    # Pin the clock mid-session (11:00 IST) so EOD square-off never interferes.
    b._now_ist = lambda: datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc)
    return b


def _run(bot, symbol="NIFTY25JUL24300CE", entry=200.0, current=200.0, tracking=None, qty=75.0):
    tracking = tracking if tracking is not None else {"entry_price": entry, "peak_price": entry}
    return bot._evaluate_cascading_exits(
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=qty,
        average_price=entry,
        current_price=current,
        tracking=tracking,
        is_tick=True,
        venue=None,
    )


def test_tiered_backstop_wider_for_cheap_options(bot):
    # Entry 250 (tier 200-500): -25% cap = 187.5
    hit, reason, _ = _run(bot, entry=250.0, current=187.0)
    assert hit and "Hard Backstop" in reason
    # -20% is inside the tier's tolerance: no exit
    hit, reason, _ = _run(bot, entry=250.0, current=201.0)
    assert not hit

    # Cheap option (entry 80, tier <100): survives -40%, dies at -50%
    hit, _, _ = _run(bot, entry=80.0, current=48.5)
    assert not hit
    hit, reason, _ = _run(bot, entry=80.0, current=39.9)
    assert hit and "Hard Backstop" in reason


def test_underlying_thesis_stop_cuts_broken_premise(bot):
    tracking = {
        "entry_price": 200.0,
        "peak_price": 200.0,
        "underlying": "NIFTY",
        "entry_underlying_price": 24300.0,
        "entry_underlying_atr": 40.0,
    }
    # Underlying fell 60 points against a CE (>= 1.25 x 40 = 50): thesis dead,
    # even though the premium itself has barely moved.
    bot._get_validated_live_price = MagicMock(return_value=(24240.0, "live"))
    hit, reason, _ = _run(bot, entry=200.0, current=195.0, tracking=tracking)
    assert hit and "Thesis Stop" in reason

    # 30-point adverse move (< 50): thesis intact.
    tracking2 = dict(tracking)
    bot._get_validated_live_price = MagicMock(return_value=(24270.0, "live"))
    hit, _, _ = _run(bot, entry=200.0, current=195.0, tracking=tracking2)
    assert not hit


def test_target_hit_adaptive_and_clamped(bot):
    tracking = {
        "entry_price": 200.0,
        "peak_price": 200.0,
        "underlying": "NIFTY",
        "entry_underlying_price": 24300.0,
        "entry_underlying_atr": 40.0,
    }
    bot._get_validated_live_price = MagicMock(return_value=(24310.0, "live"))
    # Max clamp is +25%: premium at 250 (=+25%) must always trigger.
    hit, reason, out = _run(bot, entry=200.0, current=250.1, tracking=dict(tracking))
    assert hit and "TARGET_HIT" in reason
    # Premium below the minimum +6% target can never trigger a target exit.
    hit, reason, out = _run(bot, entry=200.0, current=205.0, tracking=dict(tracking))
    assert not hit
    assert out["target_price"] >= 212.0  # >= entry * 1.06


def test_trail_lock_gives_back_at_most_1000_rupees(bot):
    # qty 75: peak profit (240-200)*75 = 3000 >= 1000 arms the lock.
    # Floor = 240 - 1000/75 = 226.67. Current 226 breaches it.
    tracking = {"entry_price": 200.0, "peak_price": 240.0}
    hit, reason, _ = _run(bot, entry=200.0, current=226.0, tracking=tracking, qty=75.0)
    assert hit and "TRAIL_LOCK" in reason

    # Above the floor: still riding.
    tracking = {"entry_price": 200.0, "peak_price": 240.0}
    hit, _, _ = _run(bot, entry=200.0, current=230.0, tracking=tracking, qty=75.0)
    assert not hit


def test_mcx_option_squares_off_at_2315_not_1520(bot):
    # 16:00 IST: NSE options are already flat, MCX crude options still live.
    bot._now_ist = lambda: datetime(2026, 7, 14, 16, 0, tzinfo=timezone.utc)
    hit, reason, _ = _run(bot, symbol="CRUDEOIL25JUL6800CE", entry=100.0, current=100.0)
    assert not hit
    hit, reason, _ = _run(bot, symbol="NIFTY25JUL24300CE", entry=200.0, current=200.0)
    assert hit and "Square-Off" in reason

    # 23:20 IST: crude squares off too.
    bot._now_ist = lambda: datetime(2026, 7, 14, 23, 20, tzinfo=timezone.utc)
    hit, reason, _ = _run(bot, symbol="CRUDEOIL25JUL6800CE", entry=100.0, current=100.0)
    assert hit and "Square-Off" in reason


def test_missing_underlying_data_skips_thesis_and_target_rungs(bot):
    # No underlying context in tracking: backstop still enforced, thesis/target
    # rungs skipped (no fabricated ATR), trail lock still works.
    tracking = {"entry_price": 200.0, "peak_price": 200.0}
    hit, _, out = _run(bot, entry=200.0, current=210.0, tracking=tracking)
    assert not hit
    assert "target_price" not in out
