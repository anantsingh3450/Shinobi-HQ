"""A module's two sides are two different bets. Scope them separately.

MEASURED 2026-08-26, full geometry (the production 1.25 ATR thesis stop applied
bar by bar on the low/high, not the close), train 2026-05..06 against a disjoint
hold-out 2026-07..08:

    SessionShift  GOLDM       long   -0.93 / -0.76   NEGATIVE ON BOTH HALVES
                              short  +1.48 / +2.52
    SessionShift  SILVERM     long   +1.12 / -0.86   negative out of sample
                              short  +0.99 / +2.94
    RangeFade     NATURALGAS  long   +2.53 / +2.23   CONFIRMED
                              short  -0.29 / +2.54   halves contradict

Two of today's three live pairs were paying for a side that measured negative,
and there was no way to say so: Hokage could express "this module, this asset"
but never "this module, this asset, this side". Both of 2026-08-26's losses were
SessionShift/GOLDM — on the winning side, as it happens, but the module was
carrying a losing half all day regardless.

THE DRIFT CHECK, WHICH IS WHY THIS IS NOT JUST A TREND IN DISGUISE. A one-sided
result usually means the period trended that way. So the underlying drift was
measured per half, and it FLIPS SIGN between them:

    GOLDM       train  -7.01%   hold  +6.27%
    SILVERM     train  -8.74%   hold  +3.58%
    NATURALGAS  train  +5.02%   hold -14.16%

Every surviving side wins on the half whose drift ran AGAINST it — gas longs
profit through a 14% collapse, metal shorts profit through a 6% rally. A trend
artifact does the opposite.

WHAT THIS IS NOT. Restricting direction removes a measured loser; it does not
confirm the survivor. Neither metal's short side clears t>=2 on train, so
SessionShift stays unconfirmed. Only RangeFade/NATURALGAS/long clears both.
"""
from __future__ import annotations

import pytest

from bots.strategy.components.mcx_entries import (
    RangeFadeEntry,
    SessionShiftEntry,
    _direction_allowed,
)


# ------------------------------------------------------- the shipped scoping
def test_gas_fades_dips_only():
    assert RangeFadeEntry.DIRECTION_BY_ASSET == {"NATURALGAS": "long"}


def test_both_metals_are_short_only():
    assert SessionShiftEntry.DIRECTION_BY_ASSET == {
        "GOLDM": "short", "SILVERM": "short",
    }


@pytest.mark.parametrize("module,asset,keep,drop", [
    (RangeFadeEntry(), "NATURALGAS", "long", "short"),
    (SessionShiftEntry(), "GOLDM", "short", "long"),
    (SessionShiftEntry(), "SILVERM", "short", "long"),
])
def test_the_measured_side_is_kept_and_the_other_refused(module, asset, keep, drop):
    assert _direction_allowed(module, asset, keep)
    assert not _direction_allowed(module, asset, drop)


def test_an_asset_with_no_entry_may_still_take_both_sides():
    """Absence means unmeasured, not forbidden. A new asset must not arrive
    silently unable to trade — that failure is invisible, which is why
    audit_asset_coverage exists at all."""
    for side in ("long", "short"):
        assert _direction_allowed(SessionShiftEntry(), "CRUDEOIL", side)
        assert _direction_allowed(RangeFadeEntry(), "GOLDM", side)


def test_the_lookup_is_case_insensitive():
    assert not _direction_allowed(SessionShiftEntry(), "goldm", "long")


# -------------------------------------------------- the gate inside evaluate
class _Ctx:
    """Enough MarketContext for the two gates under test."""

    def __init__(self, symbol, price, vwap, ema9, ema21, minutes, above, up):
        self.symbol = symbol
        self.price = price
        self.vwap = vwap
        self.ema9 = ema9
        self.ema21 = ema21
        self.minutes_into_session = minutes
        self.above_vwap = above
        self.trend_up = up
        self.closes = [price] * 20

    def distance_from_vwap_pct(self):
        return (self.price - self.vwap) / self.vwap * 100.0


def _gas(stretch_pct):
    """A quiet, rangebound gas tape stretched by `stretch_pct` from VWAP."""
    vwap = 300.0
    price = vwap * (1.0 + stretch_pct / 100.0)
    return _Ctx("NATURALGAS", price, vwap, 300.0, 300.05, 200,
                above=stretch_pct > 0, up=False)


def test_gas_still_buys_a_dip():
    sig = RangeFadeEntry().evaluate(_gas(-0.40))
    assert sig.should_enter and sig.direction == "long"


def test_gas_no_longer_sells_a_rip():
    sig = RangeFadeEntry().evaluate(_gas(+0.40))
    assert not sig.should_enter
    assert "not scoped" in sig.reason


def _metal(symbol, up):
    return _Ctx(symbol, 160000.0, 160000.0, 160000.0, 160200.0, 500,
                above=up, up=up)


@pytest.mark.parametrize("symbol", ["GOLDM", "SILVERM"])
def test_metals_still_take_the_short(symbol):
    sig = SessionShiftEntry().evaluate(_metal(symbol, up=False))
    assert sig.should_enter and sig.direction == "short"


@pytest.mark.parametrize("symbol", ["GOLDM", "SILVERM"])
def test_metals_no_longer_take_the_long(symbol):
    sig = SessionShiftEntry().evaluate(_metal(symbol, up=True))
    assert not sig.should_enter
    assert "not scoped" in sig.reason


def test_the_refusal_says_which_side_and_why():
    """A stand-aside nobody can read is a stand-aside nobody can audit — the
    gate tally ranks blockers by this text."""
    reason = SessionShiftEntry().evaluate(_metal("GOLDM", up=True)).reason
    assert "long" in reason and "GOLDM" in reason and "negative" in reason


# ------------------------------------------------------- the guard that moved
def test_the_gas_trend_guard_is_scoped_to_gas_alone():
    """0.12 -> 0.10 was measured on NATURALGAS only. A class-level change would
    have moved every asset RangeFade ever trades, which is the mistake the
    per-asset stretch table was created to prevent."""
    assert RangeFadeEntry.MAX_TREND_GAP_PCT_BY_ASSET == {"NATURALGAS": 0.10}
    assert RangeFadeEntry.MAX_TREND_GAP_PCT == 0.12, (
        "the class default is what an UNMEASURED asset gets and must not drift"
    )


def test_a_trending_gas_tape_is_still_refused():
    ctx = _gas(-0.40)
    ctx.ema9, ctx.ema21 = 300.0, 300.60   # 0.20% gap, above the 0.10% bar
    sig = RangeFadeEntry().evaluate(ctx)
    assert not sig.should_enter
    assert "trending" in sig.reason
