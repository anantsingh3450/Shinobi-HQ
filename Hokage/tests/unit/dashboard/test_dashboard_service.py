"""Unit tests for DashboardService."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bots.execution.models import ExecutionMode, TradeDirection, TradeRecord, TradeStatus
from bots.portfolio.models import Account, Position
from hokage.dashboard.models import (
    AccountMetrics,
    PortfolioOverview,
    PositionSnapshot,
    TradeSnapshot,
)
from hokage.dashboard.service import DashboardService


@pytest.fixture
def mock_account() -> Account:
    """Create a mock account with sample positions."""
    account = Account(
        account_id="test",
        initial_balance=10000.0,
        cash=5000.0,
    )
    
    # Add an open position
    position1 = Position(
        position_id="pos_001",
        market="EUR/USD",
        direction=TradeDirection.LONG,
        quantity=100.0,
        entry_price=1.0850,
        current_price=1.0900,
        status=TradeStatus.OPEN,
    )
    account.positions[position1.position_id] = position1
    
    # Add a closed position
    position2 = Position(
        position_id="pos_002",
        market="GBP/USD",
        direction=TradeDirection.SHORT,
        quantity=50.0,
        entry_price=1.2500,
        current_price=None,
        realized_pnl=100.0,
        status=TradeStatus.CLOSED,
    )
    account.positions[position2.position_id] = position2
    
    return account


@pytest.fixture
def mock_portfolio_store(mock_account: Account) -> MagicMock:
    """Create a mock portfolio store."""
    store = MagicMock()
    store.load_account.return_value = mock_account
    return store


@pytest.fixture
def mock_trade_store() -> MagicMock:
    """Create a mock trade store with sample trades."""
    trade1 = TradeRecord(
        trade_id="trade_001",
        proposal_id="prop_001",
        market="EUR/USD",
        direction=TradeDirection.LONG,
        quantity=100.0,
        entry_price=1.0850,
        simulated_value=108.5,
        status=TradeStatus.OPEN,
        mode=ExecutionMode.PAPER,
        strategy_name="Momentum Strategy",
        sources_cited=("source-1",),
        executed_at=datetime(2026, 6, 21, 10, 0, 0),
    )
    
    trade2 = TradeRecord(
        trade_id="trade_002",
        proposal_id="prop_002",
        market="GBP/USD",
        direction=TradeDirection.SHORT,
        quantity=50.0,
        entry_price=1.2500,
        simulated_value=62.5,
        status=TradeStatus.CLOSED,
        mode=ExecutionMode.PAPER,
        strategy_name="Mean Reversion",
        sources_cited=("source-2",),
        executed_at=datetime(2026, 6, 21, 11, 0, 0),
    )
    
    store = MagicMock()
    store.load_trades.return_value = [trade1, trade2]
    return store


@pytest.fixture
def dashboard_service(
    mock_portfolio_store: MagicMock,
    mock_trade_store: MagicMock,
) -> DashboardService:
    """Create a dashboard service with mocked stores."""
    return DashboardService(mock_portfolio_store, mock_trade_store)


class TestPortfolioOverview:
    """Tests for PortfolioOverview snapshot generation."""

    def test_from_account_creates_valid_overview(self, mock_account: Account) -> None:
        """Test creating overview from account."""
        overview = PortfolioOverview.from_account(mock_account)

        assert overview.account_id == "test"
        assert overview.initial_balance == 10000.0
        assert overview.current_equity == mock_account.equity
        assert overview.cash == 5000.0
        # Realized PnL is account's realized_pnl, not sum of positions
        assert overview.total_realized_pnl == mock_account.realized_pnl
        assert overview.open_positions_count == 1
        assert overview.total_trades_count == 2  # 2 total positions

    def test_to_dict_serialization(self, mock_account: Account) -> None:
        """Test converting overview to dictionary for JSON."""
        overview = PortfolioOverview.from_account(mock_account)
        data = overview.to_dict()

        assert isinstance(data, dict)
        assert "account_id" in data
        assert "current_equity" in data
        assert "return_percentage" in data


class TestPositionSnapshot:
    """Tests for PositionSnapshot generation."""

    def test_from_open_position(self, mock_account: Account) -> None:
        """Test snapshot from open position."""
        position = list(mock_account.positions.values())[0]
        snapshot = PositionSnapshot.from_position(position)

        assert snapshot.position_id == position.position_id
        assert snapshot.market == "EUR/USD"
        assert snapshot.direction == "LONG"
        assert snapshot.status == "OPEN"
        assert snapshot.unrealized_pnl == position.unrealized_pnl

    def test_from_closed_position(self, mock_account: Account) -> None:
        """Test snapshot from closed position."""
        position = list(mock_account.positions.values())[1]
        snapshot = PositionSnapshot.from_position(position)

        assert snapshot.status == "CLOSED"
        assert snapshot.current_price is None
        assert snapshot.realized_pnl == 100.0


class TestDashboardService:
    """Tests for DashboardService methods."""

    def test_get_portfolio_overview(
        self,
        dashboard_service: DashboardService,
        mock_account: Account,
    ) -> None:
        """Test retrieving portfolio overview."""
        overview = dashboard_service.get_portfolio_overview("test")

        assert overview.account_id == "test"
        assert overview.current_equity == mock_account.equity
        assert overview.open_positions_count == 1

    def test_get_open_positions(self, dashboard_service: DashboardService) -> None:
        """Test retrieving open positions only."""
        positions = dashboard_service.get_open_positions("test")

        assert len(positions) == 1
        assert positions[0].market == "EUR/USD"
        assert positions[0].status == "OPEN"

    def test_get_closed_positions(self, dashboard_service: DashboardService) -> None:
        """Test retrieving closed positions only."""
        positions = dashboard_service.get_closed_positions("test")

        assert len(positions) == 1
        assert positions[0].market == "GBP/USD"
        assert positions[0].status == "CLOSED"

    def test_get_all_positions(self, dashboard_service: DashboardService) -> None:
        """Test retrieving all positions."""
        positions = dashboard_service.get_all_positions("test")

        assert len(positions) == 2
        statuses = {p.status for p in positions}
        assert statuses == {"OPEN", "CLOSED"}

    def test_get_trade_history(self, dashboard_service: DashboardService) -> None:
        """Test retrieving trade history."""
        trades = dashboard_service.get_trade_history("test")

        assert len(trades) == 2
        # Most recent first
        assert trades[0].trade_id == "trade_002"
        assert trades[1].trade_id == "trade_001"

    def test_get_trade_history_with_limit(
        self,
        dashboard_service: DashboardService,
    ) -> None:
        """Test trade history with limit parameter."""
        trades = dashboard_service.get_trade_history("test", limit=1)

        assert len(trades) == 1
        assert trades[0].trade_id == "trade_002"

    def test_get_account_metrics(
        self,
        dashboard_service: DashboardService,
        mock_account: Account,
    ) -> None:
        """Test retrieving account metrics."""
        metrics = dashboard_service.get_account_metrics("test")

        assert metrics.account_id == "test"
        assert metrics.equity == mock_account.equity
        assert metrics.cash == 5000.0
        assert metrics.total_return == mock_account.equity - 10000.0


class TestTradeSnapshot:
    """Tests for TradeSnapshot generation."""

    def test_from_trade_record(self) -> None:
        """Test creating snapshot from trade record."""
        trade = TradeRecord(
            trade_id="trade_001",
            proposal_id="prop_001",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=100.0,
            entry_price=1.0850,
            simulated_value=108.5,
            status=TradeStatus.OPEN,
            mode=ExecutionMode.PAPER,
            strategy_name="Test Strategy",
            sources_cited=("test-source",),
            executed_at=datetime(2026, 6, 21, 10, 0, 0),
        )

        snapshot = TradeSnapshot.from_trade_record(trade)

        assert snapshot.trade_id == "trade_001"
        assert snapshot.direction == "LONG"
        assert snapshot.status == "OPEN"
        assert snapshot.mode == "PAPER"
