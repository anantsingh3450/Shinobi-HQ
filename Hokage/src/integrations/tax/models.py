from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from bots.execution.models import TradeRecord


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TaxEvent:
    """Represents a taxable event derived from an executed trade."""

    trade_id: str
    market: str
    direction: str
    quantity: float
    entry_price: float
    simulated_value: float
    executed_at: datetime
    generated_at: datetime = field(default_factory=utc_now, init=False, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TaxLedgerEntry:
    """A record of a tax event stored in the tax ledger."""

    event: TaxEvent
    recorded_at: datetime = dataclass(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recorded_at", utc_now())

    @classmethod
    def from_trade(cls, trade: TradeRecord) -> TaxEvent:
        return cls(
            trade_id=trade.trade_id,
            market=trade.market,
            direction=trade.direction.value,
            quantity=trade.quantity,
            entry_price=trade.entry_price,
            simulated_value=trade.simulated_value,
            executed_at=trade.executed_at,
        )


@dataclass(frozen=True, slots=True)
class TaxLedgerEntry:
    """A record of a tax event stored in the tax ledger."""

    event: TaxEvent
    recorded_at: datetime = field(default_factory=utc_now, init=False, repr=False, compare=False)
