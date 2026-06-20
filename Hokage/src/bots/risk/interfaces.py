"""Risk Bot interfaces (protocols).

Defines the pluggable components and boundaries for risk rules and managers.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.portfolio.models import Account
from bots.risk.models import RiskVerdict
from bots.strategy.models import StrategyProposal


@runtime_checkable
class RiskManager(Protocol):
    """Protocol for checking orders against risk rules."""

    def check_order(
        self,
        account: Account,
        proposal: StrategyProposal,
        entry_price: float,
    ) -> RiskVerdict:
        """Evaluate if the strategy proposal is allowed under risk limits.

        Args:
            account:      The active account state to check against.
            proposal:     The strategy proposal to execute.
            entry_price:  The estimated execution entry price.

        Returns:
            A RiskVerdict approving, modifying, or denying the trade.
        """
        ...
