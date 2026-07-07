"""Concrete ranking engine implementation for the Opportunity Discovery Engine.

Implements opportunity prioritization based on conviction score and risk-reward ratio.
"""
from __future__ import annotations
from shared.discovery.interfaces import BaseOpportunityRankingEngine
from shared.discovery.models import Opportunity

class OpportunityRankingEngine(BaseOpportunityRankingEngine):
    """Sorts and prioritizes heterogeneous opportunities across different asset categories."""

    def rank_opportunities(self, opportunities: list[Opportunity]) -> list[Opportunity]:
        """Rank opportunities by conviction score (descending), then expected risk-reward (descending).

        Args:
            opportunities: A list of Opportunity objects scanned across markets.

        Returns:
            List of sorted Opportunity objects, highest priority first.
        """
        return sorted(
            opportunities,
            key=lambda x: (x.conviction_score, x.expected_rr),
            reverse=True
        )
