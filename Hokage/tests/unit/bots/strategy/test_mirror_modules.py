"""FadeRange and RiderTrend: the same signal, the opposite option, gas only.

COMMANDER'S HYPOTHESIS, 2026-10-23. Where a module's directional call is
wrong, buying the OTHER option on the identical signal should be right. Run
it with paper money on natural gas, beside the originals, and find out.

SUBCLASSES, NOT COPIES, and this file pins that. The instruction was "exact
copy, trading logic will remain same" — and a literal copy guarantees the
opposite inside a month. This codebase has already paid for two copies of
"what counts as Hokage" drifting apart, and the half that drifts is whichever
one nobody ran that week. A subclass overriding nothing but the final
direction cannot drift: every threshold, window, guard and future fix reaches
the mirror on the day it reaches the original, because it IS the original.
Several tests below assert the inheritance rather than the values, so they
keep passing when the originals are retuned — which is the point.

WHY THIS IS NOT -1 x THE ORIGINAL'S P&L, and why the experiment is therefore
worth running rather than deducing. Both modules BUY options. A long call and
a long put are both long premium: both pay theta, both pay the spread, both
lose when the underlying sits still. A mirror can only win where the original
was wrong about DIRECTION — never where it was wrong about MOVEMENT. The pair
separates those two failures, which nothing else in the system can do.
"""
from __future__ import annotations

import pytest

from bots.strategy.components.mcx_entries import (
    MCX_ENTRY_MODULES,
    FadeRangeEntry,
    RangeFadeEntry,
    RiderTrendEntry,
    TrendRiderEntry,
)
from bots.strategy.components.models import MarketContext

_CLOSES = tuple(100.0 + i * 0.05 for i in range(30))
STRONG_UP = tuple(100.0 + i * 0.15 for i in range(30))


def _ctx(minutes, *, symbol="NATURALGAS", ema9=100.5, ema21=99.0,
         vwap=100.0, price=101.0, closes=None):
    c = closes if closes is not None else _CLOSES
    return MarketContext(
        symbol=symbol, price=price, ema9=ema9, ema21=ema21, vwap=vwap,
        closes=c, highs=tuple(x * 1.001 for x in c),
        lows=tuple(x * 0.999 for x in c),
        minutes_into_session=minutes,
        minute_of_day=None if minutes is None else 9 * 60 + minutes,
    )


#: A quiet, overstretched gas tape inside RangeFade's 09:30-17:00 window.
#:
#: A DIP, not a rip, and that detail is load-bearing. RangeFade is scoped
#: LONG-ONLY on gas (+2.53 train / +2.23 hold), so it refuses a short fade
#: there outright — "fading a rip is not scoped on NATURALGAS". Building the
#: fixture the other way up tests a trade neither module ever takes.
def _fadeable():
    # EMAs flat (the gap guard is MAX_TREND_GAP_PCT = 0.12) and price 0.40%
    # under VWAP, past STRETCH_PCT. RangeFade buys the dip; the mirror sells it.
    return _ctx(180, ema9=100.0, ema21=100.0, vwap=100.0, price=99.60)


#: A confirmed evening uptrend inside TrendRider's 17:00-22:30 window.
#: TrendRider joins it LONG; the mirror must take the put.
def _trending():
    return _ctx(600, ema9=101.0, ema21=99.0, vwap=100.0,
                price=STRONG_UP[-1], closes=STRONG_UP)


# ------------------------------------------------------- the flip itself
def test_faderange_takes_the_opposite_side_of_rangefade():
    ctx = _fadeable()
    original = RangeFadeEntry().evaluate(ctx)
    mirror = FadeRangeEntry().evaluate(ctx)
    assert original.should_enter and original.direction == "long"
    assert mirror.should_enter and mirror.direction == "short"


def test_ridertrend_takes_the_opposite_side_of_trendrider():
    ctx = _trending()
    original = TrendRiderEntry().evaluate(ctx)
    mirror = RiderTrendEntry().evaluate(ctx)
    assert original.should_enter and original.direction == "long"
    assert mirror.should_enter and mirror.direction == "short"


