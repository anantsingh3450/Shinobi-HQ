"""Portfolio and Account domain models.

Defines the structure for tracking open positions, account state, and PnL metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4
from shared.utils import utc_now

from bots.execution import charges as charge_schedule
from bots.execution.models import TradeDirection, TradeRecord, TradeStatus
from shared.instrument import parse as parse_symbol


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
    playbook_id: str | None = None
    volatility_regime: str | None = None
    failure_reason: str | None = None
    #: WHICH ARENA STRATEGY OPENED THIS POSITION.
    #:
    #: Added 2026-08-17. Until then, which strategy made a trade was never
    #: persisted anywhere: `trades.strategy_name` was the literal string
    #: "AutonomousExit" for all 101 rows (it records the exit MECHANISM),
    #: `trade_attributions` had zero rows ever, and `decision_journal` carried
    #: conviction and P&L but no strategy. Attribution existed only in the
    #: bot's in-memory tracking dict and in aggregate form in the portfolio
    #: JSON — where it is polluted across the pre/post-scoping eras.
    #:
    #: That made per-strategy performance impossible to reconstruct from the
    #: ledger, which blocks tiered autonomy: a loop that archives a strategy
    #: for measuring badly must be able to prove which trades were its.
    strategy_id: str | None = None

    #: WHAT THE BROKER TOOK ON THIS POSITION, both legs, in rupees.
    #:
    #: None means the position was accounted GROSS - everything closed before
    #: 2026-11-09, when `apply_trade` moved cash by the price difference and
    #: nothing else. A 0.0 would claim the trade was free, which is a
    #: different and false statement, so the two are kept apart.
    charges: float | None = None

    @property
    def net_pnl(self) -> float | None:
        """Realized P&L with this position's charges taken out.

        None when the position predates charge accounting: there is no net
        figure for it, and inventing one by subtracting zero would make the
        gross era look like a charged era that happened to be free.
        """
        if self.charges is None:
            return None
        return round(self.realized_pnl - self.charges, 6)

    def add_charges(self, amount: float) -> None:
        """Accrue one leg's charges. Starts the count rather than adding to
        None, so a position opened under charge accounting is never NULL."""
        self.charges = round((self.charges or 0.0) + float(amount), 6)

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
            "playbook_id": self.playbook_id,
            "volatility_regime": self.volatility_regime,
            "failure_reason": self.failure_reason,
            "strategy_id": self.strategy_id,
            "charges": self.charges,
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
            playbook_id=data.get("playbook_id"),
            volatility_regime=data.get("volatility_regime"),
            failure_reason=data.get("failure_reason"),
            strategy_id=data.get("strategy_id"),
            charges=data.get("charges"),
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
    currency: str = "INR"
    positions: dict[str, Position] = field(default_factory=dict)  # Keyed by position_id
    equity_history: list[EquitySnapshot] = field(default_factory=list)
    #: GROSS. The sum of price differences, unchanged since before charges
    #: were deducted, so the two eras remain comparable on this one figure.
    realized_pnl: float = 0.0

    @property
    def charges_paid(self) -> float:
        """What the broker has taken from this account, in rupees.

        DERIVED from the positions rather than stored. Cash is already net of
        it, so this is a reporting figure, and a reporting figure kept in its
        own column is a figure that can disagree with the rows it came from -
        which is how `max_portfolio_exposure_pct` came to be displayed
        everywhere and obeyed nowhere.

        Positions from before 2026-11-09 carry None and contribute nothing,
        which is correct: no charges were taken from this account for them.
        """
        return round(sum(p.charges for p in self.positions.values()
                         if p.charges is not None), 6)

    @property
    def equity(self) -> float:
        """Compute total account equity (cash + unrealized PnL of all open positions)."""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values() if p.status == TradeStatus.OPEN)
        return round(self.cash + unrealized, 6)

    def _leg_charges(self, trade: TradeRecord) -> float:
        """What the broker takes on this one executed order, in rupees.

        APPROVED BY THE COMMANDER 2026-11-09, after the measurement: across
        125 real closed positions charges came to 3.2x the entire gross
        profit and turned a profit factor of 1.03 into 0.94. Until that day
        this method did not exist and cash moved by the price difference
        alone, so every figure the system produced was gross.

        ONE ORDER, ONE BROKERAGE. The 20 rupees is per executed order, not
        per position, so an order that closes three positions pays it once -
        which is why this is computed here and then shared out, rather than
        charged inside the loop below.

        ONLY OPTIONS ARE CHARGED. A symbol that does not parse as an option
        contract is not on the schedule this models, and guessing a rate for
        it would be inventing a cost. Those fills stay gross and say so by
        leaving `charges` None.
        """
        instrument = parse_symbol(str(trade.market))
        if not instrument.parsed:
            return 0.0
        turnover = abs(float(trade.entry_price or 0.0)) * abs(
            float(trade.quantity or 0.0))
        if turnover <= 0:
            return 0.0
        # STT falls on the SELL side whether that sell opens or closes, so
        # the mapping is from the order's direction and nothing else. In
        # Hokage's bought-options universe SHORT is always the exit; if a
        # defined-risk spread ever sells to open, this is still right.
        side = "SELL" if trade.direction == TradeDirection.SHORT else "BUY"
        return charge_schedule.option_leg(
            turnover, instrument.root, side).total

    def apply_trade(self, trade: TradeRecord) -> None:
        """Apply a TradeRecord, matching opposite positions under FIFO order.

        Since 2026-11-09 the broker is paid here too: one order's charges come
        out of cash and are attributed to the positions that order touched,
        pro rata by quantity. Cash is therefore net; `realized_pnl` on a
        position stays the price difference, and `net_pnl` is the honest
        trade-level figure.
        """
        market = trade.market
        leg_cost = self._leg_charges(trade)
        touched: list[tuple[Position, float]] = []

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
                closed_qty = pos.quantity
                pos.close(trade.entry_price, trade.executed_at)
                self.realized_pnl += pos.realized_pnl
                self.cash = round(self.cash + pos.realized_pnl, 6)
                touched.append((pos, closed_qty))
                remaining_qty = round(remaining_qty - closed_qty, 6)
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
                    playbook_id=pos.playbook_id,
                    volatility_regime=pos.volatility_regime,
                    failure_reason=pos.failure_reason,
                    strategy_id=pos.strategy_id,
                    charges=pos.charges,
                )
                updated_pos.update_price(trade.entry_price)
                self.positions[pos.position_id] = updated_pos
                touched.append((updated_pos, remaining_qty))
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
                playbook_id=getattr(trade, "playbook_id", None),
                volatility_regime=getattr(trade, "volatility_regime", None),
                failure_reason=getattr(trade, "failure_reason", None),
                # The venue puts the OrderRequest's strategy_id on the trade as
                # strategy_name. Carried here so attribution survives into the
                # ledger rather than living only in the bot's memory.
                strategy_id=getattr(trade, "strategy_name", None),
            )
            new_pos.update_price(trade.entry_price)
            self.positions[trade.trade_id] = new_pos
            touched.append((new_pos, remaining_qty))

        # ------------------------------------------------- pay the broker
        # Cash moves by the WHOLE order's charges exactly once. The split
        # across positions is attribution only - it must not change the
        # total, so the last share takes the rounding remainder rather than
        # each share being rounded and the pennies going missing.
        if leg_cost > 0:
            self.cash = round(self.cash - leg_cost, 6)
            total_qty = sum(qty for _pos, qty in touched)
            if total_qty > 0:
                allocated = 0.0
                for index, (pos, qty) in enumerate(touched):
                    if index == len(touched) - 1:
                        share = round(leg_cost - allocated, 6)
                    else:
                        share = round(leg_cost * qty / total_qty, 6)
                        allocated = round(allocated + share, 6)
                    pos.add_charges(share)

    def to_dict(self) -> dict:
        """Serialize account to a JSON-compatible dictionary."""
        return {
            "account_id": self.account_id,
            "initial_balance": self.initial_balance,
            "cash": self.cash,
            "currency": self.currency,
            "realized_pnl": self.realized_pnl,
            "charges_paid": self.charges_paid,   # derived; read-only
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
            currency=data.get("currency", "INR"),
            realized_pnl=data.get("realized_pnl", 0.0),
            positions=positions,
            equity_history=equity_history,
        )


@dataclass(slots=True)
class Portfolio:
    """Aggregates accounts across different modes (e.g. PAPER, LIVE)."""

    portfolio_id: str = field(default_factory=lambda: str(uuid4()))
    accounts: dict[str, Account] = field(default_factory=dict)  # Keyed by ExecutionMode value
