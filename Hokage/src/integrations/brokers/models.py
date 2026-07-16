from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from shared.utils import utc_now
from enum import StrEnum
from typing import Any
from integrations.data.models import Instrument


@dataclass(frozen=True, slots=True)
class BrokerCapabilityProfile:
    """Declared capabilities of a registered broker, loaded from broker_registry.json.

    Used to validate that a requested operation (order type, product type,
    live execution, etc.) is supported before routing to the broker.
    """

    broker_id: str
    supported_exchanges: tuple[str, ...]
    market_orders: bool
    limit_orders: bool
    stop_orders: bool
    stop_market_orders: bool
    margin_trading: bool
    product_types: tuple[str, ...]
    options_trading: bool
    futures_trading: bool
    fractional_shares: bool
    websocket_streaming: bool
    historical_data: bool
    paper_execution_support: bool
    live_execution_support: bool
    paper_venue_id: str
    live_venue_id: str

    @classmethod
    def from_dict(cls, broker_id: str, data: dict[str, Any]) -> "BrokerCapabilityProfile":
        """Construct a BrokerCapabilityProfile from a raw config dictionary."""
        return cls(
            broker_id=broker_id,
            supported_exchanges=tuple(data.get("supported_exchanges", [])),
            market_orders=bool(data.get("market_orders", True)),
            limit_orders=bool(data.get("limit_orders", True)),
            stop_orders=bool(data.get("stop_orders", True)),
            stop_market_orders=bool(data.get("stop_market_orders", True)),
            margin_trading=bool(data.get("margin_trading", False)),
            product_types=tuple(data.get("product_types", [])),
            options_trading=bool(data.get("options_trading", False)),
            futures_trading=bool(data.get("futures_trading", False)),
            fractional_shares=bool(data.get("fractional_shares", False)),
            websocket_streaming=bool(data.get("websocket_streaming", False)),
            historical_data=bool(data.get("historical_data", False)),
            paper_execution_support=bool(data.get("paper_execution_support", True)),
            live_execution_support=bool(data.get("live_execution_support", False)),
            paper_venue_id=str(data.get("paper_venue_id", f"paper_{broker_id}")),
            live_venue_id=str(data.get("live_venue_id", f"{broker_id}_main")),
        )

    def supports_order_type(self, order_type: str) -> bool:
        """Check whether this broker supports a given order type string."""
        order_type_upper = order_type.upper()
        checks = {
            "MARKET": self.market_orders,
            "LIMIT": self.limit_orders,
            "STOP": self.stop_orders,
            "STOP_MARKET": self.stop_market_orders,
        }
        return checks.get(order_type_upper, False)

    def supports_exchange(self, exchange: str) -> bool:
        """Check whether this broker supports a given exchange name."""
        return exchange.upper() in (e.upper() for e in self.supported_exchanges)


class CapabilityViolation(Exception):
    """Raised when a requested operation is not supported by the resolved broker."""



class VenueCategory(StrEnum):
    """Category of the execution venue."""

    # Legacy values (for backward compatibility)
    EXCHANGE = "exchange"
    DEALER = "dealer"
    LIQUIDITY_PROVIDER = "liquidity_provider"
    SANDBOX = "sandbox"

    # Expanded categories
    PAPER = "PAPER"
    BROKER = "broker"  # Keep string as "broker" for backward compatibility
    CRYPTO_EXCHANGE = "CRYPTO_EXCHANGE"
    FOREX = "FOREX"
    DERIVATIVES = "DERIVATIVES"
    SIMULATION = "SIMULATION"
    SMART_CONTRACT = "SMART_CONTRACT"


class OrderSide(StrEnum):
    """Direction of the order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Supported order execution types."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"


class OrderStatus(StrEnum):
    """Lifecycle state of an execution venue order."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ConnectionState(StrEnum):
    """Connection state of the venue integration."""

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    MAINTENANCE = "MAINTENANCE"


class ExecutionMode(StrEnum):
    """Modes under which orders can be processed or blocked."""

    READ_ONLY = "READ_ONLY"
    PAPER = "PAPER"
    LIVE = "LIVE"
    HYBRID = "HYBRID"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Runtime context guiding execution routing, modes, and authority validations."""

    execution_mode: ExecutionMode
    active_venue_id: str
    brain_id: str
    authority_level: str



@dataclass(frozen=True, slots=True)
class VenueCapabilities:
    """Capabilities supported by the execution venue."""

    market_orders: bool
    limit_orders: bool
    stop_orders: bool
    websocket_streaming: bool
    historical_data: bool
    margin_trading: bool
    options_trading: bool
    futures_trading: bool
    fractional_shares: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    """Current connection state and latency."""

    state: ConnectionState
    last_checked: datetime
    latency_ms: float | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class AccountProfile:
    """Profile info and credentials configuration for a venue account."""

    account_id: str
    venue_id: str
    venue_category: VenueCategory
    username: str | None = None
    permissions: tuple[str, ...] = field(default_factory=tuple)
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An asset-agnostic order request sent to an execution venue."""

    instrument: Instrument
    side: OrderSide
    quantity: float
    order_type: OrderType
    price: float | None = None
    trigger_price: float | None = None
    venue_id: str = "paper_main"

    #: An order that may only REDUCE existing exposure, never open new exposure.
    #: Exits must set this. Without it an exit whose position is already gone is
    #: executed as a fresh opposite-side entry, which then needs its own exit —
    #: a self-feeding position factory. That is exactly what ran on 2026-07-15:
    #: the EOD square-off re-fired on positions it had already closed, minting
    #: 207 phantom CRUDEOIL longs and 377 exit notifications before it was
    #: killed by hand.
    reduce_only: bool = False

    # Audit trail fields
    strategy_id: str | None = None
    execution_reason: str | None = None
    created_by: str | None = None
    playbook_id: str | None = None
    volatility_regime: str | None = None
    failure_reason: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive.")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP) and (self.price is None or self.price <= 0):
            raise ValueError("price must be positive for limit/stop orders.")
        if self.order_type in (OrderType.STOP, OrderType.STOP_MARKET) and (self.trigger_price is None or self.trigger_price <= 0):
            raise ValueError("trigger_price must be positive for stop orders.")


@dataclass(frozen=True, slots=True)
class OrderResponse:
    """Status feedback received from the execution venue."""

    venue_order_id: str
    venue_id: str
    instrument: Instrument
    side: OrderSide
    status: OrderStatus
    quantity: float
    filled_quantity: float
    average_price: float
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Venue portfolio metrics and purchasing power."""

    venue_id: str
    total_equity: float
    cash: float
    margin_available: float
    margin_used: float
    currency: str = "INR"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VenuePosition:
    """Open position balance on the execution venue."""

    instrument: Instrument
    side: OrderSide
    quantity: float
    average_price: float
    current_price: float
    unrealized_pnl: float
    venue_id: str
    playbook_id: str | None = None
    volatility_regime: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    """A domain-level intent to execute a trade, decoupled from specific broker logic."""

    intent_id: str
    instrument: Instrument
    side: OrderSide
    quantity: float
    strategy_id: str | None = None
    execution_reason: str = ""
    risk_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive.")


@dataclass(frozen=True, slots=True)
class VenueHolding:
    """Open holding balance on the execution venue."""

    instrument: Instrument
    quantity: float
    average_price: float
    current_price: float
    unrealized_pnl: float
    venue_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

