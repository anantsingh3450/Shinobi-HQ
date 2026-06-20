"""Unit tests for Strategy Bot domain models."""
from __future__ import annotations

import pytest

from bots.strategy.models import StrategyProposal


class TestStrategyProposal:
    def test_valid_proposal(self) -> None:
        proposal = StrategyProposal(
            name="MACD Crossover",
            description="Enter long on MACD bullish crossover",
            market="EUR/USD",
            entry_rule="Enter long when MACD line crosses signal line from below.",
            exit_rule="Exit when MACD line crosses signal line from above.",
            stop_loss_rule="2% below entry price.",
            take_profit_rule="6% above entry price.",
            timeframe="1D",
            confidence_score=0.85,
            sources_cited=("source-1", "source-2"),
        )
        assert proposal.name == "MACD Crossover"
        assert proposal.market == "EUR/USD"
        assert proposal.confidence_score == 0.85
        assert proposal.sources_cited == ("source-1", "source-2")
        assert proposal.proposal_id
        assert proposal.generated_at

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="Strategy name cannot be empty"):
            StrategyProposal(
                name="   ",
                description="Desc",
                market="EUR/USD",
                entry_rule="Buy",
                exit_rule="Sell",
                stop_loss_rule="None",
                take_profit_rule="None",
                timeframe="1D",
                confidence_score=0.5,
            )

    def test_rejects_invalid_confidence_score(self) -> None:
        with pytest.raises(ValueError, match="confidence_score must be between 0.0 and 1.0"):
            StrategyProposal(
                name="Valid Name",
                description="Desc",
                market="EUR/USD",
                entry_rule="Buy",
                exit_rule="Sell",
                stop_loss_rule="None",
                take_profit_rule="None",
                timeframe="1D",
                confidence_score=1.2,
            )

        with pytest.raises(ValueError, match="confidence_score must be between 0.0 and 1.0"):
            StrategyProposal(
                name="Valid Name",
                description="Desc",
                market="EUR/USD",
                entry_rule="Buy",
                exit_rule="Sell",
                stop_loss_rule="None",
                take_profit_rule="None",
                timeframe="1D",
                confidence_score=-0.1,
            )
