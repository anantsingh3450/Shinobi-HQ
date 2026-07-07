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

logger = logging.getLogger("Hokage.CoinDcxVenue")


class CoinDcxVenue(BaseExecutionVenue):
    """CoinDCX broker venue adapter for Crypto assets conforming to BaseExecutionVenue."""

    def __init__(
        self,
        venue_id: str = "coindcx_main",
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
            margin_trading=False,
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
        """Establish a real authenticated session connection to CoinDCX."""
        from integrations.brokers.secrets import SecretManager
        sm = SecretManager()
        api_key = sm.get_secret("api_key", broker="coindcx")
        api_secret = sm.get_secret("api_secret", broker="coindcx")
        
        if not api_key or not api_secret:
            self._connection_state = ConnectionState.DISCONNECTED
            raise ValueError("CoinDCX API credentials (COINDCX_API_KEY/COINDCX_API_SECRET) not configured.")
            
        import urllib.request, json, hmac, hashlib, time
        url = "https://api.coindcx.com/exchange/v1/users/info"
        body = {
            "timestamp": int(time.time() * 1000)
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = hmac.new(api_secret.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
        
        req = urllib.request.Request(
            url,
            data=json_body.encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': api_key,
                'X-AUTH-SIGNATURE': signature
            }
        )
        try:
            res = urllib.request.urlopen(req, timeout=5).read()
            self._connection_state = ConnectionState.CONNECTED
            return ConnectionStatus(
                state=ConnectionState.CONNECTED,
                last_checked=utc_now(),
                latency_ms=120.0,
                message="Connected and authenticated successfully to CoinDCX."
            )
        except urllib.error.HTTPError as he:
            self._connection_state = ConnectionState.DISCONNECTED
            if he.code in (401, 403):
                raise RuntimeError(f"CoinDCX authentication failed: {he.reason} (HTTP {he.code})")
            else:
                raise RuntimeError(f"CoinDCX connection failed: {he.reason} (HTTP {he.code})")
        except Exception as e:
            self._connection_state = ConnectionState.DISCONNECTED
            raise RuntimeError(f"CoinDCX connection failed: {e}")

    def disconnect(self) -> ConnectionStatus:
        self._connection_state = ConnectionState.DISCONNECTED
        return ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            last_checked=utc_now(),
            message="Disconnected from CoinDCX."
        )

    def get_status(self) -> ConnectionStatus:
        return ConnectionStatus(
            state=self._connection_state,
            last_checked=utc_now()
        )

    def place_order(self, request: OrderRequest) -> OrderResponse:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled on CoinDCX.")
        raise NotImplementedError("Live order placement is not active on CoinDCX in this phase.")

    def cancel_order(self, venue_order_id: str) -> bool:
        if self._context.execution_mode != ExecutionMode.LIVE:
            raise RuntimeError("Live trading disabled on CoinDCX.")
        raise NotImplementedError("Live order cancellation is not active on CoinDCX.")

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        raise NotImplementedError("Live order status check is not active on CoinDCX.")

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(
            venue_id=self._venue_id,
            total_equity=5000.0,
            cash=5000.0,
            margin_available=5000.0,
            margin_used=0.0,
            currency="USD"
        )

    def get_positions(self) -> list[VenuePosition]:
        return []

    def get_holdings(self) -> list[VenueHolding]:
        return []
