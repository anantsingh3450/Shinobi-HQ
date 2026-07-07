from __future__ import annotations

from pathlib import Path
from integrations.brokers.interfaces import BaseExecutionVenue
from integrations.brokers.secrets import SecretManager
from integrations.brokers.kite_connection import KiteConnectionManager
from integrations.brokers.kite_account import KiteAccountService
from integrations.brokers.models import (
    AccountBalance,
    ConnectionStatus,
    OrderRequest,
    OrderResponse,
    VenueCapabilities,
    VenuePosition,
    VenueHolding,
    ConnectionState,
    ExecutionMode,
    ExecutionContext,
)
from typing import Any


class KiteVenue(BaseExecutionVenue):
    """Zerodha Kite Connect broker venue adapter.

    Provides read-only access (balances, positions, holdings) while
    blocking any order execution via hard safety locks unless ExecutionMode.LIVE is active.
    """

    LIVE_TRADING_ENABLED = False  # Hard safety lock flag

    def __init__(
        self,
        venue_id: str = "kite_main",
        connection_manager: KiteConnectionManager | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        """Initialize KiteVenue.

        Args:
            venue_id: Unique registration identifier (e.g. 'kite_main').
            connection_manager: Optional injected manager for session handling (useful for tests/mocking).
            context: Optional ExecutionContext guiding execution limits and modes.
        """
        self._venue_id = venue_id
        
        if context is None:
            self._context = ExecutionContext(
                execution_mode=ExecutionMode.READ_ONLY,
                active_venue_id=venue_id,
                brain_id="primary_brain",
                authority_level="elder",
            )
        else:
            self._context = context

        if connection_manager is None:
            sm = SecretManager()
            self._connection_manager = KiteConnectionManager(sm)
        else:
            self._connection_manager = connection_manager

        self._account_service = KiteAccountService(self._connection_manager)

        # Capabilities declaration — write operations and margin trading disabled
        self._capabilities = VenueCapabilities(
            market_orders=False,
            limit_orders=False,
            stop_orders=False,
            websocket_streaming=False,
            historical_data=True,
            margin_trading=False,
            options_trading=False,
            futures_trading=False,
            fractional_shares=False
        )

    @property
    def venue_id(self) -> str:
        return self._venue_id

    @property
    def capabilities(self) -> VenueCapabilities:
        return self._capabilities

    def connect(self) -> ConnectionStatus:
        return self._connection_manager.connect()

    def disconnect(self) -> ConnectionStatus:
        return self._connection_manager.disconnect()

    def get_status(self) -> ConnectionStatus:
        return self._connection_manager.get_status()

    # ------------------------------------------------------------------
    # Broker-Level Hard Safety Locks
    # ------------------------------------------------------------------

    def place_order(self, request: OrderRequest) -> OrderResponse:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled.")
        raise NotImplementedError("Live order placement is not active in the current execution mode.")

    def cancel_order(self, venue_order_id: str) -> bool:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled.")
        raise NotImplementedError("Live order cancellation is not active in the current execution mode.")

    def modify_order(self, *args, **kwargs) -> Any:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled.")
        raise NotImplementedError("Live order modification is not active in the current execution mode.")

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled.")
        raise NotImplementedError("Live order status retrieval is not active in the current execution mode.")

    # ------------------------------------------------------------------
    # Read-Only Operations
    # ------------------------------------------------------------------

    def get_account_balance(self) -> AccountBalance:
        if self.get_status().state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")
        return self._account_service.get_account_balance(self._venue_id)

    def get_positions(self) -> list[VenuePosition]:
        if self.get_status().state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")
        return self._account_service.get_positions(self._venue_id)

    def get_holdings(self) -> list[VenueHolding]:
        if self.get_status().state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")
        return self._account_service.get_holdings(self._venue_id)
