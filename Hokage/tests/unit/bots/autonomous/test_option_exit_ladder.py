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
    # Tiers tightened 2026-07-17 after the SENSEX -28.4% gap-fill:
    # (500+: -12%, 200-500: -20%, 100-200: -28%, <100: -40%).
    # Entry 250 (tier 200-500): -20% cap = 200.0
    hit, reason, _ = _run(bot, entry=250.0, current=187.0)
    assert hit and "Hard Backstop" in reason
    # -19.6% is inside the tier's tolerance: no exit
    hit, reason, _ = _run(bot, entry=250.0, current=201.0)
    assert not hit

    # Cheap option (entry 80, tier <100): survives -39%, dies at -40%
    hit, _, _ = _run(bot, entry=80.0, current=48.5)
    assert not hit
    hit, reason, _ = _run(bot, entry=80.0, current=39.9)
    assert hit and "Hard Backstop" in reason

    # The SENSEX class (entry ~494, tier 200-500): the old -25% line let it
    # gap-fill at -28.4%; the -20% line exits at 395.
    hit, reason, _ = _run(bot, entry=493.75, current=394.0)
    assert hit and "Hard Backstop" in reason
    hit, _, _ = _run(bot, entry=493.75, current=396.0)
    assert not hit


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


def test_profit_lock_breakeven_ratchet_arms_at_20pct(bot):
    # qty 20 keeps TRAIL_LOCK dark (peak profit 44*20=880 < 1000): this is the
    # %-based PROFIT_LOCK alone. Peak +22% arms stage 1: floor = entry + 10%
    # of the 44-point peak gain = 204.4 — a winner can no longer lose.
    tracking = {"entry_price": 200.0, "peak_price": 244.0}
    hit, reason, out = _run(bot, entry=200.0, current=204.0, tracking=tracking, qty=20.0)
    assert hit and "PROFIT_LOCK" in reason
    assert out["stop_price"] == pytest.approx(204.4)

    # Above the floor: still riding (room for option noise).
    tracking = {"entry_price": 200.0, "peak_price": 244.0}
    hit, _, _ = _run(bot, entry=200.0, current=206.0, tracking=tracking, qty=20.0)
    assert not hit


def test_profit_lock_keeps_half_the_gain_at_40pct(bot):
    # Peak +45% arms stage 2: floor = entry + 50% of the 90-point peak gain
    # = 245. qty 10 keeps the rupee TRAIL_LOCK dark (900 < 1000).
    tracking = {"entry_price": 200.0, "peak_price": 290.0}
    hit, reason, _ = _run(bot, entry=200.0, current=244.0, tracking=tracking, qty=10.0)
    assert hit and "PROFIT_LOCK" in reason

    tracking = {"entry_price": 200.0, "peak_price": 290.0}
    hit, _, _ = _run(bot, entry=200.0, current=246.0, tracking=tracking, qty=10.0)
    assert not hit


def test_profit_lock_floor_only_ratchets_up(bot):
    # First tick stores the floor; a second tick must never lower it, and a
    # breach of the stored floor exits even if peak context were lost.
    tracking = {"entry_price": 200.0, "peak_price": 290.0}
    hit, _, tracking = _run(bot, entry=200.0, current=250.0, tracking=tracking, qty=10.0)
    assert not hit
    assert tracking["stop_price"] == pytest.approx(245.0)

    hit, reason, _ = _run(bot, entry=200.0, current=244.0, tracking=tracking, qty=10.0)
    assert hit and "PROFIT_LOCK" in reason


def test_armed_winner_cannot_round_trip_to_a_loss(bot):
    # Premium ran +20.5% then collapsed toward entry: the breakeven ratchet
    # exits near entry — the old ladder would have ridden this to the -25%
    # hard backstop (a +20% winner becoming a -25% loser).
    tracking = {"entry_price": 200.0, "peak_price": 241.0}
    hit, reason, _ = _run(bot, entry=200.0, current=199.0, tracking=tracking, qty=5.0)
    assert hit and "PROFIT_LOCK" in reason


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
