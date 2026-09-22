"""The three decisions taken on 2026-09-22, and why each is scoped as it is.

The weekly audit ran for the first time with a COMPARABLE prior snapshot — same
geometry both weeks, so these deltas are real rather than a change of ruler.

1. SessionShift/GOLDM window 630 -> 570. Proposed by Hokage's OWN knob sweep,
   the first proposal the loop has ever produced unaided:
       TRAIN n=94 edge +2.956 t=+2.19  (incumbent +2.061)
       HOLD  n=94 edge +0.439 t=+2.05  (incumbent +0.314)
   Clears t>=2 on BOTH halves AND beats the incumbent on both. Applied PER
   ASSET: SILVERM was measured separately, proposed nothing, and edge does not
   travel between assets.

2. MeanReversion loses BANKNIFTY. Below the bar two consecutive audits on the
   same geometry (-0.56 then -1.26). NIFTY and SENSEX are RETAINED because they
   fell below MIN_N and were never measured — unmeasured is not the same as
   measured badly.

3. NATURALGAS parked. The fade went NEGATIVE out of sample: hold-out +0.98 then
   -0.59. RangeFade is ARCHIVED rather than left with an empty scope, because an
   empty `supported_assets` FAILS OPEN in `_strategy_supports` and would let a
   revived module trade the entire universe.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.strategy.components.mcx_entries import SessionShiftEntry

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "hokage_brain").is_dir())


def _book(name: str) -> dict:
    return json.loads((ROOT / "hokage_brain" / "portfolio" / name)
                      .read_text(encoding="utf-8-sig"))


class _Ctx:
    def __init__(self, symbol, minutes):
        self.symbol, self.minutes_into_session = symbol, minutes
        self.price = self.vwap = 160000.0
        self.ema9, self.ema21 = 160000.0, 160400.0
        self.above_vwap = self.trend_up = False
        self.closes = (160000.0,) * 20
        self.atr = 100.0

    def distance_from_vwap_pct(self):
        return 0.0


# ------------------------------------------------ 1. the GOLDM window
def test_goldm_closes_at_the_measured_hour_and_silverm_does_not():
    assert SessionShiftEntry.WINDOW_END_MIN_BY_ASSET == {"GOLDM": 570}
    assert SessionShiftEntry.WINDOW_END_MIN == 630, (
        "the class default is what an UNMEASURED asset gets and must not drift"
    )


@pytest.mark.parametrize("minutes,fires", [(480, True), (569, True), (570, False), (629, False)])
def test_goldm_stops_firing_at_570(minutes, fires):
    sig = SessionShiftEntry().evaluate(_Ctx("GOLDM", minutes))
    assert sig.should_enter is fires, sig.reason


@pytest.mark.parametrize("minutes,fires", [(569, True), (570, True), (629, True), (630, False)])
def test_silverm_keeps_the_full_window(minutes, fires):
    """GOLDM's evidence must not move SILVERM. Its own sweep proposed nothing."""
    sig = SessionShiftEntry().evaluate(_Ctx("SILVERM", minutes))
    assert sig.should_enter is fires, sig.reason


def test_the_refusal_names_the_asset_s_real_closing_time():
    reason = SessionShiftEntry().evaluate(_Ctx("GOLDM", 600)).reason
    assert "18:30" in reason, reason


# --------------------------------------- 2. MeanReversion loses BANKNIFTY
def test_meanreversion_no_longer_trades_banknifty():
    scope = _book("strategy_portfolio.json")["strategies"][
        "strat-meanreversion-sideways-v1"]["supported_assets"]
    assert "BANKNIFTY" not in scope
    assert {"NIFTY", "SENSEX"} <= set(scope), (
        "NIFTY and SENSEX were never measured, not measured badly — retained"
    )


# ------------------------------------------------- 3. natural gas parked
def test_gas_is_parked_with_the_measurement_in_the_reason():
    assert "NATURALGAS" in Bot.PARKED_ASSETS
    why = Bot.PARKED_ASSETS["NATURALGAS"]
    assert "-0.59" in why and "NEGATIVE" in why


def test_rangefade_is_archived_and_NOT_left_with_an_empty_scope():
    """An empty `supported_assets` FAILS OPEN — it reads as "no restriction
    recorded", not "trades nothing". Emptying it would arm a revived RangeFade
    against the entire universe."""
    rf = _book("mcx_strategy_portfolio.json")["strategies"]["strat-rangefade-mcx-v1"]
    assert rf["status"] == "ARCHIVED"
    assert rf["supported_assets"] == ["NATURALGAS"], rf["supported_assets"]


def test_both_parked_assets_carry_a_stated_reason():
    for asset, why in Bot.PARKED_ASSETS.items():
        assert why and len(why) > 30, f"{asset} is parked without a reason"


# ------------------------------------------------------- the whole lineup
def test_the_arena_has_no_orphan_after_all_three_changes():
    class _M:
        def __init__(self, b): self.portfolio = b

    bot = object.__new__(Bot)
    bot.strategy_portfolio = _M(_book("strategy_portfolio.json"))
    bot.mcx_strategy_portfolio = _M(_book("mcx_strategy_portfolio.json"))
    assert bot.audit_asset_coverage() == []
