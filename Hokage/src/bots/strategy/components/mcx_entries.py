"""The four competing entry engines for the MCX Commodity Arena.

Built 2026-07-18 (commander-approved): a second, fully separate league that
trades CRUDEOIL/NATURALGAS/GOLDM/SILVERM options through the same Zerodha
paper venue, on its own ledger. Each module reads the SAME MarketContext
shape used by the index Dojo (bots.strategy.components.models) so all the
shared machinery (options router, exit ladder, gate journaling) works
unmodified — only the entry HYPOTHESES differ, tuned for a market that trades
09:00-23:30 IST instead of 09:15-15:30.

`minutes_into_session` is computed by the caller from the symbol's OWN candle
data (first bar of the day to the latest bar) — for MCX symbols this
naturally reflects MCX's ~09:00 IST open, no NSE assumption baked in.
Nothing here fabricates a value: missing data means stand aside.
"""
from __future__ import annotations

from bots.strategy.components.models import EntrySignal, MarketContext


class SessionShiftEntry:
    """Trade the US-market hand-off, when crude/gold volume genuinely wakes up.

    Hypothesis: MCX commodities are quiet trackers of their NYMEX/COMEX
    parents until US trading hours begin overlapping India's evening session
    (~17:00-19:30 IST). That overlap is where the real directional volume
    shows up. Standard trend/VWAP alignment, but gated to fire ONLY inside
    this window — a signal outside it is measuring a different, thinner tape.
    """

    module_id = "entry-sessionshift-mcx-v1"

    WINDOW_START_MIN = 480  # 17:00 for a 09:00 MCX open
    WINDOW_END_MIN = 630    # 19:30
    MIN_GAP_PCT = 0.05

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        m = ctx.minutes_into_session
        if m is None:
            return EntrySignal.stand_aside("SessionShift: session clock unknown — cannot gate to the US overlap window.")
        if not (self.WINDOW_START_MIN <= m < self.WINDOW_END_MIN):
            return EntrySignal.stand_aside(
                f"SessionShift: outside the 17:00-19:30 IST US-overlap window ({m}min into session)."
            )

        gap = abs(ctx.ema9 - ctx.ema21)
        gap_pct = (gap / ctx.price * 100.0) if ctx.price else 0.0
        if gap_pct < self.MIN_GAP_PCT:
            return EntrySignal.stand_aside(f"SessionShift: EMA band flat ({gap_pct:.3f}%) — no directional wake-up yet.")

        if ctx.trend_up and ctx.above_vwap:
            return EntrySignal(
                True, "long",
                f"SessionShift: US-overlap uptrend (EMA9 {ctx.ema9:.2f} > EMA21 {ctx.ema21:.2f}), "
                f"price {ctx.price:.2f} above VWAP {ctx.vwap:.2f}.",
                confidence=min(80.0, 55.0 + gap_pct * 30.0),
            )
        if (not ctx.trend_up) and (not ctx.above_vwap):
            return EntrySignal(
                True, "short",
                f"SessionShift: US-overlap downtrend (EMA9 {ctx.ema9:.2f} < EMA21 {ctx.ema21:.2f}), "
                f"price {ctx.price:.2f} below VWAP {ctx.vwap:.2f}.",
                confidence=min(80.0, 55.0 + gap_pct * 30.0),
            )
        return EntrySignal.stand_aside("SessionShift: EMA and VWAP disagree inside the window — tape is mixed.")


