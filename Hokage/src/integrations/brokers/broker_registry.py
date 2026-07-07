"""Broker Registry for Hokage.

Configuration-driven. All exchange-to-broker mappings are read from
``config/broker_registry.json``. All broker capability profiles are
auto-discovered from ``config/brokers/<broker_id>.json`` at startup.

Routing chain:
    Asset → Exchange → BrokerRegistry (config) → Broker → ExecutionMode
    → VenueAdapter (paper_<broker> | <broker>_main) → Broker API

To add a new broker:
    1. Drop ``config/brokers/<new_broker>.json`` into the profiles directory.
    2. Add the exchange→broker mapping to ``config/broker_registry.json``.
    → No source code changes. No recompilation.

To change a broker assignment:
    1. Edit ``config/broker_registry.json`` only.
    → No source code changes. No recompilation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from integrations.brokers.interfaces import BaseExecutionVenue, ExecutionVenueRegistry
from integrations.brokers.models import (
    BrokerCapabilityProfile,
    CapabilityViolation,
    ExecutionMode,
    OrderRequest,
)
from integrations.brokers.session_manager import TradingSessionManager
from integrations.data.models import Exchange

logger = logging.getLogger("Hokage.BrokerRegistry")

# Canonical locations of configuration artefacts.
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "broker_registry.json"
_DEFAULT_BROKERS_DIR = Path(__file__).resolve().parents[4] / "config" / "brokers"

# Built-in fallback exchange mapping used when the config file is absent.
_FALLBACK_EXCHANGE_BROKER_MAP: dict[str, str] = {
    "NSE":     "zerodha",
    "BSE":     "zerodha",
    "MCX":     "zerodha",
    "BINANCE": "coindcx",
    "NASDAQ":  "alpaca",
    "NYSE":    "alpaca",
    "FOREX":   "oanda",
    "GLOBAL":  "alpaca",
}

# Built-in fallback capability profiles used when the brokers directory is absent.
_FALLBACK_BROKER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "zerodha": {
        "supported_exchanges": ["NSE", "BSE", "MCX"],
        "supported_instruments": ["equity", "futures", "options", "commodity"],
        "market_orders": True, "limit_orders": True, "stop_orders": True,
        "stop_market_orders": True, "margin_trading": True,
        "product_types": ["CNC", "MIS", "NRML"],
        "options_trading": True, "futures_trading": True, "fractional_shares": False,
        "websocket_streaming": True, "historical_data": True,
        "paper_execution_support": True, "live_execution_support": True,
        "paper_venue_id": "paper_zerodha", "live_venue_id": "kite_main",
    },
    "coindcx": {
        "supported_exchanges": ["BINANCE"],
        "supported_instruments": ["crypto_spot"],
        "market_orders": True, "limit_orders": True, "stop_orders": True,
        "stop_market_orders": True, "margin_trading": False,
        "product_types": ["DELIVERY"],
        "options_trading": False, "futures_trading": False, "fractional_shares": True,
        "websocket_streaming": True, "historical_data": True,
        "paper_execution_support": True, "live_execution_support": True,
        "paper_venue_id": "paper_coindcx", "live_venue_id": "coindcx_main",
    },
    "alpaca": {
        "supported_exchanges": ["NASDAQ", "NYSE", "GLOBAL"],
        "supported_instruments": ["equity", "etf"],
        "market_orders": True, "limit_orders": True, "stop_orders": True,
        "stop_market_orders": True, "margin_trading": True,
        "product_types": ["DAY", "GTC"],
        "options_trading": False, "futures_trading": False, "fractional_shares": True,
        "websocket_streaming": True, "historical_data": True,
        "paper_execution_support": True, "live_execution_support": True,
        "paper_venue_id": "paper_alpaca", "live_venue_id": "alpaca_main",
    },
    "oanda": {
        "supported_exchanges": ["FOREX"],
        "supported_instruments": ["forex_spot", "forex_cfd"],
        "market_orders": True, "limit_orders": True, "stop_orders": True,
        "stop_market_orders": True, "margin_trading": True,
        "product_types": ["SPOT", "CFD"],
        "options_trading": False, "futures_trading": False, "fractional_shares": True,
        "websocket_streaming": True, "historical_data": True,
        "paper_execution_support": True, "live_execution_support": True,
        "paper_venue_id": "paper_oanda", "live_venue_id": "oanda_main",
    },
}


def _load_exchange_map(config_path: Path) -> dict[str, str]:
    """Load exchange→broker mapping from ``broker_registry.json``.

    Returns the built-in fallback mapping if the file is absent or malformed.
    """
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        mapping = data.get("exchange_broker_map", {})
        logger.info("Loaded broker exchange mapping from '%s'.", config_path)
        return {k.upper(): v.lower() for k, v in mapping.items()}
    except FileNotFoundError:
        logger.warning(
            "Broker registry config not found at '%s'. Using built-in defaults.", config_path
        )
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(
            "Failed to parse broker registry config at '%s': %s. Using built-in defaults.",
            config_path, exc,
        )
    return {k.upper(): v.lower() for k, v in _FALLBACK_EXCHANGE_BROKER_MAP.items()}


def _load_broker_profiles(brokers_dir: Path) -> dict[str, BrokerCapabilityProfile]:
    """Auto-discover and load every ``*.json`` file from ``config/brokers/``.

    Each file's stem (filename without extension) becomes the ``broker_id``.
    Files that fail to parse are logged and skipped.

    Returns the built-in fallback profiles if the directory is absent.
    """
    profiles: dict[str, BrokerCapabilityProfile] = {}

    if not brokers_dir.is_dir():
        logger.warning(
            "Broker profiles directory not found at '%s'. Using built-in defaults.", brokers_dir
        )
        for broker_id, cap_data in _FALLBACK_BROKER_CAPABILITIES.items():
            profiles[broker_id] = BrokerCapabilityProfile.from_dict(broker_id, cap_data)
        return profiles

    for profile_file in sorted(brokers_dir.glob("*.json")):
        broker_id = profile_file.stem.lower()
        try:
            with profile_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            profiles[broker_id] = BrokerCapabilityProfile.from_dict(broker_id, data)
            logger.info("Loaded broker profile '%s' from '%s'.", broker_id, profile_file.name)
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
            logger.error(
                "Failed to load broker profile from '%s': %s. Skipping.", profile_file, exc
            )

    if not profiles:
        logger.warning("No broker profiles loaded from '%s'. Using built-in defaults.", brokers_dir)
        for broker_id, cap_data in _FALLBACK_BROKER_CAPABILITIES.items():
            profiles[broker_id] = BrokerCapabilityProfile.from_dict(broker_id, cap_data)

    return profiles


class BrokerRegistry:
    """Thread-safe, configuration-driven registry that maps exchanges to brokers
    and resolves execution venues dynamically.

    Exchange→broker mappings are read from ``config/broker_registry.json``.
    Broker capability profiles are auto-discovered from ``config/brokers/*.json``.

    To add a new broker: drop a profile file and update the mapping — no code changes.

    Routing chain:
        Asset → Exchange → BrokerRegistry → Broker → ExecutionMode
        → VenueAdapter → Broker API
    """

    def __init__(
        self,
        venue_registry: ExecutionVenueRegistry,
        session_manager: TradingSessionManager,
        config_path: Path | None = None,
        brokers_dir: Path | None = None,
    ) -> None:
        """Initialize BrokerRegistry from config files.

        Args:
            venue_registry:  The shared venue registry holding live venue adapters.
            session_manager: The TradingSessionManager for asset → exchange resolution.
            config_path:     Override for ``broker_registry.json`` location.
            brokers_dir:     Override for the broker profiles directory.
        """
        self.venue_registry = venue_registry
        self.session_manager = session_manager
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._brokers_dir = brokers_dir or _DEFAULT_BROKERS_DIR

        self._exchange_to_broker: dict[str, str] = _load_exchange_map(self._config_path)
        self._capability_profiles: dict[str, BrokerCapabilityProfile] = _load_broker_profiles(
            self._brokers_dir
        )

        logger.info(
            "BrokerRegistry ready. %d broker(s) loaded. Exchange map: %s",
            len(self._capability_profiles),
            dict(self._exchange_to_broker),
        )

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_broker_for_exchange(self, exchange: Exchange) -> str:
        """Return the broker identifier mapped to the given exchange."""
        return self._exchange_to_broker.get(exchange.name.upper(), "mock")

    def get_capability_profile(self, broker_id: str) -> BrokerCapabilityProfile | None:
        """Return the capability profile for a broker, or None if unknown."""
        return self._capability_profiles.get(broker_id.lower())

    def list_brokers(self) -> list[str]:
        """Return sorted list of all loaded broker identifiers."""
        return sorted(self._capability_profiles.keys())

    def list_exchange_mappings(self) -> dict[str, str]:
        """Return a copy of the current exchange → broker mapping."""
        return dict(self._exchange_to_broker)

    # ------------------------------------------------------------------
    # Runtime override (for testing only)
    # ------------------------------------------------------------------

    def register_broker_mapping(self, exchange: Exchange, broker: str) -> None:
        """Override a broker mapping at runtime (testing / hot-switch only).

        Changes persist only for the lifetime of this process.
        """
        self._exchange_to_broker[exchange.name.upper()] = broker.lower()
        logger.info("Runtime override: %s → %s", exchange.name, broker)

    # ------------------------------------------------------------------
    # Capability validation
    # ------------------------------------------------------------------

    def validate_order_request(self, request: OrderRequest, broker_id: str) -> None:
        """Validate an OrderRequest against the broker's declared capabilities.

        Raises:
            CapabilityViolation: if the broker does not support the requested order type.
        """
        profile = self._capability_profiles.get(broker_id.lower())
        if profile is None:
            logger.warning(
                "No capability profile found for broker '%s'. Skipping validation.", broker_id
            )
            return

        order_type_str = str(request.order_type).upper()
        if not profile.supports_order_type(order_type_str):
            raise CapabilityViolation(
                f"Broker '{broker_id}' does not support order type '{order_type_str}'. "
                f"Supported: MARKET={profile.market_orders}, LIMIT={profile.limit_orders}, "
                f"STOP={profile.stop_orders}, STOP_MARKET={profile.stop_market_orders}."
            )

    def validate_live_execution(self, broker_id: str) -> None:
        """Raise CapabilityViolation if the broker does not support live execution."""
        profile = self._capability_profiles.get(broker_id.lower())
        if profile is not None and not profile.live_execution_support:
            raise CapabilityViolation(
                f"Broker '{broker_id}' does not support live execution. "
                "Set 'live_execution_support': true in its profile JSON to enable."
            )

    # ------------------------------------------------------------------
    # Venue resolution
    # ------------------------------------------------------------------

    def get_venue_for_asset(
        self, asset: str, mode: ExecutionMode, validate: bool = True
    ) -> BaseExecutionVenue:
        """Resolve the appropriate execution venue for an asset and execution mode.

        Args:
            asset:    Asset symbol (e.g. "TCS", "BTCUSDT", "GOLD").
            mode:     Active execution mode (PAPER, LIVE, HYBRID, READ_ONLY).
            validate: When True, validates live-execution capability before returning.

        Returns:
            The resolved BaseExecutionVenue adapter.

        Raises:
            KeyError:            If a required live venue is not registered.
            CapabilityViolation: If the broker does not support the requested mode.
        """
        exchange = self.session_manager.resolve_exchange(asset)
        broker = self.get_broker_for_exchange(exchange)
        profile = self._capability_profiles.get(broker)

        if mode in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
            paper_venue_id = profile.paper_venue_id if profile else f"paper_{broker}"
            try:
                return self.venue_registry.get_venue(paper_venue_id)
            except KeyError:
                logger.debug(
                    "Venue '%s' not registered. Falling back to 'paper_main'.", paper_venue_id
                )
                return self.venue_registry.get_venue("paper_main")

        # Live / Read-Only
        if validate:
            self.validate_live_execution(broker)

        live_venue_id = profile.live_venue_id if profile else f"{broker}_main"
        try:
            return self.venue_registry.get_venue(live_venue_id)
        except KeyError:
            raise KeyError(
                f"Live execution venue '{live_venue_id}' for broker '{broker}' is not registered. "
                "Ensure credentials and connection adapters are configured before enabling LIVE mode."
            )
