"""Unit tests for Execution Bot orchestration."""
from __future__ import annotations

from unittest.mock import Mock

from bots.execution.execution_bot import ExecutionBot
from bots.execution.models import TradeDirection, TradeRecord
from bots.strategy.models import StrategyProposal


def test_execution_bot_with_store_and_persist() -> None:
    # Arrange
    proposal = StrategyProposal(
        name="Strategy",
        description="Desc",
        market="EUR/USD",
        entry_rule="Buy",
        exit_rule="Sell",
        stop_loss_rule="None",
        take_profit_rule="None",
        timeframe="1D",
        confidence_score=0.8,
        sources_cited=("src-1",),
    )

    trade = TradeRecord(
        proposal_id=proposal.proposal_id,
        market=proposal.market,
        direction=TradeDirection.LONG,
        quantity=1.0,
        entry_price=1.0850,
        simulated_value=1.0850,
        strategy_name=proposal.name,
        sources_cited=proposal.sources_cited,
    )

    mock_engine = Mock()
    mock_engine.execute.return_value = trade

    mock_store = Mock()

    bot = ExecutionBot(engine=mock_engine, store=mock_store)

    # Act
    result = bot.execute(proposal, persist=True)

    # Assert
    mock_engine.execute.assert_called_once_with(proposal)
    mock_store.save.assert_called_once_with(trade)
    assert result == trade


def test_execution_bot_without_persist() -> None:
    # Arrange
    proposal = StrategyProposal(
        name="Strategy",
        description="Desc",
        market="EUR/USD",
        entry_rule="Buy",
        exit_rule="Sell",
        stop_loss_rule="None",
        take_profit_rule="None",
        timeframe="1D",
        confidence_score=0.8,
        sources_cited=("src-1",),
    )

    trade = TradeRecord(
        proposal_id=proposal.proposal_id,
        market=proposal.market,
        direction=TradeDirection.LONG,
        quantity=1.0,
        entry_price=1.0850,
        simulated_value=1.0850,
        strategy_name=proposal.name,
        sources_cited=proposal.sources_cited,
    )

    mock_engine = Mock()
    mock_engine.execute.return_value = trade

    mock_store = Mock()

    bot = ExecutionBot(engine=mock_engine, store=mock_store)

    # Act
    result = bot.execute(proposal, persist=False)

    # Assert
    mock_engine.execute.assert_called_once_with(proposal)
    mock_store.save.assert_not_called()
    assert result == trade


def test_execution_bot_no_store() -> None:
    # Arrange
    proposal = StrategyProposal(
        name="Strategy",
        description="Desc",
        market="EUR/USD",
        entry_rule="Buy",
        exit_rule="Sell",
        stop_loss_rule="None",
        take_profit_rule="None",
        timeframe="1D",
        confidence_score=0.8,
        sources_cited=("src-1",),
    )

    trade = TradeRecord(
        proposal_id=proposal.proposal_id,
        market=proposal.market,
        direction=TradeDirection.LONG,
        quantity=1.0,
        entry_price=1.0850,
        simulated_value=1.0850,
        strategy_name=proposal.name,
        sources_cited=proposal.sources_cited,
    )

    mock_engine = Mock()
    mock_engine.execute.return_value = trade

    bot = ExecutionBot(engine=mock_engine, store=None)

    # Act
    result = bot.execute(proposal, persist=True)

    # Assert
    mock_engine.execute.assert_called_once_with(proposal)
    assert result == trade
