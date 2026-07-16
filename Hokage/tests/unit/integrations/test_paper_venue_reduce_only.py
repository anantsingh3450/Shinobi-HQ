"""An exit must never be able to open a position.

The 2026-07-15 runaway: the paper venue maps every order to an *opening*
proposal and nets only afterwards, inside Account.apply_trade. So an exit whose
position was already closed did not become a no-op — it opened a fresh
opposite-side position, which the monitor then tried to exit, which opened
another. One real CRUDEOIL position became 207 phantom longs, 377 exit
triggers, and 377 Telegram notifications before the process was killed by hand.

These tests pin the reduce-only contract that makes that runaway impossible.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.execution.models import TradeStatus
from integrations.brokers.models import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from integrations.brokers.paper_venue import PaperVenue
from integrations.data.models import AssetClass, Exchange, Instrument


@pytest.fixture
def venue(tmp_path: Path) -> PaperVenue:
    v = PaperVenue(brain_root=tmp_path)
    v.connect()
    return v


def _instrument(symbol: str = "TESTOPT26JUL100CE") -> Instrument:
    return Instrument(symbol=symbol, exchange=Exchange.NSE, asset_class=AssetClass.FNO)


def _order(side: OrderSide, qty: float = 10.0, reduce_only: bool = False) -> OrderRequest:
    return OrderRequest(
        instrument=_instrument(),
        side=side,
        quantity=qty,
        order_type=OrderType.MARKET,
        reduce_only=reduce_only,
        strategy_id="Test",
    )


def _open_positions(venue: PaperVenue):
    account = venue._portfolio_store.load_account(venue._account_id)
    return [p for p in account.positions.values() if p.status == TradeStatus.OPEN]


class TestReduceOnlyCannotOpenExposure:
    def test_reduce_only_exit_with_nothing_to_close_is_rejected(self, venue):
        """The runaway's first domino: an exit for a position that is already
        gone must be refused, not executed as a new entry."""
        resp = venue.place_order(_order(OrderSide.SELL, reduce_only=True))

        assert resp.status == OrderStatus.REJECTED
        assert resp.filled_quantity == 0.0
        assert "no open opposing position" in (resp.error_message or "")
        assert _open_positions(venue) == [], "a rejected exit must not create a position"

    def test_repeated_exits_cannot_mint_phantom_positions(self, venue):
        """The runaway itself, in miniature. Open one long, close it, then fire
        the exit 20 more times — as the stuck monitor did. Position count must
        never grow; the old code reached 207."""
        venue.place_order(_order(OrderSide.BUY, qty=10.0))
        assert len(_open_positions(venue)) == 1

        first_exit = venue.place_order(_order(OrderSide.SELL, qty=10.0, reduce_only=True))
        assert first_exit.status == OrderStatus.FILLED
        assert _open_positions(venue) == []

        for _ in range(20):
            resp = venue.place_order(_order(OrderSide.SELL, qty=10.0, reduce_only=True))
            assert resp.status == OrderStatus.REJECTED

        assert _open_positions(venue) == [], "exits minted phantom exposure — the 2026-07-15 bug"

    def test_reduce_only_buy_cannot_open_a_long(self, venue):
        """Same contract on the other side: flattening a short that is already
        flat must not leave a long behind."""
        resp = venue.place_order(_order(OrderSide.BUY, reduce_only=True))
        assert resp.status == OrderStatus.REJECTED
        assert _open_positions(venue) == []

    def test_oversized_reduce_only_is_clamped_to_what_is_open(self, venue):
        """Closing 10 when only 4 are open must close 4 and open no short."""
        venue.place_order(_order(OrderSide.BUY, qty=4.0))

        resp = venue.place_order(_order(OrderSide.SELL, qty=10.0, reduce_only=True))

        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == pytest.approx(4.0)
        assert _open_positions(venue) == [], "clamped exit must flatten, not reverse"


class TestNormalOrdersAreUnaffected:
    def test_ordinary_entry_still_opens_a_position(self, venue):
        resp = venue.place_order(_order(OrderSide.BUY, qty=10.0))

        assert resp.status == OrderStatus.FILLED
        open_positions = _open_positions(venue)
        assert len(open_positions) == 1
        assert open_positions[0].quantity == pytest.approx(10.0)

    def test_non_reduce_only_sell_may_still_open_a_short(self, venue):
        """reduce_only defaults to False, so deliberate short entries are
        untouched — only exits opt into the restriction."""
        resp = venue.place_order(_order(OrderSide.SELL, qty=10.0))

        assert resp.status == OrderStatus.FILLED
        assert len(_open_positions(venue)) == 1

    def test_reduce_only_closes_a_real_position_normally(self, venue):
        venue.place_order(_order(OrderSide.BUY, qty=10.0))

        resp = venue.place_order(_order(OrderSide.SELL, qty=10.0, reduce_only=True))

        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == pytest.approx(10.0)
        assert _open_positions(venue) == []
