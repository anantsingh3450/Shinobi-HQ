from __future__ import annotations

import logging
from typing import Any

from integrations.brokers.interfaces import BaseExecutionVenue
from integrations.brokers.models import (
    AccountBalance,
    ConnectionState,
    ConnectionStatus,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    VenueCapabilities,
    VenuePosition,
    VenueHolding,
    utc_now,
    ExecutionContext,
    ExecutionMode,
)
from integrations.data.models import Instrument, AssetClass, Exchange

logger = logging.getLogger("Hokage.InstitutionalVenue")


class InstitutionalVenue(BaseExecutionVenue):
    """Abstract Institutional broker venue adapter for Forex testing conforming to BaseExecutionVenue."""

    def __init__(
        self,
        venue_id: str = "oanda_main",
        context: ExecutionContext | None = None,
    ) -> None:
        self._venue_id = venue_id
        self._connection_state = ConnectionState.DISCONNECTED
        self._context = context or ExecutionContext(
            execution_mode=ExecutionMode.READ_ONLY,
            active_venue_id=venue_id,
            brain_id="primary_brain",
            authority_level="elder",
        )

        self._capabilities = VenueCapabilities(
            market_orders=True,
            limit_orders=True,
            stop_orders=True,
            websocket_streaming=True,
            historical_data=True,
            margin_trading=True,
            options_trading=False,
            futures_trading=False,
            fractional_shares=True,
        )

    @property
    def venue_id(self) -> str:
        return self._venue_id

    @property
    def capabilities(self) -> VenueCapabilities:
        return self._capabilities

    def connect(self) -> ConnectionStatus:
        self._connection_state = ConnectionState.CONNECTED
        return ConnectionStatus(
            state=ConnectionState.CONNECTED,
            last_checked=utc_now(),
            latency_ms=5.0,
            message="Connected to institutional Forex testing feed."
        )

    def disconnect(self) -> ConnectionStatus:
        self._connection_state = ConnectionState.DISCONNECTED
        return ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            last_checked=utc_now(),
            message="Disconnected from institutional Forex venue."
        )

    def get_status(self) -> ConnectionStatus:
        return ConnectionStatus(
            state=self._connection_state,
            last_checked=utc_now()
        )

    def place_order(self, request: OrderRequest) -> OrderResponse:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled on Institutional Venue.")
        raise NotImplementedError("Live order placement is not active on Institutional Venue in this phase.")

    def cancel_order(self, venue_order_id: str) -> bool:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled on Institutional Venue.")
        raise NotImplementedError("Live order cancellation is not active on Institutional Venue.")

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        raise NotImplementedError("Live order status check is not active on Institutional Venue.")

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(
            venue_id=self._venue_id,
            total_equity=1000000.0,
            cash=1000000.0,
            margin_available=1000000.0,
            margin_used=0.0,
            currency="USD"
        )

    def get_positions(self) -> list[VenuePosition]:
        return []

    def get_holdings(self) -> list[VenueHolding]:
        return []
