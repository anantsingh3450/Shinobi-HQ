"""Unit tests for the Phase 6.5 Shadow Trading & Performance Validation Framework.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hokage.memory.resolver import PathResolver
from shared.persistence.sqlite_engine import SqliteStorageEngine
from bots.autonomous.shadow_engine import ShadowEngine
from bots.autonomous.benchmark_engine import BenchmarkEngine
from bots.autonomous.attribution_engine import AttributionEngine
from bots.autonomous.calibration_engine import CalibrationEngine
from bots.autonomous.promotion_engine import PromotionEngine

class TestShadowFramework:
    """Comprehensive unit tests validating all mathematical, database, and logic components of Phase 6.5."""

    @pytest.fixture
    def temp_resolver(self):
        """Create a temporary resolver to isolate database files during testing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            resolver = PathResolver(Path(tmp_dir))
            yield resolver

    @pytest.fixture
    def sqlite_engine(self, temp_resolver):
        """Initialize an isolated SqliteStorageEngine and run migrations."""
        engine = SqliteStorageEngine(temp_resolver)
        # Force migrations to run, ensuring schema version 2 is initialized
        engine.run_migrations()
        yield engine
        engine.close()

    @pytest.fixture
    def shadow_engine(self, sqlite_engine):
        """Initialize the central ShadowEngine orchestrator."""
        return ShadowEngine(sqlite_engine)

    def test_shadow_session_lifecycle_and_audit_trail(self, shadow_engine):
        """Test that shadow sessions start, stop, and preserve full institutional audit trails."""
        session_id = shadow_engine.start_shadow_session(
            starting_equity=50000.0,
            git_version="test-commit-sha",
            config_hash="test-config-hash",
            strategy_set_version="test-strategies-hash",
            market_universe_version="test-universe-hash",
            risk_profile_version="test-risk-hash"
        )

        assert session_id.startswith("SHADOW_SES_")

        # Query database directly to verify audit trail details
        conn = shadow_engine.engine.get_connection()
        cursor = conn.execute("SELECT * FROM shadow_sessions WHERE session_id = ?;", (session_id,))
        row = cursor.fetchone()
        
        assert row is not None
        assert row["status"] == "ACTIVE"
        assert row["starting_equity"] == 50000.0
        assert row["current_equity"] == 50000.0
        assert row["git_version"] == "test-commit-sha"
        assert row["config_hash"] == "test-config-hash"
        assert row["strategy_set_version"] == "test-strategies-hash"
        assert row["market_universe_version"] == "test-universe-hash"
        assert row["risk_profile_version"] == "test-risk-hash"
        assert row["database_schema_version"] == 2

        # Stop session
        shadow_engine.stop_shadow_session(session_id)
        
        cursor = conn.execute("SELECT * FROM shadow_sessions WHERE session_id = ?;", (session_id,))
        row = cursor.fetchone()
        assert row["status"] == "STOPPED"
        assert row["stopped_at"] is not None

    def test_benchmark_performance_math(self, shadow_engine):
        """Test active return, tracking error, and Information Ratio math using hand-calculated cases."""
        session_id = "TEST_BENCH_SESSION"
        symbol = "NIFTY_50"

        # Initialize session record
        conn = shadow_engine.engine.get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO shadow_sessions (
                    session_id, status, started_at, starting_equity, current_equity,
                    git_version, config_hash, strategy_set_version, market_universe_version,
                    risk_profile_version, database_schema_version
                ) VALUES (?, 'ACTIVE', '2026-06-26T00:00:00Z', 10000.0, 10000.0, 'git', 'cfg', 'strat', 'univ', 'risk', 2);
                """,
                (session_id,)
            )

        # Record daily portfolio returns: [0.01, -0.005, 0.02]
        # Record daily benchmark closes: [100, 101, 100, 102] -> benchmark returns: [0.01, -0.0099, 0.02]
        # Matching daily returns:
        # Day 1: Portfolio=1.0%, Benchmark=1.0% -> Active Return = 0.0%
        # Day 2: Portfolio=-0.5%, Benchmark=-0.99% -> Active Return = +0.49%
        # Day 3: Portfolio=2.0%, Benchmark=2.0% -> Active Return = 0.0%
        
        shadow_engine.record_daily_performance(
            session_id, "2026-06-26T10:00:00Z", 10000.0, 10000.0, {symbol: 100.0}
        )
        shadow_engine.record_daily_performance(
            session_id, "2026-06-27T10:00:00Z", 10100.0, 10000.0, {symbol: 101.0}
        )
        shadow_engine.record_daily_performance(
            session_id, "2026-06-28T10:00:00Z", 10049.5, 10000.0, {symbol: 100.0}
        )
        shadow_engine.record_daily_performance(
            session_id, "2026-06-29T10:00:00Z", 10250.49, 10000.0, {symbol: 102.0}
        )

        metrics = shadow_engine.benchmark_engine.calculate_relative_metrics(session_id, symbol)
        
        assert metrics["sample_size"] == 4
        # Active returns: [0.0, 0.0, 0.0049, 0.0]
        # Mean active: 0.001225
        # Tracking Error: 0.00245
        # Information Ratio: 0.5
        assert abs(metrics["mean_daily_active_return"] - 0.001225) < 1e-4
        assert abs(metrics["tracking_error"] - 0.00245) < 1e-4
        assert abs(metrics["information_ratio"] - 0.5) < 1e-2

    def test_trade_attribution_classification_and_reality_score(self, shadow_engine):
        """Test that trade classification quadrants and collective Reality Scores are calculated correctly."""
        # 1. Correct Decision + Profit (Quadrant 1)
        res1 = shadow_engine.attribution_engine.classify_and_attribute_trade(
            decision_id="DEC_001",
            symbol="RELIANCE",
            pnl=500.0,
            return_pct=0.05,
            expected_return_pct=6.0,
            expected_risk_pct=3.0,  # Expected Edge = 2.0 (>= 1.0)
            ic_confidence=80,       # Structurally sound (>= 60)
            market_regime="BULL",
            volatility_regime="LOW",
            entry_price=1000.0,
            stop_price=970.0,       # Risk Taken = 30.0
            target_price=1060.0,
            reasoning_chain=[{"gate": "ConvictionScore", "decision": "PASS", "reason": "High conviction"}]
        )
        assert res1["classification"] == "CORRECT_DECISION_PROFITABLE"
        assert res1["overall_grade"] == "A"

        # 2. Correct Decision + Loss (Quadrant 2)
        res2 = shadow_engine.attribution_engine.classify_and_attribute_trade(
            decision_id="DEC_002",
            symbol="TCS",
            pnl=-300.0,
            return_pct=-0.03,
            expected_return_pct=5.0,
            expected_risk_pct=2.5,  # Expected Edge = 2.0 (>= 1.0)
            ic_confidence=75,       # Structurally sound (>= 60)
            market_regime="BULL",
            volatility_regime="LOW",
            entry_price=2000.0,
            stop_price=1950.0,
            target_price=2100.0,
            reasoning_chain=[]
        )
        assert res2["classification"] == "CORRECT_DECISION_LOSS"
        assert res2["overall_grade"] == "B"

        # 3. Incorrect Decision + Profit (Quadrant 3 - Luck!)
        res3 = shadow_engine.attribution_engine.classify_and_attribute_trade(
            decision_id="DEC_003",
            symbol="INFY",
            pnl=200.0,
            return_pct=0.02,
            expected_return_pct=2.0,
            expected_risk_pct=4.0,  # Expected Edge = 0.5 (< 1.0)
            ic_confidence=50,       # Poor structure (< 60)
            market_regime="BULL",
            volatility_regime="LOW",
            entry_price=1500.0,
            stop_price=1440.0,
            target_price=1530.0,
            reasoning_chain=[]
        )
        assert res3["classification"] == "INCORRECT_DECISION_PROFIT"
        assert res3["overall_grade"] == "C"

        # Generate reality metrics
        reality = shadow_engine.attribution_engine.generate_reality_metrics()
        
        assert reality["total_trades"] == 3
        # Decision Accuracy (Quadrants 1 + 2) = 2/3 = 66.67%
        # Luck Index (Quadrant 3) = 1/3 = 33.33%
        assert reality["decision_accuracy"] == 66.67
        assert reality["luck_index"] == 33.33
        assert reality["reality_score"] > 0.0

    def test_explainability_manifest_answering_9_whys(self, shadow_engine):
        """Test that every trade attribution captures the 9 'Why' explainability manifest."""
        res = shadow_engine.attribution_engine.classify_and_attribute_trade(
            decision_id="DEC_EXPLAIN",
            symbol="RELIANCE",
            pnl=100.0,
            return_pct=0.01,
            expected_return_pct=4.0,
            expected_risk_pct=2.0,
            ic_confidence=90,
            market_regime="BULL",
            volatility_regime="LOW",
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            reasoning_chain=[
                {"gate": "ConvictionScore", "decision": "PASS", "reason": "Momentum setup"},
                {"gate": "PositionAllocation", "decision": "PASS", "reason": "Sized to 1.5%"}
            ],
            rejected_candidates=["TCS", "INFY"]
        )
        
        manifest = res["explainability_manifest"]
        assert "why_taken" in manifest
        assert "why_position_size" in manifest
        assert "why_stop_loss" in manifest
        assert "why_target" in manifest
        assert "why_now" in manifest
        assert "why_not_later" in manifest
        assert "why_this_strategy" in manifest
        assert "why_this_asset" in manifest
        assert "why_this_regime" in manifest
        assert "why_another_rejected" in manifest

        # Check reasoning integration
        assert "Momentum setup" in manifest["why_taken"]
        assert "Sized to 1.5%" in manifest["why_position_size"]
        assert "TCS, INFY" in manifest["why_another_rejected"]

    def test_confidence_calibration_binning(self, shadow_engine):
        """Test confidence calibration curves grouping and error calculation."""
        # Insert mock trades and predictions
        conn = shadow_engine.engine.get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO trades (
                    trade_id, proposal_id, market, direction, quantity, entry_price, 
                    simulated_value, mode, status, strategy_name, sources_cited, executed_at
                ) VALUES ('T1', 'P1', 'RELIANCE', 'LONG', 10.0, 100.0, 1000.0, 'PAPER', 'CLOSED', 'S1', 'src', '2026-06-26T10:00:00Z');
                """
            )
            conn.execute(
                """
                INSERT INTO predictions (
                    proposal_id, strategy_name, market, timeframe, confidence_score, 
                    backtest_passed, win_rate, net_profit, after_tax_net_profit, provider, recorded_at
                ) VALUES ('P1', 'S1', 'RELIANCE', '1d', 85.0, 1, 60.0, 500.0, 450.0, 'prov', '2026-06-26T10:00:00Z');
                """
            )
            conn.execute(
                """
                INSERT INTO decision_outcomes (
                    decision_id, timestamp, outcome, pnl, return_pct, exit_reason, holding_days
                ) VALUES ('T1', '2026-06-26T15:00:00Z', 'PROFIT', 150.0, 0.015, 'Target', 2);
                """
            )

        calib = shadow_engine.calibration_engine.get_calibration_metrics()
        
        assert calib["total_trades"] == 1
        # Bin 8 (representing 80-90% confidence) should have 1 trade, 1 win
        bin_8 = [b for b in calib["bins"] if b["bin"] == "80-90%"][0]
        assert bin_8["trades"] == 1
        assert bin_8["actual_win_rate"] == 100.0
        assert calib["expected_vs_actual"]["holding_time_days"]["actual"] == 2.0

    def test_promotion_readiness_and_regime_matrix(self, shadow_engine):
        """Test evidence-based readiness levels and market regime diversity checks."""
        session_id = "TEST_PROMOTION_SESSION"
        conn = shadow_engine.engine.get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO shadow_sessions (
                    session_id, status, started_at, stopped_at, starting_equity, current_equity,
                    git_version, config_hash, strategy_set_version, market_universe_version,
                    risk_profile_version, database_schema_version
                ) VALUES (?, 'ACTIVE', datetime('now', '-35 days'), NULL, 100000.0, 105000.0, 'git', 'cfg', 'strat', 'univ', 'risk', 2);
                """,
                (session_id,)
            )

        # Check regime coverage matrix and readiness
        reality = shadow_engine.attribution_engine.generate_reality_metrics()
        calib = shadow_engine.calibration_engine.get_calibration_metrics()
        readiness = shadow_engine.promotion_engine.evaluate_promotion_readiness(session_id, reality, calib)
        
        # Should be NOT_READY or STABLE_SHADOW because we don't have 50 trades yet
        assert readiness["readiness_level"] in ("NOT_READY", "STABLE_SHADOW", "EARLY_SHADOW")
        assert readiness["checklist"]["shadow_duration_days"]["passed"] is True  # 35 days > 30

    def test_immutable_reports_and_cryptographic_checksums(self, shadow_engine):
        """Test report archiving, SHA-256 checksum generation, and tamper-detection."""
        session_id = shadow_engine.start_shadow_session(starting_equity=100000.0)

        # Record some daily return to have data
        shadow_engine.record_daily_performance(session_id, "2026-06-26T10:00:00Z", 101000.0, 100000.0, {"NIFTY_50": 20000.0})

        # Generate report
        report_id = shadow_engine.generate_and_archive_report(session_id, "DAILY")
        
        assert report_id.startswith("VAL_REP_DAILY_")

        # Verify integrity (should pass)
        assert shadow_engine.verify_report_integrity(report_id) is True

        # Tamper with the database to simulate unauthorized modification
        conn = shadow_engine.engine.get_connection()
        with conn:
            conn.execute(
                "UPDATE immutable_validation_reports SET content_json = REPLACE(content_json, 'ACTIVE', 'COMPROMISED') WHERE report_id = ?;",
                (report_id,)
            )

        # Verify integrity (should fail due to checksum mismatch)
        assert shadow_engine.verify_report_integrity(report_id) is False
