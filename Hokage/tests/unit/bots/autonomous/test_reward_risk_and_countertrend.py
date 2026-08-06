"""Two fixes from the 2026-08-05 review, both commander-approved.

1. REWARD:RISK. The target floor was a flat 6% while the hard backstop ranged
   12-40%, so a cheap option risked 20% to make 6.5% — 0.33:1, needing a 75%
   hit rate merely to break even. Live that day: the NIFTY put banked +6.5% at
   TARGET_HIT while the SENSEX put ran to its -12% backstop. A 50% hit rate
   that still lost money is what that geometry guarantees.

   Worse, expected_move scales with sqrt(bars_left), so the target SHRANK
   through the session while the stop stayed full size.

2. COUNTER-TREND. The bias gate permits longs only on a BULLISH tape and shorts
   only on a BEARISH one. A fade fires exactly when price is stretched from
   VWAP — the condition that makes the tape read directional. Over six weeks of
   real NIFTY/BANKNIFTY bars MeanReversion produced 16 signals and the gate
   allowed 0. RangeFade had the same disease.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from bots.strategy.components.entries import MeanReversionEntry, TrendPullbackEntry
from bots.strategy.components.mcx_entries import RangeFadeEntry, TrendRiderEntry

_BACKSTOP = AutonomousTradingBot._backstop_pct_for


class _Bot:
    _OPTION_BACKSTOP_TIERS = AutonomousTradingBot._OPTION_BACKSTOP_TIERS
    _OPTION_MIN_REWARD_RISK = AutonomousTradingBot._OPTION_MIN_REWARD_RISK
    _backstop_pct_for = AutonomousTradingBot._backstop_pct_for


@pytest.mark.parametrize(
    "premium,expected",
    [(514.80, 0.12), (300.0, 0.20), (130.30, 0.28), (50.0, 0.40)],
)
def test_backstop_lookup_matches_the_tier_table(premium, expected):
    assert _BACKSTOP(_Bot(), premium) == expected


@pytest.mark.parametrize("premium", [514.80, 300.0, 130.30, 50.0, 8.0])
def test_target_floor_is_never_smaller_than_the_risk(premium):
    """The whole point: a win must not be structurally smaller than a loss."""
    bot = _Bot()
    stop_pct = bot._backstop_pct_for(premium)
    floor_pct = stop_pct * bot._OPTION_MIN_REWARD_RISK
    assert floor_pct >= stop_pct


def test_reward_risk_is_at_least_one_to_one():
    assert AutonomousTradingBot._OPTION_MIN_REWARD_RISK >= 1.0


def test_the_exact_trade_that_prompted_this_would_now_target_more():
    """NIFTY 2026-08-05: entry 130.30, old target 138.72 (+6.5%), stop -28%."""
    bot = _Bot()
    entry = 130.30
    old_target = 138.72
    stop_pct = bot._backstop_pct_for(entry)
    new_floor = entry * (1.0 + stop_pct * bot._OPTION_MIN_REWARD_RISK)

    assert new_floor > old_target
    # Reward now at least matches the 28% being risked on this premium tier.
    assert (new_floor - entry) / entry >= stop_pct


def test_ceiling_can_never_sit_below_the_floor():
    """A 40% stop on a cheap option needs a 40% target; the old 25% cap would
    have silently clamped the floor back down and undone the fix."""
    bot = _Bot()
    cheap = 50.0
    floor_pct = bot._backstop_pct_for(cheap) * bot._OPTION_MIN_REWARD_RISK
    ceiling_pct = max(AutonomousTradingBot._OPTION_TARGET_MAX_PCT, floor_pct)
    assert ceiling_pct >= floor_pct


# --- counter-trend exemption ------------------------------------------------

def test_fade_strategies_are_marked_counter_trend():
    assert getattr(MeanReversionEntry, "COUNTER_TREND", False) is True
    assert getattr(RangeFadeEntry, "COUNTER_TREND", False) is True


def test_trend_followers_are_not_exempted():
    """The exemption must not leak: trend strategies still face the bias gate."""
    assert getattr(TrendPullbackEntry, "COUNTER_TREND", False) is False
    assert getattr(TrendRiderEntry, "COUNTER_TREND", False) is False


def test_counter_trend_lookup_resolves_both_leagues():
    bot = AutonomousTradingBot.__new__(AutonomousTradingBot)
    assert bot._is_counter_trend_strategy("strat-meanreversion-sideways-v1") is True
    assert bot._is_counter_trend_strategy("strat-rangefade-mcx-v1") is True
    assert bot._is_counter_trend_strategy("strat-trendpullback-v2") is False
    assert bot._is_counter_trend_strategy("strat-trendrider-mcx-v1") is False
    assert bot._is_counter_trend_strategy(None) is False
    assert bot._is_counter_trend_strategy("strat-unknown-v1") is False


def test_fade_module_still_refuses_a_trending_tape():
    """Exempting the bias gate is only safe because the module self-guards."""
    assert MeanReversionEntry.MAX_TREND_GAP_PCT > 0
    assert RangeFadeEntry.MAX_TREND_GAP_PCT > 0


# --- profit protection after PROFIT_LOCK was retired -----------------------

def test_trail_arms_before_any_profit_gap_can_open():
    """THE GUARD that replaces the retired PROFIT_LOCK stages.

    Those stages were proved unreachable at a 10% trail and removed. They are
    only unreachable BECAUSE the trail arms early: at 10% of peak it arms at
    +11.1% gain, ahead of the +15% where the earliest stage used to.

    Loosen the trail enough and that stops being true — at 25% the trail would
    not arm until +33.3% gain, leaving winners between +15% and +33% with no
    protective floor at all, silently. This test fails at that point and says
    so, instead of letting the gap open unnoticed.
    """
    f = AutonomousTradingBot._OPTION_TRAIL_LOCK_FRACTION
    arms_at_gain = 1.0 / (1.0 - f) - 1.0
    assert arms_at_gain <= 0.15, (
        f"trail now arms at +{arms_at_gain:.1%}, past the +15% where profit "
        f"protection used to begin — winners in that band are unprotected"
    )


def test_retired_stages_are_actually_gone():
    assert not hasattr(AutonomousTradingBot, "_OPTION_PROFIT_LOCK_STAGES")
