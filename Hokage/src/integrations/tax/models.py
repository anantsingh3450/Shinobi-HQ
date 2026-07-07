from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from bots.execution.models import TradeRecord
from shared.utils import utc_now


class TaxJurisdiction(StrEnum):
    """Tax jurisdiction for simulated trade accounting."""

    INDIA = "IN"
    UNITED_STATES = "US"
    GLOBAL = "GLOBAL"


class TaxComponentType(StrEnum):
    """Tax and fee components that can be modeled by future providers."""

    BROKERAGE = "BROKERAGE"
    GST = "GST"
    STT = "STT"
    STAMP_DUTY = "STAMP_DUTY"
    CAPITAL_GAINS = "CAPITAL_GAINS"
    CRYPTO_TAX = "CRYPTO_TAX"
    FNO_TAX = "FNO_TAX"
    EXCHANGE_FEES = "EXCHANGE_FEES"
    SEBI_TURNOVER = "SEBI_TURNOVER"
    TDS = "TDS"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class TaxComponent:
    """Single simulated tax or fee line item."""

    component_type: TaxComponentType
    amount: float
    currency: str = "USD"
    description: str = ""


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
    jurisdiction: TaxJurisdiction = TaxJurisdiction.GLOBAL
    currency: str = "USD"
    components: tuple[TaxComponent, ...] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=utc_now, init=False, repr=False, compare=False)

    @property
    def total_tax(self) -> float:
        """Total simulated tax and fees for this event."""
        return round(sum(component.amount for component in self.components), 6)

    @property
    def after_tax_value(self) -> float:
        """Trade notional after subtracting simulated tax components."""
        return round(self.simulated_value - self.total_tax, 6)

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
