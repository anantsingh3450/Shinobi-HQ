from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from bots.autonomous.portfolio_intelligence import (
    PortfolioAwarenessEngine,
    PortfolioHealthEngine,
    PositionAllocationEngine,
)
from integrations.brokers.models import VenuePosition, AccountBalance
from integrations.data.models import Instrument, AssetClass, Exchange


@pytest.fixture
def mock_venue():
    venue = MagicMock()
    # Configure mock account balance: 80,000 cash, 100,000 total equity
    venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_main", total_equity=100000.0, cash=80000.0, margin_available=80000.0, margin_used=0.0
    )
    
    # Configure mock open positions (TCS and ONGC)
    pos_tcs = MagicMock()
    pos_tcs.instrument.symbol = "TCS"
    pos_tcs.quantity = 5.0
    pos_tcs.average_price = 3000.0
    pos_tcs.current_price = 3200.0
    pos_tcs.unrealized_pnl = 1000.0
    
    pos_ongc = MagicMock()
    pos_ongc.instrument.symbol = "ONGC"
    pos_ongc.quantity = 20.0
    pos_ongc.average_price = 200.0
    pos_ongc.current_price = 200.0
    pos_ongc.unrealized_pnl = 0.0
    
    venue.get_positions.return_value = [pos_tcs, pos_ongc]
    return venue


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.read_intelligence.return_value = {}
    return cache


def test_portfolio_awareness_metrics(mock_venue, mock_cache):
    awareness = PortfolioAwarenessEngine(mock_venue, mock_cache)
    metrics = awareness.compute_portfolio_metrics()
    
    # Total equity = 80000 cash + (5 * 3200) + (20 * 200) = 80000 + 16000 + 4000 = 100000.0
    assert metrics["total_assets"] == 100000.0
    assert metrics["cash_allocation_pct"] == 80.0
    assert metrics["invested_capital_pct"] == 20.0
    
    # Sector exposure: TCS (IT) is 16%, ONGC (Energy) is 4%
    assert metrics["sector_exposure"]["it"] == 16.0
    assert metrics["sector_exposure"]["energy"] == 4.0
    
    # Diversification Score = (1.0 - correlation_concentration) * 100
    # squared exposure: IT is 0.16, Energy is 0.04
    # concentration_index = 0.16^2 + 0.04^2 = 0.0256 + 0.0016 = 0.0272 -> rounded 0.027
    # diversification_score = (1.0 - 0.027) * 100 = 97.3
    assert metrics["diversification_score"] == 97.3
    assert metrics["concentration_risk_pct"] == 2.7
    
    # Weighted Beta: TCS beta = 0.85 (weight 0.16) + ONGC beta = 1.15 (weight 0.04)
    # 0.85 * 0.16 + 1.15 * 0.04 = 0.136 + 0.046 = 0.182 -> rounded 0.18
    assert metrics["portfolio_beta"] == 0.18


def test_portfolio_health_grading():
    # 1. STRONG
    metrics = {
        "drawdown_pct": 0.0,
        "correlation_concentration": 0.05,
        "cash_allocation_pct": 50.0,
        "diversification_score": 95.0,
        "sector_exposure": {"it": 10.0}
    }
    res = PortfolioHealthEngine.calculate_health(metrics, win_rate=80.0)
    assert res["health_grade"] == "STRONG"
    assert res["health_score"] >= 86
    
    # 2. HEALTHY
    metrics["drawdown_pct"] = 8.0  # -16 pts
    res = PortfolioHealthEngine.calculate_health(metrics, win_rate=70.0)
    assert res["health_grade"] == "HEALTHY"
    
    # 3. WEAK
    metrics["cash_allocation_pct"] = 5.0  # cash < 20%: deficit = 15 -> -30 pts
    res = PortfolioHealthEngine.calculate_health(metrics, win_rate=60.0)
    assert res["health_grade"] == "WEAK"
    
    # 4. CRITICAL
    metrics["sector_exposure"] = {"it": 45.0}  # -30 pts for sector imbalance
    res = PortfolioHealthEngine.calculate_health(metrics, win_rate=40.0)
    assert res["health_grade"] == "CRITICAL"


def test_position_allocation_engine(mock_venue, mock_cache):
    awareness = PortfolioAwarenessEngine(mock_venue, mock_cache)
    engine = PositionAllocationEngine(awareness)
    
    # TCS (IT sector) has existing exposure = 16%.
    # Strong Buy (Conviction 90) suggest base 2.0% allocation.
    res_tcs = engine.evaluate_allocation("TCS", conviction_score=90)
    assert res_tcs["action"] == "STRONG BUY"
    assert res_tcs["suggested_allocation_pct"] == 2.0
    
    # Banking has 0% exposure. Allocation should be fully suggested.
    res_sbin = engine.evaluate_allocation("SBIN", conviction_score=80)
    assert res_sbin["action"] == "BUY"
    assert res_sbin["suggested_allocation_pct"] == 1.5


def test_portfolio_constraint_enforcement(mock_venue, mock_cache):
    # Set mock balance cash to critically low level (15% cash)
    mock_venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_main", total_equity=100000.0, cash=15000.0, margin_available=15000.0, margin_used=0.0
    )
    # Configure 85% equity exposure to trigger min cash reserve breach
    pos_tcs = MagicMock()
    pos_tcs.instrument.symbol = "TCS"
    pos_tcs.quantity = 26.5
    pos_tcs.average_price = 3200.0
    pos_tcs.current_price = 3200.0
    mock_venue.get_positions.return_value = [pos_tcs]
    
    awareness = PortfolioAwarenessEngine(mock_venue, mock_cache)
    engine = PositionAllocationEngine(awareness)
    
    # Cash reserve is 15% (which is < 20%). Suggested allocation should be capped to 0.0.
    res = engine.evaluate_allocation("INFY", conviction_score=90)
    assert res["suggested_allocation_pct"] == 0.0
    assert "minimum limit" in res["portfolio_impact"]
    assert res["action"] == "AVOID"


def test_capital_preservation_interaction(mock_venue, mock_cache):
    awareness = PortfolioAwarenessEngine(mock_venue, mock_cache)
    engine = PositionAllocationEngine(awareness)
    
    # Capital preservation restricts max allocation to 0.5% (e.g. Moderate Drawdown)
    pres_data = {"mode": "RECOVERY", "max_allocation_pct": 0.5}
    res = engine.evaluate_allocation("SBIN", conviction_score=80, preservation_data=pres_data)
    assert res["suggested_allocation_pct"] == 0.5
    assert "Capital Preservation" in res["portfolio_impact"]
