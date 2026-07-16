"""The four competing entry engines.

Each implements a genuinely different market hypothesis. This is the point of
the Dojo: if every strategy fires on the same signal, the tournament measures
nothing about entry quality — only exits and sizing. Each module reads the same
MarketContext (identical live data) and reaches its own verdict, so the arena
can attribute MFE back to a specific idea.

Nothing here fabricates data: a module with insufficient bars stands aside.
"""
from __future__ import annotations

from bots.strategy.components.models import EntrySignal, MarketContext


class TrendPullbackEntry:
    """Join an established trend on a dip — never chase the top.

    Hypothesis: in a trending tape, a shallow pullback into the EMA band is a
    discount, not a reversal. Requires the trend (EMA9 > EMA21), price still on
    the right side of session VWAP, and price to have actually pulled back
    toward the EMA band rather than extended away from it.
    """

    module_id = "entry-trendpullback-v1"

    #: A pullback is "in the zone" when price sits within this multiple of the
    #: EMA9/EMA21 gap from EMA9. Wider = looser entries.
    ZONE_MULT = 1.0
    #: Ignore a band this tight — a flat EMA gap means no trend to join.
    MIN_GAP_PCT = 0.05

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        gap = abs(ctx.ema9 - ctx.ema21)
        gap_pct = (gap / ctx.price * 100.0) if ctx.price else 0.0
        if gap_pct < self.MIN_GAP_PCT:
            return EntrySignal.stand_aside(
                f"TrendPullback: EMA band flat ({gap_pct:.3f}%) — no trend to join."
            )

        zone = gap * self.ZONE_MULT
        if ctx.trend_up and ctx.above_vwap:
            # Pulled back to within the EMA zone (but not broken below EMA21).
            if ctx.ema21 <= ctx.price <= ctx.ema9 + zone:
                depth = abs(ctx.price - ctx.ema9) / gap if gap else 0.0
                return EntrySignal(
                    True, "long",
                    f"TrendPullback: uptrend (EMA9 {ctx.ema9:.2f} > EMA21 {ctx.ema21:.2f}), "
                    f"price {ctx.price:.2f} above VWAP {ctx.vwap:.2f}, pulled into EMA zone.",
                    confidence=max(55.0, 85.0 - depth * 20.0),
                )
            return EntrySignal.stand_aside("TrendPullback: uptrend intact but price not in the pullback zone.")

        if (not ctx.trend_up) and (not ctx.above_vwap):
            if ctx.ema9 - zone <= ctx.price <= ctx.ema21:
                depth = abs(ctx.price - ctx.ema9) / gap if gap else 0.0
                return EntrySignal(
                    True, "short",
                    f"TrendPullback: downtrend (EMA9 {ctx.ema9:.2f} < EMA21 {ctx.ema21:.2f}), "
                    f"price {ctx.price:.2f} below VWAP {ctx.vwap:.2f}, rallied into EMA zone.",
                    confidence=max(55.0, 85.0 - depth * 20.0),
                )
            return EntrySignal.stand_aside("TrendPullback: downtrend intact but price not in the rally zone.")

        return EntrySignal.stand_aside("TrendPullback: EMA and VWAP disagree — tape is mixed.")


