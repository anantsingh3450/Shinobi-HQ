from __future__ import annotations

from bots.research.models import ResearchReport
from bots.strategy.models import StrategyProposal


class StrategyBot:
    """
    Converts research reports into strategy proposals.
    """

    def generate(
        self,
        report: ResearchReport,
    ) -> StrategyProposal:

        market = "UNKNOWN"

        if report.query.topics:
            market = report.query.topics[0].upper()

        return StrategyProposal(
            name=f"{market} Trend Strategy",
            description=report.executive_summary,
            market=market,
            entry_rule="Enter when trend confirms.",
            exit_rule="Exit when trend weakens.",
            stop_loss_rule="1% stop loss.",
            take_profit_rule="2% take profit.",
            timeframe="1D",
            confidence_score=0.70,
        )