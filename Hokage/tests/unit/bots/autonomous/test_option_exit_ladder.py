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
    # Rewritten 2026-08-05. The target floor is no longer a flat +6% with a
    # +25% ceiling; it is the position's OWN backstop times the minimum
    # reward:risk. Entry 200 sits in the 20% backstop tier, so at 1.5:1 the
    # floor is +30% (260.0) and the ceiling is +60%. The old numbers asserted a
    # target Hokage must no longer take: banking +25% while risking 20% needs a
    # 44% hit rate, and the measured directional read is ~47%.
    hit, reason, out = _run(bot, entry=200.0, current=320.1, tracking=dict(tracking))
    assert hit and "TARGET_HIT" in reason
    # Premium below the floor can never trigger a target exit.
    hit, reason, out = _run(bot, entry=200.0, current=205.0, tracking=dict(tracking))
    assert not hit
    assert out["target_price"] >= 260.0  # entry * (1 + 0.20 * 1.5)


def test_trail_lock_exits_at_ten_percent_off_peak(bot):
    """Rewritten 2026-08-06. These five tests were built on a flat Rs 1,000
    giveback and used `qty` as the lever that kept TRAIL_LOCK dark — a lever
    that no longer exists, because the trail is now a fraction of PEAK premium
    and quantity does not enter into it.

    They now assert the effective protective FLOOR and the invariant that
    matters, rather than which rung's label happened to produce it. That is the
    honest test: the commander's directive was "in profit must not become a
    loss, but leave room for option volatility", and a floor satisfies or
    violates that regardless of its name.
    """
    # Peak 240 -> floor 216.0. Quantity is irrelevant now; 75 and 5 must agree.
    for qty in (75.0, 5.0):
        tracking = {"entry_price": 200.0, "peak_price": 240.0}
        hit, reason, out = _run(bot, entry=200.0, current=215.0, tracking=tracking, qty=qty)
        assert hit and "TRAIL_LOCK" in reason
        assert out["stop_price"] == pytest.approx(216.0)

    # Above the floor: still riding.
    tracking = {"entry_price": 200.0, "peak_price": 240.0}
    hit, _, _ = _run(bot, entry=200.0, current=220.0, tracking=tracking, qty=75.0)
    assert not hit


def test_trail_stays_dark_until_its_floor_clears_entry(bot):
    """Below that the trail must not exist at all, or it would place a floor
    UNDER entry and turn a winner into a loser."""
    # Peak +5%: 210 * 0.90 = 189, below the 200 entry -> not armed.
    tracking = {"entry_price": 200.0, "peak_price": 210.0}
    hit, _, out = _run(bot, entry=200.0, current=205.0, tracking=tracking, qty=75.0)
    assert not hit
    assert out.get("stop_price") is None or out["stop_price"] >= 200.0


def test_the_protective_floor_only_ever_ratchets_up(bot):
    tracking = {"entry_price": 200.0, "peak_price": 290.0}
    hit, _, tracking = _run(bot, entry=200.0, current=270.0, tracking=tracking, qty=10.0)
    assert not hit
    first_floor = tracking["stop_price"]
    assert first_floor == pytest.approx(261.0)          # 290 * 0.90

    # A lower tick must never lower the stored floor, and breaching it exits.
    hit, reason, _ = _run(bot, entry=200.0, current=260.0, tracking=tracking, qty=10.0)
    assert hit
    assert tracking["stop_price"] >= first_floor


def test_an_armed_winner_can_never_round_trip_to_a_loss(bot):
    """The invariant the whole rung exists for. A premium that ran +20.5% and
    collapsed toward entry must exit at or above entry, never ride to the
    backstop."""
    tracking = {"entry_price": 200.0, "peak_price": 241.0}
    hit, reason, out = _run(bot, entry=200.0, current=199.0, tracking=tracking, qty=5.0)
    assert hit
    assert out["stop_price"] >= 200.0


def test_bigger_winners_keep_progressively_more(bot):
    """A runner must not be handed back the same rupees as a small winner."""
    small = _run(bot, entry=200.0, current=210.0,
                 tracking={"entry_price": 200.0, "peak_price": 240.0}, qty=10.0)[2]["stop_price"]
    large = _run(bot, entry=200.0, current=210.0,
                 tracking={"entry_price": 200.0, "peak_price": 400.0}, qty=10.0)[2]["stop_price"]
    assert large > small


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
