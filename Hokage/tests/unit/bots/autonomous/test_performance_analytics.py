"""Tests for PerformanceAnalyticsEngine — Phase 4C.5D.

Covers: record_trade_outcome (with decision_id), load_records,
query_win_rate (legacy), profit_factor, expectancy, Sharpe,
drawdown analytics, holding period stats, rolling metrics,
conviction grade / regime / sector dimensional queries,
generate_performance_report, and JSONL format validity.
"""
from __future__ import annotations

import json
import math
import pytest
from pathlib import Path
from bots.autonomous.performance_analytics import PerformanceAnalyticsEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path: Path) -> PerformanceAnalyticsEngine:
    return PerformanceAnalyticsEngine(brain_root=tmp_path)


def _seed(engine: PerformanceAnalyticsEngine, decision_id: str = "test-id") -> None:
    """Seed 5 realistic trade records."""
    engine.record_trade_outcome(
        symbol="ONGC", sector="energy", market_regime="BULL_RISK-ON",
        conviction_score=89, holding_period_days=3, pnl=1200.0, is_win=True,
        decision_id="d001", entry_price=185.0, exit_price=198.5, return_pct=0.073,
    )
    engine.record_trade_outcome(
        symbol="BEL", sector="defence", market_regime="BULL_RISK-ON",
        conviction_score=84, holding_period_days=2, pnl=800.0, is_win=True,
        decision_id="d002", entry_price=300.0, exit_price=326.0, return_pct=0.087,
    )
    engine.record_trade_outcome(
        symbol="HAL", sector="defence", market_regime="HIGH_VOLATILITY",
        conviction_score=78, holding_period_days=4, pnl=-400.0, is_win=False,
        decision_id="d003", entry_price=3500.0, exit_price=3385.0, return_pct=-0.033,
    )
    engine.record_trade_outcome(
        symbol="HDFCBANK", sector="banking", market_regime="BEAR_RISK-OFF",
        conviction_score=45, holding_period_days=1, pnl=-600.0, is_win=False,
        decision_id="d004", entry_price=1600.0, exit_price=1555.0, return_pct=-0.028,
    )
    engine.record_trade_outcome(
        symbol="TCS", sector="it", market_regime="BULL_RISK-ON",
        conviction_score=92, holding_period_days=5, pnl=2000.0, is_win=True,
        decision_id="d005", entry_price=3800.0, exit_price=4020.0, return_pct=0.058,
    )


# ---------------------------------------------------------------------------
# Basic record / load
# ---------------------------------------------------------------------------

def test_record_creates_file(engine, tmp_path):
    engine.record_trade_outcome(
        symbol="ONGC", sector="energy", market_regime="BULL_RISK-ON",
        conviction_score=89, holding_period_days=3, pnl=1200.0, is_win=True,
    )
    assert engine._history_file.exists()


def test_record_includes_decision_id(engine):
    r = engine.record_trade_outcome(
        symbol="ONGC", sector="energy", market_regime="BULL_RISK-ON",
        conviction_score=89, holding_period_days=3, pnl=1200.0, is_win=True,
        decision_id="uuid-test-001",
    )
    assert r["decision_id"] == "uuid-test-001"


def test_record_includes_conviction_grade(engine):
    r = engine.record_trade_outcome(
        symbol="TCS", sector="it", market_regime="BULL",
        conviction_score=90, holding_period_days=2, pnl=500.0, is_win=True,
    )
    assert r["conviction_grade"] == "ELITE"


def test_load_records_returns_all(engine):
    _seed(engine)
    records = engine.load_records()
    assert len(records) == 5


def test_jsonl_each_line_valid_json(engine):
    _seed(engine)
    lines = engine._history_file.read_text(encoding="utf-8").strip().split("\n")
    for line in lines:
        obj = json.loads(line)
        assert "symbol" in obj
        assert "decision_id" in obj


# ---------------------------------------------------------------------------
# Legacy query_win_rate — backward compatibility
# ---------------------------------------------------------------------------

