"""Domain models for the Execution Bot.

These dataclasses and enums define the core vocabulary of the paper trading
pipeline. They are pure data structures with no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4


def utc_now() -> datetime:
    """Return the current UTC timestamp with timezone awareness."""
    return datetime.now(UTC)


class TradeDirection(Enum):
    """Direction of a simulated trade."""

    LONG = "LONG"
    SHORT = "SHORT"


class ExecutionMode(Enum):
    """Execution environment.

    LIVE mode is defined here for future use but is never activated by the
    current pipeline. Hokage enforces a three-gate check before any LIVE
    promotion is permitted.
    """

    PAPER = "PAPER"
    LIVE = "LIVE"  # Disabled — do not wire until Hokage live gates are built


class TradeStatus(Enum):
    """Lifecycle state of a trade.

    OPEN  — position has been entered; not yet closed.
    CLOSED — position has been exited (future: PnL realised).
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """A single simulated trade produced by PaperEngine.

    Carries complete provenance from the originating StrategyProposal all the
    way back to the ResearchSource that generated the intelligence.

    Attributes:
        trade_id:        Unique identifier for this trade.
        proposal_id:     Links back to ``StrategyProposal.proposal_id``.
        market:          Instrument traded (e.g. ``"EUR/USD"``).
        direction:       LONG or SHORT.
        quantity:        Number of units simulated.
        entry_price:     Simulated fill price from the PriceSource.
        simulated_value: ``quantity × entry_price`` — notional exposure.
        mode:            Always PAPER in this phase.
        status:          OPEN on creation; CLOSED when the position is exited.
        strategy_name:   Name from the originating StrategyProposal.
        sources_cited:   Provenance chain from ResearchSource IDs.
        executed_at:     UTC timestamp of simulated execution.
    """

    proposal_id: str
    market: str
    direction: TradeDirection
    quantity: float
    entry_price: float
    simulated_value: float
    strategy_name: str
    sources_cited: tuple[str, ...]

    mode: ExecutionMode = ExecutionMode.PAPER
    status: TradeStatus = TradeStatus.OPEN

    executed_at: datetime = field(default_factory=utc_now)
    trade_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty.")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive.")
        if self.entry_price <= 0:
            raise ValueError("entry_price must be positive.")
        if self.mode is ExecutionMode.LIVE:
            raise ValueError(
                "ExecutionMode.LIVE is disabled. Only PAPER mode is permitted."
            )

    def to_dict(self) -> dict:
        """Serialize the trade record to a JSON-compatible dictionary."""
        return {
            "trade_id": self.trade_id,
            "proposal_id": self.proposal_id,
            "market": self.market,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "simulated_value": self.simulated_value,
            "mode": self.mode.value,
            "status": self.status.value,
            "strategy_name": self.strategy_name,
            "sources_cited": list(self.sources_cited),
            "executed_at": self.executed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TradeRecord:
        """Deserialize a trade record from a dictionary."""
        from datetime import datetime

        return cls(
            trade_id=data["trade_id"],
            proposal_id=data["proposal_id"],
            market=data["market"],
            direction=TradeDirection(data["direction"]),
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            simulated_value=data["simulated_value"],
            mode=ExecutionMode(data["mode"]),
            status=TradeStatus(data["status"]),
            strategy_name=data["strategy_name"],
            sources_cited=tuple(data["sources_cited"]),
            executed_at=datetime.fromisoformat(data["executed_at"]),
        )