@pytest.mark.parametrize("mirror,original,ctx_fn", [
    (FadeRangeEntry, RangeFadeEntry, _fadeable),
    (RiderTrendEntry, TrendRiderEntry, _trending),
])
def test_the_mirror_fires_exactly_when_its_original_fires(mirror, original, ctx_fn):
    """Not more often and not less. The flip happens AFTER the parent has
    finished, so every gate the original passes, the mirror passed too."""
    ctx = ctx_fn()
    assert mirror().evaluate(ctx).should_enter is original().evaluate(ctx).should_enter


@pytest.mark.parametrize("mirror,original,minutes", [
    (FadeRangeEntry, RangeFadeEntry, 600),     # outside the quiet window
    (RiderTrendEntry, TrendRiderEntry, 420),   # before the evening window
])
def test_a_mirror_stands_aside_wherever_its_original_does(mirror, original, minutes):
    ctx = _ctx(minutes, ema9=101.0, ema21=99.0, vwap=100.0, price=100.35)
    assert not original().evaluate(ctx).should_enter
    assert not mirror().evaluate(ctx).should_enter


def test_the_original_reason_survives_inside_the_mirrors(caplog):
    """The mirror must not hide WHY the trade was taken. The journal, the
    gate tally and `why` all read these strings."""
    sig = RiderTrendEntry().evaluate(_trending())
    assert "MIRROR of LONG" in sig.reason
    assert "confirmed uptrend" in sig.reason, "the original thesis must survive"
    assert "2026-10-23" in sig.reason, "the hypothesis must name its date"


def test_a_stand_aside_keeps_the_originals_words_unchanged():
    """A refusal is the original's refusal. Rewording it would land in the
    UNCLASSIFIED bucket of gate_analytics, the one bucket that must stay
    easy to see."""
    ctx = _ctx(600, ema9=101.0, ema21=99.0, vwap=100.0, price=100.35)
    assert (FadeRangeEntry().evaluate(ctx).reason
            == RangeFadeEntry().evaluate(ctx).reason)


def test_confidence_is_carried_across_unchanged():
    """The auction ranks on confidence. A mirror that inflated its own would
    steal the asset from the module it is being compared against."""
    ctx = _trending()
    assert (RiderTrendEntry().evaluate(ctx).confidence
            == TrendRiderEntry().evaluate(ctx).confidence)


# ------------------------------------------------------------- gas only
@pytest.mark.parametrize("mirror", [FadeRangeEntry, RiderTrendEntry])
@pytest.mark.parametrize("asset", ["GOLDM", "SILVERM", "CRUDEOIL", "NIFTY"])
def test_the_mirrors_refuse_every_asset_but_gas(mirror, asset):
    """Scoped by the commander to natural gas. Enforced in the module as
    well as in supported_assets, because an empty scope FAILS OPEN in
    _strategy_supports and a mirror armed against the whole universe would
    be an experiment nobody authorised."""
    ctx = _ctx(600, symbol=asset, ema9=101.0, ema21=99.0, vwap=100.0,
               price=STRONG_UP[-1], closes=STRONG_UP)
    sig = mirror().evaluate(ctx)
    assert not sig.should_enter
    assert "scoped to NATURALGAS only" in sig.reason


def test_gas_is_recognised_however_it_is_spelled():
    ctx = _ctx(600, symbol="natural_gas", ema9=101.0, ema21=99.0,
               vwap=100.0, price=STRONG_UP[-1], closes=STRONG_UP)
    assert RiderTrendEntry().evaluate(ctx).should_enter


# ------------------------------------- it is the original, not a copy of it
@pytest.mark.parametrize("mirror,original", [
    (FadeRangeEntry, RangeFadeEntry),
    (RiderTrendEntry, TrendRiderEntry),
])
def test_a_mirror_is_a_subclass_so_the_logic_cannot_drift(mirror, original):
    """THE LOAD-BEARING TEST. If someone ever replaces these with copied
    classes, this fails — and the reason it matters is written in this
    codebase's history: two copies of one rule drift apart, and nobody
    notices until the half that drifted is the half being measured."""
    assert issubclass(mirror, original)


@pytest.mark.parametrize("mirror,original,fields", [
    (FadeRangeEntry, RangeFadeEntry,
     ("WINDOW_START_MIN", "WINDOW_END_MIN", "STRETCH_PCT", "MAX_TREND_GAP_PCT")),
    (RiderTrendEntry, TrendRiderEntry,
     ("WINDOW_START_MIN", "WINDOW_END_MIN")),
])
def test_every_tuned_value_is_inherited_rather_than_restated(mirror, original, fields):
    """Asserts the IDENTITY, not the values, so retuning an original keeps
    these green while still proving the mirror followed it."""
    for field in fields:
        assert getattr(mirror, field) is getattr(original, field), field


