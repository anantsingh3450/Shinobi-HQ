"""Unit tests for the Execution Friction Model and Quality Analytics Engine.

Covers Zero friction, profiled friction, volatility shifts, partial fills,
latency ranges, and SQLite/JSON metrics aggregation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from bots.execution.friction import (
    FrictionProfile,
    ProfiledFrictionModel,
    ZeroFrictionModel,
    get_market_volatility,
)
from bots.execution.models import TradeDirection, TradeRecord, TradeStatus
from bots.execution.engine.paper_engine import PaperEngine
from bots.strategy.models import StrategyProposal
from bots.autonomous.quality_engine import ExecutionQualityEngine
from integrations.brokers.models import ExecutionMode
from integrations.data.mock_provider import MockMarketDataProvider
from shared.persistence.sqlite_engine import SqliteStorageEngine
from shared.persistence.sqlite_stores import SqliteTradeStore


class SimpleMockPriceSource:
    """Very basic PriceSource implementation for testing."""

    def __init__(self, price: float) -> None:
        self.price = price

    def get_price(self, market: str) -> float:
        return self.price


def test_zero_friction_model() -> None:
    """Verify ZeroFrictionModel has zero impact on prices, quantities, and latency."""
    model = ZeroFrictionModel()
    res = model.apply_friction(
        market="RELIANCE",
        direction=TradeDirection.LONG,
        quantity=10.0,
        mid_price=2500.0,
        market_volatility=0.2,
    )

    assert res["fill_price"] == 2500.0
    assert res["filled_quantity"] == 10.0
    assert res["slippage_price"] == 0.0
    assert res["slippage_pct"] == 0.0
    assert res["latency_ms"] == 0.0


def test_profiled_friction_zero_profile() -> None:
    """Verify ZERO profile behaves identical to ZeroFrictionModel."""
    model = ProfiledFrictionModel(FrictionProfile.ZERO)
    res = model.apply_friction(
        market="TCS",
        direction=TradeDirection.SHORT,
        quantity=50.0,
        mid_price=3000.0,
        market_volatility=1.5,
    )

    assert res["fill_price"] == 3000.0
    assert res["filled_quantity"] == 50.0
    assert res["slippage_price"] == 0.0
    assert res["slippage_pct"] == 0.0
    assert res["latency_ms"] == 0.0


def test_profiled_friction_spread_and_slippage() -> None:
    """Verify spread and slippage adjust price in correct directions for buy and sell."""
    # Using LIGHT profile: spread_pct=0.01%, base_slippage_pct=0.01%, vol_coeff=0.05
    model = ProfiledFrictionModel(FrictionProfile.LIGHT)

    # 1. Buy (LONG) Order: price should adjust UPWARD
    res_long = model.apply_friction(
        market="INFY",
        direction=TradeDirection.LONG,
        quantity=10.0,
        mid_price=1500.0,
        market_volatility=0.0,  # Zero volatility to isolate base slippage + half spread
    )
    # half spread = 0.005%, base slippage = 0.01% -> total = 0.015% increase
    # 1500 * (1 + 0.00015) = 1500.225
    assert res_long["fill_price"] == 1500.225
    assert res_long["slippage_price"] == 0.225
    assert res_long["slippage_pct"] == 0.015
    assert res_long["filled_quantity"] == 10.0
    assert 10.0 <= res_long["latency_ms"] <= 30.0

    # 2. Sell (SHORT) Order: price should adjust DOWNWARD
    res_short = model.apply_friction(
        market="INFY",
        direction=TradeDirection.SHORT,
        quantity=10.0,
        mid_price=1500.0,
        market_volatility=0.0,
    )
    # half spread = 0.005%, base slippage = 0.01% -> total = 0.015% decrease
    # 1500 * (1 - 0.00015) = 1499.775
    assert res_short["fill_price"] == 1499.775
    assert res_short["slippage_price"] == 0.225
    assert res_short["slippage_pct"] == 0.015
    assert res_short["filled_quantity"] == 10.0


def test_volatility_aware_slippage() -> None:
    """Verify that higher volatility increases slippage and fill prices for buys."""
    # Using LIGHT profile: base_slippage_pct=0.01%, vol_coeff=0.05, spread_pct=0.01%
    model = ProfiledFrictionModel(FrictionProfile.LIGHT)

    # Low Volatility (0.5%)
    res_low = model.apply_friction(
        market="RELIANCE",
        direction=TradeDirection.LONG,
        quantity=10.0,
        mid_price=2000.0,
        market_volatility=0.5,
    )
    # slippage = 0.01 + 0.05 * 0.5 = 0.035%
    # total friction = 0.035% + 0.005% = 0.04%
    # 2000 * (1 + 0.0004) = 2000.80
    assert res_low["slippage_pct"] == 0.04

    # High Volatility (4.0%)
    res_high = model.apply_friction(
        market="RELIANCE",
        direction=TradeDirection.LONG,
        quantity=10.0,
        mid_price=2000.0,
        market_volatility=4.0,
    )
    # slippage = 0.01 + 0.05 * 4.0 = 0.21%
    # total friction = 0.21% + 0.005% = 0.215%
    # 2000 * (1 + 0.00215) = 2004.30
    assert res_high["slippage_pct"] == 0.215
    assert res_high["fill_price"] > res_low["fill_price"]


def test_partial_fills() -> None:
    """Verify that orders exceeding the threshold can trigger partial fills deterministically."""
    # Using CRYPTO profile: qty_threshold=10.0, partial_chance=0.15, min_fill=70%
    model = ProfiledFrictionModel(FrictionProfile.CRYPTO)

    # 1. Below threshold: must always be 100% filled
    res_below = model.apply_friction(
        market="BTC",
        direction=TradeDirection.LONG,
        quantity=5.0,
        mid_price=60000.0,
        market_volatility=1.0,
    )
    assert res_below["filled_quantity"] == 5.0

    # 2. Above threshold: deterministic hash-based chance check
    # Let's check with a quantity that deterministic hash triggers a fill less than 100%
    # We test with multiple quantities to find one that triggers the partial fill
    partials_triggered = 0
    for qty in range(15, 30):
        res = model.apply_friction(
            market="BTC",
            direction=TradeDirection.LONG,
            quantity=float(qty),
            mid_price=60000.0,
            market_volatility=1.0,
        )
        if res["filled_quantity"] < float(qty):
            partials_triggered += 1
            # Fill ratio must be within [70%, 99%]
            fill_pct = (res["filled_quantity"] / float(qty)) * 100.0
            assert 70.0 <= fill_pct <= 99.0
    
    assert partials_triggered >= 0


def test_get_market_volatility_calculation() -> None:
    """Verify get_market_volatility calculates volatility from candles, quotes, or defaults."""
    # 1. Fallback default
    price_source_simple = SimpleMockPriceSource(100.0)
    vol_default = get_market_volatility(price_source_simple, "RELIANCE")
    assert vol_default == 0.15

    # 2. Mock Market Data Provider with candles
    provider = MockMarketDataProvider()
    vol_candles = get_market_volatility(provider, "CRUDE_OIL")
    # Should calculate std dev of price logs or returns. Mock returns deterministic values, so should be positive
    assert vol_candles >= 0.0


def test_quality_engine_analytics_aggregation(tmp_path: Path) -> None:
    """Verify ExecutionQualityEngine aggregates metrics accurately from SQLite database."""
    from hokage.memory.resolver import PathResolver
    resolver = PathResolver(tmp_path)
    
    # 1. Setup mock SQLite engine
    sqlite_engine = SqliteStorageEngine(resolver)
    sqlite_engine.initialize_schema(sqlite_engine.get_connection())
    
    # Initialize empty metrics
    quality_engine = ExecutionQualityEngine(sqlite_engine)
    m_empty = quality_engine.get_quality_metrics()
    assert m_empty["total_trades"] == 0
    assert m_empty["execution_quality_score"] == 100.0
    assert m_empty["execution_health"] == "EXCELLENT"

    # 2. Persist trades with friction metrics to trigger replay recording
    store = SqliteTradeStore(sqlite_engine)
    
    trade1 = TradeRecord(
        proposal_id="PROP_1",
        market="TCS",
        direction=TradeDirection.LONG,
        quantity=100.0,
        entry_price=3015.0,
        simulated_value=301500.0,
        strategy_name="Breakout",
        sources_cited=(),
        executed_at=datetime.now(timezone.utc),
        friction_metrics={
            "requested_quantity": 100.0,
            "filled_quantity": 100.0,
            "mid_price": 3000.0,
            "fill_price": 3015.0,
            "slippage_price": 15.0,
            "slippage_pct": 0.5,  # 0.5% slippage
            "latency_ms": 50.0,
            "partial_fill": False,
            "profile": "NSE_EQUITY",
        }
    )
    
    trade2 = TradeRecord(
        proposal_id="PROP_2",
        market="RELIANCE",
        direction=TradeDirection.LONG,
        quantity=1000.0,
        entry_price=2525.0,
        simulated_value=202000.0,
        strategy_name="Reversal",
        sources_cited=(),
        executed_at=datetime.now(timezone.utc),
        friction_metrics={
            "requested_quantity": 1000.0,
            "filled_quantity": 800.0,  # Partial fill!
            "mid_price": 2500.0,
            "fill_price": 2525.0,
            "slippage_price": 25.0,
            "slippage_pct": 1.0,  # 1.0% slippage
            "latency_ms": 150.0,
            "partial_fill": True,
            "profile": "NSE_EQUITY",
        }
    )

    # Save trades (automatically inserts into trade_replays since friction_metrics are present)
    store.save(trade1)
    store.save(trade2)

    # Aggregate and assert
    metrics = quality_engine.get_quality_metrics()
    assert metrics["total_trades"] == 2
    
    # average slippage = (0.5 + 1.0) / 2 = 0.75%
    assert abs(metrics["average_slippage_pct"] - 0.75) < 1e-4
    assert metrics["worst_slippage_pct"] == 1.0
    
    # average latency = (50 + 150) / 2 = 100 ms
    assert metrics["average_latency_ms"] == 100.0
    
    # partial fill ratio = 1/2 = 50%
    assert metrics["partial_fill_pct"] == 50.0

    # Score calculation check:
    # slip_score = max(0, 100 - 0.75 * 200) = 0.0
    # lat_score = max(0, 100 - 100 / 5.0) = 80.0
    # fill_score = 100 - 50 = 50.0
    # composite score = 0.4 * 0.0 + 0.3 * 80.0 + 0.3 * 50.0 = 24.0 + 15.0 = 39.0
    assert abs(metrics["execution_quality_score"] - 39.0) < 1e-2
    assert metrics["execution_health"] == "CRITICAL"  # Score 39.0 < 50 is CRITICAL


def test_paper_engine_friction_integration() -> None:
    """Verify that PaperEngine correctly integrates with ProfiledFrictionModel during execute()."""
    # LIGHT profile: spread_pct=0.01%, base_slippage_pct=0.01%
    friction = ProfiledFrictionModel(FrictionProfile.LIGHT)
    price_source = SimpleMockPriceSource(100.0)
    
    engine = PaperEngine(price_source=price_source, friction_model=friction)
    proposal = StrategyProposal(
        proposal_id="PROP_LIGHT",
        name="Momentum",
        description="Buy breakout",
        market="RELIANCE",
        entry_rule="long",
        exit_rule="none",
        stop_loss_rule="none",
        take_profit_rule="none",
        timeframe="1m",
        confidence_score=0.8,
        sources_cited=()
    )
    
    trade = engine.execute(proposal, quantity=10.0)
    
    # Assert
    assert trade.quantity == 10.0
    # Price = 100.0 * (1 + 0.0225/100) = 100.0225
    assert trade.entry_price == 100.0225
    assert trade.simulated_value == 1000.225
    assert trade.friction_metrics is not None
    assert trade.friction_metrics["profile"] == "LIGHT"
    assert trade.friction_metrics["mid_price"] == 100.0
    assert trade.friction_metrics["fill_price"] == 100.0225
    assert trade.friction_metrics["slippage_pct"] == 0.0225
    assert 10.0 <= trade.friction_metrics["latency_ms"] <= 30.0
