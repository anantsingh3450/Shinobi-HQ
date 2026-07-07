"""Position Review Engine for Hokage — Phase 4C.5D.

Performs post-exit quality analysis for every closed trade.
Runs asynchronously after exit to preserve Layer 1 execution speed.

Reviews:
    - Entry quality  : How close to ideal entry price?
    - Exit quality   : TSL / TP / Premature / Trailing?
    - Sizing quality : Was position size calibrated to conviction?
    - Stop quality   : Was stop too tight, correct, or too wide?
    - Lesson         : Auto-generated structured lesson text

Storage: hokage_brain/reviews/position_reviews.jsonl
Lessons are also forwarded to MemoryManager for long-term retention.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from hokage.memory.resolver import PathResolver
from bots.autonomous.models import PositionReview

if TYPE_CHECKING:
    from bots.autonomous.memory import MemoryManager

logger = logging.getLogger("Hokage.PositionReview")

# ---------------------------------------------------------------------------
# Quality grade constants
# ---------------------------------------------------------------------------
_ENTRY_EXCELLENT_THRESHOLD = 0.005   # within 0.5% of entry
_ENTRY_GOOD_THRESHOLD      = 0.01    # within 1%
_ENTRY_FAIR_THRESHOLD      = 0.02    # within 2%

_STOP_TIGHT_RATIO   = 0.03   # stop < 3% from entry
_STOP_WIDE_RATIO    = 0.10   # stop > 10% from entry

_SIZING_OVER        = 3.0    # size > 3% per conviction unit = oversized
_SIZING_UNDER       = 0.5    # size < 0.5% per conviction unit = undersized


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
        position_size_pct: float,
        holding_days: int,
        exit_reason: str,
        pnl: float,
        decision_id: str = "",
        return_pct: float = 0.0,
    ) -> PositionReview:
        """Generate a PositionReview for a closed trade.

        Returns a frozen PositionReview dataclass and persists to disk.
        Lesson is forwarded to MemoryManager if available.
        """
        entry_quality  = self._grade_entry_quality(entry_price, target_price, stop_price)
        exit_quality   = self._grade_exit_quality(exit_reason, exit_price, target_price, stop_price, entry_price)
        sizing_quality = self._grade_sizing_quality(position_size_pct, conviction_score)
        stop_quality   = self._grade_stop_quality(entry_price, stop_price)
        rr_achieved    = self._compute_rr_achieved(entry_price, exit_price, stop_price)
        lesson         = self._generate_lesson(
            symbol, entry_quality, exit_quality, sizing_quality,
            stop_quality, rr_achieved, pnl, holding_days, conviction_score
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
            "Position review: %s | entry=%s exit=%s sizing=%s stop=%s R:R=%.2f",
            symbol.upper(), entry_quality, exit_quality, sizing_quality, stop_quality, rr_achieved
        )
        return review

    # ------------------------------------------------------------------
    # Grading helpers
    # ------------------------------------------------------------------

    def _grade_entry_quality(
        self,
        entry_price: float,
        target_price: float,
        stop_price: float,
    ) -> str:
        """Assess how close the actual entry was to the ideal entry zone."""
        if entry_price <= 0 or target_price <= 0:
            return "FAIR"
        trade_range = abs(target_price - stop_price)
        if trade_range == 0:
            return "FAIR"
        # Ideal entry is at or below stop + 10% of range
        ideal_entry_zone = stop_price + trade_range * 0.10
        deviation = abs(entry_price - ideal_entry_zone) / trade_range
        if deviation <= _ENTRY_EXCELLENT_THRESHOLD * 10:
            return "EXCELLENT"
        elif deviation <= _ENTRY_GOOD_THRESHOLD * 10:
            return "GOOD"
        elif deviation <= _ENTRY_FAIR_THRESHOLD * 10:
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
        """Classify exit type."""
        reason_upper = exit_reason.upper()
        if "TAKE PROFIT" in reason_upper or "TP" in reason_upper:
            return "ON_TARGET"
        if "TRAILING" in reason_upper or "TSL" in reason_upper:
            return "TRAILING"
        if "STOP" in reason_upper or "SL" in reason_upper:
            # Differentiate: did it hit stop near target (trailing) or early?
            if target_price > entry_price and exit_price > entry_price:
                return "TRAILING"
            return "STOP_HIT"
        # Premature = exit before stop or target triggered
        return "PREMATURE"

    def _grade_sizing_quality(
        self,
        position_size_pct: float,
        conviction_score: int,
    ) -> str:
        """Compare position size to conviction score ratio."""
        if conviction_score <= 0:
            return "CORRECT"
        size_per_conviction = position_size_pct / conviction_score * 100.0
        if size_per_conviction > _SIZING_OVER:
            return "OVERSIZED"
        elif size_per_conviction < _SIZING_UNDER:
            return "UNDERSIZED"
        return "CORRECT"

    def _grade_stop_quality(self, entry_price: float, stop_price: float) -> str:
        """Grade stop placement relative to entry distance."""
        if entry_price <= 0 or stop_price <= 0:
            return "CORRECT"
        stop_distance = abs(entry_price - stop_price) / entry_price
        if stop_distance < _STOP_TIGHT_RATIO:
            return "TIGHT"
        elif stop_distance > _STOP_WIDE_RATIO:
            return "WIDE"
        return "CORRECT"

    def _compute_rr_achieved(
        self,
        entry_price: float,
        exit_price: float,
        stop_price: float,
    ) -> float:
        """Compute actual R:R achieved at exit."""
        if entry_price <= 0 or stop_price <= 0:
            return 0.0
        risk = abs(entry_price - stop_price)
        if risk == 0:
            return 0.0
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
        rr_achieved: float,
        pnl: float,
        holding_days: int,
        conviction_score: int,
    ) -> str:
        """Auto-generate a structured lesson from quality grades."""
        outcome_str = "profitable" if pnl >= 0 else "a loss-making"
        parts: list[str] = [
            f"{symbol} was {outcome_str} trade (PnL: {pnl:+.2f}, "
            f"{holding_days}d hold, conviction={conviction_score})."
        ]

        if entry_quality in ("FAIR", "POOR"):
            parts.append("Entry quality was suboptimal — entry was placed too far from the ideal entry zone.")
        if exit_quality == "PREMATURE":
            parts.append("Exit was premature — trade closed before stop or target triggered.")
        if exit_quality == "STOP_HIT" and pnl < 0:
            parts.append("Stop was hit — review whether stop placement or entry timing contributed.")
        if sizing_quality == "OVERSIZED":
            parts.append("Position was oversized relative to conviction level — reduce size on similar setups.")
        if sizing_quality == "UNDERSIZED":
            parts.append("Position was undersized relative to conviction — review sizing model calibration.")
        if stop_quality == "TIGHT":
            parts.append("Stop was placed too tightly — increased risk of stop hunting on volatile sessions.")
        if stop_quality == "WIDE":
            parts.append("Stop was too wide — poor risk management, exceeding normal risk-per-trade tolerance.")
        if rr_achieved >= 2.0 and pnl >= 0:
            parts.append(f"Excellent R:R achieved: {rr_achieved:.2f} — this setup should be replicated.")
        if rr_achieved < 1.0 and pnl >= 0:
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
