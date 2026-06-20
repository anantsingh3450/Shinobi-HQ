from __future__ import annotations

from bots.research.models import ResearchReport
from bots.strategy.models import StrategyProposal

from bots.strategy.interfaces import StrategyGenerator

class StrategyBot:
    """
    Converts research reports into strategy proposals using an injected generator.
    """

    def __init__(self, generator: StrategyGenerator) -> None:
        """Initialize with a strategy generator."""
        self.generator = generator

    def generate(
        self,
        report: ResearchReport,
    ) -> StrategyProposal:
        """Delegate generation to the injected adapter."""
        return self.generator.generate(report)