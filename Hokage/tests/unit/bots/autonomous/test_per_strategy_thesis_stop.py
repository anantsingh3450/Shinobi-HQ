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

Commander-approved 2026-08-13: SessionShift to 3.0 ATR, MeanReversion to 2.5.
RangeFade and MacroBreakout stay at 1.25 because the tight stop measured
OPTIMAL for them — a blanket "the stops are too tight" change would have made
those two worse, which is the entire reason the table is per-strategy.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


@pytest.fixture
def bot():
    return object.__new__(Bot)


def test_the_approved_values_are_exactly_what_was_measured(bot):
    """Commander-approved 2026-08-13. MeanReversion widens on every index;
    SessionShift widens ONLY on gold."""
    for index in ("NIFTY", "BANKNIFTY", "SENSEX"):
        assert bot._thesis_atr_mult_for("strat-meanreversion-sideways-v1", index) == 2.5
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1", "GOLDM") == 3.0


def test_silver_did_NOT_inherit_golds_stop(bot):
    """The measurement that made this table per-asset.

    stop_lab, measuring the stop with a TIME exit, said SessionShift was better
    at 3.0 on both its assets. Production also floors the target at 1.5x the
    risk the stop creates, and measured TOGETHER the assets separate:

        GOLDM    1.25 +0.069  ->  3.0 +0.355
        SILVERM  1.25 +0.007  ->  3.0 -0.061   (negative at 2.0 and 2.5 too)

    One value per strategy would have shipped a measured-NEGATIVE stop onto
    silver on the strength of gold's numbers — "edge does not travel between
    assets" reappearing in a new place.
    """
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1", "SILVERM") == 1.25
    assert ("strat-sessionshift-mcx-v1", "SILVERM") not in Bot._THESIS_ATR_MULT_BY_STRATEGY_ASSET
    assert "strat-sessionshift-mcx-v1" not in Bot._THESIS_ATR_MULT_BY_STRATEGY


def test_asset_scope_beats_strategy_scope(bot, monkeypatch):
    monkeypatch.setattr(Bot, "_THESIS_ATR_MULT_BY_STRATEGY", {"s": 2.0})
    monkeypatch.setattr(Bot, "_THESIS_ATR_MULT_BY_STRATEGY_ASSET", {("s", "GOLDM"): 3.0})
    assert bot._thesis_atr_mult_for("s", "GOLDM") == 3.0
    assert bot._thesis_atr_mult_for("s", "SILVERM") == 2.0
    assert bot._thesis_atr_mult_for("s") == 2.0


def test_asset_matching_is_case_insensitive(bot):
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1", "goldm") == 3.0
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1", "GoldM") == 3.0


def test_a_missing_symbol_never_grants_the_widened_stop(bot):
    """If the underlying is unknown the position must get the DEFAULT stop, not
    an asset-scoped widening it may not qualify for. Fail safe, always tighter
    when in doubt."""
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1", None) == 1.25
    assert bot._thesis_atr_mult_for("strat-sessionshift-mcx-v1", "") == 1.25


def test_the_dashboard_publishes_EVERY_widened_stop(bot):
    """Reporting only the strategy-wide table tells the commander every
    SessionShift position runs 1.25 ATR when gold runs 3.0.

    The first version of this test asserted the substring
    "thesis_stop_atr_mult_by_strategy" appeared in api.py — which passed while
    the asset table was still missing, because the strategy table's key is a
    prefix of the asset table's. Assert on the SHAPE the endpoint builds
    instead, and on every value actually reaching it.
    """
    from hokage.dashboard import api

    source = Path(api.__file__).read_text(encoding="utf-8")
    assert "thesis_stop_atr_mult_by_strategy_asset" in source, (
        "the per-asset stops are not published anywhere"
    )

    rows = [
        {"strategy_id": sid, "asset": asset, "atr_mult": mult}
        for (sid, asset), mult in sorted(Bot._THESIS_ATR_MULT_BY_STRATEGY_ASSET.items())
    ]
    import json

    json.dumps(rows)  # tuple keys are not serialisable; the row form must be
    assert {"strategy_id": "strat-sessionshift-mcx-v1", "asset": "GOLDM",
            "atr_mult": 3.0} in rows

    # Both endpoints that publish an exit ladder must carry it, not just one.
    assert source.count("thesis_stop_atr_mult_by_strategy_asset") == source.count(
        "\"thesis_stop_atr_mult\":"
    )


