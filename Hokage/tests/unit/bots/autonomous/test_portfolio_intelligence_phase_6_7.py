"""Unit tests for Phase 6.7: Portfolio Intelligence."""
from __future__ import annotations

import math
from unittest.mock import MagicMock
import pytest

from bots.autonomous.portfolio_intelligence import (
    PortfolioVolatilityEngine,
    PortfolioAwarenessEngine,
    PositionAllocationEngine,
    PortfolioHealthEngine,
)
from integrations.brokers.models import AccountBalance, VenuePosition, OrderSide
from integrations.data.models import Instrument, AssetClass, Exchange
from bots.autonomous.cache import IntelligenceCache


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock(spec=IntelligenceCache)
    cache.read_intelligence.return_value = {}
    return cache


@pytest.fixture
def mock_price_source() -> MagicMock:
    source = MagicMock()
    # Mock resolve_instrument to return a default Instrument
    def resolve(symbol):
        return Instrument(
            symbol=symbol,
            asset_class=AssetClass.INDIAN_EQUITY,
            exchange=Exchange.NSE,
            currency="INR",
            name=symbol
        )
    source.resolve_instrument.side_effect = resolve
    source.get_historical_candles.return_value = None
    return source


def test_portfolio_volatility_engine():
    # Test volatility on standard inputs
    returns_single = [0.01, 0.02, -0.01, 0.03, -0.02]
    vol = PortfolioVolatilityEngine.calculate_volatility(returns_single)
    assert vol > 0.0
    
    # Empty or single item
    assert PortfolioVolatilityEngine.calculate_volatility([]) == 0.0
    assert PortfolioVolatilityEngine.calculate_volatility([0.05]) == 0.0

    # Covariance
    cov = PortfolioVolatilityEngine.calculate_covariance(returns_single, returns_single)
    assert math.isclose(cov, vol * vol, rel_tol=1e-5)
    
    # Zero cov on single element
    assert PortfolioVolatilityEngine.calculate_covariance([0.01], [0.02]) == 0.0


def test_portfolio_awareness_metrics(mock_cache, mock_price_source):
    # Set up mock execution venue
    venue = MagicMock()
    venue.get_account_balance.return_value = AccountBalance(
        venue_id="temp_paper", total_equity=150000.0, cash=100000.0, margin_available=0.0, margin_used=0.0
    )

    # 2 Mock positions: TCS and INFY (both in IT sector)
    inst_tcs = Instrument("TCS", AssetClass.INDIAN_EQUITY, Exchange.NSE, "INR", "TCS")
    inst_infy = Instrument("INFY", AssetClass.INDIAN_EQUITY, Exchange.NSE, "INR", "INFY")
    
    pos_tcs = VenuePosition(
        instrument=inst_tcs,
        side=OrderSide.BUY,
        quantity=10.0,
        average_price=4000.0,
        current_price=4100.0,
        unrealized_pnl=1000.0,
        venue_id="temp_paper"
    )
    pos_infy = VenuePosition(
        instrument=inst_infy,
        side=OrderSide.BUY,
        quantity=2.0,
        average_price=1500.0,
        current_price=1550.0,
        unrealized_pnl=100.0,
        venue_id="temp_paper"
    )
    venue.get_positions.return_value = [pos_tcs, pos_infy]

    # Instantiate PortfolioAwareness
    awareness = PortfolioAwarenessEngine(venue, mock_cache, mock_price_source)
    metrics = awareness.compute_portfolio_metrics()

    # Verify basic computations. total_assets is the venue's EQUITY, not
    # cash + position value: the paper cash model never debits entries, so
    # cash+value double-counts every open position (the 2026-07-16 fake
    # kill-switch spike). This fixture's balance declares equity 150,000.
    total_value = (10 * 4100.0) + (2 * 1550.0)  # 41000 + 3100 = 44100
    total_assets = 150000.0
    assert metrics["total_assets"] == total_assets
    assert metrics["total_value"] == total_value
    
    # Exposure percentages: invested is the complement of the cash share of
    # equity (cash 100,000 of 150,000 equity -> 33.33% invested).
    expected_invested = 100.0 - (100000.0 / total_assets) * 100.0
    assert math.isclose(metrics["invested_capital_pct"], expected_invested, abs_tol=0.1)

    # Sector exposure (position value over equity)
    assert "it" in metrics["sector_exposure"]
    assert math.isclose(metrics["sector_exposure"]["it"], (total_value / total_assets) * 100.0, abs_tol=0.1)

    # Portfolio Volatility
    assert metrics["portfolio_volatility"] >= 0.0
    assert metrics["recommended_cash_reserve_pct"] in (20.0, 30.0, 50.0)
    assert metrics["diversification_score"] <= 100.0


def test_volatility_targeting_reserve(mock_cache, mock_price_source):
    venue = MagicMock()
    venue.get_account_balance.return_value = AccountBalance(
        venue_id="temp_paper", total_equity=100000.0, cash=100000.0, margin_available=0.0, margin_used=0.0
    )
    venue.get_positions.return_value = []

    awareness = PortfolioAwarenessEngine(venue, mock_cache, mock_price_source)
    metrics = awareness.compute_portfolio_metrics()

    # Zero open positions should give zero volatility (LOW regime)
    assert metrics["portfolio_volatility"] == 0.0
    assert metrics["volatility_regime"] == "LOW"
    assert metrics["recommended_cash_reserve_pct"] == 20.0


