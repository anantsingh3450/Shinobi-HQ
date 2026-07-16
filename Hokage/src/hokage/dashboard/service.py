"""Dashboard service — query orchestrator and format data for frontend.

The DashboardService is a read-only adapter that:
1. Loads account state from JsonPortfolioStore
2. Queries trade history from storage
3. Transforms domain models to dashboard view models
4. Provides REST-friendly endpoint implementations

This service has NO side effects and does NOT modify account or trade data.
"""
from __future__ import annotations

from bots.execution.store.json_trade_store import JsonTradeStore
from bots.portfolio.store import JsonPortfolioStore
from hokage.dashboard.models import (
    AccountMetrics,
    PortfolioOverview,
    PositionSnapshot,
    TradeSnapshot,
)


class DashboardService:
    """Provides read-only portfolio data for frontend visualization."""

    def __init__(
        self,
        portfolio_store: JsonPortfolioStore,
        trade_store: JsonTradeStore,
    ) -> None:
        """Initialize dashboard service with data stores.

        Args:
            portfolio_store: JsonPortfolioStore for account state.
            trade_store: JsonTradeStore for trade history.
        """
        self.portfolio_store = portfolio_store
        self.trade_store = trade_store

    def get_portfolio_overview(self, account_id: str) -> PortfolioOverview:
        """Get high-level portfolio summary.

        Args:
            account_id: Account to retrieve overview for.

        Returns:
            PortfolioOverview with key metrics.
        """
        account = self.portfolio_store.load_account(account_id)
        return PortfolioOverview.from_account(account)

    def get_open_positions(self, account_id: str) -> list[PositionSnapshot]:
        """Get all currently open positions.

        Args:
            account_id: Account to retrieve positions for.

        Returns:
            List of PositionSnapshot for open positions only.
        """
        account = self.portfolio_store.load_account(account_id)
        from bots.execution.models import TradeStatus

        return [
            PositionSnapshot.from_position(pos)
            for pos in account.positions.values()
            if pos.status == TradeStatus.OPEN
        ]

    def get_closed_positions(self, account_id: str) -> list[PositionSnapshot]:
        """Get all closed positions.

        Args:
            account_id: Account to retrieve positions for.

        Returns:
            List of PositionSnapshot for closed positions only.
        """
        account = self.portfolio_store.load_account(account_id)
        from bots.execution.models import TradeStatus

        return [
            PositionSnapshot.from_position(pos)
            for pos in account.positions.values()
            if pos.status == TradeStatus.CLOSED
        ]

    def get_all_positions(self, account_id: str) -> list[PositionSnapshot]:
        """Get all positions (open and closed).

        Args:
            account_id: Account to retrieve positions for.

        Returns:
            List of all PositionSnapshot objects.
        """
        account = self.portfolio_store.load_account(account_id)
        # The 2026-07-15 exit runaway minted hundreds of PHANTOM-tagged
        # positions (exits that opened exposure, later force-flattened). They
        # are bookkeeping, not trading history — showing them (with their
        # fabricated ±PnL) misleads the commander. Same filter as the arena.
        return [
            PositionSnapshot.from_position(pos)
            for pos in account.positions.values()
            if not str(getattr(pos, "failure_reason", "") or "").startswith("PHANTOM")
        ]

    def get_trade_history(self, account_id: str, limit: int | None = None) -> list[TradeSnapshot]:
        """Get trade history, optionally limited to most recent N trades.

        Args:
            account_id: Account to retrieve trades for (used for context).
            limit: Maximum number of trades to return (None = all).

        Returns:
            List of TradeSnapshot objects, ordered newest first.
        """
        # For now, we load trades from JsonTradeStore
        # In a real system with multiple accounts, we'd filter by account_id
        trades = self.trade_store.load_all()
        
        if limit:
            trades = trades[-limit:]
        
        return [TradeSnapshot.from_trade_record(trade) for trade in reversed(trades)]

    def get_account_metrics(self, account_id: str) -> AccountMetrics:
        """Get detailed performance metrics for an account.

        Args:
            account_id: Account to compute metrics for.

        Returns:
            AccountMetrics with performance data.
        """
        account = self.portfolio_store.load_account(account_id)
        return AccountMetrics.from_account(account)
