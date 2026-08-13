"""The thesis stop is the most common exit, and its distance was never measured.

Across Hokage's history: THESIS_STOP 23, square-off 12, TARGET_HIT 12, backstop
11, TRAIL_LOCK 9. It is the rule with the most influence on results and 1.25 ATR
was chosen, not measured.

`tools/research/stop_lab.py` measured it on 2026-08-13 at the 60-minute horizon.
One distance does not fit, and the split follows no tidy philosophical line —
two mean-reversion modules land on opposite sides of it:

    RangeFade NATURALGAS    1.25 is OPTIMAL   (+0.455 t=+2.95 vs +0.415 unstopped)
    MacroBreakout BANKNIFTY 1.25 is OPTIMAL   (+0.389 t=+2.02 vs +0.309 unstopped)
    SessionShift GOLDM      1.25 AMPUTATES    (+0.142 t=+1.53 vs +0.327 t=+3.13)

These tests cover the MECHANISM, which ships ahead of any value change: stop
distance is a risk constant and needs explicit commander approval. The table is
empty, so today every strategy still resolves to 1.25 and behaviour is
unchanged.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


@pytest.fixture
def bot():
    return object.__new__(Bot)


def test_the_override_table_ships_EMPTY_so_nothing_changes_yet():
    """Shipping the mechanism must not move a single stop. Values are a
    separate, approved decision."""
    assert Bot._THESIS_ATR_MULT_BY_STRATEGY == {}


def test_every_strategy_resolves_to_the_default_today(bot):
    for strategy_id in (
        "strat-sessionshift-mcx-v1",
        "strat-rangefade-mcx-v1",
        "strat-macrobreakout-v1",
        "strat-meanreversion-v1",
    ):
        assert bot._thesis_atr_mult_for(strategy_id) == 1.25


def test_an_unlisted_strategy_keeps_its_stop_rather_than_losing_it(bot):
    """Fails SAFE, the opposite of `supported_assets` which fails OPEN. An
    absent scope should not mute a strategy; an absent stop distance must never
    leave a position unprotected."""
    assert bot._thesis_atr_mult_for("never-seen-before") == Bot._OPTION_THESIS_ATR_MULT
    assert bot._thesis_atr_mult_for(None) == Bot._OPTION_THESIS_ATR_MULT
    assert bot._thesis_atr_mult_for("") == Bot._OPTION_THESIS_ATR_MULT


def test_an_override_is_actually_honoured(bot, monkeypatch):
    monkeypatch.setattr(
        Bot, "_THESIS_ATR_MULT_BY_STRATEGY", {"strat-sessionshift-mcx-v1": 3.0}
    )
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1") == 3.0
    assert bot._thesis_atr_mult_for("strat-rangefade-mcx-v1") == 1.25


def test_the_target_floor_moves_WITH_the_strategys_stop(bot, monkeypatch):
    """The reward:risk floor is computed from the stop. If a strategy widened
    its stop while the target stayed priced off the 1.25 default, reward:risk
    would silently fall below the 1.5 minimum — the unreachable-target geometry
    that caused the 2026-08-06/07 loss, running in reverse.
    """
    monkeypatch.setattr(Bot, "_THESIS_ATR_MULT_BY_STRATEGY", {"wide": 3.0})

    # A premium high enough that the thesis stop, not the backstop tier, is the
    # binding constraint — otherwise the clamp hides the scaling being tested.
    premium, und_price, atr = 5000.0, 240000.0, 200.0
    narrow = bot._risk_pct_for(premium, und_price, atr, "default-strategy")
    wide = bot._risk_pct_for(premium, und_price, atr, "wide")

    assert wide < bot._backstop_pct_for(premium), "clamp would mask the scaling"
    assert wide > narrow, "a wider stop must report MORE risk, not the same"
    # 3.0 / 1.25 = 2.4x the underlying move, and the conversion is linear.
    assert wide == pytest.approx(narrow * (3.0 / 1.25), rel=1e-6)


def test_a_wide_stop_hands_protection_to_the_premium_backstop(bot, monkeypatch):
    """The warning in the table, encoded. On a cheap option a 3.0 ATR thesis
    stop prices past the hard premium cap, so the cap — not the thesis stop —
    becomes what actually protects the account. Whoever widens a stop must know
    they are changing WHICH RUNG does the protecting, not just how far it sits.
    """
    monkeypatch.setattr(Bot, "_THESIS_ATR_MULT_BY_STRATEGY", {"wide": 3.0})

    premium, und_price, atr = 100.0, 25000.0, 30.0
    narrow = bot._risk_pct_for(premium, und_price, atr, "default-strategy")
    wide = bot._risk_pct_for(premium, und_price, atr, "wide")
    backstop = bot._backstop_pct_for(premium)

    assert narrow < backstop, "at 1.25 ATR the thesis stop is still the binding rung"
    assert wide == backstop, "at 3.0 ATR the backstop has taken over"


def test_risk_is_still_clamped_by_the_premium_backstop(bot, monkeypatch):
    """Widening the thesis stop must NOT let reported risk exceed the hard
    premium cap. Past 2.5-3.0 ATR the thesis stop rarely fires and the backstop
    becomes the real floor — the arithmetic has to reflect that."""
    monkeypatch.setattr(Bot, "_THESIS_ATR_MULT_BY_STRATEGY", {"absurd": 50.0})
    premium, und_price, atr = 100.0, 25000.0, 30.0
    risk = bot._risk_pct_for(premium, und_price, atr, "absurd")
    assert risk == bot._backstop_pct_for(premium)


def test_missing_ATR_still_falls_back_to_the_backstop(bot):
    """No ATR means no thesis stop to price, whatever the strategy. Never
    guess a stop distance from nothing."""
    assert bot._risk_pct_for(100.0, 25000.0, None, "anything") == bot._backstop_pct_for(100.0)
    assert bot._risk_pct_for(100.0, 25000.0, 0.0, "anything") == bot._backstop_pct_for(100.0)


def test_default_call_without_a_strategy_is_unchanged(bot):
    """Existing callers that pass no strategy_id must behave exactly as before,
    which is what makes this refactor safe to ship."""
    premium, und_price, atr = 100.0, 25000.0, 30.0
    assert bot._risk_pct_for(premium, und_price, atr) == bot._risk_pct_for(
        premium, und_price, atr, None
    )
