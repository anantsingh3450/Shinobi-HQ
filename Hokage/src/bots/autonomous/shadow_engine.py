"""Shadow Trading Engine for Phase 6.5.

Orchestrates shadow session lifecycles, daily performance tracking,
and compilation of immutable, SHA-256 checksummed validation reports.
"""
from __future__ import annotations

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from shared.persistence.sqlite_engine import SqliteStorageEngine
from bots.autonomous.benchmark_engine import BenchmarkEngine
from bots.autonomous.attribution_engine import AttributionEngine
from bots.autonomous.calibration_engine import CalibrationEngine
from bots.autonomous.promotion_engine import PromotionEngine

logger = logging.getLogger("Hokage.ShadowEngine")

class ShadowEngine:
    """Central orchestrator for shadow trading operations and performance validation."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize and wire all modular sub-engines."""
        self.engine = engine
        self.benchmark_engine = BenchmarkEngine(engine)
        self.attribution_engine = AttributionEngine(engine)
        self.calibration_engine = CalibrationEngine(engine)
        self.promotion_engine = PromotionEngine(engine)

    def start_shadow_session(
        self,
        starting_equity: float,
        git_version: str = "N/A",
        config_hash: str = "N/A",
        strategy_set_version: str = "N/A",
        market_universe_version: str = "N/A",
        risk_profile_version: str = "N/A",
        exchange: str | None = None,
    ) -> str:
        """Initialize a new shadow trading session with an institutional audit trail."""
        conn = self.engine.get_connection()
        suffix = f"{exchange.upper()}_" if exchange else ""
        session_id = f"SHADOW_SES_{suffix}{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO shadow_sessions (
                        session_id, status, started_at, stopped_at, starting_equity, current_equity,
                        git_version, config_hash, strategy_set_version, market_universe_version,
                        risk_profile_version, database_schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        session_id,
                        "ACTIVE",
                        datetime.now(timezone.utc).isoformat(),
                        None,
                        starting_equity,
                        starting_equity,
                        git_version,
                        config_hash,
                        strategy_set_version,
                        market_universe_version,
                        risk_profile_version,
                        2,  # schema version 2
                    ),
                )
            logger.info(f"Initialized shadow session {session_id} with starting equity ₹{starting_equity}.")
            return session_id
        except Exception as exc:
            logger.error(f"Failed to start shadow session: {exc}")
            raise exc

    def stop_shadow_session(self, session_id: str) -> None:
        """Stop an active shadow session."""
        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE shadow_sessions
                    SET status = 'STOPPED', stopped_at = ?
                    WHERE session_id = ?;
                    """,
                    (datetime.now(timezone.utc).isoformat(), session_id),
                )
            logger.info(f"Stopped shadow session {session_id}.")
        except Exception as exc:
            logger.error(f"Failed to stop shadow session {session_id}: {exc}")
            raise exc

    def record_daily_performance(
        self,
        session_id: str,
        timestamp: str,
        portfolio_equity: float,
        portfolio_cash: float,
        benchmark_prices: dict[str, float],
    ) -> None:
        """Record portfolio close state and update all generic benchmarks daily returns."""
        conn = self.engine.get_connection()
        try:
            # 1. Calculate portfolio return % compared to previous day
            cursor = conn.execute(
                """
                SELECT portfolio_equity FROM shadow_daily_performance
                WHERE session_id = ? AND timestamp < ?
                ORDER BY timestamp DESC LIMIT 1;
                """,
                (session_id, timestamp),
            )
            row = cursor.fetchone()
            prev_equity = row[0] if row else None

            portfolio_return = 0.0
            if prev_equity is not None and prev_equity > 0:
                portfolio_return = (portfolio_equity - prev_equity) / prev_equity

            # 2. Record portfolio daily return
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO shadow_daily_performance (
                        timestamp, session_id, portfolio_equity, portfolio_cash, portfolio_return
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    (timestamp, session_id, portfolio_equity, portfolio_cash, portfolio_return),
                )
                # Update current equity in session
                conn.execute(
                    "UPDATE shadow_sessions SET current_equity = ? WHERE session_id = ?;",
                    (portfolio_equity, session_id),
                )

            # 3. Record all benchmark prices dynamically
            for symbol, price in benchmark_prices.items():
                self.benchmark_engine.record_benchmark_price(session_id, timestamp, symbol, price)

            logger.info(f"Successfully recorded EOD performance for session {session_id} on {timestamp}.")
        except Exception as exc:
            logger.error(f"Failed to record daily performance: {exc}")
            raise exc

    def generate_and_archive_report(self, session_id: str, report_type: str) -> str:
        """Generate a structured, cryptographic SHA-256 checksummed EOD validation report."""
        conn = self.engine.get_connection()
        report_id = f"VAL_REP_{report_type.upper()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            # 1. Load session metadata
            cursor = conn.execute("SELECT * FROM shadow_sessions WHERE session_id = ?;", (session_id,))
            session = cursor.fetchone()
            if not session:
                raise ValueError(f"Session {session_id} not found.")

            # 2. Compile metrics
            reality_metrics = self.attribution_engine.generate_reality_metrics()
            calibration_metrics = self.calibration_engine.get_calibration_metrics()
            readiness = self.promotion_engine.evaluate_promotion_readiness(
                session_id, reality_metrics, calibration_metrics
            )

            # 3. Compile generic benchmark comparisons
            benchmarks_summary = {}
            bench_cursor = conn.execute(
                "SELECT DISTINCT benchmark_symbol FROM shadow_benchmark_performance WHERE session_id = ?;",
                (session_id,),
            )
            for brow in bench_cursor.fetchall():
                b_sym = brow["benchmark_symbol"]
                benchmarks_summary[b_sym] = self.benchmark_engine.calculate_relative_metrics(session_id, b_sym)

            # 4. Compile portfolio metrics
            portfolio_metrics = {
                "starting_equity": session["starting_equity"],
                "current_equity": session["current_equity"],
                "total_return": (session["current_equity"] - session["starting_equity"]) / session["starting_equity"] if session["starting_equity"] > 0 else 0.0,
            }

            # 5. Compile Incident Summary (Watchdog checks)
            inc_cursor = conn.execute("SELECT COUNT(*) FROM watchdog_incidents WHERE timestamp > datetime('now', '-7 days');")
            inc_count = inc_cursor.fetchone()[0]

            # Assemble the complete report content
            report_content = {
                "report_id": report_id,
                "report_type": report_type.upper(),
                "session_metadata": {
                    "session_id": session["session_id"],
                    "started_at": session["started_at"],
                    "status": session["status"],
                    "git_version": session["git_version"],
                    "config_hash": session["config_hash"],
                    "strategy_set_version": session["strategy_set_version"],
                },
                "portfolio_metrics": portfolio_metrics,
                "benchmarks": benchmarks_summary,
                "reality_metrics": reality_metrics,
                "calibration_metrics": calibration_metrics,
                "readiness": {
                    "level": readiness["readiness_level"],
                    "recommendation": readiness["recommendation"],
                    "checklist": readiness["checklist"],
                },
                "incidents": {
                    "recent_incident_count": inc_count,
                },
                "timestamp": timestamp,
            }

            # 6. Cryptographic serialization and checksumming
            serialized = json.dumps(report_content, sort_keys=True)
            checksum = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

            # 7. Transactional write to database
            with conn:
                conn.execute(
                    """
                    INSERT INTO immutable_validation_reports (
                        report_id, report_type, session_id, timestamp, checksum, content_json
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (report_id, report_type.upper(), session_id, timestamp, checksum, serialized),
                )

            logger.info(f"Archived immutable {report_type} report {report_id} with checksum {checksum[:8]}...")
            return report_id
        except Exception as exc:
            logger.error(f"Failed to generate and archive report: {exc}")
            raise exc

    def verify_report_integrity(self, report_id: str) -> bool:
        """Verify report immutability by recalculating and validating its SHA-256 checksum."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute(
                "SELECT checksum, content_json FROM immutable_validation_reports WHERE report_id = ?;",
                (report_id,),
            )
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Report {report_id} not found.")
                return False

            stored_checksum = row["checksum"]
            content_json = row["content_json"]

            # Recalculate checksum
            # Re-serialize to guarantee key sorting
            data = json.loads(content_json)
            serialized = json.dumps(data, sort_keys=True)
            recalculated_checksum = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

            matches = stored_checksum == recalculated_checksum
            if not matches:
                logger.critical(
                    f"INTEGRITY_VIOLATION DETECTED! Historical report {report_id} has been altered! "
                    f"Stored Checksum: {stored_checksum}, Recalculated Checksum: {recalculated_checksum}"
                )
            return matches
        except Exception as exc:
            logger.error(f"Error during report verification: {exc}")
            return False