class EventRiderEntry:
    """Ride a sharp momentum thrust in the evening high-volatility window.

    Hypothesis: MCX commodities carry real evening volatility clusters
    (US inventory/data releases land in this window on a public, recurring
    weekly cadence). Rather than hard-code specific release timestamps —
    Hokage has no live economic-calendar feed to verify those against, and
    doctrine forbids trading on an unverifiable assumption — this module
    detects the OBSERVABLE SIGNATURE of such a release: a strong, fresh
    rate-of-change thrust, gated to the same evening window and requiring NO
    prior trend (a release can reverse the day's trend entirely). Tighter
    window and higher ROC bar than SessionShift/TrendRider — this is built to
    catch the spike, not the drift.
    """

    module_id = "entry-eventrider-mcx-v1"

    WINDOW_START_MIN = 480  # 17:00
    WINDOW_END_MIN = 570    # 18:30 — the sharpest part of the overlap
    ROC_BARS = 2
    MIN_ROC_PCT = 0.25

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        m = ctx.minutes_into_session
        if m is None:
            return EntrySignal.stand_aside("EventRider: session clock unknown.")
        if not (self.WINDOW_START_MIN <= m < self.WINDOW_END_MIN):
            return EntrySignal.stand_aside(
                f"EventRider: outside the 17:00-18:30 IST thrust window ({m}min into session)."
            )
        if len(ctx.closes) < self.ROC_BARS + 1:
            return EntrySignal.stand_aside(f"EventRider: need {self.ROC_BARS + 1} bars, have {len(ctx.closes)}.")

        ref = ctx.closes[-(self.ROC_BARS + 1)]
        roc = ((ctx.price - ref) / ref * 100.0) if ref else 0.0

        if roc >= self.MIN_ROC_PCT:
            return EntrySignal(
                True, "long",
                f"EventRider: sharp thrust +{roc:.2f}% over {self.ROC_BARS} bars in the evening "
                f"volatility window — riding the release-shaped move.",
                confidence=min(85.0, 55.0 + roc * 15.0),
            )
        if roc <= -self.MIN_ROC_PCT:
            return EntrySignal(
                True, "short",
                f"EventRider: sharp thrust {roc:.2f}% over {self.ROC_BARS} bars in the evening "
                f"volatility window — riding the release-shaped move.",
                confidence=min(85.0, 55.0 + abs(roc) * 15.0),
            )
        return EntrySignal.stand_aside(f"EventRider: thrust only {roc:+.2f}% — below the {self.MIN_ROC_PCT}% bar.")


class RangeFadeEntry:
    """Fade an overstretched price during the quiet pre-overlap hours.

    Hypothesis: before US trading hours join in (09:30-16:30 IST), MCX
    commodities chop inside a range tracking their overnight parent close.
    A stretch from session VWAP in this quiet window is noise, not a new
    trend — fade it back to fair value. Explicitly refuses to fire once a
    real trend is present (same discipline as the index MeanReversion
    module) and stands aside once the session moves into the SessionShift/
    EventRider window, where a stretch might be the START of something real.
    """

    module_id = "entry-rangefade-mcx-v1"

    WINDOW_START_MIN = 30    # 09:30
    WINDOW_END_MIN = 450     # 16:30 — before the evening wake-up
    STRETCH_PCT = 0.30
    MAX_TREND_GAP_PCT = 0.12

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        m = ctx.minutes_into_session
        if m is None:
            return EntrySignal.stand_aside("RangeFade: session clock unknown.")
        if not (self.WINDOW_START_MIN <= m < self.WINDOW_END_MIN):
            return EntrySignal.stand_aside(
                f"RangeFade: outside the 09:30-16:30 IST quiet window ({m}min into session)."
            )

        gap_pct = (abs(ctx.ema9 - ctx.ema21) / ctx.price * 100.0) if ctx.price else 0.0
        if gap_pct > self.MAX_TREND_GAP_PCT:
            return EntrySignal.stand_aside(f"RangeFade: tape is trending (EMA gap {gap_pct:.3f}%) — refusing to fade it.")

        stretch = ctx.distance_from_vwap_pct()
        if stretch >= self.STRETCH_PCT:
            return EntrySignal(
                True, "short",
                f"RangeFade: price {ctx.price:.2f} stretched +{stretch:.2f}% above VWAP {ctx.vwap:.2f} "
                f"in the quiet pre-overlap window — fading back to fair value.",
                confidence=min(78.0, 52.0 + stretch * 18.0),
            )
        if stretch <= -self.STRETCH_PCT:
            return EntrySignal(
                True, "long",
                f"RangeFade: price {ctx.price:.2f} stretched {stretch:.2f}% below VWAP {ctx.vwap:.2f} "
                f"in the quiet pre-overlap window — fading back to fair value.",
                confidence=min(78.0, 52.0 + abs(stretch) * 18.0),
            )
        return EntrySignal.stand_aside(f"RangeFade: price only {stretch:+.2f}% from VWAP — not stretched enough.")


