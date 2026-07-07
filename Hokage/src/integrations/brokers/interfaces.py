from __future__ import annotations

from typing import Protocol, runtime_checkable
from integrations.brokers.models import (
    OrderRequest,
    OrderResponse,
    AccountBalance,
    VenuePosition,
    VenueHolding,
    VenueCapabilities,
    ConnectionStatus,
)


@runtime_checkable
class BaseExecutionVenue(Protocol):
    """Unified port representing any custodian, exchange, dealer, or smart contract venue."""

    @property
    def venue_id(self) -> str:
        """Unique registration identifier (e.g., 'zerodha_main', 'binance_retail')."""
        ...

    @property
    def capabilities(self) -> VenueCapabilities:
        """The specific execution features supported by this venue."""
        ...

    def connect(self) -> ConnectionStatus:
        """Establish session connection and return status."""
        ...

    def disconnect(self) -> ConnectionStatus:
        """Cleanly close session connection."""
        ...

    def place_order(self, request: OrderRequest) -> OrderResponse:
        """Route order request to the venue."""
        ...

    def cancel_order(self, venue_order_id: str) -> bool:
        """Request order cancellation on the venue."""
        ...

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        """Retrieve latest details for a specific order."""
        ...

    def get_account_balance(self) -> AccountBalance:
        """Query account capital and margins."""
        ...

    def get_positions(self) -> list[VenuePosition]:
        """Query currently active open positions."""
        ...

    def get_holdings(self) -> list[VenueHolding]:
        """Query currently active holdings."""
        ...

    def get_status(self) -> ConnectionStatus:
        """Perform diagnostics checks and return current connection state."""
        ...


class ExecutionVenueRegistry:
    """Thread-safe registry managing active execution venue instances."""

    def __init__(self) -> None:
        self._venues: dict[str, BaseExecutionVenue] = {}

    def register_venue(self, venue: BaseExecutionVenue) -> None:
        """Add an execution venue instance under its venue_id."""
        if venue.venue_id in self._venues:
            raise ValueError(f"Venue with id '{venue.venue_id}' already registered.")
        self._venues[venue.venue_id] = venue

    def get_venue(self, venue_id: str) -> BaseExecutionVenue:
        """Retrieve a specific execution venue instance."""
        if venue_id not in self._venues:
            raise KeyError(f"No execution venue registered with id '{venue_id}'.")
        return self._venues[venue_id]

    def list_venues(self) -> list[str]:
        """List all active registered venue IDs."""
        return list(self._venues.keys())

    def unregister_venue(self, venue_id: str) -> None:
        """Remove a venue from the registry."""
        if venue_id in self._venues:
            del self._venues[venue_id]
