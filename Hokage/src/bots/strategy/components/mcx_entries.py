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


#: The normal MCX open, in minutes since midnight IST. EVERY module's window
#: constants in this file are offsets from THIS, never from whenever the
#: session happened to start.
#:
#: 2026-10-20 showed why that distinction is load-bearing: MCX ran an
#: evening-only session opening at 17:00, and SessionShift's 480-minute
#: offset mapped to 01:00. Its window never arrived and the evening was lost.
#: The other four modules carried the same bug and were saved only by being
#: archived at the time.
MCX_SESSION_ANCHOR_MIN = 9 * 60     # 09:00 IST


class SessionShiftEntry:
    """Trade the US-market hand-off, when crude/gold volume genuinely wakes up.

    Hypothesis: MCX commodities are quiet trackers of their NYMEX/COMEX
    parents until US trading hours begin overlapping India's evening session
    (~17:00-19:30 IST). That overlap is where the real directional volume
    shows up. Standard trend/VWAP alignment, but gated to fire ONLY inside
    this window — a signal outside it is measuring a different, thinner tape.
    """

    module_id = "entry-sessionshift-mcx-v1"

    #: The normal MCX open, in minutes since midnight IST. The window
    #: constants below are offsets from THIS, not from whenever the session
    #: happened to start — see evaluate(). Changing it would move the window
    #: for every asset at once.
    #: One definition for the whole file; see MCX_SESSION_ANCHOR_MIN. Kept as
    #: a class attribute because the TUNABLES contract and its tests read it
    #: off the module.
    SESSION_ANCHOR_MIN = MCX_SESSION_ANCHOR_MIN

    WINDOW_START_MIN = 480  # +480 from 09:00 = 17:00 IST
    WINDOW_END_MIN = 630    # +630 from 09:00 = 19:30 IST
    MIN_GAP_PCT = 0.05

    #: Per asset, because the measurement was per asset.
    #:
    #: GOLDM 630 -> 570 (19:30 -> 18:30), proposed by Hokage's OWN knob sweep on
    #: 2026-09-22 — the first proposal the loop has ever generated unaided — and
    #: commander-approved the same day:
    #:
    #:   TRAIN n=94 edge=+2.956 t=+2.19   (incumbent +2.061)
    #:   HOLD  n=94 edge=+0.439 t=+2.05   (incumbent +0.314)
    #:
    #: Clears t>=2 on BOTH halves and beats the incumbent on both, which is the
    #: full ship bar. SILVERM is deliberately NOT moved: it was measured
    #: separately and its own sweep proposed nothing, and edge does not travel
    #: between assets. A class-level change here would have applied GOLDM's
    #: evidence to SILVERM for free.
    WINDOW_END_MIN_BY_ASSET: dict[str, int] = {
        "GOLDM": 570,
    }

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
            "per_asset": "WINDOW_END_MIN_BY_ASSET",
        },
    }

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        # THE WALL CLOCK, NOT MINUTES SINCE THE OPEN. Fixed 2026-10-20,
        # commander-approved, after an evening-only MCX session cost the
        # whole window.
        #
        # This read `ctx.minutes_into_session` against constants written for
        # a 09:00 open. On Dussehra, MCX ran the evening session only and
        # opened at 17:00, so 480 minutes in mapped to 01:00 and the window
        # never arrived. Both metals were evaluated ten times and refused
        # every one — "outside the window (30min into session)" — while the
        # clock read 17:30.
        #
        # The hypothesis was always about an EXTERNAL market's hours: the
        # US overlap happens at 17:00 IST whatever time MCX opened. Minutes
        # since the open only coincided with that on a normal day.
        #
        # THE CONSTANTS DO NOT CHANGE MEANING. They stay in minutes-since-
        # 09:00 so the TUNABLES contract holds and the commander-approved
        # GOLDM 570 still means 18:30; they are converted to a wall-clock
        # minute here. On any 09:00-open day the behaviour is identical,
        # which is what makes this safe to ship against measurements taken
        # the old way.
        now_min = ctx.minute_of_day
        if now_min is None:
            return EntrySignal.stand_aside("SessionShift: session clock unknown — cannot gate to the US overlap window.")
        asset = (ctx.symbol or "").upper()
        window_end = self.WINDOW_END_MIN_BY_ASSET.get(asset, self.WINDOW_END_MIN)
        start_min = self.SESSION_ANCHOR_MIN + self.WINDOW_START_MIN
        end_min = self.SESSION_ANCHOR_MIN + window_end
        if not (start_min <= now_min < end_min):
            close_hhmm = "%02d:%02d" % (end_min // 60, end_min % 60)
            open_hhmm = "%02d:%02d" % (start_min // 60, start_min % 60)
            return EntrySignal.stand_aside(
                f"SessionShift: outside the {open_hhmm}-{close_hhmm} IST US-overlap window "
                f"(clock {now_min // 60:02d}:{now_min % 60:02d})."
            )

        gap = abs(ctx.ema9 - ctx.ema21)
        gap_pct = (gap / ctx.price * 100.0) if ctx.price else 0.0
        if gap_pct < self.MIN_GAP_PCT:
            return EntrySignal.stand_aside(f"SessionShift: EMA band flat ({gap_pct:.3f}%) — no directional wake-up yet.")

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
        # WALL CLOCK, not minutes-since-open — see SessionShift.evaluate
        # for why. The constants stay offsets from a 09:00 anchor, so
        # every tuned value keeps its meaning and a normal day behaves
        # exactly as before.
        m = ctx.minute_of_day
        if m is None:
            return EntrySignal.stand_aside("EventRider: session clock unknown.")
        start = MCX_SESSION_ANCHOR_MIN + self.WINDOW_START_MIN
        end = MCX_SESSION_ANCHOR_MIN + self.WINDOW_END_MIN
        if not (start <= m < end):
            return EntrySignal.stand_aside(
                f"EventRider: outside the {start // 60:02d}:{start % 60:02d}-"
                f"{end // 60:02d}:{end % 60:02d} IST thrust window "
                f"(clock {m // 60:02d}:{m % 60:02d})."
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

    #: Weekdays this module refuses to fade, per asset. Monday=0.
    #:
    #: RangeFade's whole hypothesis is that the pre-overlap hours are RANGEBOUND
    #: — "a stretch in this quiet window is noise, not a new trend". Open-source
    #: research on gas (2026-08-27) says that assumption has a known weak spot:
    #: natural gas return volatility is measurably HIGHER ON THURSDAYS than any
    #: other weekday, because the EIA storage report prints at 20:00 IST and the
    #: market spends the day positioning for it — "estimates circulate from
    #: Monday; positions get squared Wednesday night".
    #:
    #: A day whose morning is spent positioning for an evening release is not a
    #: quiet range, so fading it may be fading a real move. That is a HYPOTHESIS,
    #: not a finding — and unlike the EIA module itself it can be settled on a
    #: real sample, because every Thursday already sits inside the corpus the
    #: module is measured on. Empty until measured.
    SKIP_WEEKDAYS_BY_ASSET: dict[str, tuple[int, ...]] = {}

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
        #: () = fade every day, (3,) = sit out Thursdays. See
        #: SKIP_WEEKDAYS_BY_ASSET for why Thursday is the one worth asking about.
        "SKIP_WEEKDAYS": {
            "values": ((), (3,)),
            "tier": "propose",
            "per_asset": "SKIP_WEEKDAYS_BY_ASSET",
            "default": (),
        },
    }

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        # WALL CLOCK, not minutes-since-open — see SessionShift.evaluate
        # for why. The constants stay offsets from a 09:00 anchor, so
        # every tuned value keeps its meaning and a normal day behaves
        # exactly as before.
        m = ctx.minute_of_day
        if m is None:
            return EntrySignal.stand_aside("RangeFade: session clock unknown.")
        start = MCX_SESSION_ANCHOR_MIN + self.WINDOW_START_MIN
        end = MCX_SESSION_ANCHOR_MIN + self.WINDOW_END_MIN
        if not (start <= m < end):
            return EntrySignal.stand_aside(
                f"RangeFade: outside the {start // 60:02d}:{start % 60:02d}-"
                f"{end // 60:02d}:{end % 60:02d} IST quiet window "
                f"(clock {m // 60:02d}:{m % 60:02d})."
            )

        asset = (ctx.symbol or "").upper()
        skip = self.SKIP_WEEKDAYS_BY_ASSET.get(asset, ())
        if skip and ctx.weekday is not None and ctx.weekday in skip:
            return EntrySignal.stand_aside(
                f"RangeFade: {asset} does not fade on this weekday — its quiet-range "
                f"assumption did not hold there."
            )

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


class EIAReactionEntry:
    """Trade the weekly EIA gas storage print — after the vacuum, not into it.

    THE ONE GENUINELY FORECASTABLE EVENT IN THE GAS WEEK. Built 2026-08-27 from
    open sources, because natural gas has a scheduled information release that
    nothing else Hokage trades does:

      * The EIA Weekly Natural Gas Storage Report publishes EVERY THURSDAY at
        10:30 a.m. ET — 20:00 IST — and MCX natural gas is a cash-settled
        derivative of NYMEX Henry Hub that "follows within seconds".
      * Academic work on energy futures finds gas return volatility is
        MEASURABLY HIGHER ON THURSDAYS than any other weekday. Two independent
        sources, one practitioner and one academic, point at the same hour.
      * A 10 Bcf surprise against consensus moves the front month 10-20 cents
        almost instantly.

    AND HOKAGE WAS BLIND TO IT TWICE OVER. MarketContext carried no weekday at
    all until today, so a weekly event was literally inexpressible; and every
    live gas window (RangeFade 09:30-17:00) closes three hours before the print.
    The most informative hour of the gas week had no module in it.

    WHY IT REFUSES THE FIRST FIFTEEN MINUTES. The same sources are blunt about
    the release itself being untradeable: repricing is complete "by 10:30:01",
    spreads go from "a tick wide" to "ten wide in the release seconds", "the
    worst fills of the week happen between 10:30 and 10:35", and "stops placed
    at sensible technical levels get vacuumed in both directions". Whatever edge
    exists is NOT in the print. So this module never fires on the 20:00 scan —
    it waits for the release bar to CLOSE and reads what the move actually was.
    Liquidity is "tradeable within the half hour" and "the most honest prices
    print after 11:00", which is where the window sits.

    THE HYPOTHESIS BEING TESTED, stated before it was measured so the result
    cannot be rewritten afterwards: the initial print is a liquidity event, not
    a valuation event — "a bullish print spikes price into resting sell orders
    and reverses within fifteen minutes". If that is true beyond the first bar,
    the release-bar move should partially REVERSE over the following hour, and
    fading it pays. If it is false, the move is real information and following
    it pays. Both readings are measurable; DIRECTION_BY_ASSET records which one
    the tape actually supports, and an empty table means neither has earned
    capital yet.

    THE HONEST LIMIT, which no amount of care removes: this is a WEEKLY event.
    Kite serves at most 200 days of 15-minute candles, so the entire measurable
    universe is roughly 28 Thursdays. One observation per Thursday — counting
    four bars inside one release window as four observations would be
    manufacturing n, which is the exact trick every lab here exists to refuse.
    Fourteen events per half cannot reach the ship bar, and a module that cannot
    reach the bar does not get told it has.
    """

    module_id = "entry-eiareaction-mcx-v1"

    #: The EIA storage report lands 10:30 ET = 20:00 IST, which on a 09:00 MCX
    #: open is minute 660 — confirmed against Hokage's own 2026-08-26 scan log,
    #: which stamped the 20:00:26 scan "(660min into session)".
    RELEASE_MIN = 660

    #: 20:15-20:45 IST. Starts one full bar AFTER the print so the release bar
    #: has closed and the vacuum has passed; two scans wide so a single missed
    #: poll does not silently skip the week's only opportunity.
    WINDOW_START_MIN = 675
    WINDOW_END_MIN = 705

    #: Thursday. Monday=0, so EIA day is 3.
    EIA_WEEKDAY = 3

    #: Counter-trend by design - see MeanReversionEntry.COUNTER_TREND, which
    #: measured 16 valid signals and 0 allowed through. EIAReaction FADES the
    #: release move, so it fires precisely when price is extended from VWAP,
    #: which is the condition the trend-join veto refuses. On 2026-10-22 it won
    #: its only window of the week with confidence 62 and was blocked by
    #: "NATURALGAS MIXED - 2.13 ATR from VWAP, too extended to join the trend".
    #: Mutually exclusive by construction, which is why it had never traded.
    #:
    #: Safe to exempt ONLY because MAX_REACTION_ATR below is this module's own,
    #: correctly-oriented guard. Commander-approved 2026-10-23.
    COUNTER_TREND = True

    #: How far the release bar must have travelled, in ATR, to count as a
    #: reaction worth trading rather than an ordinary bar that happened to land
    #: at 20:00. Sweepable.
    MIN_REACTION_ATR = 0.50

    #: THE CEILING, and the reason the veto exemption above is safe. This
    #: module's whole hypothesis is that the print is a LIQUIDITY event that
    #: reverses - "a bullish print spikes price into resting sell orders and
    #: reverses within fifteen minutes". Above some size the move is genuine
    #: repricing, and fading it is betting against information rather than
    #: against a vacuum. Without this, exempting the module from the trend veto
    #: would remove a gate and put nothing in its place.
    #:
    #: 2.0 IS A STATED PRIOR, NOT A MEASUREMENT, and cannot become one here:
    #: Kite serves ~200 days of 15-minute candles, so the measurable universe
    #: is ~28 Thursdays, 14 per half, and this module can never reach the ship
    #: bar (see the class docstring). It sits in TUNABLES at propose tier so
    #: nothing tunes it automatically. For calibration, the 2026-10-22 print
    #: moved 0.65 ATR and is unaffected.
    MAX_REACTION_ATR = 2.00

    #: EMPTY ON PURPOSE. Nothing is scoped until it has been measured on this
    #: asset — the whole point of the module is that the direction is the open
    #: question, and an unmeasured guess about it is how CRUDEOIL cost 6 sweeps.
    DIRECTION_BY_ASSET: dict[str, str] = {}

    #: True = fade the release move, False = follow it. Not per-asset yet
    #: because the module trades exactly one asset; it becomes per-asset the
    #: moment a second one is scoped.
    FADE_THE_PRINT = True

    TUNABLES = {
        "MIN_REACTION_ATR": {
            "values": (0.25, 0.50, 0.75, 1.00, 1.50),
            "tier": "propose",
        },
        "MAX_REACTION_ATR": {
            "values": (1.50, 2.00, 3.00, 5.00),
            "tier": "propose",
        },
        "FADE_THE_PRINT": {
            "values": (True, False),
            "tier": "propose",
        },
        "WINDOW_START_MIN": {
            "values": (675, 690, 705),
            "tier": "propose",
        },
    }

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        weekday = ctx.weekday
        if weekday is None:
            return EntrySignal.stand_aside(
                "EIAReaction: session date unknown — cannot tell whether this is EIA day."
            )
        if weekday != self.EIA_WEEKDAY:
            return EntrySignal.stand_aside(
                "EIAReaction: not a Thursday — the storage report only prints once a week."
            )

        # WALL CLOCK, not minutes-since-open — see SessionShift.evaluate
        # for why. The constants stay offsets from a 09:00 anchor, so
        # every tuned value keeps its meaning and a normal day behaves
        # exactly as before.
        m = ctx.minute_of_day
        if m is None:
            return EntrySignal.stand_aside("EIAReaction: session clock unknown.")
        m = m - MCX_SESSION_ANCHOR_MIN
        if m < self.WINDOW_START_MIN:
            return EntrySignal.stand_aside(
                f"EIAReaction: too early ({m}min) — refusing the 20:00-20:15 release vacuum, "
                f"where spreads go ten wide and stops are hunted in both directions."
            )
        if m >= self.WINDOW_END_MIN:
            return EntrySignal.stand_aside(
                f"EIAReaction: past the 20:15-20:45 post-release window ({m}min into session)."
            )

        if ctx.atr is None or ctx.atr <= 0:
            return EntrySignal.stand_aside(
                "EIAReaction: ATR unavailable — the reaction bar cannot be sized without it."
            )
        if len(ctx.closes) < 3:
            return EntrySignal.stand_aside(
                f"EIAReaction: need 3 bars to measure the release move, have {len(ctx.closes)}."
            )

        # The release bar is the one BEFORE the current (still forming) bar.
        move = ctx.closes[-2] - ctx.closes[-3]
        reaction = abs(move) / ctx.atr
        if reaction < self.MIN_REACTION_ATR:
            return EntrySignal.stand_aside(
                f"EIAReaction: the print barely moved the tape ({reaction:.2f} ATR) — "
                f"no reaction to trade."
            )
        # The ceiling that earns this module its veto exemption. A move this
        # big is repricing, not a liquidity vacuum, and fading it is betting
        # against information.
        if reaction > self.MAX_REACTION_ATR:
            return EntrySignal.stand_aside(
                f"EIAReaction: the print repriced the tape {reaction:.2f} ATR "
                f"(ceiling {self.MAX_REACTION_ATR:.2f}) — that is information, "
                f"not a vacuum to fade."
            )

        spiked_up = move > 0
        direction = ("short" if spiked_up else "long") if self.FADE_THE_PRINT \
            else ("long" if spiked_up else "short")

        asset = (ctx.symbol or "").upper()
        if not _direction_allowed(self, asset, direction):
            return EntrySignal.stand_aside(
                f"EIAReaction: the {direction} side is not scoped on {asset}."
            )

        stance = "fading" if self.FADE_THE_PRINT else "following"
        return EntrySignal(
            True, direction,
            f"EIAReaction: the storage print moved the tape {move:+.2f} ({reaction:.2f} ATR) "
            f"and the release bar has closed — {stance} it into the post-vacuum hour.",
            confidence=min(80.0, 55.0 + reaction * 10.0),
        )


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
        # WALL CLOCK, not minutes-since-open — see SessionShift.evaluate
        # for why. The constants stay offsets from a 09:00 anchor, so
        # every tuned value keeps its meaning and a normal day behaves
        # exactly as before.
        m = ctx.minute_of_day
        if m is None:
            return EntrySignal.stand_aside("TrendRider: session clock unknown.")
        start = MCX_SESSION_ANCHOR_MIN + self.WINDOW_START_MIN
        end = MCX_SESSION_ANCHOR_MIN + self.WINDOW_END_MIN
        if not (start <= m < end):
            return EntrySignal.stand_aside(
                f"TrendRider: outside the {start // 60:02d}:{start % 60:02d}-"
                f"{end // 60:02d}:{end % 60:02d} IST evening-trend window "
                f"(clock {m // 60:02d}:{m % 60:02d})."
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
    "strat-eiareaction-mcx-v1": EIAReactionEntry(),
}
