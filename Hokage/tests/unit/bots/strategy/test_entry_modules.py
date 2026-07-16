"""The four entry engines must hold genuinely different opinions.

If they all fire together the arena measures nothing about entry quality — it
just re-measures the shared signal four times. These tests pin the distinct
hypotheses and the doctrine rule that missing data means stand aside, never a
fabricated verdict.
"""
from __future__ import annotations

import pytest

from bots.strategy.components.entries import (
    ENTRY_MODULES,
    MacroBreakoutEntry,
    MalfoyMomentumEntry,
    MeanReversionEntry,
    TrendPullbackEntry,
)
from bots.strategy.components.models import MarketContext


def _ctx(price, ema9, ema21, vwap, closes=None, highs=None, lows=None, **kw):
    closes = closes or [price] * 30
    highs = highs or [c * 1.001 for c in closes]
    lows = lows or [c * 0.999 for c in closes]
    return MarketContext(
        symbol="NIFTY", price=price, ema9=ema9, ema21=ema21, vwap=vwap,
        closes=tuple(closes), highs=tuple(highs), lows=tuple(lows), **kw
    )


def test_all_four_strategies_have_their_own_entry_engine():
    ids = {m.module_id for m in ENTRY_MODULES.values()}
    assert len(ENTRY_MODULES) == 4
    assert len(ids) == 4, "each strategy must own a distinct entry module"


class TestTrendPullback:
    def test_fires_long_on_dip_into_ema_zone_in_uptrend(self):
        # Uptrend (EMA9 > EMA21), above VWAP, price pulled back into the band.
        sig = TrendPullbackEntry().evaluate(_ctx(price=101.0, ema9=100.5, ema21=99.0, vwap=100.0))
        assert sig.should_enter and sig.direction == "long"

    def test_stands_aside_when_extended_far_above_the_zone(self):
        """The whole idea is buying the dip — not chasing an extended price."""
        sig = TrendPullbackEntry().evaluate(_ctx(price=120.0, ema9=100.5, ema21=99.0, vwap=100.0))
        assert not sig.should_enter

    def test_stands_aside_when_ema_band_is_flat(self):
        sig = TrendPullbackEntry().evaluate(_ctx(price=100.0, ema9=100.0, ema21=100.0, vwap=99.9))
        assert not sig.should_enter and "flat" in sig.reason


class TestMacroBreakout:
    def test_fires_long_only_after_clearing_the_prior_range(self):
        closes = [100.0] * 25
        highs = [101.0] * 25
        lows = [99.0] * 25
        # Live bar pushes decisively through the 20-bar high of 101.
        sig = MacroBreakoutEntry().evaluate(
            _ctx(price=103.0, ema9=101.0, ema21=100.0, vwap=100.5,
                 closes=closes + [103.0], highs=highs + [103.0], lows=lows + [100.5])
        )
        assert sig.should_enter and sig.direction == "long"

    def test_stands_aside_inside_the_range(self):
        closes = [100.0] * 25
        sig = MacroBreakoutEntry().evaluate(
            _ctx(price=100.2, ema9=100.1, ema21=100.0, vwap=100.0,
                 closes=closes + [100.2], highs=[101.0] * 26, lows=[99.0] * 26)
        )
        assert not sig.should_enter and "inside" in sig.reason

    def test_stands_aside_without_enough_bars(self):
        sig = MacroBreakoutEntry().evaluate(
            _ctx(price=100.0, ema9=100.0, ema21=99.0, vwap=99.5,
                 closes=[100.0] * 5, highs=[100.0] * 5, lows=[99.0] * 5)
        )
        assert not sig.should_enter and "need" in sig.reason


class TestMeanReversion:
    def test_fades_a_stretch_above_vwap_on_a_balance_tape(self):
        sig = MeanReversionEntry().evaluate(_ctx(price=100.5, ema9=100.02, ema21=100.0, vwap=100.0))
        assert sig.should_enter and sig.direction == "short"

    def test_refuses_to_fade_a_trending_tape(self):
        """Fading a real trend is how reversion books die — must refuse."""
        sig = MeanReversionEntry().evaluate(_ctx(price=100.5, ema9=101.0, ema21=99.0, vwap=100.0))
        assert not sig.should_enter and "trending" in sig.reason

    def test_stands_aside_when_not_stretched(self):
        sig = MeanReversionEntry().evaluate(_ctx(price=100.05, ema9=100.02, ema21=100.0, vwap=100.0))
        assert not sig.should_enter


class TestMalfoyMomentum:
    def _momentum_ctx(self, **kw):
        closes = [100.0, 100.2, 100.5, 100.8, 101.2]
        # Leave range room above so the meta-label does not veto.
        return _ctx(price=101.2, ema9=101.0, ema21=100.0, vwap=100.5,
                    closes=closes, highs=[103.0] * 5, lows=[99.5] * 5, **kw)

    def test_fires_long_when_ema_vwap_and_roc_all_agree(self):
        sig = MalfoyMomentumEntry().evaluate(self._momentum_ctx(minutes_into_session=60))
        assert sig.should_enter and sig.direction == "long"

    def test_midday_blackout_vetoes_an_otherwise_valid_setup(self):
        sig = MalfoyMomentumEntry().evaluate(self._momentum_ctx(minutes_into_session=180))
        assert not sig.should_enter and "blackout" in sig.reason

    def test_late_session_cutoff_vetoes(self):
        sig = MalfoyMomentumEntry().evaluate(self._momentum_ctx(minutes_into_session=300))
        assert not sig.should_enter and "cutoff" in sig.reason

    def test_high_vix_vetoes_buying_rich_premium(self):
        sig = MalfoyMomentumEntry().evaluate(
            self._momentum_ctx(minutes_into_session=60, vix_percentile=0.9)
        )
        assert not sig.should_enter and "VIX" in sig.reason

    def test_missing_vix_skips_the_guard_rather_than_guessing(self):
        """Doctrine: no data means the gate is skipped, not fabricated."""
        sig = MalfoyMomentumEntry().evaluate(
            self._momentum_ctx(minutes_into_session=60, vix_percentile=None)
        )
        assert sig.should_enter

    def test_meta_label_vetoes_momentum_with_no_range_left(self):
        """Hokage's edge over the source bot: the primary signal fires, but a
        long jammed against the top of its range has no room — veto it."""
        closes = [100.0, 100.5, 101.0, 101.5, 102.0]
        ctx = _ctx(price=102.0, ema9=101.5, ema21=100.0, vwap=100.5,
                   closes=closes, highs=[102.0] * 5, lows=[99.0] * 5,
                   minutes_into_session=60)
        sig = MalfoyMomentumEntry().evaluate(ctx)
        assert not sig.should_enter and "meta-label" in sig.reason


def test_breakout_and_reversion_never_agree_on_the_same_tape():
    """They are opposite bets by construction. If both fire, the tournament is
    measuring noise, not competing hypotheses."""
    closes = [100.0] * 25 + [103.0]
    ctx = _ctx(price=103.0, ema9=100.05, ema21=100.0, vwap=100.0,
               closes=closes, highs=[101.0] * 25 + [103.0], lows=[99.0] * 26)

    breakout = MacroBreakoutEntry().evaluate(ctx)
    reversion = MeanReversionEntry().evaluate(ctx)

    # Same tape, opposite reads: breakout buys the escape, reversion fades it.
    assert breakout.should_enter and breakout.direction == "long"
    assert reversion.should_enter and reversion.direction == "short"
    assert breakout.direction != reversion.direction