def test_faderange_inherits_the_counter_trend_exemption():
    """RangeFade skips the directional veto because it bets against the move.
    Its mirror bets WITH the move — but it fires on the same bars, where the
    tape still reads directional, so the veto would refuse it for the same
    structural reason. Inheriting the flag keeps the pair comparable, which
    is the entire point of running them side by side."""
    assert FadeRangeEntry.COUNTER_TREND is True


def test_a_mirror_inherits_its_parents_direction_scoping():
    """THIS TEST FOUND A REAL BUG IN THE FIRST VERSION, 2026-10-23.

    _MirrorEntry originally set DIRECTION_BY_ASSET = {}, reasoning that the
    parent had already applied its own scoping. `_direction_allowed` reads
    the scoping off `self`, and inside a parent method `self` is the CHILD —
    so the empty dict silently switched the parent's measured scoping OFF.
    FadeRange fired on the short-fade signals RangeFade refuses on gas, which
    would have made the mirror trade MORE OFTEN than the module it mirrors
    and quietly destroyed the comparison the experiment exists for."""
    assert FadeRangeEntry.DIRECTION_BY_ASSET == RangeFadeEntry.DIRECTION_BY_ASSET
    assert RangeFadeEntry.DIRECTION_BY_ASSET == {"NATURALGAS": "long"}


def test_the_mirror_refuses_a_side_its_original_is_not_scoped_for():
    """The consequence, as behaviour rather than configuration: a rip on gas
    is a short fade, RangeFade is long-only there, so NEITHER trades it."""
    rip = _ctx(180, ema9=100.1, ema21=100.0, vwap=100.0, price=100.35)
    assert not RangeFadeEntry().evaluate(rip).should_enter
    mirror = FadeRangeEntry().evaluate(rip)
    assert not mirror.should_enter
    assert "not scoped" in mirror.reason


def test_the_originals_are_untouched_by_any_of_this():
    """An experiment that changes its own control proves nothing."""
    assert not issubclass(RangeFadeEntry, FadeRangeEntry)
    assert RangeFadeEntry().evaluate(_fadeable()).direction == "long"
    assert TrendRiderEntry().evaluate(_trending()).direction == "long"


# --------------------------------------------------------------- plumbing
def test_both_mirrors_are_registered_so_the_labs_can_see_them():
    assert MCX_ENTRY_MODULES["strat-faderange-mcx-v1"].module_id == "entry-faderange-mcx-v1"
    assert MCX_ENTRY_MODULES["strat-ridertrend-mcx-v1"].module_id == "entry-ridertrend-mcx-v1"


def test_no_two_modules_share_a_module_id():
    """Every lab keys its results by module_id. A duplicate would silently
    score one strategy on another's signals."""
    ids = [m.module_id for m in MCX_ENTRY_MODULES.values()]
    assert len(set(ids)) == len(ids), sorted(ids)


def test_a_mirror_never_guesses_at_a_direction_it_cannot_invert():
    """Fails closed. Only long and short have an opposite; anything else
    stands the entry down rather than picking a side."""
    from bots.strategy.components.mcx_entries import _OPPOSITE
    from bots.strategy.components.models import EntrySignal

    assert _OPPOSITE == {"long": "short", "short": "long"}

    class _Sideways(FadeRangeEntry):
        def evaluate(self, ctx):
            return _MirrorEntry.evaluate(self, ctx)

        def _parent(self, ctx):
            return EntrySignal(True, "sideways", "nonsense", confidence=50.0)

    from bots.strategy.components.mcx_entries import _MirrorEntry, RangeFadeEntry as _RF
    original = _RF.evaluate
    try:
        _RF.evaluate = lambda self, ctx: EntrySignal(
            True, "sideways", "nonsense", confidence=50.0)
        sig = FadeRangeEntry().evaluate(_fadeable())
        assert not sig.should_enter
        assert "cannot mirror direction" in sig.reason
    finally:
        _RF.evaluate = original