class MacroBreakoutEntry:
    """Buy the break of a established range — catch the move's ignition.

    Hypothesis: price escaping a multi-bar range with conviction continues.
    Deliberately the opposite bet to MeanReversion, so the two can never both
    be right on the same tape — which is exactly what makes the tournament
    informative.
    """

    module_id = "entry-macrobreakout-v1"

    LOOKBACK = 20
    #: Break must clear the range edge by this margin to filter noise ticks.
    MARGIN_PCT = 0.05

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        if len(ctx.highs) < self.LOOKBACK + 1 or len(ctx.lows) < self.LOOKBACK + 1:
            return EntrySignal.stand_aside(
                f"MacroBreakout: need {self.LOOKBACK + 1} bars, have {len(ctx.highs)}."
            )

        # Exclude the live bar from the range it is trying to break.
        prior_high = max(ctx.highs[-(self.LOOKBACK + 1):-1])
        prior_low = min(ctx.lows[-(self.LOOKBACK + 1):-1])
        margin = ctx.price * (self.MARGIN_PCT / 100.0)

        if ctx.price > prior_high + margin:
            extension = (ctx.price - prior_high) / prior_high * 100.0 if prior_high else 0.0
            return EntrySignal(
                True, "long",
                f"MacroBreakout: price {ctx.price:.2f} cleared {self.LOOKBACK}-bar high "
                f"{prior_high:.2f} by {extension:.2f}%.",
                confidence=min(85.0, 60.0 + extension * 10.0),
            )
        if ctx.price < prior_low - margin:
            extension = (prior_low - ctx.price) / prior_low * 100.0 if prior_low else 0.0
            return EntrySignal(
                True, "short",
                f"MacroBreakout: price {ctx.price:.2f} broke {self.LOOKBACK}-bar low "
                f"{prior_low:.2f} by {extension:.2f}%.",
                confidence=min(85.0, 60.0 + extension * 10.0),
            )
        return EntrySignal.stand_aside(
            f"MacroBreakout: price {ctx.price:.2f} still inside {prior_low:.2f}-{prior_high:.2f} range."
        )


class MeanReversionEntry:
    """Fade the extreme — bet price snaps back to fair value.

    Hypothesis: on a balance (non-trending) day, a large stretch from session
    VWAP is an overreaction. Explicitly refuses to fire when a trend exists:
    fading a real trend is how mean-reversion books blow up.
    """

    module_id = "entry-meanreversion-v1"

    #: Stretch from VWAP (in %) that counts as an overreaction worth fading.
    STRETCH_PCT = 0.35
    #: Above this EMA gap the tape is trending — do not fade it.
    MAX_TREND_GAP_PCT = 0.15

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        gap_pct = (abs(ctx.ema9 - ctx.ema21) / ctx.price * 100.0) if ctx.price else 0.0
        if gap_pct > self.MAX_TREND_GAP_PCT:
            return EntrySignal.stand_aside(
                f"MeanReversion: tape is trending (EMA gap {gap_pct:.3f}%) — refusing to fade it."
            )

        stretch = ctx.distance_from_vwap_pct()
        if stretch >= self.STRETCH_PCT:
            return EntrySignal(
                True, "short",
                f"MeanReversion: price {ctx.price:.2f} stretched +{stretch:.2f}% above VWAP "
                f"{ctx.vwap:.2f} on a balance tape — fading back to fair value.",
                confidence=min(80.0, 55.0 + stretch * 20.0),
            )
        if stretch <= -self.STRETCH_PCT:
            return EntrySignal(
                True, "long",
                f"MeanReversion: price {ctx.price:.2f} stretched {stretch:.2f}% below VWAP "
                f"{ctx.vwap:.2f} on a balance tape — fading back to fair value.",
                confidence=min(80.0, 55.0 + abs(stretch) * 20.0),
            )
        return EntrySignal.stand_aside(
            f"MeanReversion: price only {stretch:+.2f}% from VWAP — not stretched enough."
        )