class TrendRiderEntry:
    """Ride an established evening trend that already has momentum behind it.

    Hypothesis: distinct from SessionShift (which reacts to freshly forming
    alignment) — TrendRider only joins a trend ALREADY confirmed and running
    with above-typical volume, later in the evening session. No pullback
    requirement (distinct from the index TrendPullback) and no range-break
    requirement (distinct from MacroBreakout): pure continuation, joined
    directly, on the belief that a volume-backed evening trend in crude/gold
    tends to run into the close rather than mean-revert.
    """

    module_id = "entry-trendrider-mcx-v1"

    WINDOW_START_MIN = 540   # 18:00 — trend has had time to establish
    WINDOW_END_MIN = 810     # 22:30 — Hokage's own MCX last-entry cutoff
    MIN_GAP_PCT = 0.08
    ROC_BARS = 6
    MIN_ROC_PCT = 0.15

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        m = ctx.minutes_into_session
        if m is None:
            return EntrySignal.stand_aside("TrendRider: session clock unknown.")
        if not (self.WINDOW_START_MIN <= m < self.WINDOW_END_MIN):
            return EntrySignal.stand_aside(
                f"TrendRider: outside the 18:00-22:30 IST evening-trend window ({m}min into session)."
            )

        gap_pct = (abs(ctx.ema9 - ctx.ema21) / ctx.price * 100.0) if ctx.price else 0.0
        if gap_pct < self.MIN_GAP_PCT:
            return EntrySignal.stand_aside(f"TrendRider: EMA band flat ({gap_pct:.3f}%) — no established trend to join.")
        if len(ctx.closes) < self.ROC_BARS + 1:
            return EntrySignal.stand_aside(f"TrendRider: need {self.ROC_BARS + 1} bars, have {len(ctx.closes)}.")

        ref = ctx.closes[-(self.ROC_BARS + 1)]
        roc = ((ctx.price - ref) / ref * 100.0) if ref else 0.0

        if ctx.trend_up and ctx.above_vwap and roc >= self.MIN_ROC_PCT:
            return EntrySignal(
                True, "long",
                f"TrendRider: confirmed uptrend (EMA9 {ctx.ema9:.2f} > EMA21 {ctx.ema21:.2f}) still "
                f"running +{roc:.2f}% over {self.ROC_BARS} bars — joining the continuation.",
                confidence=min(82.0, 55.0 + roc * 12.0),
            )
        if (not ctx.trend_up) and (not ctx.above_vwap) and roc <= -self.MIN_ROC_PCT:
            return EntrySignal(
                True, "short",
                f"TrendRider: confirmed downtrend (EMA9 {ctx.ema9:.2f} < EMA21 {ctx.ema21:.2f}) still "
                f"running {roc:.2f}% over {self.ROC_BARS} bars — joining the continuation.",
                confidence=min(82.0, 55.0 + abs(roc) * 12.0),
            )
        return EntrySignal.stand_aside(
            f"TrendRider: trend/VWAP/momentum not all aligned (ROC {roc:+.2f}%) — not a confirmed continuation."
        )


#: strategy_id -> its entry engine. Mirrors bots.strategy.components.entries.ENTRY_MODULES
#: but for the MCX Arena's own 4-strategy lineup.
MCX_ENTRY_MODULES: dict[str, object] = {
    "strat-sessionshift-mcx-v1": SessionShiftEntry(),
    "strat-eventrider-mcx-v1": EventRiderEntry(),
    "strat-rangefade-mcx-v1": RangeFadeEntry(),
    "strat-trendrider-mcx-v1": TrendRiderEntry(),
}
