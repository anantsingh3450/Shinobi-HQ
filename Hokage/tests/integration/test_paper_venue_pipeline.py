from __future__ import annotations

from pathlib import Path

from integrations.data.models import Instrument, AssetClass, Exchange
from integrations.brokers.models import (
    OrderRequest,
    OrderSide,
    OrderType,
    OrderStatus,
)
from integrations.brokers.paper_venue import PaperVenue


def test_paper_venue_pipeline_integration(tmp_path: Path):
    # 1. Setup PaperVenue under a temporary brain root
    venue = PaperVenue(venue_id="paper_main", account_id="paper", brain_root=tmp_path)
    venue.connect()

    # Verify initial balance is at default (10000)
    bal_initial = venue.get_account_balance()
    assert bal_initial.cash == 10000.0
    assert len(venue.get_positions()) == 0

    # 2. Place OrderRequest
    inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    req = OrderRequest(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        strategy_id="strat-123",
        execution_reason="integration test trigger"
    )

    resp = venue.place_order(req)

    # 3. Verify OrderResponse
    assert resp.status == OrderStatus.FILLED
    assert resp.quantity == 10.0
    assert resp.average_price == 100.0  # Mock price resolves to 100
    assert resp.venue_order_id

    # 4. Verify data persistence files are written
    assert (tmp_path / "trades" / "trades.jsonl").exists()
    assert (tmp_path / "tax" / "tax_events.jsonl").exists()
    assert (tmp_path / "portfolio" / "account_paper.json").exists()

    # 5. Verify live state queries
    positions = venue.get_positions()
    assert len(positions) == 1
    assert positions[0].instrument.symbol == "TATA"
    assert positions[0].quantity == 10.0

    # Verify balance matches legacy CFD-style cash accounting (cash remains constant, unrealized pnl updates equity)
    bal_after = venue.get_account_balance()
    assert bal_after.cash == 10000.0
    assert bal_after.total_equity == 10000.0  # position unrealized is 0.0 initially

    # 6. Verify order status retrieval
    status_resp = venue.get_order_status(resp.venue_order_id)
    assert status_resp.venue_order_id == resp.venue_order_id
    assert status_resp.status == OrderStatus.FILLED
    assert status_resp.average_price == 100.0

    # 7. Restart simulation: Instantiate a new PaperVenue pointing to the same folder
    venue2 = PaperVenue(venue_id="paper_main", account_id="paper", brain_root=tmp_path)
    venue2.connect()

    # 8. Verify data recovery
    bal2 = venue2.get_account_balance()
    assert bal2.cash == bal_after.cash

    positions2 = venue2.get_positions()
    assert len(positions2) == 1
    assert positions2[0].instrument.symbol == "TATA"
    assert positions2[0].quantity == 10.0

    status_resp2 = venue2.get_order_status(resp.venue_order_id)
    assert status_resp2.venue_order_id == resp.venue_order_id
    assert status_resp2.status == OrderStatus.FILLED
