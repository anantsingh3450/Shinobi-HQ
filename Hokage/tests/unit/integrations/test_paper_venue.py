from __future__ import annotations

from pathlib import Path
import pytest

from integrations.data.models import Instrument, AssetClass, Exchange
from integrations.brokers.interfaces import BaseExecutionVenue, ExecutionVenueRegistry
from integrations.brokers.models import (
    OrderRequest,
    OrderSide,
    OrderType,
    OrderStatus,
    ConnectionState,
)
from integrations.brokers.paper_venue import PaperVenue


def test_paper_venue_conforms_to_protocol(tmp_path: Path):
    venue = PaperVenue(brain_root=tmp_path)
    assert isinstance(venue, BaseExecutionVenue)


def test_paper_venue_lifecycle(tmp_path: Path):
    venue = PaperVenue(brain_root=tmp_path)
    
    # Defaults to disconnected
    assert venue.get_status().state == ConnectionState.DISCONNECTED

    # Connect
    status = venue.connect()
    assert status.state == ConnectionState.CONNECTED
    assert status.latency_ms is not None
    assert status.latency_ms > 0
    assert venue.get_status().state == ConnectionState.CONNECTED

    # Disconnect
    status = venue.disconnect()
    assert status.state == ConnectionState.DISCONNECTED
    assert venue.get_status().state == ConnectionState.DISCONNECTED


def test_paper_venue_raises_if_disconnected(tmp_path: Path):
    venue = PaperVenue(brain_root=tmp_path)
    inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    req = OrderRequest(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=5.0,
        order_type=OrderType.MARKET
    )

    # All operational queries raise when disconnected
    with pytest.raises(RuntimeError, match="Venue is not connected"):
        venue.place_order(req)

    with pytest.raises(RuntimeError, match="Venue is not connected"):
        venue.get_positions()

    with pytest.raises(RuntimeError, match="Venue is not connected"):
        venue.get_account_balance()

    with pytest.raises(RuntimeError, match="Venue is not connected"):
        venue.cancel_order("order-123")

    with pytest.raises(RuntimeError, match="Venue is not connected"):
        venue.get_order_status("order-123")


def test_paper_venue_capabilities(tmp_path: Path):
    venue = PaperVenue(brain_root=tmp_path)
    caps = venue.capabilities
    assert caps.market_orders is True
    assert caps.limit_orders is True
    assert caps.stop_orders is True
    assert caps.fractional_shares is True


def test_venue_registry_multi_venue_routing(tmp_path: Path):
    registry = ExecutionVenueRegistry()
    
    # Register two distinct paper venues mapping to different target accounts
    venue_main = PaperVenue(venue_id="paper_main", account_id="paper", brain_root=tmp_path)
    venue_sand = PaperVenue(venue_id="paper_sandbox", account_id="sandbox", brain_root=tmp_path)

    registry.register_venue(venue_main)
    registry.register_venue(venue_sand)

    assert "paper_main" in registry.list_venues()
    assert "paper_sandbox" in registry.list_venues()

    # Route and check instances
    assert registry.get_venue("paper_main") is venue_main
    assert registry.get_venue("paper_sandbox") is venue_sand


def test_paper_venue_quantity_isolation(tmp_path: Path):
    venue1 = PaperVenue(venue_id="paper_main", account_id="paper1", brain_root=tmp_path)
    venue2 = PaperVenue(venue_id="paper_sandbox", account_id="paper2", brain_root=tmp_path)
    venue1.connect()
    venue2.connect()

    inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    req1 = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=10.0, order_type=OrderType.MARKET)
    req2 = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=25.0, order_type=OrderType.MARKET)

    # Place orders and verify response quantities are isolated
    resp1 = venue1.place_order(req1)
    resp2 = venue2.place_order(req2)

    assert resp1.quantity == 10.0
    assert resp2.quantity == 25.0

    # Verify positions on venues match requested quantities
    pos1 = venue1.get_positions()
    pos2 = venue2.get_positions()

    assert len(pos1) == 1
    assert pos1[0].quantity == 10.0

    assert len(pos2) == 1
    assert pos2[0].quantity == 25.0


def test_paper_venue_multi_venue_storage_isolation(tmp_path: Path):
    # Initialize three distinct venues
    venue_main = PaperVenue(venue_id="paper_main", account_id="acc_main", brain_root=tmp_path)
    venue_sandbox = PaperVenue(venue_id="paper_sandbox", account_id="acc_sandbox", brain_root=tmp_path)
    venue_evolution = PaperVenue(venue_id="paper_evolution", account_id="acc_evolution", brain_root=tmp_path)

    venue_main.connect()
    venue_sandbox.connect()
    venue_evolution.connect()

    # Place order on main
    inst = Instrument(symbol="INFY", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    req_main = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=5.0, order_type=OrderType.MARKET)
    venue_main.place_order(req_main)

    # Place order on sandbox
    req_sand = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=15.0, order_type=OrderType.MARKET)
    venue_sandbox.place_order(req_sand)

    # Place order on evolution
    req_evol = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=30.0, order_type=OrderType.MARKET)
    venue_evolution.place_order(req_evol)

    # Confirm trades file isolation
    assert (tmp_path / "trades" / "trades.jsonl").exists()
    assert (tmp_path / "trades" / "paper_sandbox" / "trades.jsonl").exists()
    assert (tmp_path / "trades" / "paper_evolution" / "trades.jsonl").exists()

    # Confirm tax ledger isolation
    assert (tmp_path / "tax" / "tax_events.jsonl").exists()
    assert (tmp_path / "tax" / "paper_sandbox" / "tax_events.jsonl").exists()
    assert (tmp_path / "tax" / "paper_evolution" / "tax_events.jsonl").exists()

    # Confirm portfolio files isolation
    assert (tmp_path / "portfolio" / "account_acc_main.json").exists()
    assert (tmp_path / "portfolio" / "paper_sandbox" / "account_acc_sandbox.json").exists()
    assert (tmp_path / "portfolio" / "paper_evolution" / "account_acc_evolution.json").exists()

    # Confirm no trade records bleeds across venues
    assert len(venue_main._trade_store.load_all()) == 1
    assert len(venue_sandbox._trade_store.load_all()) == 1
    assert len(venue_evolution._trade_store.load_all()) == 1


def test_paper_venue_consecutive_execution_consistency(tmp_path: Path):
    venue = PaperVenue(venue_id="paper_main", account_id="paper", brain_root=tmp_path)
    venue.connect()

    inst = Instrument(symbol="SBIN", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)

    # Order 1: Buy 10 units
    req1 = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=10.0, order_type=OrderType.MARKET)
    resp1 = venue.place_order(req1)
    assert resp1.status == OrderStatus.FILLED
    assert resp1.quantity == 10.0

    # Order 2: Buy 5 units
    req2 = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=5.0, order_type=OrderType.MARKET)
    resp2 = venue.place_order(req2)
    assert resp2.status == OrderStatus.FILLED
    assert resp2.quantity == 5.0

    # Verify combined positions (tracked individually under FIFO contract style)
    positions = venue.get_positions()
    assert len(positions) == 2
    assert sum(p.quantity for p in positions) == 15.0

    # Order 3: Sell 15 units (closes position in CFD-style netting)
    req3 = OrderRequest(instrument=inst, side=OrderSide.SELL, quantity=15.0, order_type=OrderType.MARKET)
    resp3 = venue.place_order(req3)
    assert resp3.status == OrderStatus.FILLED
    assert resp3.quantity == 15.0

    # Verify positions are net zero/empty
    positions_after = venue.get_positions()
    assert len(positions_after) == 0
