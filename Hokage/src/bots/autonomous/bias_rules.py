"""The directional veto's decision logic, as a pure function.

WHY THIS IS ITS OWN MODULE
`_compute_underlying_bias` used to fetch candles, derive EMA/VWAP/ATR and decide
the verdict all in one method on the bot. That made the verdict impossible to
measure: any research harness had to re-implement the rules, and a copy that
drifts from production measures a strategy nobody is running.

The fetching and the deriving stay on the bot. The DECISION lives here, taking
already-derived primitives, so `tools/research/veto_lab.py` scores the exact
branch production executes. If this file changes, the measurement changes with
it — which is the only arrangement under which a number means anything.

Nothing here does I/O, logs, or touches the clock.
"""
from __future__ import annotations

from typing import Sequence

#: Minimum COMPLETED bars of the current session before the engine will name a
#: direction. Six 15-minute bars = 90 minutes, so index entries begin from
#: ~10:45 instead of inheriting the previous session's trend at 09:46.
MIN_SESSION_BARS = 6
#: How far price must sit clear of session VWAP, as a fraction of ATR(14),
#: before that counts as a direction rather than noise.
VWAP_ATR_FRACTION = 0.5
#: How far from VWAP (in ATR) counts as a stretch worth fading.
REVERSION_ATR = 1.5
#: How close to VWAP (in ATR) a trend entry must be to count as a pullback
#: rather than a chase.
PULLBACK_ATR = 0.5

#: Which directional rule each asset gets. Chosen by measurement, not by taste
#: — see tools/research/signal_lab.py. Anything unlisted falls back to
#: "persistence", the rule that measured best on the indices.
#:
#: Re-measured 2026-08-06 on the front-month MCX futures. Two corrections, both
#: from numbers that did NOT reproduce or were never checked:
#:
#: GOLDM was shipped as trend_pullback citing t=+2.43. It does not reproduce.
#: Trend-pullback on GOLDM measures NEGATIVE at both horizons (t=-0.16 at 60m,
#: t=-0.07 at 120m) while persistence+EMA measures t=+2.25 and +2.91. GOLDM is
#: therefore absent from this table and falls back to the persistence default.
#:
#: NATURALGAS was never in the table at all, so it inherited the index
#: persistence rule — which measures as noise on it (t=+1.06 at 60m, +0.36 at
#: 120m). Trend-pullback measures t=+2.97 at 120m. Added.
#:
#: Reproduced and unchanged: CRUDEOIL mean-reversion (t=+2.55/+3.90/+5.13 on
#: n~1,200) and SILVERM trend-pullback (t=+3.02 at 60m, +4.49 at 120m). Note
#: CRUDEOIL is the mirror image of the index rule: persistence measures
#: NEGATIVE there (t=-2.26/-3.27/-2.05), so one shared direction engine could
#: never have served both.
#:
#: CAVEAT THAT MUST TRAVEL WITH THESE NUMBERS: every t above scores the rule as
#: a STANDALONE SIGNAL. None of them scores it in the job it actually holds,
#: which is vetoing another module's entry. Those are different questions and
#: `veto_lab.py` exists to answer the second one.
RULE_BY_SYMBOL: dict[str, str] = {
    "CRUDEOIL": "mean_reversion",    # t=+3.90 (60m), +5.13 (120m)
    "NATURALGAS": "trend_pullback",  # t=+2.97 (120m)
    "SILVERM": "trend_pullback",     # t=+3.02 (60m), +4.49 (120m)
    # GOLDM: deliberately absent -> persistence (t=+2.25 60m, +2.91 120m)
}

#: Symbols whose veto has been MEASURED as a veto (not merely as a signal) and
#: found to subtract from the module it gates. On these, direction is left
#: entirely to the entry module, which is the component that was measured
#: choosing it. Populated only by veto_lab.py evidence — never by taste.
#:
#: MEASURED 2026-08-12, tools/research/veto_lab.py, 2026-05-01 to 2026-08-12,
#: at the 60-minute horizon Hokage's trades actually live. SessionShift is the
#: only strategy scoped to either symbol, so disabling per-symbol costs nothing
#: else:
#:
#:   GOLDM    SessionShift  alone n=411 t=+3.30  ->  gated n=58 t=+1.23
#:   SILVERM  SessionShift  alone n=556 t=+2.59  ->  gated n=40 t=+1.53
#:
#: The veto blocked 86% / 93% of signals and the BLOCKED set carried the edge
#: (GOLDM blocked t=+3.06, SILVERM blocked t=+2.22). A module that clears the
#: t>=2 bar on its own falls below it once gated: the gate is not filtering,
#: it is replacing the chooser with something that fires almost never.
#:
#: WHY, mechanically — the two conditions are near mutually exclusive by
#: construction. SessionShift fires when price is ABOVE VWAP. The SILVERM veto
#: rule (trend_pullback) only says yes when price is WITHIN 0.5 ATR OF VWAP.
#: They can agree only inside a narrow band, which is why the live log for
#: 2026-08-12 shows 16 auction wins and 15 "tape is MIXED" blocks.
#:
#: THE VETO IS KEPT EVERYWHERE ELSE, because there it measures as a real
#: filter rather than an off switch. On MacroBreakout — live on all three
#: indices — it blocks only ~30-45% and IMPROVES the module it gates:
#:   NIFTY  alone t=+2.88 -> gated t=+3.52   SENSEX alone t=+2.32 -> +2.51
#: MeanReversion and RangeFade are COUNTER_TREND and already skip the veto in
#: `_check_conduct_gates`; the lab confirms that exemption is correct (applied,
#: it would block 100% of their signals, including RangeFade's t=+2.43 on
#: NATURALGAS).
#:
#: CAVEAT THE COMMANDER MUST HEAR WITH THESE NUMBERS: edge_atr measures the
#: UNDERLYING's forward move, not option P&L. SessionShift's accuracy is 52.3%
#: on GOLDM and 48.6% on SILVERM — it earns its t by winning BIGGER, not more
#: often. Premium decay and spread are paid on every trade including the
#: losers, so a positive underlying edge is necessary for an option buyer but
#: not by itself sufficient. Live paper trades are the only proof.
VETO_DISABLED_SYMBOLS: frozenset[str] = frozenset({"GOLDM", "SILVERM"})


