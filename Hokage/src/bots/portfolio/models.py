"""Portfolio and Account domain models.

Defines the structure for tracking open positions, account state, and PnL metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from bots.execution.models import TradeDirection, TradeRecord, TradeStatus


def utc_now() -> datetime:
    """Return current UTC timezone-aware datetime."""
    return datetime.now(UTC)


@dataclass(slots=True)
class Position:
    """Tracks exposure, pricing, and realized/unrealized PnL of a simulated trade position.

    Attributes:
        position_id:    Unique identifier (usually matches entry trade_id).
        market:         Market symbol traded (e.g. "EUR/USD").
        direction:      LONG or SHORT.
        quantity:       Volume/units held.
        entry_price:    Weighted average entry price.
        current_price:  Last updated ticker price.
        unrealized_pnl: Computed paper gain/loss.
        realized_pnl:   Realized gain/loss upon closing.
        status:         OPEN or CLOSED.
        opened_at:      Time of position entry.
        closed_at:      Time of position exit.
    """

    position_id: str
    market: str
    direction: TradeDirection
    quantity: float
    entry_price: float
    current_price: float

    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    status: TradeStatus = TradeStatus.OPEN

    opened_at: datetime = field(default_factory=utc_now)
    closed_at: datetime | None = None

    def update_price(self, price: float) -> None:
        """Update current price and recalculate unrealized PnL."""
        self.current_price = price
        if self.status == TradeStatus.CLOSED:
            self.unrealized_pnl = 0.0
            return
        factor = 1.0 if self.direction == TradeDirection.LONG else -1.0
        self.unrealized_pnl = round(factor * (self.current_price - self.entry_price) * self.quantity, 6)

    def close(self, price: float, closed_at: datetime) -> None:
        """Close the position, recalculating and locking in realized PnL."""
        self.current_price = price
        factor = 1.0 if self.direction == TradeDirection.LONG else -1.0
        self.realized_pnl = round(factor * (self.current_price - self.entry_price) * self.quantity, 6)
        self.unrealized_pnl = 0.0
        self.status = TradeStatus.CLOSED
        self.closed_at = closed_at

    def to_dict(self) -> dict:
        """Serialize the position to a JSON-compatible dictionary."""
        return {
            "position_id": self.position_id,
            "market": self.market,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "status": self.status.value,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Position:
        """Deserialize a position from a dictionary."""
        closed_at = data["closed_at"]
        return cls(
            position_id=data["position_id"],
            market=data["market"],
            direction=TradeDirection(data["direction"]),
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            current_price=data["current_price"],
            unrealized_pnl=data["unrealized_pnl"],
            realized_pnl=data["realized_pnl"],
            status=TradeStatus(data["status"]),
            opened_at=datetime.fromisoformat(data["opened_at"]),
            closed_at=datetime.fromisoformat(closed_at) if closed_at else None,
        )


@dataclass(frozen=True, slots=True)
class EquitySnapshot:
    """A point-in-time snapshot of account valuation metrics."""

    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float

    def to_dict(self) -> dict:
        """Serialize snapshot to dict."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "equity": self.equity,
            "cash": self.cash,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EquitySnapshot:
        """Deserialize snapshot from dict."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            equity=data["equity"],
            cash=data["cash"],
            unrealized_pnl=data["unrealized_pnl"],
            realized_pnl=data["realized_pnl"],
        )


@dataclass(slots=True)
class Account:
    """Tracks balances, open positions, equity history, and executes trade adjustments.

    Supports multiple positions per market using unique position IDs.
    Opposing trades trigger First-In, First-Out (FIFO) netting.
    """

    account_id: str
    initial_balance: float
    cash: float
    currency: str = "USD"
    positions: dict[str, Position] = field(default_factory=dict)  # Keyed by position_id
    equity_history: list[EquitySnapshot] = field(default_factory=list)
    realized_pnl: float = 0.0

    @property
    def equity(self) -> float:
        """Compute total account equity (cash + unrealized PnL of all open positions)."""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values() if p.status == TradeStatus.OPEN)
        return round(self.cash + unrealized, 6)

    def apply_trade(self, trade: TradeRecord) -> None:
        """Apply a TradeRecord, matching opposite positions under FIFO order."""
        market = trade.market

        # Find all open positions in this market that have an opposite direction
        opposite_positions = [
            pos for pos in self.positions.values()
            if pos.market == market and pos.status == TradeStatus.OPEN and pos.direction != trade.direction
        ]

        # Sort opposite positions by opened_at (FIFO)
        opposite_positions.sort(key=lambda p: p.opened_at)

        remaining_qty = trade.quantity

        for pos in opposite_positions:
            if remaining_qty <= 0:
                break

            if remaining_qty >= pos.quantity:
                # Fully close this position
                pos.close(trade.entry_price, trade.executed_at)
                self.realized_pnl += pos.realized_pnl
                self.cash = round(self.cash + pos.realized_pnl, 6)
                remaining_qty = round(remaining_qty - pos.quantity, 6)
            else:
                # Partially close this position
                factor = 1.0 if pos.direction == TradeDirection.LONG else -1.0
                realized = round(factor * (trade.entry_price - pos.entry_price) * remaining_qty, 6)
                self.realized_pnl += realized
                self.cash = round(self.cash + realized, 6)

                new_qty = round(pos.quantity - remaining_qty, 6)
                updated_pos = Position(
                    position_id=pos.position_id,
                    market=pos.market,
                    direction=pos.direction,
                    quantity=new_qty,
                    entry_price=pos.entry_price,
                    current_price=trade.entry_price,
                    opened_at=pos.opened_at,
                )
                updated_pos.update_price(trade.entry_price)
                self.positions[pos.position_id] = updated_pos
                remaining_qty = 0.0

        # If there is remaining quantity, open a new position
        if remaining_qty > 0:
            new_pos = Position(
                position_id=trade.trade_id,
                market=trade.market,
                direction=trade.direction,
                quantity=remaining_qty,
                entry_price=trade.entry_price,
                current_price=trade.entry_price,
                opened_at=trade.executed_at,
            )
            new_pos.update_price(trade.entry_price)
            self.positions[trade.trade_id] = new_pos

    def to_dict(self) -> dict:
        """Serialize account to a JSON-compatible dictionary."""
        return {
            "account_id": self.account_id,
            "initial_balance": self.initial_balance,
            "cash": self.cash,
            "currency": self.currency,
            "realized_pnl": self.realized_pnl,
            "positions": {pid: pos.to_dict() for pid, pos in self.positions.items()},
            "equity_history": [snap.to_dict() for snap in self.equity_history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Account:
        """Deserialize an account from a dictionary."""
        positions = {
            pid: Position.from_dict(pdata)
            for pid, pdata in data.get("positions", {}).items()
        }
        equity_history = [
            EquitySnapshot.from_dict(sdata)
            for sdata in data.get("equity_history", [])
        ]
        return cls(
            account_id=data["account_id"],
            initial_balance=data["initial_balance"],
            cash=data["cash"],
            currency=data.get("currency", "USD"),
            realized_pnl=data.get("realized_pnl", 0.0),
            positions=positions,
            equity_history=equity_history,
        )


@dataclass(slots=True)
class Portfolio:
    """Aggregates accounts across different modes (e.g. PAPER, LIVE)."""

    portfolio_id: str = field(default_factory=lambda: str(uuid4()))
    accounts: dict[str, Account] = field(default_factory=dict)  # Keyed by ExecutionMode value
