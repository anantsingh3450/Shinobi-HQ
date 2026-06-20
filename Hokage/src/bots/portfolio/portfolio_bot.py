"""Portfolio Bot orchestration service.

Provides a clean architecture wrapper around an Account and exposes
portfolio-level operations used by higher-level workflow orchestrators.
"""
from __future__ import annotations

from bots.execution.models import TradeRecord
from bots.portfolio.models import Account


class PortfolioBot:
    """Orchestrates portfolio activity for a single account.

    The PortfolioBot is a thin application service that delegates portfolio
    accounting responsibilities to the underlying Account domain model.
    """

    def __init__(self, account: Account) -> None:
        """Initialize the PortfolioBot with an Account.

        Args:
            account: The account instance whose positions and equity are managed.
        """
        self._account = account

    def apply_trade(self, trade: TradeRecord) -> None:
        """Apply a trade to the account.

        Delegates the trade application logic to ``Account.apply_trade()``.

        Args:
            trade: The trade record to apply to the account.
        """
        self._account.apply_trade(trade)

    def equity(self) -> float:
        """Return the current account equity.

        Equity is computed by the Account domain model as cash plus the
        unrealized PnL of all open positions.

        Returns:
            The account equity as a floating-point value.
        """
        return self._account.equity

    def open_positions_count(self) -> int:
        """Return the number of open positions in the account.

        Returns:
            The count of positions whose status is OPEN.
        """
        return sum(
            1
            for position in self._account.positions.values()
            if position.status.name == "OPEN"
        )

    def realized_pnl(self) -> float:
        """Return the total realized profit and loss for the account.

        Returns:
            The account's realized PnL as a floating-point value.
        """
        return self._account.realized_pnl