def rule_for(symbol: str) -> str:
    """Which branch `classify_tape` will take for this symbol."""
    return RULE_BY_SYMBOL.get(symbol.upper(), "persistence")


def classify_tape(
    *,
    symbol: str,
    price: float,
    vwap: float,
    atr: float,
    ema9: float,
    ema21: float,
    recent_closes: Sequence[float],
    session_bar_count: int,
) -> tuple[str, str]:
    """Classify the underlying tape as BULLISH / BEARISH / MIXED.

    Returns (verdict, reason). The reason is a plain sentence the caller logs;
    returning it rather than logging here is what keeps this function pure.

    `recent_closes` must be the last four closes, oldest first — the
    persistence rule reads three steps out of them.
    """
    # --- the tape must actually BE today's tape --------------------------
    # EMA21 on 15-minute bars needs 21 bars = 5.25 hours. At 09:46 only THREE
    # of today's bars exist, so ~93% of the window is previous sessions: the
    # "bias" was reporting yesterday's trend and calling it today's. On
    # 2026-07-30 that passed a NIFTY CE at 09:46 which was stopped 40 minutes
    # later, and by 10:00 the same symbol read MIXED. Below the floor there is
    # no intraday trend to read, so stand aside rather than inherit a
    # direction from a session that has ended.
    if session_bar_count < MIN_SESSION_BARS:
        return "MIXED", (
            f"only {session_bar_count} of today's bars for {symbol} "
            f"(need {MIN_SESSION_BARS}) — tape not established, standing aside."
        )

    rule = rule_for(symbol)

    if rule == "mean_reversion":
        # Fade a stretch from a REAL volume-weighted VWAP. Works on MCX futures
        # and not on NSE index spot for one reason only: Kite reports volume 0
        # on the latter, so its "VWAP" is a plain mean of closes.
        if not atr:
            return "MIXED", f"{symbol} MIXED — no ATR to measure the stretch against."
        stretch = (price - vwap) / atr
        if stretch >= REVERSION_ATR:
            return "BEARISH", f"{symbol} BEARISH — {stretch:+.2f} ATR above VWAP, fading."
        if stretch <= -REVERSION_ATR:
            return "BULLISH", f"{symbol} BULLISH — {stretch:+.2f} ATR below VWAP, fading."
        return "MIXED", (
            f"{symbol} MIXED — only {stretch:+.2f} ATR from VWAP "
            f"(fade needs {REVERSION_ATR:.1f})."
        )

    if rule == "trend_pullback":
        # Trend direction, entered while price sits NEAR VWAP rather than
        # extended away from it — buying the pullback, not the spike.
        if not atr:
            return "MIXED", f"{symbol} MIXED — no ATR to measure the pullback against."
        dist = abs(price - vwap) / atr
        if dist <= PULLBACK_ATR:
            if ema9 > ema21:
                return "BULLISH", f"{symbol} BULLISH — pullback to VWAP with EMA9 > EMA21."
            if ema9 < ema21:
                return "BEARISH", f"{symbol} BEARISH — pullback to VWAP with EMA9 < EMA21."
        return "MIXED", (
            f"{symbol} MIXED — {dist:.2f} ATR from VWAP, too extended to join "
            f"the trend (needs <= {PULLBACK_ATR:.1f})."
        )

    # Default: persistence + EMA structure (measured best on the indices).
    # Three consecutive closes the same way is a weak-looking rule that
    # measures well precisely because it describes what price is DOING rather
    # than where it has BEEN. The VWAP leg this replaced was actively harmful:
    # gating persistence with it dropped t from 2.45 to 1.34 on NIFTY.
    closes_seq = list(recent_closes)[-4:]
    if len(closes_seq) < 4:
        return "MIXED", f"{symbol} MIXED — fewer than four closes to read a push from."
    steps = [closes_seq[i + 1] - closes_seq[i] for i in range(3)]
    if all(s > 0 for s in steps) and ema9 > ema21:
        return "BULLISH", f"{symbol} BULLISH — three-bar push up with EMA9 > EMA21."
    if all(s < 0 for s in steps) and ema9 < ema21:
        return "BEARISH", f"{symbol} BEARISH — three-bar push down with EMA9 < EMA21."
    return "MIXED", (
        f"{symbol} MIXED — no 3-bar push in agreement with EMA structure "
        f"(EMA9 {ema9:.2f} vs EMA21 {ema21:.2f})."
    )
