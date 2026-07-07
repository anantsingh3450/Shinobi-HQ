from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from bots.autonomous.capital_preservation import CapitalPreservationEngine


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    return cache


def test_capital_preservation_normal_mode(mock_cache):
    engine = CapitalPreservationEngine(mock_cache)
    
    # Under optimal conditions, system should run in NORMAL mode with 2.0% max allocation
    res = engine.evaluate_risk_profile(
        consecutive_losses=0,
        drawdown_pct=0.0,
        prediction_win_rate=100.0,
        vix_impact_delta=0.0
    )
    assert res["mode"] == "NORMAL"
    assert res["max_allocation_pct"] == 2.0
    assert res["min_conviction_threshold"] == 51


def test_capital_preservation_recovery_drawdown(mock_cache):
    engine = CapitalPreservationEngine(mock_cache)
    
    # 10% drawdown should trigger RECOVERY mode with 0.5% max allocation per trade
    res = engine.evaluate_risk_profile(
        consecutive_losses=0,
        drawdown_pct=11.5,
        prediction_win_rate=100.0,
        vix_impact_delta=0.0
    )
    assert res["mode"] == "RECOVERY"
    assert res["max_allocation_pct"] == 0.5
    assert res["min_conviction_threshold"] == 71


def test_capital_preservation_no_trade_drawdown(mock_cache):
    engine = CapitalPreservationEngine(mock_cache)
    
    # 15% drawdown should trigger NO TRADE mode
    res = engine.evaluate_risk_profile(
        consecutive_losses=0,
        drawdown_pct=16.0,
        prediction_win_rate=100.0,
        vix_impact_delta=0.0
    )
    assert res["mode"] == "NO TRADE"
    assert res["max_allocation_pct"] == 0.0
    assert res["min_conviction_threshold"] == 100


def test_capital_preservation_losing_streak(mock_cache):
    engine = CapitalPreservationEngine(mock_cache)
    
    # 5 consecutive losses should cap allocation at 1.0% and trigger RECOVERY mode
    res = engine.evaluate_risk_profile(
        consecutive_losses=5,
        drawdown_pct=0.0,
        prediction_win_rate=100.0,
        vix_impact_delta=0.0
    )
    assert res["mode"] == "RECOVERY"
    assert res["max_allocation_pct"] == 1.0
    assert res["min_conviction_threshold"] == 71


def test_capital_preservation_prediction_degradation(mock_cache):
    engine = CapitalPreservationEngine(mock_cache)
    
    # Prediction win rate < 50% should trigger RECOVERY mode and scale allocations
    res = engine.evaluate_risk_profile(
        consecutive_losses=0,
        drawdown_pct=0.0,
        prediction_win_rate=45.0,
        vix_impact_delta=0.0
    )
    assert res["mode"] == "RECOVERY"
    assert res["max_allocation_pct"] == 1.0
