"""End-of-Day Learning Loop for Hokage.

Automatically executes after hours to match historical predictions against actual
portfolio outcomes, archiving key event lessons in permanent memory.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.memory import MemoryManager

logger = logging.getLogger("Hokage.LearningLoop")


class EODLearningLoop:
    """Matches predictions against actual portfolio metrics to log cognitive lessons."""

    def __init__(self, orchestrator: HokageOrchestrator, memory_manager: MemoryManager) -> None:
        """Initialize learning loop."""
        self.orchestrator = orchestrator
        self.memory_manager = memory_manager

    def run_close_of_day_learning(self) -> dict[str, Any]:
        """Correlate strategy predictions from ledger with actual asset price changes."""
        logger.info("Executing EOD learning post-mortem analyzer.")
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 1. Fetch recorded predictions from ledger
        predictions = self.orchestrator.prediction_ledger.load_all()
        
        today_preds = []
        for p in predictions:
            pred_time = getattr(p, "predicted_at", None) or getattr(p, "recorded_at", None)
            if pred_time and pred_time.strftime("%Y-%m-%d") == today_str:
                today_preds.append(p)

        prediction_list = []
        actual_outcome_list = []
        error_count = 0

        for pred in today_preds:
            symbol = pred.market
            win_rate = pred.win_rate if (hasattr(pred, "win_rate") and isinstance(pred.win_rate, (int, float))) else 60.0
            
            # Use getattr with fallbacks to avoid AttributeErrors on standard PredictionRecord
            direction = str(getattr(pred, "direction", "LONG"))
            entry_price = float(getattr(pred, "entry_price", 100.0))
            
            prediction_list.append({
                "symbol": symbol,
                "predicted_direction": direction,
                "entry_price": entry_price,
                "expected_win_rate": win_rate
            })

            try:
                # Retrieve current price and compute change from entry
                current_price = self.orchestrator.price_source.get_price(symbol)
                pred_entry_price = getattr(pred, "entry_price", 100.0)
                pred_direction = getattr(pred, "direction", "LONG")
                price_delta = current_price - pred_entry_price
                direction_match = (price_delta > 0 and pred_direction == "LONG") or (price_delta < 0 and pred_direction == "SHORT")
                
                if not direction_match:
                    error_count += 1

                actual_outcome_list.append({
                    "symbol": symbol,
                    "actual_price": current_price,
                    "price_delta": round(price_delta, 2),
                    "is_correct": direction_match
                })
            except Exception as exc:
                logger.warning(f"Could not load EOD price for prediction match ({symbol}): {exc}")

        # 2. Query actual exits/trades taken today to calculate portfolio P&L
        realized_pnl = 0.0
        exits_count = 0
        try:
            bot = self.orchestrator.autonomous_bot
            realized_pnl = sum(e.get("pnl", 0.0) for e in bot._exits_executed_today)
            exits_count = len(bot._exits_executed_today)
        except Exception:
            pass

        total_preds = len(today_preds)
        win_rate = ((total_preds - error_count) / total_preds * 100.0) if total_preds > 0 else 0.0

        # Formulate divergence and errors
        prediction_error = {
            "mismatch_count": error_count,
            "prediction_win_rate": round(win_rate, 2),
            "realized_pnl_divergence": round(realized_pnl, 2)
        }

        # 3. Formulate lessons and persist into permanent memory
        lesson_desc = "Sideways consolidation"
        if win_rate >= 70.0:
            lesson_desc = "Heuristics aligned accurately with asset momentum."
        elif total_preds > 0 and win_rate < 40.0:
            lesson_desc = "Predictive parameters failed under high volatility; tighten risk stop limits."

        # Apply persona engine formatting
        try:
            from bots.autonomous.persona import PersonaEngine
            pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
            lesson_desc = pe.format_text(lesson_desc)
        except Exception:
            pass

        event_record = {
            "event_id": f"eod_learning_{today_str}",
            "event_description": f"End of Day prediction outcome check for {today_str}",
            "event_category": "LEARNING_LOOP",
            "event_date": today_str,
            "affected_sectors": ["general"],
            "predictions": prediction_list,
            "actual_outcomes": actual_outcome_list,
            "prediction_error": prediction_error,
            "lessons_learned": lesson_desc,
            "sentiment_score": 0.2 if win_rate > 50 else -0.2,
            "vix_impact_delta": 0.0
        }

        # Write EOD event permanently into memory
        self.memory_manager.record_event(event_record)

        return {
            "date": today_str,
            "predictions_checked": total_preds,
            "prediction_win_rate": round(win_rate, 2),
            "realized_pnl": round(realized_pnl, 2),
            "exits_count": exits_count,
            "lesson": lesson_desc
        }