def test_legacy_query_win_rate_sector(engine):
    _seed(engine)
    assert engine.query_win_rate("sector", "defence") == 50.0


def test_legacy_query_win_rate_regime(engine):
    _seed(engine)
    assert engine.query_win_rate("regime", "BULL_RISK-ON") == 100.0


def test_legacy_query_win_rate_conviction_min(engine):
    _seed(engine)
    assert engine.query_win_rate("conviction_min", 80) == 100.0


def test_legacy_query_win_rate_all(engine):
    _seed(engine)
    # 3 wins / 5 = 60.0%
    assert engine.query_win_rate("all", None) == 60.0


def test_legacy_query_empty_returns_100(engine):
    assert engine.query_win_rate("all", None) == 100.0


# ---------------------------------------------------------------------------
# Profit factor
# ---------------------------------------------------------------------------

def test_profit_factor_correct(engine):
    _seed(engine)
    # gross wins = 1200+800+2000 = 4000, gross losses = 400+600 = 1000
    assert engine.compute_profit_factor() == pytest.approx(4.0, abs=0.01)


def test_profit_factor_no_losses(engine):
    engine.record_trade_outcome(
        symbol="BEL", sector="defence", market_regime="BULL",
        conviction_score=80, holding_period_days=2, pnl=500.0, is_win=True,
    )
    pf = engine.compute_profit_factor()
    assert pf == 500.0  # no losses → gross_wins


def test_profit_factor_no_records(engine):
    assert engine.compute_profit_factor() == 0.0


# ---------------------------------------------------------------------------
# Expectancy
# ---------------------------------------------------------------------------

def test_expectancy_positive(engine):
    _seed(engine)
    exp = engine.compute_expectancy()
    # (0.6 × avg_win) - (0.4 × avg_loss)
    # avg_win = (1200+800+2000)/3 = 1333.33, avg_loss = (400+600)/2 = 500
    # = 0.6*1333.33 - 0.4*500 = 800 - 200 = 600
    assert exp == pytest.approx(600.0, abs=1.0)


def test_expectancy_no_records(engine):
    assert engine.compute_expectancy() == 0.0


# ---------------------------------------------------------------------------
# Sharpe ratio (risk-free = 0%)
# ---------------------------------------------------------------------------

def test_sharpe_requires_min_2_records(engine):
    engine.record_trade_outcome(
        symbol="X", sector="it", market_regime="BULL",
        conviction_score=80, holding_period_days=1, pnl=100.0, is_win=True,
    )
    assert engine.compute_sharpe() == 0.0


def test_sharpe_with_variation(engine):
    _seed(engine)
    sharpe = engine.compute_sharpe()
    # Must be a finite float — not 0 because there are both wins and losses
    assert isinstance(sharpe, float)
    assert math.isfinite(sharpe)


def test_sharpe_all_equal_returns_zero(engine):
    for _ in range(3):
        engine.record_trade_outcome(
            symbol="X", sector="it", market_regime="BULL",
            conviction_score=80, holding_period_days=1, pnl=100.0, is_win=True,
        )
    assert engine.compute_sharpe() == 0.0


# ---------------------------------------------------------------------------
# Drawdown analytics
# ---------------------------------------------------------------------------

def test_drawdown_no_records(engine):
    dd = engine.compute_drawdown_analytics()
    assert dd["max_drawdown_pct"] == 0.0
    assert dd["consecutive_losses_max"] == 0


def test_drawdown_consecutive_losses(engine):
    # Two consecutive losses then a win
    engine.record_trade_outcome(
        symbol="A", sector="x", market_regime="BEAR",
        conviction_score=50, holding_period_days=1, pnl=-100.0, is_win=False,
    )
    engine.record_trade_outcome(
        symbol="B", sector="x", market_regime="BEAR",
        conviction_score=50, holding_period_days=1, pnl=-100.0, is_win=False,
    )
    engine.record_trade_outcome(
        symbol="C", sector="x", market_regime="BULL",
        conviction_score=80, holding_period_days=1, pnl=500.0, is_win=True,
    )
    dd = engine.compute_drawdown_analytics()
    assert dd["consecutive_losses_max"] == 2
    assert dd["recovery_trade_count"] == 1


