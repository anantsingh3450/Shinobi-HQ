from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.execution.models import TradeRecord


@runtime_checkable
class TaxProvider(Protocol):
    """Adapter that converts executed trades into taxable events."""

    def to_tax_event(self, trade: TradeRecord) -> "TaxEvent":
        """Convert a trade record into a tax event."""
        ...


@runtime_checkable
class TaxLedger(Protocol):
    """Adapter that persists and queries tax events."""

    def record_event(self, event: "TaxEvent") -> None:
        """Persist a tax event for later reporting."""
        ...

    def load_events(self) -> tuple["TaxEvent", ...]:
        """Load all persisted tax events."""
        ...
