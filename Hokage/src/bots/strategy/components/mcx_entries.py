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


def _direction_allowed(module, asset: str, direction: str) -> bool:
    """May this module take this side on this asset?

    MEASURED 2026-08-26, full geometry (production 1.25 ATR stop), train
    2026-05..06 against hold-out 2026-07..08:

        SessionShift GOLDM    long  -0.93 / -0.76   NEGATIVE ON BOTH HALVES
                              short +1.48 / +2.52
        SessionShift SILVERM  long  +1.12 / -0.86   negative out of sample
                              short +0.99 / +2.94
        RangeFade    NATURALGAS long +2.53 / +2.23  CONFIRMED
                              short -0.29 / +2.54   halves contradict

    A module's two sides are two different bets and there was never a reason to
    assume both work. Until this, Hokage could not express "this asset, this
    side" at all, so a measured-losing direction kept its capital because the
    winning one shared a module with it.

    THE DRIFT CHECK THAT MAKES THIS BELIEVABLE. A one-sided result is usually
    just the period's trend wearing a t-statistic, so the underlying drift was
    measured per half and it FLIPS SIGN between them:

        GOLDM       train  -7.01%   hold  +6.27%   -> short still wins
        SILVERM     train  -8.74%   hold  +3.58%   -> short still wins
        NATURALGAS  train  +5.02%   hold -14.16%   -> long  still wins

    Each surviving side wins on the half whose drift opposed it. That is the
    opposite of a trend artifact.
    """
    allowed = getattr(module, "DIRECTION_BY_ASSET", None) or {}
    want = allowed.get((asset or "").upper())
    return want is None or want == direction


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

    #: SHORT ONLY on both metals — see _direction_allowed for the measurement.
    #: The long side measured negative on both halves for GOLDM and out of
    #: sample for SILVERM, so this removes a loser rather than adding a winner.
    #: Neither short side clears t>=2 on TRAIN, so this module is still
    #: unconfirmed; it is simply no longer paying for its own wrong half.
    DIRECTION_BY_ASSET: dict[str, str] = {
        "GOLDM": "short",
        "SILVERM": "short",
    }

    #: See RangeFadeEntry.TUNABLES for the contract. All tier "propose": each
    #: changes only WHEN this module fires, never how much it risks when it does.
    TUNABLES = {
        "DIRECTION": {
            "values": (None, "long", "short"),
            "tier": "propose",
            "per_asset": "DIRECTION_BY_ASSET",
            "default": None,
        },
        "MIN_GAP_PCT": {
            "values": (0.02, 0.05, 0.10, 0.15, 0.25),
            "tier": "propose",
        },
        "WINDOW_START_MIN": {
            "values": (420, 480, 510, 540),
            "tier": "propose",
        },
        "WINDOW_END_MIN": {
            "values": (570, 630, 690, 750, 810),
            "tier": "propose",
        },
    }

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

        asset = (ctx.symbol or "").upper()
        if ctx.trend_up and ctx.above_vwap and not _direction_allowed(self, asset, "long"):
            return EntrySignal.stand_aside(
                f"SessionShift: long side is not scoped on {asset} — it measured negative there."
            )
        if (not ctx.trend_up) and (not ctx.above_vwap) and not _direction_allowed(self, asset, "short"):
            return EntrySignal.stand_aside(
                f"SessionShift: short side is not scoped on {asset} — it measured negative there."
            )

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

    Hypothesis: before US trading hours join in (09:30-17:00 IST), MCX
    commodities chop inside a range tracking their overnight parent close.
    A stretch from session VWAP in this quiet window is noise, not a new
    trend — fade it back to fair value. Explicitly refuses to fire once a
    real trend is present (same discipline as the index MeanReversion
    module) and stands aside once the session moves into the SessionShift/
    EventRider window, where a stretch might be the START of something real.
    """

    module_id = "entry-rangefade-mcx-v1"

    #: Counter-trend by design — see MeanReversionEntry.COUNTER_TREND. RangeFade
    #: had also never traded, for exactly the same reason.
    COUNTER_TREND = True

    WINDOW_START_MIN = 30    # 09:30
    #: Extended 16:30 -> 17:00 on 2026-08-05. Retiring SessionShift (17:00-19:30)
    #: and EventRider (17:00-18:30) in the consolidation left NOTHING awake
    #: between 16:30 and 18:00 — and 17:00 onward is exactly when MCX wakes up
    #: on the US overlap. The commander found Hokage idle at 17:58. RangeFade now
    #: hands straight over to TrendRider at 17:00: quiet hours fade, active hours
    #: trend, no gap and no overlap.
    WINDOW_END_MIN = 480     # 17:00 — hands over to TrendRider
    #: Default stretch that counts as overextended. PER ASSET below, because
    #: the two assets RangeFade trades measure nothing like each other.
    STRETCH_PCT = 0.30

    #: Commander-approved 2026-08-20. NATURALGAS only.
    #:
    #: Swept six thresholds, train 2026-05..06 against hold-out 2026-07..08,
    #: with the trend guard left ON throughout:
    #:
    #:   NATURALGAS  >=0.15%  TRAIN n=129 +0.368 t=+1.70  HOLD n=207 +0.486 t=+4.08
    #:               >=0.30%  TRAIN n= 65 +0.196 t=+0.58  HOLD n= 87 +0.585 t=+3.10
    #:
    #: Halving the bar more than DOUBLES the signals and improves BOTH halves.
    #: Overfitting degrades out of sample; this does the opposite, which is the
    #: reason to believe it. Train still misses t>=2, so this is a measured
    #: improvement rather than a confirmed edge.
    #:
    #: CRUDEOIL IS EXCLUDED ON PURPOSE. The same sweep on crude is negative at
    #: every band on the hold-out and WORST at 0.15% (n=143, edge -0.052). One
    #: class-level constant would have loosened both assets at once and bought
    #: 57% more crude trades with negative expectancy.
    STRETCH_PCT_BY_ASSET: dict[str, float] = {
        "NATURALGAS": 0.15,
    }

    #: How far EMA9 and EMA21 may separate before the tape counts as trending
    #: and a fade is refused. NEVER MEASURED — it was chosen, and on 2026-08-26
    #: it blocked every single one of NATURALGAS's 31 in-window scans, with
    #: observed gaps of 0.23% to 0.76% against a 0.12% bar. A guard that
    #: refuses 100% of a day is either the only thing keeping the module alive
    #: or the reason it never trades, and nothing on record said which.
    MAX_TREND_GAP_PCT = 0.12

    #: Per asset, for the same reason STRETCH_PCT is: a guard tuned on one
    #: commodity's volatility is not a guard on another's.
    #:
    #: NATURALGAS 0.12 -> 0.10, measured 2026-08-26 under full geometry on the
    #: long side (the only side now scoped — see DIRECTION_BY_ASSET):
    #:
    #:   guard   TRAIN n    edge      t   |  HOLD  n    edge      t
    #:    0.06      39   +1.098  +2.35   |    53  +0.827  +3.20   n below the floor
    #:    0.08      49   +0.866  +2.24   |    66  +0.716  +3.30   CONFIRMED
    #:    0.10      55   +0.821  +2.35   |    85  +0.497  +2.67   CONFIRMED  <- shipped
    #:    0.12      64   +0.782  +2.53   |   113  +0.347  +2.23   CONFIRMED  (today)
    #:    0.16      90   +0.782  +2.94   |   148  +0.131  +1.03
    #:    0.20     113   +0.605  +2.63   |   179  +0.119  +1.08
    #:
    #: 0.08 scores best and 0.10 was shipped instead, on purpose. Three adjacent
    #: values confirm, hold-out edge falls monotonically as the guard loosens,
    #: and 0.06 already drops below the sample floor — so 0.08 sits one step from
    #: a cliff while 0.10 sits inside the plateau. Taking the middle of a
    #: contiguous confirmed band rather than its best-scoring edge is the
    #: defence against shipping a boundary that was lucky, and it keeps 29% more
    #: signals on an asset that is already starved for them.
    MAX_TREND_GAP_PCT_BY_ASSET: dict[str, float] = {
        "NATURALGAS": 0.10,
    }

    #: LONG ONLY on gas — fade the dip, never the rip. See _direction_allowed.
    #: The short side measured -0.29 on train and turned significantly NEGATIVE
    #: as the guard loosened (-2.17 at 0.16, -3.15 at 0.20) while the hold-out
    #: stayed positive. Halves that contradict each other are noise, and this
    #: one has the train half saying it loses.
    DIRECTION_BY_ASSET: dict[str, str] = {
        "NATURALGAS": "long",
    }

    #: Knobs sweep_lab may try at other settings. Declared here rather than in
    #: the lab so that a module and the thing measuring it can never disagree
    #: about what is tunable, and so a NEW module arrives sweepable.
    #:
    #: Tier "propose" changes only WHEN this module fires. Nothing here widens
    #: a stop, raises a cap, or increases position size — those are tier "ask"
    #: and sweep_lab will not write them as proposals at any confidence.
    TUNABLES = {
        "DIRECTION": {
            "values": (None, "long", "short"),
            "tier": "propose",
            "per_asset": "DIRECTION_BY_ASSET",
            "default": None,
        },
        "MAX_TREND_GAP_PCT": {
            "values": (0.06, 0.08, 0.10, 0.12, 0.16, 0.20),
            "tier": "propose",
            "per_asset": "MAX_TREND_GAP_PCT_BY_ASSET",
        },
        "STRETCH_PCT": {
            "values": (0.10, 0.15, 0.20, 0.30, 0.45),
            "tier": "propose",
            "per_asset": "STRETCH_PCT_BY_ASSET",
        },
        "WINDOW_END_MIN": {
            "values": (360, 420, 480, 540, 600),
            "tier": "propose",
        },
        "WINDOW_START_MIN": {
            "values": (0, 30, 60, 120),
            "tier": "propose",
        },
    }

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        m = ctx.minutes_into_session
        if m is None:
            return EntrySignal.stand_aside("RangeFade: session clock unknown.")
        if not (self.WINDOW_START_MIN <= m < self.WINDOW_END_MIN):
            return EntrySignal.stand_aside(
                f"RangeFade: outside the 09:30-17:00 IST quiet window ({m}min into session)."
            )

        asset = (ctx.symbol or "").upper()
        gap_pct = (abs(ctx.ema9 - ctx.ema21) / ctx.price * 100.0) if ctx.price else 0.0
        max_gap = self.MAX_TREND_GAP_PCT_BY_ASSET.get(asset, self.MAX_TREND_GAP_PCT)
        if gap_pct > max_gap:
            return EntrySignal.stand_aside(f"RangeFade: tape is trending (EMA gap {gap_pct:.3f}%) — refusing to fade it.")

        stretch = ctx.distance_from_vwap_pct()
        threshold = self.STRETCH_PCT_BY_ASSET.get(asset, self.STRETCH_PCT)
        if stretch >= threshold and not _direction_allowed(self, asset, "short"):
            return EntrySignal.stand_aside(
                f"RangeFade: fading a rip is not scoped on {asset} — that side did not survive."
            )
        if stretch <= -threshold and not _direction_allowed(self, asset, "long"):
            return EntrySignal.stand_aside(
                f"RangeFade: fading a dip is not scoped on {asset} — that side did not survive."
            )
        if stretch >= threshold:
            return EntrySignal(
                True, "short",
                f"RangeFade: price {ctx.price:.2f} stretched +{stretch:.2f}% above VWAP {ctx.vwap:.2f} "
                f"in the quiet pre-overlap window — fading back to fair value.",
                confidence=min(78.0, 52.0 + stretch * 18.0),
            )
        if stretch <= -threshold:
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

    #: Pulled 18:00 -> 17:00 to take RangeFade's handoff (see its WINDOW_END_MIN).
    WINDOW_START_MIN = 480   # 17:00 — trend has had time to establish
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
                f"TrendRider: outside the 17:00-22:30 IST evening-trend window ({m}min into session)."
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
