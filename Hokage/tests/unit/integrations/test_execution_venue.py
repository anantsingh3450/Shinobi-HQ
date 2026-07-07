from __future__ import annotations

import pytest
from datetime import datetime, UTC

from integrations.data.models import Instrument, AssetClass, Exchange
from integrations.brokers.models import (
    VenueCategory,
    OrderSide,
    OrderType,
    OrderStatus,
    ConnectionState,
    VenueCapabilities,
    ConnectionStatus,
    AccountProfile,
    OrderRequest,
    OrderResponse,
    AccountBalance,
    VenuePosition,
    VenueHolding,
)
from integrations.brokers.interfaces import BaseExecutionVenue, ExecutionVenueRegistry


# Dummy implementation of BaseExecutionVenue for testing purposes
class DummyExecutionVenue:
    def __init__(self, venue_id: str) -> None:
        self._venue_id = venue_id
        self._capabilities = VenueCapabilities(
            market_orders=True,
            limit_orders=True,
            stop_orders=False,
            websocket_streaming=True,
            historical_data=True,
            margin_trading=False,
            options_trading=False,
            futures_trading=False,
            fractional_shares=True
        )

    @property
    def venue_id(self) -> str:
        return self._venue_id

    @property
    def capabilities(self) -> VenueCapabilities:
        return self._capabilities

    def connect(self) -> ConnectionStatus:
        return ConnectionStatus(state=ConnectionState.CONNECTED, last_checked=datetime.now(UTC))

    def disconnect(self) -> ConnectionStatus:
        return ConnectionStatus(state=ConnectionState.DISCONNECTED, last_checked=datetime.now(UTC))

    def place_order(self, request: OrderRequest) -> OrderResponse:
        return OrderResponse(
            venue_order_id="order-123",
            venue_id=self._venue_id,
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.FILLED,
            quantity=request.quantity,
            filled_quantity=request.quantity,
            average_price=request.price if request.price else 100.0
        )

    def cancel_order(self, venue_order_id: str) -> bool:
        return True

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
        return OrderResponse(
            venue_order_id=venue_order_id,
            venue_id=self._venue_id,
            instrument=inst,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=10.0,
            filled_quantity=10.0,
            average_price=100.0
        )

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(
            venue_id=self._venue_id,
            total_equity=10000.0,
            cash=8000.0,
            margin_available=5000.0,
            margin_used=3000.0
        )

    def get_positions(self) -> list[VenuePosition]:
        inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
        return [
            VenuePosition(
                instrument=inst,
                side=OrderSide.BUY,
                quantity=10.0,
                average_price=100.0,
                current_price=105.0,
                unrealized_pnl=50.0,
                venue_id=self._venue_id
            )
        ]

    def get_holdings(self) -> list[VenueHolding]:
        return []

    def get_status(self) -> ConnectionStatus:
        return ConnectionStatus(state=ConnectionState.CONNECTED, last_checked=datetime.now(UTC))


def test_enums_defined():
    assert VenueCategory.BROKER == "broker"
    assert OrderSide.BUY == "BUY"
    assert OrderType.LIMIT == "LIMIT"
    assert OrderStatus.FILLED == "FILLED"
    assert ConnectionState.CONNECTED == "CONNECTED"


def test_order_request_validation():
    inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    
    # Valid MARKET order
    req = OrderRequest(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET
    )
    assert req.quantity == 10.0
    assert req.price is None
    
    # Valid LIMIT order
    req_limit = OrderRequest(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.LIMIT,
        price=100.0
    )
    assert req_limit.price == 100.0

    # Test strategy_id, execution_reason, created_by audit trail fields
    req_audit = OrderRequest(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        strategy_id="strat-001",
        execution_reason="momentum cross",
        created_by="risk_bot"
    )
    assert req_audit.strategy_id == "strat-001"
    assert req_audit.execution_reason == "momentum cross"
    assert req_audit.created_by == "risk_bot"

    # Invalid quantity
    with pytest.raises(ValueError, match="order quantity must be positive"):
        OrderRequest(
            instrument=inst,
            side=OrderSide.BUY,
            quantity=0.0,
            order_type=OrderType.MARKET
        )

    # Invalid limit price
    with pytest.raises(ValueError, match="price must be positive for limit/stop orders"):
        OrderRequest(
            instrument=inst,
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.LIMIT,
            price=0.0
        )

    # Invalid trigger price for stop market order
    with pytest.raises(ValueError, match="trigger_price must be positive for stop orders"):
        OrderRequest(
            instrument=inst,
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.STOP_MARKET
        )


def test_account_profile_creation():
    prof = AccountProfile(
        account_id="acc-123",
        venue_id="zerodha_main",
        venue_category=VenueCategory.BROKER,
        username="user1",
        permissions=("trade", "read")
    )
    assert prof.account_id == "acc-123"
    assert prof.venue_category == VenueCategory.BROKER
    assert "trade" in prof.permissions
    assert prof.is_active is True


def test_venue_conforms_to_protocol():
    venue = DummyExecutionVenue("zerodha_retail")
    assert isinstance(venue, BaseExecutionVenue)


def test_execution_venue_registry():
    registry = ExecutionVenueRegistry()
    venue1 = DummyExecutionVenue("zerodha_retail")
    venue2 = DummyExecutionVenue("coindcx_retail")

    # Registration
    registry.register_venue(venue1)
    registry.register_venue(venue2)
    assert len(registry.list_venues()) == 2
    assert "zerodha_retail" in registry.list_venues()
    assert "coindcx_retail" in registry.list_venues()

    # Get venue
    assert registry.get_venue("zerodha_retail") is venue1
    
    # Duplicate registration error
    with pytest.raises(ValueError, match="already registered"):
        registry.register_venue(venue1)

    # Missing venue error
    with pytest.raises(KeyError, match="No execution venue registered"):
        registry.get_venue("missing_venue")

    # Unregister
    registry.unregister_venue("zerodha_retail")
    assert len(registry.list_venues()) == 1
    with pytest.raises(KeyError):
        registry.get_venue("zerodha_retail")


def test_venue_category_uniqueness():
    # Verify no duplicate enum member names (case-insensitive)
    names = [member.name.upper() for member in VenueCategory]
    assert len(names) == len(set(names)), f"Duplicate enum keys found: {names}"

    # Verify no duplicate enum values (case-insensitive)
    values = [member.value.upper() for member in VenueCategory]
    assert len(values) == len(set(values)), f"Duplicate enum values found: {values}"
