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
class BaseVenue(Protocol):
    """Unified abstract base class representing any custodian, exchange, dealer, or smart contract venue."""

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
