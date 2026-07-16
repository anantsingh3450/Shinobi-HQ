"""Dashboard data models — expose portfolio state for frontend consumption.

These models transform Account and TradeRecord data into frontend-friendly
JSON structures suitable for REST API responses.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from bots.execution.models import TradeRecord, TradeStatus
from bots.portfolio.models import Account, Position


@dataclass
class PositionSnapshot:
    """Represents a single open or closed position for dashboard display.
    
    Attributes:
        position_id: Unique identifier for this position.
        market: Trading pair (e.g., 'EUR/USD').
        direction: 'LONG' or 'SHORT'.
        quantity: Number of units.
        entry_price: Price at which position was opened.
        current_price: Current market price (if open).
        unrealized_pnl: Profit/loss if position were closed now (if open).
        realized_pnl: Profit/loss if position is closed.
        status: 'OPEN' or 'CLOSED'.
    """
    position_id: str
    market: str
    direction: str
    quantity: float
    entry_price: float
    current_price: float | None
    unrealized_pnl: float | None
    realized_pnl: float
    status: str
    closed_at: str | None = None
    opened_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_position(position: Position) -> PositionSnapshot:
        """Create snapshot from a Position domain model."""
        closed_at = None
        if hasattr(position, "closed_at") and position.closed_at:
            closed_at = position.closed_at.isoformat() if hasattr(position.closed_at, "isoformat") else str(position.closed_at)
        opened_at = None
        if hasattr(position, "opened_at") and position.opened_at:
            opened_at = position.opened_at.isoformat() if hasattr(position.opened_at, "isoformat") else str(position.opened_at)
        return PositionSnapshot(
            position_id=position.position_id,
            market=position.market,
            direction=position.direction.name,
            quantity=position.quantity,
            entry_price=position.entry_price,
            current_price=position.current_price,
            unrealized_pnl=position.unrealized_pnl,
            realized_pnl=position.realized_pnl,
            status=position.status.name,
            closed_at=closed_at,
            opened_at=opened_at,
        )


@dataclass
class PortfolioOverview:
    """High-level portfolio summary for dashboard header.
    
    Attributes:
        account_id: Account identifier.
        initial_balance: Starting capital.
        current_equity: Cash + unrealized PnL.
        cash: Available cash.
        total_realized_pnl: All closed position profits/losses.
        total_unrealized_pnl: All open position profits/losses.
        open_positions_count: Number of currently open positions.
        total_trades_count: All trades ever executed.
        return_percentage: Total return as percentage.
        last_updated: ISO timestamp of last account update.
    """
    account_id: str
    initial_balance: float
    current_equity: float
    cash: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    open_positions_count: int
    total_trades_count: int
    return_percentage: float
    last_updated: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_account(account: Account) -> PortfolioOverview:
        """Create overview snapshot from an Account domain model."""
        total_unrealized = sum(
            pos.unrealized_pnl or 0.0
            for pos in account.positions.values()
            if pos.status == TradeStatus.OPEN
        )
        open_count = sum(
            1
            for pos in account.positions.values()
            if pos.status == TradeStatus.OPEN
        )
        # Total positions (open + closed) as proxy for total trades
        total_trades = len(account.positions)
        return_pct = (
            ((account.equity - account.initial_balance) / account.initial_balance * 100)
            if account.initial_balance != 0
            else 0.0
        )

        return PortfolioOverview(
            account_id=account.account_id,
            initial_balance=account.initial_balance,
            current_equity=account.equity,
            cash=account.cash,
            total_realized_pnl=account.realized_pnl,
            total_unrealized_pnl=total_unrealized,
            open_positions_count=open_count,
            total_trades_count=total_trades,
            return_percentage=return_pct,
            last_updated=datetime.now().isoformat(),
        )


@dataclass
class TradeSnapshot:
    """Represents a single trade for dashboard history view.
    
    Attributes:
        trade_id: Unique trade identifier.
        proposal_id: Strategy proposal that generated this trade.
        market: Trading pair.
        direction: 'LONG' or 'SHORT'.
        quantity: Units traded.
        entry_price: Execution price.
        status: 'OPEN' or 'CLOSED'.
        mode: 'PAPER' or 'LIVE'.
        strategy_name: Name of strategy that generated trade.
        executed_at: ISO timestamp of execution.
    """
    trade_id: str
    proposal_id: str
    market: str
    direction: str
    quantity: float
    entry_price: float
    status: str
    mode: str
    strategy_name: str
    executed_at: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_trade_record(trade: TradeRecord) -> TradeSnapshot:
        """Create snapshot from a TradeRecord domain model."""
        return TradeSnapshot(
            trade_id=trade.trade_id,
            proposal_id=trade.proposal_id,
            market=trade.market,
            direction=trade.direction.name,
            quantity=trade.quantity,
            entry_price=trade.entry_price,
            status=trade.status.name,
            mode=trade.mode.name,
            strategy_name=trade.strategy_name,
            executed_at=trade.executed_at.isoformat(),
        )


@dataclass
class AccountMetrics:
    """Detailed metrics for account performance dashboard.
    
    Attributes:
        account_id: Account identifier.
        equity: Current total equity.
        cash: Available cash.
        margin_used: Capital tied up in open positions.
        margin_available: Available margin for new trades.
        total_return: Absolute return (currency).
        return_percentage: Return as percentage.
        sharpe_ratio: Risk-adjusted return metric (if calculable).
        win_rate: Percentage of winning trades.
        profit_factor: Gross profit / gross loss.
        max_drawdown: Largest peak-to-trough decline.
    """
    account_id: str
    equity: float
    cash: float
    margin_used: float
    margin_available: float
    total_return: float
    return_percentage: float
    sharpe_ratio: float | None
    win_rate: float | None
    profit_factor: float | None
    max_drawdown: float | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_account(account: Account) -> AccountMetrics:
        """Create metrics from an Account domain model.
        
        Note: Some metrics (sharpe_ratio, win_rate, profit_factor, max_drawdown)
        require historical data. Currently set to None for Phase 2.
        """
        margin_used = sum(
            (pos.quantity * pos.entry_price)
            for pos in account.positions.values()
            if pos.status == TradeStatus.OPEN
        )
        total_return = account.equity - account.initial_balance
        return_pct = (
            (total_return / account.initial_balance * 100)
            if account.initial_balance != 0
            else 0.0
        )

        closed = [p for p in account.positions.values() if p.status == TradeStatus.CLOSED]
        win_rate = None
        profit_factor = None
        max_dd = None
        if closed:
            wins = sum(1 for p in closed if p.realized_pnl > 0)
            win_rate = (wins / len(closed)) * 100.0
            gross_profit = sum(p.realized_pnl for p in closed if p.realized_pnl > 0)
            gross_loss = abs(sum(p.realized_pnl for p in closed if p.realized_pnl < 0))
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit
            if account.initial_balance > 0:
                max_dd = (abs(total_return) / account.initial_balance * 100.0) if total_return < 0 else 0.0

        return AccountMetrics(
            account_id=account.account_id,
            equity=account.equity,
            cash=account.cash,
            margin_used=margin_used,
            margin_available=account.cash - margin_used,
            total_return=total_return,
            return_percentage=return_pct,
            sharpe_ratio=None,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
        )
