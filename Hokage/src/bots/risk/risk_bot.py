"""Risk Bot orchestration service.

Handles pipeline pre-trade gating checks using pluggable RiskManager rules.
"""
from __future__ import annotations

from bots.portfolio.models import Account
from bots.risk.interfaces import RiskManager
from bots.risk.models import RiskVerdict
from bots.strategy.models import StrategyProposal


class RiskBot:
    """Orchestrates pre-trade risk evaluation checks.

    Delegates check rules to an injected RiskManager.
    """

    def __init__(self, manager: RiskManager) -> None:
        """Initialize with a risk manager.

        Args:
            manager: Concrete RiskManager (typically a CompositeRiskManager).
        """
        self._manager = manager

    @property
    def manager(self) -> RiskManager:
        """The configured risk manager."""
        return self._manager

    def check_proposal(
        self,
        account: Account,
        proposal: StrategyProposal,
        entry_price: float,
    ) -> RiskVerdict:
        """Evaluate if a strategy proposal complies with risk policies.

        Args:
            account:     The active account state.
            proposal:    The generated strategy proposal.
            entry_price: Market entry price.

        Returns:
            A RiskVerdict approving or rejecting the proposal.
        """
        return self._manager.check_order(account, proposal, entry_price)
