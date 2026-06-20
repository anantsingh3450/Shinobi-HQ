"""Unit tests for Strategy Bot orchestration."""
from __future__ import annotations

from unittest.mock import Mock

from bots.research.models import ResearchQuery, ResearchReport
from bots.strategy.models import StrategyProposal
from bots.strategy.strategy_bot import StrategyBot
from tests.conftest import make_finding


def test_strategy_bot_orchestration(sample_query: ResearchQuery) -> None:
    # Arrange
    finding = make_finding("Bullish breakout", relevance_score=0.9, source_id="src-1")
    report = ResearchReport(
        query=sample_query,
        findings=(finding,),
        executive_summary="ECB looks supportive",
    )

    mock_proposal = StrategyProposal(
        name="Mock Strategy",
        description="Desc",
        market="EUR/USD",
        entry_rule="Buy",
        exit_rule="Sell",
        stop_loss_rule="None",
        take_profit_rule="None",
        timeframe="1D",
        confidence_score=0.9,
        sources_cited=("src-1",),
    )

    mock_generator = Mock()
    mock_generator.generate.return_value = mock_proposal

    bot = StrategyBot(generator=mock_generator)

    # Act
    proposal = bot.generate(report)

    # Assert
    mock_generator.generate.assert_called_once_with(report)
    assert proposal == mock_proposal
