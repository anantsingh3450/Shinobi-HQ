"""Execution Quality Analytics Engine.

Decomposes and aggregates transaction friction metrics (slippage, latency, and fills)
to evaluate execution health and generate a composite advisory quality score.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from shared.persistence.sqlite_engine import SqliteStorageEngine

logger = logging.getLogger("Hokage.ExecutionQualityEngine")


class ExecutionQualityEngine:
    """Aggregates and grades execution metrics across shadow trading history."""

    def __init__(self, sqlite_engine: SqliteStorageEngine) -> None:
        """Initialize with SQLite storage engine."""
        self.sqlite_engine = sqlite_engine

    def get_quality_metrics(self) -> dict[str, Any]:
        """Aggregate execution quality metrics from SQLite or fallback to JSON trade log.

        Returns:
            Dictionary containing:
                - average_slippage_pct
                - worst_slippage_pct
                - average_latency_ms
                - partial_fill_pct
                - execution_quality_score
                - execution_health
                - total_trades
        """
        slippages = []
        latencies = []
        partial_fills_count = 0
        total_count = 0

        # 1. Query SQLite trade_replays table
        try:
            conn = self.sqlite_engine.get_connection()
            cursor = conn.execute("SELECT lifecycle_timeline FROM trade_replays;")
            rows = cursor.fetchall()
            for row in rows:
                timeline_str = row["lifecycle_timeline"]
                if not timeline_str:
                    continue
                timeline = json.loads(timeline_str)
                for event in timeline:
                    if event.get("event") == "EXECUTION_FRICTION" and "metadata" in event:
                        meta = event["metadata"]
                        slippages.append(meta.get("slippage_pct", 0.0))
                        latencies.append(meta.get("latency_ms", 0.0))
                        if meta.get("partial_fill", False):
                            partial_fills_count += 1
                        total_count += 1
                        break  # Only one execution event per trade timeline
        except Exception as e:
            logger.debug(f"SQLite trade_replays table query bypassed or empty: {e}")

        # 2. Fallback to trades.jsonl if no database records were processed
        if total_count == 0:
            try:
                from bots.execution.store.json_trade_store import JsonTradeStore
                trades_dir = self.sqlite_engine.resolver.resolve_trades_dir()
                store = JsonTradeStore(trades_dir)
                # Ensure we bypass delegation to load from raw json file if needed
                if hasattr(store, "_delegate"):
                    # Temporarily clear delegate to read directly from JSON file as a true fallback
                    orig_delegate = store._delegate
                    store._delegate = None
                    trades = store.load_all()
                    store._delegate = orig_delegate
                else:
                    trades = store.load_all()

                for trade in trades:
                    if trade.friction_metrics:
                        meta = trade.friction_metrics
                        slippages.append(meta.get("slippage_pct", 0.0))
                        latencies.append(meta.get("latency_ms", 0.0))
                        if meta.get("partial_fill", False):
                            partial_fills_count += 1
                        total_count += 1
            except Exception as e:
                logger.error(f"Failed fallback retrieval of trade logs: {e}")

        # 3. Handle zero trades state gracefully with safe default values
        if total_count == 0:
            return {
                "average_slippage_pct": 0.0,
                "worst_slippage_pct": 0.0,
                "average_latency_ms": 0.0,
                "partial_fill_pct": 0.0,
                "execution_quality_score": 100.0,
                "execution_health": "EXCELLENT",
                "total_trades": 0,
            }

        # 4. Calculate statistical metrics
        avg_slippage = sum(slippages) / total_count
        worst_slippage = max(slippages) if slippages else 0.0
        avg_latency = sum(latencies) / total_count
        partial_fill_pct = (partial_fills_count / total_count) * 100.0

        # 5. Composite advisory execution quality score
        # Slippage component: 100 at 0% slippage, dropping to 0 at 0.5% slippage
        slip_score = max(0.0, 100.0 - (avg_slippage * 200.0))
        # Latency component: 100 at 0ms, dropping to 0 at 500ms
        lat_score = max(0.0, 100.0 - (avg_latency / 5.0))
        # Fill component: 100% minus percentage of partial fills
        fill_score = max(0.0, 100.0 - partial_fill_pct)

        # Weighted composite score: 40% slippage, 30% latency, 30% fill
        score = 0.4 * slip_score + 0.3 * lat_score + 0.3 * fill_score
        score = round(score, 2)

        # 6. Overall health classification
        if score >= 90.0:
            health = "EXCELLENT"
        elif score >= 75.0:
            health = "GOOD"
        elif score >= 50.0:
            health = "DEGRADED"
        else:
            health = "CRITICAL"

        return {
            "average_slippage_pct": round(avg_slippage, 4),
            "worst_slippage_pct": round(worst_slippage, 4),
            "average_latency_ms": round(avg_latency, 2),
            "partial_fill_pct": round(partial_fill_pct, 2),
            "execution_quality_score": score,
            "execution_health": health,
            "total_trades": total_count,
        }