def test_the_modules_the_tight_stop_HELPS_were_left_alone(bot):
    """RangeFade measured +0.455 t=+2.95 at 1.25 against +0.415 unstopped, and
    MacroBreakout +0.389 t=+2.02 against +0.309. Widening these would make them
    WORSE. A blanket 'stops are too tight' change would have done exactly that,
    which is the whole reason the table is per-strategy.
    """
    assert bot._thesis_atr_mult_for("strat-rangefade-mcx-v1") == 1.25
    assert bot._thesis_atr_mult_for("strat-macrobreakout-commodities-v1") == 1.25
    assert "strat-rangefade-mcx-v1" not in Bot._THESIS_ATR_MULT_BY_STRATEGY
    assert "strat-macrobreakout-commodities-v1" not in Bot._THESIS_ATR_MULT_BY_STRATEGY


def test_every_key_matches_a_REAL_strategy_id_in_the_live_portfolios():
    """A typo here fails silently and invisibly — the strategy simply keeps the
    1.25 default and nobody is told the approved change never took effect.
    Pin the ids against the actual brain state.
    """
    import json
    from pathlib import Path

    # tests/unit/bots/autonomous/<this file> -> parents[4] is the repo root.
    root = Path(__file__).resolve().parents[4]
    base = root / "hokage_brain" / "portfolio"
    if not base.exists():  # pragma: no cover - fresh checkout without state
        pytest.skip("no brain state in this checkout")

    known: set[str] = set()
    for name in ("strategy_portfolio.json", "mcx_strategy_portfolio.json"):
        path = base / name
        if path.exists():
            known |= set(json.loads(path.read_text(encoding="utf-8-sig"))["strategies"])

    ids = set(Bot._THESIS_ATR_MULT_BY_STRATEGY) | {
        sid for sid, _ in Bot._THESIS_ATR_MULT_BY_STRATEGY_ASSET
    }
    for strategy_id in ids:
        assert strategy_id in known, f"{strategy_id} matches no registered strategy"


def test_every_scoped_asset_is_one_the_strategy_actually_trades():
    """A widened stop on an asset the strategy is not scoped to is dead config
    that springs to life the moment scope changes."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    base = root / "hokage_brain" / "portfolio"
    if not base.exists():  # pragma: no cover - fresh checkout without state
        pytest.skip("no brain state in this checkout")

    scope: dict[str, set[str]] = {}
    for name in ("strategy_portfolio.json", "mcx_strategy_portfolio.json"):
        path = base / name
        if path.exists():
            for sid, s in json.loads(path.read_text(encoding="utf-8-sig"))["strategies"].items():
                scope[sid] = {a.upper() for a in (s.get("supported_assets") or [])}

    for (strategy_id, symbol) in Bot._THESIS_ATR_MULT_BY_STRATEGY_ASSET:
        assert symbol in scope.get(strategy_id, set()), (
            f"{strategy_id} carries a stop for {symbol} but is not scoped to it"
        )


def test_archived_strategies_are_not_carrying_widened_stops():
    """Archived modules cannot trade, so an entry for one is dead config that
    will quietly come back to life if it is ever un-archived."""
    ids = set(Bot._THESIS_ATR_MULT_BY_STRATEGY) | {
        sid for sid, _ in Bot._THESIS_ATR_MULT_BY_STRATEGY_ASSET
    }
    for strategy_id in ids:
        assert "trendrider" not in strategy_id
        assert "trendpullback" not in strategy_id
        assert "malfoy" not in strategy_id
        assert "eventrider" not in strategy_id


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
