"""Unit tests for TradingSessionManager, BrokerRegistry (config-driven with
directory-based profile auto-discovery), and BrokerCapabilityProfile.

Tests verify:
- Asset → exchange resolution
- Exchange status and tradability logic
- Exchange mapping loaded from broker_registry.json
- Broker profiles auto-discovered from config/brokers/*.json directory
- Fallback to built-in defaults when config is absent
- Runtime broker mapping overrides
- Capability profile parsing and query methods (order type, exchange support)
- Capability validation gates (order type, live execution)
- Venue routing in PAPER and LIVE modes
- HokageOrchestrator integration (all config-loaded profiles have registered venues)
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from integrations.brokers.broker_registry import BrokerRegistry
from integrations.brokers.session_manager import TradingSessionManager
from integrations.brokers.interfaces import ExecutionVenueRegistry
from integrations.brokers.models import (
    BrokerCapabilityProfile,
    CapabilityViolation,
    ExecutionMode,
    OrderRequest,
    OrderType,
    OrderSide,
)
from integrations.data.models import Exchange, AssetClass, Instrument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_venue(venue_id: str) -> MagicMock:
    v = MagicMock()
    v.venue_id = venue_id
    return v


def _make_registry_with_venues(*venue_ids: str) -> ExecutionVenueRegistry:
    reg = ExecutionVenueRegistry()
    for vid in venue_ids:
        reg.register_venue(_make_venue(vid))
    return reg


def _write_mapping(tmp_path: Path, exchange_map: dict) -> Path:
    """Write a broker_registry.json with only the exchange mapping."""
    cfg = tmp_path / "broker_registry.json"
    cfg.write_text(json.dumps({"exchange_broker_map": exchange_map}), encoding="utf-8")
    return cfg


def _write_broker_profile(brokers_dir: Path, broker_id: str, data: dict) -> Path:
    """Write a single broker profile JSON file into the brokers directory."""
    brokers_dir.mkdir(parents=True, exist_ok=True)
    profile_file = brokers_dir / f"{broker_id}.json"
    profile_file.write_text(json.dumps(data), encoding="utf-8")
    return profile_file


def _minimal_profile(broker_id: str, **overrides) -> dict:
    """Build a minimal but valid broker capability dict."""
    base = {
        "supported_exchanges": ["NSE"],
        "supported_instruments": ["equity"],
        "market_orders": True,
        "limit_orders": True,
        "stop_orders": True,
        "stop_market_orders": True,
        "margin_trading": False,
        "product_types": [],
        "options_trading": False,
        "futures_trading": False,
        "fractional_shares": False,
        "websocket_streaming": False,
        "historical_data": False,
        "paper_execution_support": True,
        "live_execution_support": True,
        "paper_venue_id": f"paper_{broker_id}",
        "live_venue_id": f"{broker_id}_main",
    }
    base.update(overrides)
    return base


_MISSING = Path("/nonexistent/path/broker_registry.json")
_MISSING_DIR = Path("/nonexistent/brokers_dir")


# ---------------------------------------------------------------------------
# TradingSessionManager tests
# ---------------------------------------------------------------------------

def test_session_manager_asset_resolution() -> None:
    """Assets resolve to the correct exchange and asset class."""
    mgr = TradingSessionManager()

    assert mgr.resolve_exchange("INFY") == Exchange.NSE
    assert mgr.resolve_asset_class("INFY") == AssetClass.INDIAN_EQUITY
    assert mgr.resolve_exchange("TCS") == Exchange.NSE

    assert mgr.resolve_exchange("GOLD") == Exchange.MCX
    assert mgr.resolve_asset_class("GOLD") == AssetClass.COMMODITY
    assert mgr.resolve_exchange("CRUDEOIL") == Exchange.MCX

    assert mgr.resolve_exchange("BTCUSDT") == Exchange.BINANCE
    assert mgr.resolve_asset_class("BTCUSDT") == AssetClass.CRYPTO
    assert mgr.resolve_exchange("ETH") == Exchange.BINANCE

    assert mgr.resolve_exchange("AAPL") == Exchange.NASDAQ
    assert mgr.resolve_asset_class("AAPL") == AssetClass.GLOBAL_EQUITY
    assert mgr.resolve_exchange("TSLA") == Exchange.NASDAQ

    assert mgr.resolve_exchange("EURUSD") == Exchange.FOREX
    assert mgr.resolve_asset_class("EURUSD") == AssetClass.FOREX


def test_session_manager_tradability_and_hours() -> None:
    """Exchange status and tradability logic for various times."""
    mgr = TradingSessionManager()

    crypto_time = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
    assert mgr.get_exchange_status(Exchange.BINANCE, crypto_time) == "OPEN"
    assert mgr.is_tradable("BTCUSDT", crypto_time) is True

    maint_time = datetime(2026, 6, 28, 3, 5, 0, tzinfo=timezone.utc)
    assert mgr.get_exchange_status(Exchange.BINANCE, maint_time) == "MAINTENANCE"
    assert mgr.is_tradable("BTCUSDT", maint_time) is False

    nse_open_utc = datetime(2026, 6, 26, 4, 30, 0, tzinfo=timezone.utc)
    assert mgr.get_exchange_status(Exchange.NSE, nse_open_utc) == "OPEN"
    assert mgr.is_tradable("INFY", nse_open_utc) is True

    nse_closed_utc = datetime(2026, 6, 26, 12, 30, 0, tzinfo=timezone.utc)
    assert mgr.get_exchange_status(Exchange.NSE, nse_closed_utc) == "CLOSED"
    assert mgr.is_tradable("INFY", nse_closed_utc) is False

    nse_weekend_utc = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)
    assert mgr.get_exchange_status(Exchange.NSE, nse_weekend_utc) == "CLOSED"
    assert mgr.is_tradable("INFY", nse_weekend_utc) is False


# ---------------------------------------------------------------------------
# BrokerCapabilityProfile tests
# ---------------------------------------------------------------------------

def test_capability_profile_from_dict() -> None:
    """BrokerCapabilityProfile.from_dict parses all fields correctly."""
    data = {
        "supported_exchanges": ["NSE", "BSE", "MCX"],
        "supported_instruments": ["equity", "futures", "options"],
        "market_orders": True, "limit_orders": True, "stop_orders": True,
        "stop_market_orders": False, "margin_trading": True,
        "product_types": ["CNC", "MIS", "NRML"],
        "options_trading": True, "futures_trading": True, "fractional_shares": False,
        "websocket_streaming": True, "historical_data": True,
        "paper_execution_support": True, "live_execution_support": True,
        "paper_venue_id": "paper_zerodha", "live_venue_id": "kite_main",
    }
    profile = BrokerCapabilityProfile.from_dict("zerodha", data)

    assert profile.broker_id == "zerodha"
    assert "NSE" in profile.supported_exchanges
    assert "MCX" in profile.supported_exchanges
    assert profile.market_orders is True
    assert profile.stop_market_orders is False
    assert "CNC" in profile.product_types
    assert profile.paper_venue_id == "paper_zerodha"
    assert profile.live_venue_id == "kite_main"


def test_capability_profile_supports_order_type() -> None:
    """BrokerCapabilityProfile.supports_order_type is case-insensitive."""
    data = _minimal_profile("x", stop_orders=False, stop_market_orders=False)
    profile = BrokerCapabilityProfile.from_dict("x", data)

    assert profile.supports_order_type("MARKET") is True
    assert profile.supports_order_type("market") is True
    assert profile.supports_order_type("LIMIT") is True
    assert profile.supports_order_type("STOP") is False
    assert profile.supports_order_type("STOP_MARKET") is False


def test_capability_profile_supports_exchange() -> None:
    """BrokerCapabilityProfile.supports_exchange is case-insensitive."""
    data = _minimal_profile("x", supported_exchanges=["NSE", "BSE"])
    profile = BrokerCapabilityProfile.from_dict("x", data)

    assert profile.supports_exchange("NSE") is True
    assert profile.supports_exchange("nse") is True
    assert profile.supports_exchange("MCX") is False


# ---------------------------------------------------------------------------
# BrokerRegistry — directory auto-discovery
# ---------------------------------------------------------------------------

def test_broker_registry_loads_profiles_from_directory(tmp_path: Path) -> None:
    """BrokerRegistry auto-discovers all *.json files in the brokers directory."""
    brokers_dir = tmp_path / "brokers"
    _write_broker_profile(brokers_dir, "brokerA", _minimal_profile(
        "brokerA", supported_exchanges=["NSE"], paper_venue_id="paper_brokera",
        live_venue_id="brokera_main"
    ))
    _write_broker_profile(brokers_dir, "brokerB", _minimal_profile(
        "brokerB", supported_exchanges=["BINANCE"], paper_venue_id="paper_brokerb",
        live_venue_id="brokerb_main"
    ))
    mapping_file = _write_mapping(tmp_path, {"NSE": "brokerA", "BINANCE": "brokerB"})

    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=mapping_file, brokers_dir=brokers_dir)

    assert "brokera" in br.list_brokers()
    assert "brokerb" in br.list_brokers()
    assert br.get_broker_for_exchange(Exchange.NSE) == "brokera"
    assert br.get_broker_for_exchange(Exchange.BINANCE) == "brokerb"

    profile_a = br.get_capability_profile("brokera")
    assert profile_a is not None
    assert profile_a.paper_venue_id == "paper_brokera"

    profile_b = br.get_capability_profile("brokerb")
    assert profile_b is not None
    assert profile_b.paper_venue_id == "paper_brokerb"


def test_broker_registry_adding_new_broker_requires_only_file_drop(tmp_path: Path) -> None:
    """Dropping a new profile file auto-registers a new broker on next startup."""
    brokers_dir = tmp_path / "brokers"
    _write_broker_profile(brokers_dir, "brokerA", _minimal_profile("brokerA"))
    mapping_file = _write_mapping(tmp_path, {"NSE": "brokerA"})

    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br1 = BrokerRegistry(reg, mgr, config_path=mapping_file, brokers_dir=brokers_dir)
    assert "brokera" in br1.list_brokers()
    assert "brokerB" not in br1.list_brokers()

    # Simulate "dropping" a new broker profile file
    _write_broker_profile(brokers_dir, "brokerB", _minimal_profile(
        "brokerB", supported_exchanges=["BINANCE"]
    ))
    # Update mapping to include new broker
    _write_mapping(tmp_path, {"NSE": "brokerA", "BINANCE": "brokerB"})

    # A new registry instance picks it up automatically
    reg2 = ExecutionVenueRegistry()
    br2 = BrokerRegistry(reg2, mgr, config_path=mapping_file, brokers_dir=brokers_dir)
    assert "brokera" in br2.list_brokers()
    assert "brokerb" in br2.list_brokers()


def test_broker_registry_fallback_on_missing_config() -> None:
    """BrokerRegistry falls back to built-in defaults when config files are absent."""
    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    assert br.get_broker_for_exchange(Exchange.NSE) == "zerodha"
    assert br.get_broker_for_exchange(Exchange.BINANCE) == "coindcx"
    assert "zerodha" in br.list_brokers()
    assert "coindcx" in br.list_brokers()


def test_broker_registry_mapping_and_profiles_are_separate(tmp_path: Path) -> None:
    """The exchange mapping file and broker profile directory are independent concerns."""
    # Write mapping only — no profiles directory
    mapping_file = _write_mapping(tmp_path, {"NSE": "zerodha"})
    missing_brokers_dir = tmp_path / "brokers_nonexistent"

    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    # Should fall back to built-in profiles but use the file mapping
    br = BrokerRegistry(reg, mgr, config_path=mapping_file, brokers_dir=missing_brokers_dir)

    assert br.get_broker_for_exchange(Exchange.NSE) == "zerodha"
    assert "zerodha" in br.list_brokers()  # from built-in fallback


def test_broker_registry_runtime_override() -> None:
    """register_broker_mapping overrides config at runtime without file changes."""
    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    assert br.get_broker_for_exchange(Exchange.NSE) == "zerodha"
    br.register_broker_mapping(Exchange.NSE, "new_broker")
    assert br.get_broker_for_exchange(Exchange.NSE) == "new_broker"


def test_broker_registry_list_exchange_mappings() -> None:
    """list_exchange_mappings returns a copy of the full mapping dict."""
    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)
    mappings = br.list_exchange_mappings()

    assert isinstance(mappings, dict)
    assert "NSE" in mappings
    assert mappings["NSE"] == "zerodha"


def test_broker_registry_ignores_malformed_profile_file(tmp_path: Path) -> None:
    """A malformed profile JSON file is skipped; valid profiles still load."""
    brokers_dir = tmp_path / "brokers"
    _write_broker_profile(brokers_dir, "good_broker", _minimal_profile("good_broker"))
    # Write an invalid JSON file
    (brokers_dir / "bad_broker.json").write_text("{ this is not valid json }", encoding="utf-8")

    mapping_file = _write_mapping(tmp_path, {"NSE": "good_broker"})
    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=mapping_file, brokers_dir=brokers_dir)

    assert "good_broker" in br.list_brokers()
    assert "bad_broker" not in br.list_brokers()


# ---------------------------------------------------------------------------
# Capability validation tests
# ---------------------------------------------------------------------------

def test_validate_order_request_passes_for_supported_type() -> None:
    """validate_order_request does not raise for supported order types."""
    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    instrument = Instrument(symbol="INFY", exchange="NSE", asset_class="INDIAN_EQUITY")
    request = OrderRequest(
        instrument=instrument, side=OrderSide.BUY, quantity=10.0,
        order_type=OrderType.LIMIT, price=1500.0,
    )
    br.validate_order_request(request, "zerodha")  # must not raise


def test_validate_order_request_raises_for_unsupported_type(tmp_path: Path) -> None:
    """validate_order_request raises CapabilityViolation for unsupported order types."""
    brokers_dir = tmp_path / "brokers"
    _write_broker_profile(brokers_dir, "restricted", _minimal_profile(
        "restricted", market_orders=False
    ))
    mapping_file = _write_mapping(tmp_path, {"NSE": "restricted"})

    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=mapping_file, brokers_dir=brokers_dir)

    instrument = Instrument(symbol="INFY", exchange="NSE", asset_class="INDIAN_EQUITY")
    request = OrderRequest(
        instrument=instrument, side=OrderSide.BUY, quantity=5.0,
        order_type=OrderType.MARKET,
    )
    with pytest.raises(CapabilityViolation, match="does not support order type 'MARKET'"):
        br.validate_order_request(request, "restricted")


def test_validate_live_execution_raises_when_unsupported(tmp_path: Path) -> None:
    """validate_live_execution raises CapabilityViolation for paper-only brokers."""
    brokers_dir = tmp_path / "brokers"
    _write_broker_profile(brokers_dir, "paper_only", _minimal_profile(
        "paper_only", live_execution_support=False
    ))
    mapping_file = _write_mapping(tmp_path, {"NSE": "paper_only"})

    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=mapping_file, brokers_dir=brokers_dir)

    with pytest.raises(CapabilityViolation, match="does not support live execution"):
        br.validate_live_execution("paper_only")


def test_validate_unknown_broker_logs_warning_and_passes(caplog) -> None:
    """validate_order_request allows unknown brokers through with a warning."""
    import logging
    reg = ExecutionVenueRegistry()
    mgr = TradingSessionManager()
    br = BrokerRegistry(reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    instrument = Instrument(symbol="INFY", exchange="NSE", asset_class="INDIAN_EQUITY")
    request = OrderRequest(
        instrument=instrument, side=OrderSide.BUY, quantity=1.0,
        order_type=OrderType.MARKET,
    )
    with caplog.at_level(logging.WARNING, logger="Hokage.BrokerRegistry"):
        br.validate_order_request(request, "completely_unknown_broker")
    assert "No capability profile found" in caplog.text


# ---------------------------------------------------------------------------
# Venue routing tests
# ---------------------------------------------------------------------------

def test_broker_registry_routing_paper_mode() -> None:
    """In PAPER mode, routing resolves to the broker-specific paper venue."""
    venue_reg = _make_registry_with_venues("paper_main", "paper_zerodha", "kite_main")
    mgr = TradingSessionManager()
    br = BrokerRegistry(venue_reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    venue = br.get_venue_for_asset("INFY", ExecutionMode.PAPER)
    assert venue.venue_id == "paper_zerodha"


def test_broker_registry_routing_paper_fallback() -> None:
    """In PAPER mode, falls back to paper_main if broker-specific venue not registered."""
    venue_reg = _make_registry_with_venues("paper_main", "paper_zerodha", "kite_main")
    mgr = TradingSessionManager()
    br = BrokerRegistry(venue_reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    # BTCUSDT → coindcx → paper_coindcx (not registered) → paper_main
    venue = br.get_venue_for_asset("BTCUSDT", ExecutionMode.PAPER)
    assert venue.venue_id == "paper_main"


def test_broker_registry_routing_live_mode() -> None:
    """In LIVE mode, routing resolves to the broker live venue."""
    venue_reg = _make_registry_with_venues("paper_main", "paper_zerodha", "kite_main")
    mgr = TradingSessionManager()
    br = BrokerRegistry(venue_reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    venue = br.get_venue_for_asset("INFY", ExecutionMode.LIVE, validate=False)
    assert venue.venue_id == "kite_main"


def test_broker_registry_live_mode_raises_for_unregistered_venue() -> None:
    """In LIVE mode, raises KeyError if the live venue is not registered."""
    venue_reg = _make_registry_with_venues("paper_main", "paper_zerodha")
    mgr = TradingSessionManager()
    br = BrokerRegistry(venue_reg, mgr, config_path=_MISSING, brokers_dir=_MISSING_DIR)

    with pytest.raises(KeyError, match="kite_main"):
        br.get_venue_for_asset("INFY", ExecutionMode.LIVE, validate=False)


# ---------------------------------------------------------------------------
# HokageOrchestrator integration test
# ---------------------------------------------------------------------------

def test_orchestrator_integration() -> None:
    """HokageOrchestrator wires broker registry, session manager, and venues correctly."""
    from hokage.orchestrator.pipeline import HokageOrchestrator

    orchestrator = HokageOrchestrator()

    assert orchestrator.session_manager is not None
    assert orchestrator.broker_registry is not None

    # All brokers loaded from config/brokers/ must have paper venues registered
    for broker in orchestrator.broker_registry.list_brokers():
        profile = orchestrator.broker_registry.get_capability_profile(broker)
        assert profile is not None, f"No capability profile for broker '{broker}'"
        venue = orchestrator.registry.get_venue(profile.paper_venue_id)
        assert venue is not None
        assert venue.venue_id == profile.paper_venue_id

    # Core four brokers are always present
    for broker in ["zerodha", "coindcx", "alpaca", "oanda"]:
        profile = orchestrator.broker_registry.get_capability_profile(broker)
        assert profile is not None, f"Missing capability profile for '{broker}'"
        assert profile.paper_execution_support is True