class MalfoyMomentumEntry:
    """Conduct-gated intraday momentum, derived from the Malfoy benchmark bot.

    Hypothesis: momentum works, but only inside the hours where it works and
    only when volatility is not already priced in. The source bot's measured
    edge was discipline, not signal exotica. Hokage's additions (the meta-label
    filter and the VIX veto) are what this competitor must prove are an upgrade
    rather than a handicap.
    """

    module_id = "entry-malfoy-momentum-v1"

    #: Rate-of-change over this many bars must confirm the EMA/VWAP alignment.
    ROC_BARS = 4
    MIN_ROC_PCT = 0.10
    #: India VIX percentile above which option premium is too rich to buy.
    VIX_BLOCK_PCTILE = 0.80
    #: Chop window (minutes into session) the source bot measured as a leak.
    BLACKOUT_START_MIN = 135  # 11:30 for a 09:15 open
    BLACKOUT_END_MIN = 255    # 13:30
    #: No fresh risk late in the session.
    LATE_CUTOFF_MIN = 285     # 14:00

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        # Conduct gates first: a setup inside a bad window is not a setup.
        m = ctx.minutes_into_session
        if m is not None:
            if self.BLACKOUT_START_MIN <= m < self.BLACKOUT_END_MIN:
                return EntrySignal.stand_aside("Malfoy: midday blackout (11:30-13:30) — measured chop.")
            if m >= self.LATE_CUTOFF_MIN:
                return EntrySignal.stand_aside("Malfoy: past the 14:00 cutoff — no fresh risk late.")

        # VIX veto: when volatility is already rich, long premium is a bad buy.
        # None means no data — the guard is skipped, never guessed.
        if ctx.vix_percentile is not None and ctx.vix_percentile >= self.VIX_BLOCK_PCTILE:
            return EntrySignal.stand_aside(
                f"Malfoy: India VIX at {ctx.vix_percentile:.0%} percentile — premium too rich."
            )

        if len(ctx.closes) < self.ROC_BARS + 1:
            return EntrySignal.stand_aside(
                f"Malfoy: need {self.ROC_BARS + 1} bars, have {len(ctx.closes)}."
            )

        ref = ctx.closes[-(self.ROC_BARS + 1)]
        roc = ((ctx.price - ref) / ref * 100.0) if ref else 0.0

        aligned_long = ctx.trend_up and ctx.above_vwap and roc >= self.MIN_ROC_PCT
        aligned_short = (not ctx.trend_up) and (not ctx.above_vwap) and roc <= -self.MIN_ROC_PCT

        if not (aligned_long or aligned_short):
            return EntrySignal.stand_aside(
                f"Malfoy: no three-way agreement (EMA/VWAP/ROC {roc:+.2f}%)."
            )

        # Meta-label filter (Hokage's edge over the source): the primary signal
        # has fired — now a second, independent check on whether THIS instance
        # of the setup is worth taking. Momentum riding an already-overextended
        # price is the classic false positive, so demand the move still have
        # room relative to its own recent range.
        quality = self._meta_label_quality(ctx, roc)
        if quality < 50.0:
            return EntrySignal.stand_aside(
                f"Malfoy: meta-label vetoed a {('long' if aligned_long else 'short')} "
                f"(quality {quality:.0f} < 50) — signal fired but the instance is low grade."
            )

        direction = "long" if aligned_long else "short"
        return EntrySignal(
            True, direction,
            f"Malfoy: {direction} momentum — EMA9/21 aligned, price vs VWAP agrees, "
            f"ROC {roc:+.2f}% over {self.ROC_BARS} bars, meta-label quality {quality:.0f}.",
            confidence=quality,
        )

    def _meta_label_quality(self, ctx: MarketContext, roc: float) -> float:
        """Grade the fired signal 0-100. Penalise entries that are already
        extended into the top/bottom of their recent range (no room left) and
        reward momentum that still has range to travel."""
        window = min(len(ctx.highs), len(ctx.lows), 20)
        if window < 5:
            return 50.0  # too little history to grade — neutral, let it pass
        hi = max(ctx.highs[-window:])
        lo = min(ctx.lows[-window:])
        span = hi - lo
        if span <= 0:
            return 50.0

        # Where in the range are we? 1.0 = at the high, 0.0 = at the low.
        pos = (ctx.price - lo) / span
        room = (1.0 - pos) if roc > 0 else pos  # room left in the trade's direction
        base = 40.0 + room * 60.0
        # Strong thrust earns a bonus, but it is SCALED BY ROOM: violent
        # momentum into the top of the range is the classic false positive, so
        # thrust must never rescue a setup that has nowhere left to travel.
        bonus = min(15.0, abs(roc) * 10.0) * room
        return round(min(95.0, base + bonus), 1)


#: strategy_id -> its entry engine. A strategy without an entry here falls back
#: to the shared scan signal (and is therefore NOT being judged on entry).
ENTRY_MODULES: dict[str, object] = {
    "strat-trendpullback-v2": TrendPullbackEntry(),
    "strat-macrobreakout-commodities-v1": MacroBreakoutEntry(),
    "strat-meanreversion-sideways-v1": MeanReversionEntry(),
    "strat-malfoy-momentum-v1": MalfoyMomentumEntry(),
}
