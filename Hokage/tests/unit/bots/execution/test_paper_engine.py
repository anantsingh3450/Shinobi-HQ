"""Unit tests for the PaperEngine."""
from __future__ import annotations

import pytest

from bots.execution.engine.paper_engine import PaperEngine
from bots.execution.models import ExecutionMode, TradeDirection, TradeStatus
from bots.strategy.models import StrategyProposal
from integrations.data.mock_price_source import MockPriceSource


class TestPaperEngine:
    def test_invalid_default_quantity(self) -> None:
        price_source = MockPriceSource()
        with pytest.raises(ValueError, match="default_quantity must be positive"):
            PaperEngine(price_source=price_source, default_quantity=0)

        with pytest.raises(ValueError, match="default_quantity must be positive"):
            PaperEngine(price_source=price_source, default_quantity=-1.5)

    def test_execute_long_trade(self) -> None:
        # Arrange
        price_source = MockPriceSource()  # EUR/USD mock price is 1.0850
        engine = PaperEngine(price_source=price_source, default_quantity=100.0)

        proposal = StrategyProposal(
            name="EUR/USD Momentum Long",
            description="Buy EUR/USD",
            market="EUR/USD",
            entry_rule="Enter long when 50 EMA crosses 200 EMA.",
            exit_rule="Exit on cross down.",
            stop_loss_rule="1% SL",
            take_profit_rule="3% TP",
            timeframe="1H",
            confidence_score=0.75,
            sources_cited=("source-alpha", "source-beta"),
        )

        # Act
        trade = engine.execute(proposal)

        # Assert
        assert trade.proposal_id == proposal.proposal_id
        assert trade.market == "EUR/USD"
        assert trade.direction == TradeDirection.LONG
        assert trade.quantity == 100.0
        assert trade.entry_price == 1.0850
        assert trade.simulated_value == 108.50  # 100 * 1.0850
        assert trade.mode == ExecutionMode.PAPER
        assert trade.status == TradeStatus.OPEN
        assert trade.strategy_name == "EUR/USD Momentum Long"
        assert trade.sources_cited == ("source-alpha", "source-beta")

    def test_execute_short_trade(self) -> None:
        # Arrange
        price_source = MockPriceSource()  # BTC/USD mock price is 65000.0
        engine = PaperEngine(price_source=price_source, default_quantity=2.0)

        proposal = StrategyProposal(
            name="BTC/USD Short Strategy",
            description="Short BTC/USD",
            market="BTC/USD",
            entry_rule="Enter SHORT breakout below $65,000 support.",
            exit_rule="Exit rule",
            stop_loss_rule="SL",
            take_profit_rule="TP",
            timeframe="1H",
            confidence_score=0.8,
            sources_cited=("source-gamma",),
        )

        # Act
        trade = engine.execute(proposal)

        # Assert
        assert trade.market == "BTC/USD"
        assert trade.direction == TradeDirection.SHORT
        assert trade.quantity == 2.0
        assert trade.entry_price == 65000.0
        assert trade.simulated_value == 130000.0  # 2 * 65000
        assert trade.strategy_name == "BTC/USD Short Strategy"
        assert trade.sources_cited == ("source-gamma",)
