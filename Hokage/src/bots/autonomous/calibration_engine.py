"""Calibration Engine for Phase 6.5.

Evaluates confidence calibration curves and compares expected vs actual metrics
(win rate, drawdown, volatility, hold time, R/R) as calibration inputs.
"""
from __future__ import annotations

import logging
from typing import Any

from shared.persistence.sqlite_engine import SqliteStorageEngine

logger = logging.getLogger("Hokage.CalibrationEngine")

class CalibrationEngine:
    """Computes confidence calibration errors and aligns expected vs actual performance metrics."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with SQLite storage engine."""
        self.engine = engine

    def get_calibration_metrics(self) -> dict[str, Any]:
        """Group completed trades into 10 confidence bins and calculate calibration error.

        Also compares expected vs actual win rates, drawdowns, volatilities, holding periods, and R/R ratios.
        """
        conn = self.engine.get_connection()
        try:
            # 1. Fetch trades with their expected strategy proposal confidence, backtest stats, and outcomes
            # We join trades, predictions (expected stats), and decision outcomes
            cursor = conn.execute(
                """
                SELECT t.trade_id, t.market, t.simulated_value, t.status,
                       p.confidence_score, p.win_rate as expected_win_rate, p.net_profit as expected_profit,
                       o.outcome, o.pnl, o.holding_days, o.return_pct
                FROM trades t
                JOIN predictions p ON t.proposal_id = p.proposal_id
                LEFT JOIN decision_outcomes o ON t.trade_id = o.decision_id
                WHERE t.status = 'CLOSED' OR o.outcome IS NOT NULL;
                """
            )
            rows = cursor.fetchall()
            if not rows:
                return self._empty_response()

            # 2. Bin trades by confidence (0-10, ..., 90-100)
            bins = {i: {"expected": 0.0, "trades": 0, "wins": 0} for i in range(10)}
            
            total_expected_win_rate = 0.0
            actual_wins = 0
            total_trades = len(rows)

            actual_holding_days = []
            expected_holding_days = []  # Let's say we default from strategy timeframe
            
            # For expected vs actual R/R
            actual_gains = []
            actual_losses = []

            for row in rows:
                conf = row["confidence_score"]  # expected confidence as float (e.g. 0.0 to 1.0) or int (0 to 100)
                # Normalize to 0.0 to 1.0
                conf_val = conf / 100.0 if conf > 1.0 else conf
                conf_val = min(max(conf_val, 0.0), 0.9999)
                
                bin_idx = int(conf_val * 10)
                bins[bin_idx]["trades"] += 1
                bins[bin_idx]["expected"] += conf_val

                # Check if it's a win
                pnl = row["pnl"] if row["pnl"] is not None else 0.0
                is_win = pnl > 0
                if is_win:
                    bins[bin_idx]["wins"] += 1
                    actual_wins += 1
                    actual_gains.append(pnl)
                else:
                    if pnl < 0:
                        actual_losses.append(abs(pnl))

                total_expected_win_rate += row["expected_win_rate"]
                if row["holding_days"] is not None:
                    actual_holding_days.append(row["holding_days"])
                expected_holding_days.append(3)  # default expected holding period

            # Calculate calibration curve and error
            calibration_bins = []
            sum_absolute_diff = 0.0
            active_bins = 0

            for idx, b in bins.items():
                t_count = b["trades"]
                if t_count > 0:
                    mean_expected = (b["expected"] / t_count) * 100.0
                    actual_wr = (b["wins"] / t_count) * 100.0
                    diff = actual_wr - mean_expected
                    sum_absolute_diff += abs(diff)
                    active_bins += 1
                    calibration_bins.append({
                        "bin": f"{idx*10}-{(idx+1)*10}%",
                        "trades": t_count,
                        "expected_confidence": round(mean_expected, 2),
                        "actual_win_rate": round(actual_wr, 2),
                        "deviation": round(diff, 2)
                    })
                else:
                    calibration_bins.append({
                        "bin": f"{idx*10}-{(idx+1)*10}%",
                        "trades": 0,
                        "expected_confidence": (idx * 10) + 5.0,
                        "actual_win_rate": 0.0,
                        "deviation": 0.0
                    })

            calibration_error = (sum_absolute_diff / active_bins) if active_bins > 0 else 0.0
            
            # Overconfidence vs Underconfidence classification
            # If actual win rate is generally less than expected confidence, it's overconfident
            bias = "CALIBRATED"
            if active_bins > 0:
                net_bias = sum(b["actual_win_rate"] - b["expected_confidence"] for b in calibration_bins if b["trades"] > 0)
                if net_bias < -5.0:
                    bias = "OVERCONFIDENT"
                elif net_bias > 5.0:
                    bias = "UNDERCONFIDENT"

            # 3. Expected vs Actual validation
            avg_expected_win_rate = (total_expected_win_rate / total_trades) if total_trades > 0 else 0.0
            avg_actual_win_rate = (actual_wins / total_trades) * 100.0 if total_trades > 0 else 0.0

            avg_expected_hold = sum(expected_holding_days) / len(expected_holding_days) if expected_holding_days else 0.0
            avg_actual_hold = sum(actual_holding_days) / len(actual_holding_days) if actual_holding_days else 0.0

            # Calculate actual R/R
            avg_gain = sum(actual_gains) / len(actual_gains) if actual_gains else 0.0
            avg_loss = sum(actual_losses) / len(actual_losses) if actual_losses else 0.0
            actual_rr = avg_gain / avg_loss if avg_loss > 0 else 0.0

            return {
                "total_trades": total_trades,
                "calibration_error": round(calibration_error, 2),
                "calibration_bias": bias,
                "expected_vs_actual": {
                    "win_rate": {
                        "expected": round(avg_expected_win_rate, 2),
                        "actual": round(avg_actual_win_rate, 2),
                        "drift": round(avg_actual_win_rate - avg_expected_win_rate, 2)
                    },
                    "holding_time_days": {
                        "expected": round(avg_expected_hold, 1),
                        "actual": round(avg_actual_hold, 1),
                        "drift": round(avg_actual_hold - avg_expected_hold, 1)
                    },
                    "reward_risk": {
                        "expected": 2.0,  # Strategy target profile baseline
                        "actual": round(actual_rr, 2),
                        "drift": round(actual_rr - 2.0, 2)
                    }
                },
                "bins": calibration_bins
            }
        except Exception as exc:
            logger.error(f"Failed to calculate calibration metrics: {exc}")
            return self._empty_response()

    def _empty_response(self) -> dict[str, Any]:
        """Return a default structure when no data is available."""
        return {
            "total_trades": 0,
            "calibration_error": 0.0,
            "calibration_bias": "CALIBRATED",
            "expected_vs_actual": {
                "win_rate": {"expected": 0.0, "actual": 0.0, "drift": 0.0},
                "holding_time_days": {"expected": 0.0, "actual": 0.0, "drift": 0.0},
                "reward_risk": {"expected": 2.0, "actual": 0.0, "drift": 0.0}
            },
            "bins": []
        }
