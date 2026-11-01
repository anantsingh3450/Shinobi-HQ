"""Position Review Engine for Hokage — Phase 4C.5D.

Performs post-exit quality analysis for every closed trade.
Runs asynchronously after exit to preserve Layer 1 execution speed.

Reviews:
    - Entry quality  : How much heat did the hold take after the entry?
    - Exit quality   : TSL / TP / Premature / Trailing?
    - Sizing quality : Was the premium committed calibrated to conviction?
    - Stop quality   : Was the risk accepted sized to the noise he trades in?
    - Lesson         : Auto-generated structured lesson text

A GRADE MUST BE ABLE TO SAY IT DOES NOT KNOW. Two of these four were constants
until 2026-11-01 — entry read POOR on 436 of 488 reviews because the entry
price cancelled out of its own formula, and sizing read CORRECT on 487 of 488
because it fabricated a default for an input that two of the three entry paths
never wrote. Both now return UNKNOWN rather than invent an answer, because
these lessons are forwarded to long-term memory and an invented grade there is
indelible. See `absent-is-not-false`.

Storage: hokage_brain/reviews/position_reviews.jsonl
Lessons are also forwarded to MemoryManager for long-term retention.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from hokage.memory.resolver import PathResolver
from bots.autonomous.models import PositionReview
from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION

if TYPE_CHECKING:
    from bots.autonomous.memory import MemoryManager

logger = logging.getLogger("Hokage.PositionReview")

# ---------------------------------------------------------------------------
# Quality grade constants
# ---------------------------------------------------------------------------
#: Returned when the input a grade needs was never recorded. NOT a grade, and
#: deliberately not a neutral one: "absent" and "average" are different facts,
#: and the lesson generator stays silent on this value.
UNKNOWN = "UNKNOWN"

#: Entry quality is graded from the ADVERSE excursion the hold actually
#: recorded, as a percentage of the entry premium. Hokage only ever BUYS
#: premium, so these are negative and ordered worst-last.
#:
#: The boundaries are read off his own tape, not invented. Bucketing the 110
#: real closed trades in trade_autopsies.jsonl by max_adverse_excursion_pct on
#: 2026-11-01 gave:
#:
#:     MAE >= -3%     n=39   win 87.2%   net +82,496
#:     -8% .. -3%     n=26   win 42.3%   net  +9,887
#:     -15% .. -8%    n=23   win  8.7%   net -34,679
#:     MAE < -15%     n= 6   win  0.0%   net -14,422
#:
#: Monotone in both win rate and money, which is the whole reason to grade on
#: it. It is also IN-SAMPLE — the buckets were cut on the corpus they
#: describe — so this is a descriptive label for an autopsy, NOT a measured
#: edge and NOT a gate. Nothing here may size a position or open a trade.
_ENTRY_MAE_EXCELLENT = -3.0
_ENTRY_MAE_GOOD      = -8.0
_ENTRY_MAE_FAIR      = -15.0

#: Stop quality is graded on the fraction of premium the position ACTUALLY
#: risked — `_risk_pct_for`, min(premium backstop, ATR thesis stop) — not on a
#: distance to `stop_price`, which for a bought option is the TRAIL_LOCK profit
#: floor and stops nothing (see _grade_stop_quality).
#:
#: Both bounds are cut on his own tape, and deliberately on the two populations
#: that are NOT circular. Judging a stop by how far trades ran against
#: themselves would be circular for every trade the stop truncated, so:
#:
#: TIGHT is read off the heat his WINNERS took — noise the stop had to SURVIVE,
#: which the stop did not cause. Over the 47 valid winners on 2026-11-01:
#:
#:     a stop at  3%  would have killed 13 of 47 winners  (27.7%)
#:     a stop at  5%  would have killed  8 of 47           (17.0%)
#:     a stop at  7%  would have killed  4 of 47           ( 8.5%)
#:     a stop at 12%  would have killed  0 of 47
#:
#: 7.04% is the winners' p90 heat: below it, more than one winner in ten was
#: carrying adverse movement the stop would have cut off. The old 0.03 was the
#: right idea in the wrong unit — it is a third of the way inside his noise.
#:
#: WIDE is read off where his LOSERS actually resolved, because a stop beyond
#: that never gets a chance to act. Over the same 47 losers: p50 8.90%,
#: p90 17.01%, p95 22.11%, max 28.36%. Past 17% a stop is further out than 9
#: of 10 of his realised losses ever reached.
#:
#: GRADING bounds. They change no order, no size, no stop and no gate — the
#: real stops are _OPTION_BACKSTOP_TIERS and the ATR thesis multiple, and
#: neither is touched here. In-sample, like the entry bands.
_STOP_TIGHT_RATIO   = 0.07   # risk < 7% of premium = inside his own noise
_STOP_WIDE_RATIO    = 0.17   # risk > 17% of premium = past where losses land

#: Sizing is graded against the cap the options router already enforces —
#: MAX_PREMIUM_CHEST_FRACTION, one position's premium against its strategy's
#: war chest — scaled by conviction, so a 100-conviction trade is entitled to
#: the whole cap and a 50-conviction trade to half of it. These two numbers
#: are the tolerance band around that entitlement. They are GRADING
#: tolerances: they change no order, no size, no stop and no gate.
_SIZING_OVER_MULT   = 1.5
_SIZING_UNDER_MULT  = 0.5

#: Whole-word matchers for the exit reason. The bare substrings these replace
#: were the same landmine the "TP" test already proved: "SL" also matches
#: SLIPPAGE and "TSL" also matches TSLA, and the thesis-stop reason
#: interpolates the underlying's own name straight into the text.
_SL_TOKEN  = re.compile(r"\bSL\b")
_TSL_TOKEN = re.compile(r"\bTSL\b")


def _format_hold(holding_days: int, holding_seconds: float | None) -> str:
    """Render the hold the way it was actually held.

    `holding_days` is an int, and this system's trades live and die inside one
    session, so every honest value rounds to 0 and "0d hold" says nothing.
    When the caller knows the seconds, say them.
    """
    if not holding_seconds or holding_seconds <= 0:
        return f"{holding_days}d"
    minutes = holding_seconds / 60.0
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


class PositionReviewEngine:
    """Analyses closed trades and generates structured quality reviews.

    Usage (called asynchronously from autonomous_bot after exit):

        review = engine.review_trade(
            symbol="ONGC",
            entry_price=190.0,
            exit_price=198.5,
            stop_price=180.0,
            target_price=210.0,
            conviction_score=84,
            position_size_pct=2.0,
            holding_days=3,
            exit_reason="Take Profit Triggered",
            pnl=1200.0,
            decision_id="uuid-...",
        )
    """

    def __init__(
        self,
        memory_manager: MemoryManager | None = None,
        brain_root: Path | None = None,
    ) -> None:
        """Initialize PositionReviewEngine."""
        self._memory_manager = memory_manager
        self._resolver = PathResolver(brain_root)
        self._reviews_dir = self._resolver.resolve_brain_root() / "reviews"
        self._reviews_dir.mkdir(parents=True, exist_ok=True)
        self._reviews_file = self._reviews_dir / "position_reviews.jsonl"

    # ------------------------------------------------------------------
    # Primary review method
    # ------------------------------------------------------------------

    def review_trade(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        stop_price: float,
        target_price: float,
        conviction_score: int,
        position_size_pct: float | None,
        holding_days: int,
        exit_reason: str,
        pnl: float,
        decision_id: str = "",
        return_pct: float = 0.0,
        holding_seconds: float | None = None,
        mae_pct: float | None = None,
        risk_pct: float | None = None,
    ) -> PositionReview:
        """Generate a PositionReview for a closed trade.

        `position_size_pct` is the premium committed at entry as a percentage
        of that strategy's war chest — the denominator the premium cap is
        already written in. `mae_pct` is the worst unrealized move against the
        position during the hold, in percent of entry, recorded live by the
        exit ladder. `risk_pct` is the fraction of premium the position
        actually risked, frozen at entry by `_risk_pct_for`. All three accept
        None, meaning the entry record never carried the fact; the grade that
        needs it then reads UNKNOWN.

        Returns a frozen PositionReview dataclass and persists to disk.
        Lesson is forwarded to MemoryManager if available.
        """
        entry_quality  = self._grade_entry_quality(mae_pct)
        exit_quality   = self._grade_exit_quality(exit_reason, exit_price, target_price, stop_price, entry_price)
        sizing_quality = self._grade_sizing_quality(position_size_pct, conviction_score)
        stop_quality   = self._grade_stop_quality(risk_pct)
        rr_measured    = self._compute_rr_achieved(entry_price, exit_price, stop_price)
        # The dataclass field stays a float so the JSONL stays valid JSON and
        # every existing reader keeps working; the lesson and the log line are
        # told the difference between "zero" and "could not tell".
        rr_achieved    = 0.0 if rr_measured is None else rr_measured
        lesson         = self._generate_lesson(
            symbol, entry_quality, exit_quality, sizing_quality,
            stop_quality, rr_measured, pnl, holding_days, conviction_score,
            holding_seconds,
        )

        review = PositionReview(
            decision_id=decision_id,
            symbol=symbol.upper(),
            entry_quality=entry_quality,
            exit_quality=exit_quality,
            sizing_quality=sizing_quality,
            stop_quality=stop_quality,
            risk_reward_achieved=rr_achieved,
            pnl=round(pnl, 2),
            return_pct=round(return_pct, 4),
            holding_days=holding_days,
            lesson=lesson,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._persist(review)
        self._forward_lesson(review)

        logger.info(
            "Position review: %s | entry=%s exit=%s sizing=%s stop=%s R:R=%s",
            symbol.upper(), entry_quality, exit_quality, sizing_quality, stop_quality,
            "unknown (no entry stop on record)" if rr_measured is None
            else f"{rr_measured:.2f}",
        )
        return review

    # ------------------------------------------------------------------
    # Grading helpers
    # ------------------------------------------------------------------

    def _grade_entry_quality(self, mae_pct: float | None) -> str:
        """Grade the entry on the heat it took, measured live during the hold.

        WHAT THIS REPLACED, AND WHY (2026-11-01)
        The old grade compared the entry price to an "ideal entry zone" at
        stop + 10% of the stop-to-target range. But all three of Hokage's
        entry paths derive BOTH levels from the entry itself:

            stop   = entry * (1 - tsl_percent)
            target = entry * (1 + tp_percent)

        so the entry price cancels out of the formula completely. Substituting
        the production 5%/10% geometry:

            deviation = (0.9*tsl - 0.1*tp) / (tsl + tp) = 0.2333

        for a 1-rupee option and a 184,000-rupee one alike — and 0.2333 is
        past the 0.20 FAIR bound, so the answer was POOR for every trade ever
        taken. The corpus agrees: 436 of 488 reviews read POOR. The grade was
        a readout of the risk config, not of the entry.

        The 52 that read otherwise were not better entries. They are records
        where entry_price and the stop/target it was supposed to have
        generated had come apart — BROKEN records. Which is why EXCELLENT
        landed on exactly 5 trades, all 5 of them losses, together -7,721.75,
        while POOR covered 64 trades worth +40,646.25. This did not merely
        fail to inform: it pointed backwards, and _generate_lesson forwarded
        "entry was placed too far from the ideal entry zone" into long-term
        memory on every winner Hokage has ever had.

        Adverse excursion is the honest measurement, and it was already being
        taken — the exit ladder writes `trough_price` on every surveillance
        tick and the exit path already computes MAE% from it for component
        attribution. It was simply never handed to the review.

        An MAE of exactly 0.00 is kept as a measurement, not discarded: the
        ladder seeds `trough_price` AT the entry and lowers it on every tick,
        so zero means "never once traded below entry" for any position the
        ladder actually saw. It is indistinguishable from a position the
        ladder never saw at all, which biases very short holds optimistic —
        the trade-off is accepted because throwing the value away would lose
        the real zeroes too, and they are the best entries he has.

        A POSITIVE MAE is UNKNOWN, not EXCELLENT. Hokage only buys premium, so
        the worst point of a hold cannot sit above the entry; 16 of the 110
        real trades carry one anyway (together -26,671.75, 6% win rate), and
        grading those EXCELLENT would rebuild the exact bug this replaces.
        """
        if mae_pct is None:
            return UNKNOWN
        try:
            mae = float(mae_pct)
        except (TypeError, ValueError):
            return UNKNOWN
        if mae > 0.0:
            return UNKNOWN
        if mae >= _ENTRY_MAE_EXCELLENT:
            return "EXCELLENT"
        if mae >= _ENTRY_MAE_GOOD:
            return "GOOD"
        if mae >= _ENTRY_MAE_FAIR:
            return "FAIR"
        return "POOR"

    def _grade_exit_quality(
        self,
        exit_reason: str,
        exit_price: float,
        target_price: float,
        stop_price: float,
        entry_price: float,
    ) -> str:
        """Classify the exit from the reason the ladder ACTUALLY emitted.

        THIS GRADED HOKAGE'S BEST TRADES AS HIS WORST (found 2026-08-19). The
        matcher was written against English paraphrases the exit ladder has
        never produced. Production emits TOKENS, and the real distribution
        across every exit in history was:

            Underlying Thesis Stop   26  -> STOP_HIT   (matched by luck: "Stop")
            EOD                      18  -> PREMATURE
            TARGET_HIT               15  -> PREMATURE  WRONG. It is ON_TARGET.
            Option Hard Backstop     12  -> STOP_HIT   (matched: "stop" inside
                                                        "Backstop")
            TRAIL_LOCK                9  -> PREMATURE  WRONG. It is TRAILING.

        24 of 80 exits — 30%, and EVERY SINGLE TARGET HIT — fell through to the
        worst grade available. _build_lesson then wrote "Exit was premature,
        trade closed before stop or target triggered" into the autopsy of a
        trade that closed exactly ON its target, fifteen times. ImprovementBot
        has been learning from that record.

        The two clean wins on 2026-08-19 and 2026-08-18 were both filed this
        way, which is how it surfaced: a CRUDEOIL call that hit its adaptive
        target to the rupee was recorded as exiting prematurely.

        ORDER MATTERS. TARGET_HIT and TRAIL_LOCK are matched BEFORE the generic
        "STOP" test, because "Option Hard Backstop" contains "stop" and would
        otherwise swallow anything checked after it.

        The bare "TP" substring is also gone: it matched any reason containing
        those two letters anywhere, which is a false positive waiting to happen.
        "SL" and "TSL" were the same landmine still armed — "SL" is inside
        SLIPPAGE, "TSL" inside TSLA, and the thesis-stop reason interpolates
        the underlying's name into the text — so both are whole-word now.

        A MANDATED exit (EOD square-off, kill switch, commander instant-exit)
        still reads PREMATURE. That is pinned, not overlooked: whether an exit
        Hokage was ORDERED to take deserves the word "premature" is the
        commander's judgement, and renaming it here would be a silent one.
        See test_eod_squareoff_still_grades_premature.
        """
        reason_upper = exit_reason.upper()
        if "TARGET_HIT" in reason_upper or "TAKE PROFIT" in reason_upper:
            return "ON_TARGET"
        if ("TRAIL_LOCK" in reason_upper or "TRAILING" in reason_upper
                or _TSL_TOKEN.search(reason_upper)):
            return "TRAILING"
        if "STOP" in reason_upper or _SL_TOKEN.search(reason_upper):
            # A stop that fired ABOVE the entry is the trailing floor doing its
            # job, not the entry stop being hit.
            #
            # The `target_price > entry_price` term this used to carry as well
            # was dead weight: every entry path sets target = entry * (1 +
            # tp_percent), so it is true by construction and never once
            # changed the answer.
            if exit_price > entry_price:
                return "TRAILING"
            return "STOP_HIT"
        # Everything left really did close before either level was reached —
        # an EOD square-off, a kill switch, or a manual exit.
        return "PREMATURE"

    def _grade_sizing_quality(
        self,
        chest_fraction_pct: float | None,
        conviction_score: int,
    ) -> str:
        """Was the premium committed proportional to the conviction behind it?

        WHY THIS WAS DEAD (2026-11-01)
        It read `allocation_pct` off the entry record, and only ONE of the
        three entry paths has ever written that key. The index options path
        sets it; the MCX Arena path and the manual-entry path do not. So the
        review fell to its `1.0` default, and 1.0/conviction*100 lands inside
        the CORRECT band for every conviction Hokage scores. 487 of 488
        reviews read CORRECT, 1 read OVERSIZED. The grade was a constant, and
        it was a constant computed from a number nobody had measured.

        The denominator is now the strategy's own war chest, recorded at entry
        by every path, because that is the denominator the risk cap is already
        written in: MAX_PREMIUM_CHEST_FRACTION caps one position's premium at
        33% of its chest. Entitlement scales with conviction, and the grade is
        where the trade actually sat against its own entitlement.

        None stays UNKNOWN. Inventing a size for a trade that never recorded
        one is precisely what made this grade useless, and the lesson built on
        it goes to long-term memory.
        """
        if chest_fraction_pct is None:
            return UNKNOWN
        try:
            used = float(chest_fraction_pct)
        except (TypeError, ValueError):
            return UNKNOWN
        if used <= 0.0 or conviction_score <= 0:
            return UNKNOWN
        entitled = MAX_PREMIUM_CHEST_FRACTION * 100.0 * (conviction_score / 100.0)
        if entitled <= 0.0:
            return UNKNOWN
        ratio = used / entitled
        if ratio > _SIZING_OVER_MULT:
            return "OVERSIZED"
        if ratio < _SIZING_UNDER_MULT:
            return "UNDERSIZED"
        return "CORRECT"

    def _grade_stop_quality(self, risk_pct: float | None) -> str:
        """Was the risk accepted sized to the noise this instrument produces?

        WHAT THIS REPLACED, AND WHY (2026-11-01)
        It measured the distance from entry to `stop_price`, and for a BOUGHT
        option `stop_price` is not a stop. It is the TRAIL_LOCK profit floor:
        rung 4 only arms once the peak clears entry * (1 + TRAIL_ARM_PCT), and
        the floor it then sets is max(trail_floor, entry) — never below entry.
        The value sitting in that field before arming is a seed that can never
        fire. The grade was reading a number that cannot stop anything.

        It was also a CONSTANT, and it became one as a side effect of the R:R
        fix (9f0d6f4). Freezing `initial_stop_price` made the input exactly
        entry * (1 - tsl_percent) on every path, so the distance was
        tsl_percent = 0.05 for every trade, which sits inside the old
        0.03 .. 0.10 band: CORRECT, always. The 20 TIGHT and 22 WIDE in the
        corpus are all pre-fix records that read the live ratcheting floor —
        which is why 14 of his 48 winners were filed TIGHT, the same
        winners-only bias that fix was written to remove.

        And the unit was wrong, which is what the commander flagged: 3% and
        10% were calibrated for moves in an UNDERLYING and applied to option
        PREMIUM, where 3% is routine tick noise.

        The real risk is whichever stop bites first — the tiered premium
        backstop or the ATR thesis stop on the underlying — and production
        already computes exactly that in `_risk_pct_for`, validated against
        real fills (it predicts ~4.1% for NATURALGAS where thesis exits landed
        at 2.9-5.3%). It is now frozen at entry and read here.

        UNKNOWN, not CORRECT, when it was never recorded. The old fallback
        asserted the stop was right while admitting it could not see it.
        """
        if risk_pct is None:
            return UNKNOWN
        try:
            risk = float(risk_pct)
        except (TypeError, ValueError):
            return UNKNOWN
        if risk <= 0.0:
            return UNKNOWN
        if risk < _STOP_TIGHT_RATIO:
            return "TIGHT"
        if risk > _STOP_WIDE_RATIO:
            return "WIDE"
        return "CORRECT"

    def _compute_rr_achieved(
        self,
        entry_price: float,
        exit_price: float,
        stop_price: float,
    ) -> float | None:
        """Reward at exit over the risk accepted at entry, or None if unknown.

        `stop_price` MUST be the stop as it stood at entry. The caller's
        `tracking["stop_price"]` is a live trailing floor that the ladder
        ratchets to break-even at Target 1 and higher after, so a trade that
        ran far enough to win arrives here with stop == entry: risk zero.
        That is why GOLDM26NOV141000PE, +13.8% and ON_TARGET on 2026-10-30,
        was reviewed `stop=TIGHT R:R=0.00` at a true 2.75 - and why the
        generated lesson told the commander to tighten the target on the best
        trade of his day. The entry path now freezes `initial_stop_price`.

        None means UNMEASURABLE, which is not 0.00. A zero would be read as a
        trade that risked everything for nothing, and would pull the "Low R:R
        despite profit" lesson onto a clean winner.
        """
        if entry_price <= 0 or stop_price <= 0:
            return None
        risk = abs(entry_price - stop_price)
        if risk == 0:
            return None
        reward = exit_price - entry_price
        return round(reward / risk, 4)

    # ------------------------------------------------------------------
    # Lesson generation
    # ------------------------------------------------------------------

    def _generate_lesson(
        self,
        symbol: str,
        entry_quality: str,
        exit_quality: str,
        sizing_quality: str,
        stop_quality: str,
        rr_achieved: float | None,
        pnl: float,
        holding_days: int,
        conviction_score: int,
        holding_seconds: float | None = None,
    ) -> str:
        """Auto-generate a structured lesson from quality grades."""
        outcome_str = "profitable" if pnl >= 0 else "a loss-making"
        parts: list[str] = [
            f"{symbol} was {outcome_str} trade (PnL: {pnl:+.2f}, "
            f"{_format_hold(holding_days, holding_seconds)} hold, "
            f"conviction={conviction_score})."
        ]

        # UNKNOWN is deliberately absent from every test below. A grade that
        # could not be computed must produce no sentence at all: this text is
        # forwarded to long-term memory, where a guess is indelible.
        if entry_quality == "POOR":
            parts.append(
                "Entry took heavy heat — the position ran more than 15% "
                "against itself before this exit, which is the worst band in "
                "Hokage's record and has never yet produced a win."
            )
        if entry_quality == "FAIR":
            parts.append(
                "Entry took real heat — the position ran 8-15% against itself "
                "during the hold. Consider waiting for confirmation before "
                "committing premium on similar setups."
            )
        if exit_quality == "PREMATURE":
            parts.append("Exit was premature — trade closed before stop or target triggered.")
        if exit_quality == "STOP_HIT" and pnl < 0:
            parts.append("Stop was hit — review whether stop placement or entry timing contributed.")
        if sizing_quality == "OVERSIZED":
            parts.append("Position was oversized relative to conviction level — reduce size on similar setups.")
        if sizing_quality == "UNDERSIZED":
            parts.append("Position was undersized relative to conviction — review sizing model calibration.")
        if stop_quality == "TIGHT":
            parts.append(
                "The risk accepted was inside this market's own noise — adverse "
                "movement of this size has been survived by more than one in "
                "ten of Hokage's winners, so a stop here gets taken out by "
                "fluctuation rather than by the thesis failing."
            )
        if stop_quality == "WIDE":
            parts.append(
                "The risk accepted was further out than 9 of 10 realised losses "
                "ever reach, so it was not protecting the position — review the "
                "premium backstop tier and the ATR thesis multiple."
            )
        # Both clauses stay silent when R:R is unmeasurable. Saying "Low R:R
        # of 0.00 despite profit - tighten target" to a trade that hit its
        # target is worse than saying nothing, and these lessons are forwarded
        # to long-term memory.
        if rr_achieved is not None and rr_achieved >= 2.0 and pnl >= 0:
            parts.append(f"Excellent R:R achieved: {rr_achieved:.2f} — this setup should be replicated.")
        if rr_achieved is not None and rr_achieved < 1.0 and pnl >= 0:
            parts.append(f"Low R:R of {rr_achieved:.2f} despite profit — tighten target or improve exit timing.")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, review: PositionReview) -> None:
        """Append review to position_reviews.jsonl."""
        try:
            with self._reviews_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(review), sort_keys=True) + "\n")
        except Exception as exc:
            logger.error("Failed to persist position review: %s", exc)

    def _forward_lesson(self, review: PositionReview) -> None:
        """Forward lesson to MemoryManager for long-term retention."""
        if self._memory_manager is None:
            return
        try:
            event = {
                "event_id":          f"review_{review.decision_id or review.symbol}_{review.timestamp[:10]}",
                "event_description": review.lesson,
                "event_category":    "POSITION_REVIEW",
                "event_date":        review.timestamp[:10],
                "affected_sectors":  [review.symbol.lower()],
                "lessons_learned":   review.lesson,
                "sentiment_score":   0.2 if review.pnl >= 0 else -0.2,
                "vix_impact_delta":  0.0,
            }
            self._memory_manager.record_event(event)
        except Exception as exc:
            logger.warning("Failed to forward lesson to MemoryManager: %s", exc)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_reviews(self) -> list[dict[str, Any]]:
        """Load all position reviews from disk."""
        reviews: list[dict[str, Any]] = []
        if not self._reviews_file.exists():
            return reviews
        try:
            with self._reviews_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_str = line.strip()
                    if line_str:
                        reviews.append(json.loads(line_str))
        except Exception as exc:
            logger.error("Failed to read position reviews: %s", exc)
        return reviews

    def get_reviews_path(self) -> Path:
        """Return absolute path to reviews file (for testing)."""
        return self._reviews_file