def test_opportunity_ranking_and_capital_efficiency(mock_cache, mock_price_source):
    venue = MagicMock()
    venue.get_account_balance.return_value = AccountBalance(
        venue_id="temp_paper", total_equity=100000.0, cash=100000.0, margin_available=0.0, margin_used=0.0
    )
    venue.get_positions.return_value = []

    awareness = PortfolioAwarenessEngine(venue, mock_cache, mock_price_source)
    allocator = PositionAllocationEngine(awareness)

    # Competing opportunities
    proposal_a = MagicMock()
    proposal_a.market = "TCS"
    proposal_a.entry_rule = "long"
    proposal_a.confidence_score = 80
    
    backtest_a = MagicMock()
    backtest_a.win_rate = 65.0
    backtest_a.profit_factor = 2.0

    proposal_b = MagicMock()
    proposal_b.market = "RELIANCE"
    proposal_b.entry_rule = "long"
    proposal_b.confidence_score = 90

    backtest_b = MagicMock()
    backtest_b.win_rate = 55.0
    backtest_b.profit_factor = 1.8

    opportunities = [
        {"proposal": proposal_a, "backtest_result": backtest_a, "conviction_score": 80, "entry_price": 4000.0},
        {"proposal": proposal_b, "backtest_result": backtest_b, "conviction_score": 90, "entry_price": 2950.0},
    ]

    metrics = awareness.compute_portfolio_metrics()
    ranked = allocator.rank_opportunities(opportunities, metrics)

    # Validate that both candidates received rankings and are sorted by composite score desc
    assert len(ranked) == 2
    assert ranked[0]["composite_score"] >= ranked[1]["composite_score"]
    assert "composite_score" in ranked[0]
    assert "capital_efficiency" in ranked[0]
    assert "diversification_bonus" in ranked[0]
    assert "correlation_penalty" in ranked[0]


def test_portfolio_health_grade():
    metrics = {
        "drawdown_pct": 1.0,
        "correlation_concentration": 0.2,
        "cash_allocation_pct": 25.0,
        "recommended_cash_reserve_pct": 20.0,
        "sector_exposure": {"it": 15.0},
        "diversification_score": 85.0
    }
    health = PortfolioHealthEngine.calculate_health(metrics)
    assert health["health_score"] > 80
    assert health["health_grade"] in ("STRONG", "HEALTHY")


def test_portfolio_budgeting_ranges(mock_cache, mock_price_source):
    venue = MagicMock()
    venue.get_account_balance.return_value = AccountBalance(
        venue_id="temp_paper", total_equity=100000.0, cash=100000.0, margin_available=0.0, margin_used=0.0
    )
    venue.get_positions.return_value = []

    awareness = PortfolioAwarenessEngine(venue, mock_cache, mock_price_source)
    metrics = awareness.compute_portfolio_metrics()

    assert "portfolio_budgets" in metrics
    budgets = metrics["portfolio_budgets"]
    assert "asset_class" in budgets
    assert "equity" in budgets["asset_class"]
    
    equity_budget = budgets["asset_class"]["equity"]
    assert equity_budget["min"] == 30.0
    assert equity_budget["max"] == 70.0
    assert equity_budget["target"] == 50.0
    # Decoupled dynamic target calculation
    assert equity_budget["dynamic_target"] >= 30.0


def test_position_allocation_budget_enforcement(mock_cache, mock_price_source):
    venue = MagicMock()
    # Mocking active exposures: let's pretend IT sector has 69.0% exposure already
    venue.get_account_balance.return_value = AccountBalance(
        venue_id="temp_paper", total_equity=100000.0, cash=31000.0, margin_available=0.0, margin_used=0.0
    )
    
    inst_tcs = Instrument("TCS", AssetClass.INDIAN_EQUITY, Exchange.NSE, "INR", "TCS")
    pos_tcs = VenuePosition(
        instrument=inst_tcs,
        side=OrderSide.BUY,
        quantity=23.0,
        average_price=3000.0,
        current_price=3000.0,
        unrealized_pnl=0.0,
        venue_id="temp_paper"
    )
    venue.get_positions.return_value = [pos_tcs] # 69% exposure

    awareness = PortfolioAwarenessEngine(venue, mock_cache, mock_price_source)
    custom_budget = {
        "max_deployable_capital_pct": 80.0,
        "cash_reserve_target_pct": 20.0,
        "asset_class_budgets": {
            "equity": { "target": 50.0, "min": 30.0, "max": 65.0 }
        },
        "exchange_budgets": {
            "nse": { "target": 60.0, "min": 30.0, "max": 65.0 }
        }
    }
    awareness._load_budget_config = MagicMock(return_value=custom_budget)
    allocator = PositionAllocationEngine(awareness)

    # TCS is in "it" sector (equity). Max limit is 65%. Proposed size is 2.0% CNC.
    # Exceeding the max ceiling: 69% is already above 65% max limit.
    # The allocator should scale it down to 0.0% and record "AssetClassBudgetMaxLimit" constraint.
    res = allocator.evaluate_allocation("TCS", 90)
    assert res["suggested_allocation_pct"] == 0.0
    assert "AssetClassBudgetMaxLimit" in res["active_constraints"]
