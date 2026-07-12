"""Benchmark Engine for Phase 6.5.

Tracks generic, asset-agnostic benchmark prices and returns,
and calculates active returns, tracking error, and information ratio.
"""
from __future__ import annotations

import math
import logging
from typing import Any

from shared.persistence.sqlite_engine import SqliteStorageEngine

logger = logging.getLogger("Hokage.BenchmarkEngine")

class BenchmarkEngine:
    """Manages dynamic, asset-agnostic benchmark tracking and relative performance math."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with SQLite storage engine."""
        self.engine = engine

    def record_benchmark_price(
        self, session_id: str, timestamp: str, symbol: str, close_price: float
    ) -> None:
        """Record the daily close price of a benchmark and calculate its daily return."""
        conn = self.engine.get_connection()
        try:
            # 1. Fetch previous day's close price to compute return
            cursor = conn.execute(
                """
                SELECT close_price FROM shadow_benchmark_performance
                WHERE session_id = ? AND benchmark_symbol = ? AND timestamp < ?
                ORDER BY timestamp DESC LIMIT 1;
                """,
                (session_id, symbol, timestamp),
            )
            row = cursor.fetchone()
            prev_close = row[0] if row else None

            daily_return = 0.0
            if prev_close is not None and prev_close > 0:
                daily_return = (close_price - prev_close) / prev_close

            # 2. Insert or replace close price and return
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO shadow_benchmark_performance (
                        timestamp, session_id, benchmark_symbol, close_price, daily_return
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    (timestamp, session_id, symbol, close_price, daily_return),
                )
            logger.info(
                f"Recorded benchmark {symbol} for session {session_id} on {timestamp}: Close={close_price}, Return={daily_return:.4f}"
            )
        except Exception as exc:
            logger.error(f"Failed to record benchmark price for {symbol}: {exc}")
            raise exc

    def calculate_relative_metrics(
        self, session_id: str, benchmark_symbol: str
    ) -> dict[str, Any]:
        """Calculate Active Return (Alpha), Tracking Error (TE), and Information Ratio (IR).

        Uses pure Python and the standard math library to calculate all statistics.
        """
        conn = self.engine.get_connection()
        try:
            # Fetch daily returns for both portfolio and benchmark for matching timestamps
            cursor = conn.execute(
                """
                SELECT p.timestamp, p.portfolio_return, b.daily_return as benchmark_return
                FROM shadow_daily_performance p
                JOIN shadow_benchmark_performance b ON p.timestamp = b.timestamp AND p.session_id = b.session_id
                WHERE p.session_id = ? AND b.benchmark_symbol = ?
                ORDER BY p.timestamp ASC;
                """,
                (session_id, benchmark_symbol),
            )
            rows = cursor.fetchall()
            if not rows:
                return {
                    "benchmark": benchmark_symbol,
                    "sample_size": 0,
                    "active_return": 0.0,
                    "tracking_error": 0.0,
                    "information_ratio": 0.0,
                    "annualized_information_ratio": 0.0,
                }

            active_returns = []
            for row in rows:
                p_ret = row["portfolio_return"]
                b_ret = row["benchmark_return"]
                active_returns.append(p_ret - b_ret)

            n = len(active_returns)
            if n == 0:
                return {
                    "benchmark": benchmark_symbol,
                    "sample_size": 0,
                    "active_return": 0.0,
                    "tracking_error": 0.0,
                    "information_ratio": 0.0,
                    "annualized_information_ratio": 0.0,
                }

            # 1. Mean active return
            mean_active = sum(active_returns) / n

            # 2. Tracking Error (Sample standard deviation of active returns)
            if n > 1:
                variance = sum((r - mean_active) ** 2 for r in active_returns) / (n - 1)
                tracking_error = math.sqrt(variance)
            else:
                tracking_error = 0.0

            # 3. Information Ratio
            if tracking_error > 0:
                information_ratio = mean_active / tracking_error
                annualized_ir = information_ratio * math.sqrt(252)
            else:
                information_ratio = 0.0
                annualized_ir = 0.0

            # Cumulative returns
            cum_portfolio = 1.0
            cum_benchmark = 1.0
            for row in rows:
                cum_portfolio *= (1.0 + row["portfolio_return"])
                cum_benchmark *= (1.0 + row["benchmark_return"])

            active_return = cum_portfolio - cum_benchmark

            return {
                "benchmark": benchmark_symbol,
                "sample_size": n,
                "active_return": round(active_return, 6),
                "mean_daily_active_return": round(mean_active, 6),
                "tracking_error": round(tracking_error, 6),
                "information_ratio": round(information_ratio, 6),
                "annualized_information_ratio": round(annualized_ir, 6),
            }
        except Exception as exc:
            logger.error(f"Failed to calculate relative metrics for {benchmark_symbol}: {exc}")
            return {
                "benchmark": benchmark_symbol,
                "sample_size": 0,
                "active_return": 0.0,
                "tracking_error": 0.0,
                "information_ratio": 0.0,
                "annualized_information_ratio": 0.0,
            }
