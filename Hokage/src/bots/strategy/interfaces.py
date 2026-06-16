from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.research.models import ResearchReport
from bots.strategy.models import StrategyProposal


@runtime_checkable
class StrategyGenerator(Protocol):
    """
    Generates trading strategies from research reports.
    """

    def generate(
        self,
        report: ResearchReport,
    ) -> StrategyProposal:
        """
        Convert research into a strategy proposal.
        """