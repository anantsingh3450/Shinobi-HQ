"""Attribution Engine for Phase 6.5.

Grades trade decisions, outcomes, and reality attributions.
Computes the Shadow Reality Score and compiles the 9-Why Explainability Manifest.
"""
from __future__ import annotations

import json
import math
import logging
from datetime import datetime, timezone
from typing import Any

from shared.persistence.sqlite_engine import SqliteStorageEngine

logger = logging.getLogger("Hokage.AttributionEngine")

class AttributionEngine:
    """Manages trade decision attribution, quadrant classification, and reality score calculations."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with SQLite storage engine."""
        self.engine = engine

    def classify_and_attribute_trade(
        self,
        decision_id: str,
        symbol: str,
        pnl: float,
        return_pct: float,
        expected_return_pct: float,
        expected_risk_pct: float,
        ic_confidence: int,
        market_regime: str,
        volatility_regime: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        reasoning_chain: list[dict[str, Any]],
        rejected_candidates: list[str] | None = None,
    ) -> dict[str, Any]:
        """Classify a completed trade, record its attribution, and generate its explainability manifest."""
        conn = self.engine.get_connection()

        # 1. Math calculations
        expected_move = expected_return_pct
        actual_move = return_pct * 100.0  # convert decimal to percentage

        # Expected Edge = Expected Return % / Expected Risk % (avoid division by zero)
        expected_edge = expected_move / expected_risk_pct if expected_risk_pct > 0 else 0.0

        # Risk Taken % (distance from entry to stop as % of entry)
        risk_taken_pct = (abs(entry_price - stop_price) / entry_price) * 100.0 if entry_price > 0 else expected_risk_pct
        
        # Realized Edge = Actual Move % / Risk Taken %
        realized_edge = actual_move / risk_taken_pct if risk_taken_pct > 0 else 0.0

        # Risk Taken absolute value
        risk_taken = abs(entry_price - stop_price)

        # Risk/Reward Quality (Actual Reward / Actual Risk)
        actual_reward = abs(target_price - entry_price)
        actual_risk = abs(entry_price - stop_price)
        risk_reward_quality = actual_reward / actual_risk if actual_risk > 0 else 0.0

        # 2. Quadrant Classification
        # Favorable expected edge and structurally sound IC confidence
        is_correct_decision = (expected_edge >= 1.0) and (ic_confidence >= 60)
        is_profitable = pnl > 0

        if is_correct_decision and is_profitable:
            classification = "CORRECT_DECISION_PROFITABLE"
        elif is_correct_decision and not is_profitable:
            classification = "CORRECT_DECISION_LOSS"
        elif not is_correct_decision and is_profitable:
            classification = "INCORRECT_DECISION_PROFIT"  # Luck!
        else:
            classification = "INCORRECT_DECISION_LOSS"

        # 3. Post-Trade Quality Grading (A+ to F)
        overall_grade = "B"
        if classification == "CORRECT_DECISION_PROFITABLE":
            overall_grade = "A+" if realized_edge >= 2.0 else "A"
        elif classification == "CORRECT_DECISION_LOSS":
            overall_grade = "B"  # Structurally correct, just bad luck
        elif classification == "INCORRECT_DECISION_PROFIT":
            overall_grade = "C"  # Profitable but bad structure (lucky)
        elif classification == "INCORRECT_DECISION_LOSS":
            overall_grade = "F"

        # 4. Compile the 9-Why Explainability Manifest
        why_taken = "Triggered on technical momentum signal."
        why_size = "Sized according to 1% account risk limit."
        why_stop = f"Placed at key support level of {stop_price}."
        why_target = f"Placed at resistance level of {target_price}."
        why_now = "Breakout confirmed by volume expansion."
        why_not_later = "Entering late would violate the minimum 1:2 risk/reward ratio."
        why_strategy = "Strategy selected fits the current regime."
        why_asset = f"Asset {symbol} ranked highest on scanner."
        why_regime = f"Executed under {market_regime} market and {volatility_regime} volatility regime."
        why_rejected = f"Vetoed other candidates: {', '.join(rejected_candidates or ['None'])} due to risk limits."

        for gate in reasoning_chain:
            gate_name = gate.get("gate", "").lower()
            gate_decision = gate.get("decision", "")
            gate_reason = gate.get("reason", "")
            if "preservation" in gate_name or "health" in gate_name:
                why_size = f"Sized using Portfolio Health adjustments: {gate_reason}"
            if "conviction" in gate_name:
                why_taken = f"Conviction Score evaluation: {gate_reason}"
            if "allocation" in gate_name or "risk" in gate_name:
                why_size = f"Position Allocation constraints: {gate_reason}"
            if "no_trade" in gate_name and gate_decision == "VETO":
                why_rejected = f"Rejected candidate: {gate_reason}"

        explainability_manifest = {
            "why_taken": why_taken,
            "why_position_size": why_size,
            "why_stop_loss": why_stop,
            "why_target": why_target,
            "why_now": why_now,
            "why_not_later": why_not_later,
            "why_this_strategy": why_strategy,
            "why_this_asset": why_asset,
            "why_this_regime": why_regime,
            "why_another_rejected": why_rejected,
        }

        # 5. Persist Attribution and Replay Chronology
        try:
            with conn:
                # Insert into trade_attributions
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trade_attributions (
                        decision_id, symbol, ic_gates_snapshot, dominant_factor,
                        expected_move, actual_move, expected_edge, realized_edge,
                        risk_taken, risk_reward_quality, ic_confidence, market_regime, volatility_regime,
                        decision_classification, entry_quality_grade, exit_quality_grade,
                        timing_quality_grade, risk_quality_grade, sizing_quality_grade,
                        overall_grade, explanation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        decision_id,
                        symbol,
                        json.dumps(reasoning_chain),
                        "TECHNICAL",
                        expected_move,
                        actual_move,
                        expected_edge,
                        realized_edge,
                        risk_taken,
                        risk_reward_quality,
                        ic_confidence,
                        market_regime,
                        volatility_regime,
                        classification,
                        "A",
                        "A",
                        "A",
                        "A",
                        "A",
                        overall_grade,
                        f"Trade classified as {classification} with overall grade {overall_grade}.",
                    ),
                )

                # Initialize lifecycle timeline with entry event
                timeline = [
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": "ENTRY",
                        "description": f"Position opened for {symbol} at price {entry_price}.",
                        "market_regime": market_regime,
                        "volatility_regime": volatility_regime,
                    }
                ]

                # Insert into trade_replays
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trade_replays (
                        trade_id, symbol, explainability_manifest, lifecycle_timeline
                    ) VALUES (?, ?, ? , ?);
                    """,
                    (
                        decision_id,
                        symbol,
                        json.dumps(explainability_manifest),
                        json.dumps(timeline),
                    ),
                )

            logger.info(f"Persisted trade attribution and replay engine shell for {decision_id}.")
        except Exception as exc:
            logger.error(f"Failed to persist trade attribution for {decision_id}: {exc}")
            raise exc

        return {
            "decision_id": decision_id,
            "classification": classification,
            "expected_edge": expected_edge,
            "realized_edge": realized_edge,
            "overall_grade": overall_grade,
            "explainability_manifest": explainability_manifest,
        }

    def record_replay_event(
        self, trade_id: str, event_type: str, description: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Append an event chronologically to the trade replay timeline."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute(
                "SELECT lifecycle_timeline FROM trade_replays WHERE trade_id = ?;", (trade_id,)
            )
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Replay timeline not found for trade {trade_id}. Cannot append event.")
                return

            timeline = json.loads(row[0])
            timeline.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": event_type.upper(),
                    "description": description,
                    "metadata": metadata or {},
                }
            )

            with conn:
                conn.execute(
                    "UPDATE trade_replays SET lifecycle_timeline = ? WHERE trade_id = ?;",
                    (json.dumps(timeline), trade_id),
                )
        except Exception as exc:
            logger.error(f"Failed to record replay event for {trade_id}: {exc}")

    def generate_reality_metrics(self) -> dict[str, Any]:
        """Load historical trade attributions and compute collective decision statistics."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT expected_edge, realized_edge, decision_classification FROM trade_attributions;")
            rows = cursor.fetchall()
            if not rows:
                return {
                    "total_trades": 0,
                    "decision_accuracy": 100.0,
                    "luck_index": 0.0,
                    "edge_realization": 0.0,
                    "decision_consistency": 100.0,
                    "reality_score": 100.0,
                    "quadrant_counts": {
                        "CORRECT_DECISION_PROFITABLE": 0,
                        "CORRECT_DECISION_LOSS": 0,
                        "INCORRECT_DECISION_PROFIT": 0,
                        "INCORRECT_DECISION_LOSS": 0,
                    }
                }

            total = len(rows)
            q_counts = {
                "CORRECT_DECISION_PROFITABLE": 0,
                "CORRECT_DECISION_LOSS": 0,
                "INCORRECT_DECISION_PROFIT": 0,
                "INCORRECT_DECISION_LOSS": 0,
            }

            sum_expected = 0.0
            sum_realized = 0.0
            scores = []

            for row in rows:
                cl = row["decision_classification"]
                if cl in q_counts:
                    q_counts[cl] += 1

                sum_expected += row["expected_edge"]
                sum_realized += row["realized_edge"]

                # Score mappings for consistency calculation
                if cl == "CORRECT_DECISION_PROFITABLE":
                    scores.append(100.0)
                elif cl == "CORRECT_DECISION_LOSS":
                    scores.append(80.0)
                elif cl == "INCORRECT_DECISION_PROFIT":
                    scores.append(40.0)
                else:
                    scores.append(20.0)

            # Decision Accuracy = Correct Decisions / Total
            correct_count = q_counts["CORRECT_DECISION_PROFITABLE"] + q_counts["CORRECT_DECISION_LOSS"]
            decision_accuracy = (correct_count / total) * 100.0

            # Luck Index = Incorrect + Profit / Total
            luck_index = (q_counts["INCORRECT_DECISION_PROFIT"] / total) * 100.0

            # Edge Realization = Sum(Realized) / Sum(Expected)
            edge_realization = sum_realized / sum_expected if sum_expected > 0 else 0.0
            # Clip edge realization percentage at 100% maximum for score mapping
            edge_realization_pct = min(max(edge_realization, 0.0), 1.0) * 100.0

            # Decision Consistency (Std dev of scores)
            if total > 1:
                mean_score = sum(scores) / total
                variance = sum((s - mean_score) ** 2 for s in scores) / (total - 1)
                decision_consistency = 100.0 - math.sqrt(variance)
            else:
                decision_consistency = 100.0

            # Reality Score: 50% Accuracy + 30% Edge Realization + 20% (100 - Luck)
            reality_score = (
                0.50 * decision_accuracy +
                0.30 * edge_realization_pct +
                0.20 * (100.0 - luck_index)
            )

            return {
                "total_trades": total,
                "decision_accuracy": round(decision_accuracy, 2),
                "luck_index": round(luck_index, 2),
                "edge_realization": round(edge_realization, 4),
                "decision_consistency": round(decision_consistency, 2),
                "reality_score": round(reality_score, 2),
                "quadrant_counts": q_counts,
            }
        except Exception as exc:
            logger.error(f"Failed to generate reality metrics: {exc}")
            return {
                "total_trades": 0,
                "decision_accuracy": 0.0,
                "luck_index": 0.0,
                "edge_realization": 0.0,
                "decision_consistency": 0.0,
                "reality_score": 0.0,
                "quadrant_counts": {},
            }