def test_drawdown_worst_session_symbol(engine):
    _seed(engine)
    dd = engine.compute_drawdown_analytics()
    assert dd["worst_session_symbol"] in ("HDFCBANK", "HAL")


# ---------------------------------------------------------------------------
# Holding period stats
# ---------------------------------------------------------------------------

def test_holding_period_stats(engine):
    _seed(engine)
    hp = engine.compute_holding_period_stats()
    # winners: 3, 2, 5 → avg = 10/3 ≈ 3.33
    # losers:  4, 1   → avg = 5/2 = 2.5
    assert hp["avg_hold_winners"] == pytest.approx(10.0 / 3.0, abs=0.01)
    assert hp["avg_hold_losers"]  == pytest.approx(2.5, abs=0.01)


def test_holding_period_no_records(engine):
    hp = engine.compute_holding_period_stats()
    assert hp["avg_hold_all"] == 0.0


# ---------------------------------------------------------------------------
# Rolling metrics
# ---------------------------------------------------------------------------

def test_rolling_metrics_window_5(engine):
    _seed(engine)
    rm = engine.compute_rolling_metrics(5)
    assert rm["window"] == 5
    assert rm["trades"] == 5
    assert isinstance(rm["win_rate"], float)
    assert isinstance(rm["expectancy"], float)


def test_rolling_metrics_window_larger_than_records(engine):
    _seed(engine)
    rm = engine.compute_rolling_metrics(50)
    # Should use all available records (5)
    assert rm["trades"] == 5


def test_rolling_metrics_empty(engine):
    rm = engine.compute_rolling_metrics(20)
    assert rm["win_rate"] == 100.0
    assert rm["trades"] == 0


# ---------------------------------------------------------------------------
# Dimensional queries
# ---------------------------------------------------------------------------

def test_query_by_conviction_grade_elite(engine):
    _seed(engine)
    res = engine.query_by_conviction_grade("ELITE")
    # Scores >= 86: ONGC(89), TCS(92) = 2 trades, both wins
    assert res["trades"] == 2
    assert res["win_rate"] == 100.0


def test_query_by_conviction_grade_no_trades(engine):
    _seed(engine)
    res = engine.query_by_conviction_grade("AVOID")
    assert res["trades"] == 0
    assert res["win_rate"] == 0.0


def test_query_by_regime(engine):
    _seed(engine)
    res = engine.query_by_regime("BULL_RISK-ON")
    assert res["trades"] == 3
    assert res["win_rate"] == 100.0


def test_query_by_sector(engine):
    _seed(engine)
    res = engine.query_by_sector("defence")
    assert res["trades"] == 2
    assert res["win_rate"] == 50.0


def test_query_by_sector_no_match(engine):
    _seed(engine)
    res = engine.query_by_sector("pharma")
    assert res["trades"] == 0


# ---------------------------------------------------------------------------
# Generate performance report
# ---------------------------------------------------------------------------

def test_generate_performance_report_keys(engine):
    _seed(engine)
    report = engine.generate_performance_report()
    required = [
        "generated_at", "total_trades", "win_count", "loss_count",
        "overall_win_rate", "profit_factor", "expectancy_inr",
        "sharpe_ratio", "drawdown", "holding_periods",
        "rolling_20", "rolling_10", "by_grade",
    ]
    for key in required:
        assert key in report, f"Missing key: {key}"


def test_generate_performance_report_grade_breakdown(engine):
    _seed(engine)
    report = engine.generate_performance_report()
    assert "ELITE" in report["by_grade"]
    assert "HIGH" in report["by_grade"]
    assert "MODERATE" in report["by_grade"]
    assert "WATCH" in report["by_grade"]
    assert "AVOID" in report["by_grade"]


def test_generate_performance_report_overall_win_rate(engine):
    _seed(engine)
    report = engine.generate_performance_report()
    # 3 wins out of 5 = 60%
    assert report["overall_win_rate"] == 60.0
