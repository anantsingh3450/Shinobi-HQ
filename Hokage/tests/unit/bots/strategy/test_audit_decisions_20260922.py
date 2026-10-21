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
import os
from pathlib import Path

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.strategy.components.mcx_entries import SessionShiftEntry

# The repo root is found by pyproject.toml, NOT by a directory named
# `hokage_brain` -- the brain is relocatable and left the repo on
# 2026-10-09, which killed the whole suite at collection.
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())


def _book(name: str) -> dict:
    # The live portfolio, wherever it lives. Published by conftest.py.
    brain = Path(os.environ["HOKAGE_PRODUCTION_BRAIN"])
    return json.loads((brain / "portfolio" / name)
                      .read_text(encoding="utf-8-sig"))


class _Ctx:
    def __init__(self, symbol, minutes):
        self.symbol, self.minutes_into_session = symbol, minutes
        # SessionShift gates on the WALL CLOCK from 2026-10-20. These
        # cases were all written for a normal 09:00 open, where the
        # two agree exactly, so the clock is derived from the same
        # offset and every assertion below keeps its original meaning.
        self.minute_of_day = None if minutes is None else 9 * 60 + minutes
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


# -------------------------------------- 3. natural gas: parked, then un-parked
def test_gas_is_no_longer_parked_and_the_reversal_is_recorded():
    """REVERSED 2026-10-21 by commander directive, and the measurement that
    justified the original parking is still in the source beside it.

    Gas was parked on 09-22 because the fade went negative out of sample. That
    remains true. Re-measured over the whole archive on 10-21, three horizons:
    RangeFade +1.65/+1.80/+0.22, SessionShift +0.39/+0.38/+0.16, TrendRider
    -0.29/-0.40/-2.03, EventRider -0.41/-1.08/-1.25. Nothing clears t=2, and
    split train/hold RangeFade is +3.11 in sample against -1.91 out of it.

    It trades again to ACCUMULATE A RECORD, not because an edge was found: the
    old gas evidence was destroyed by a futures roll before the candle archive
    existed, and the archive now keeps every bar. Paper money buying a
    measurable history.
    """
    import inspect

    assert "NATURALGAS" not in Bot.PARKED_ASSETS
    src = inspect.getsource(Bot)
    assert "NATURALGAS UN-PARKED 2026-10-21" in src
    assert "-0.239 t-1.91" in src or "-1.91" in src, (
        "the measurement against gas must stay visible beside the reversal")


def test_rangefade_is_live_again_and_still_NOT_left_with_an_empty_scope():
    """Un-archived 2026-10-21. The scope rule is unchanged and still matters
    MORE now, not less: an empty `supported_assets` FAILS OPEN — it reads as
    "no restriction recorded", not "trades nothing" — so a live RangeFade with
    a blank scope would be armed against the entire universe."""
    rf = _book("mcx_strategy_portfolio.json")["strategies"]["strat-rangefade-mcx-v1"]
    assert rf["status"] != "ARCHIVED"
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
