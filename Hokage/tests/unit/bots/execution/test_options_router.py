"""OptionsRouter: directional underlying signals become BOUGHT ATM options.

The previous router only matched the literal substring "CRUDEOIL", so the
universe symbol CRUDE_OIL (underscore) never routed at all, and it built
tradingsymbols by string-guessing expiries instead of reading the venue's
real contract chain. These tests lock in the rebuilt behavior: real chain
resolution, fail-closed on any gap, premium-capped affordability.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from bots.execution.options_router import OptionsRouter, OptionsRoutingError
from integrations.brokers.models import OrderRequest, OrderSide, OrderType
from integrations.data.models import AssetClass, Exchange, Instrument


def _underlying_request(symbol: str, side: OrderSide) -> OrderRequest:
    exchange = Exchange.MCX if "CRUDE" in symbol else Exchange.NSE
    return OrderRequest(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.INDEX, exchange=exchange, currency="INR"),
        side=side,
        quantity=1.0,
        order_type=OrderType.MARKET,
        venue_id="paper_main",
        strategy_id="test-strat",
        execution_reason="test",
    )


def _provider(contract: dict | None, premium: float | None = 150.0):
    provider = MagicMock()
    provider.resolve_option_contract.return_value = contract
    if premium is None:
        provider.get_quote.side_effect = ValueError("no quote")
    else:
        quote = MagicMock()
        quote.price = premium
        provider.get_quote.return_value = quote
    return provider


_NIFTY_CE = {
    "tradingsymbol": "NIFTY25JUL24300CE",
    "exchange": "NFO",
    "strike": 24300.0,
    "expiry": date.today() + timedelta(days=3),
    "lot_size": 75.0,
}

_CRUDE_PE = {
    "tradingsymbol": "CRUDEOIL25JUL6800PE",
    "exchange": "MCX",
    "strike": 6800.0,
    "expiry": date.today() + timedelta(days=10),
    "lot_size": 100.0,
}


def test_bullish_nifty_signal_buys_atm_call():
    router = OptionsRouter(price_source=_provider(_NIFTY_CE, premium=180.0))
    req = router.route_to_options(
        _underlying_request("NIFTY", OrderSide.BUY), current_price=24310.0, available_cash=50000.0
    )
    assert req.instrument.symbol == "NIFTY25JUL24300CE"
    assert req.side == OrderSide.BUY
    assert req.quantity == 75.0
    assert req.instrument.metadata["is_option"] is True
    assert req.instrument.metadata["premium_at_entry"] == 180.0


def test_bearish_crude_oil_underscore_symbol_buys_put():
    """Regression: CRUDE_OIL (the actual universe symbol) must route — the
    old substring check missed the underscore and never fired."""
    router = OptionsRouter(price_source=_provider(_CRUDE_PE, premium=95.0))
    req = router.route_to_options(
        _underlying_request("CRUDE_OIL", OrderSide.SELL), current_price=6812.0, available_cash=50000.0
    )
    assert req.instrument.symbol == "CRUDEOIL25JUL6800PE"
    # Bearish signal still BUYS (a put): loss capped at premium.
    assert req.side == OrderSide.BUY
    assert req.quantity == 100.0
    assert req.instrument.exchange == Exchange.MCX


def test_no_live_contract_fails_closed():
    router = OptionsRouter(price_source=_provider(None))
    with pytest.raises(OptionsRoutingError):
        router.route_to_options(
            _underlying_request("NIFTY", OrderSide.BUY), current_price=24310.0
        )


def test_missing_premium_quote_fails_closed():
    router = OptionsRouter(price_source=_provider(_NIFTY_CE, premium=None))
    with pytest.raises(OptionsRoutingError):
        router.route_to_options(
            _underlying_request("NIFTY", OrderSide.BUY), current_price=24310.0
        )


def test_unaffordable_premium_fails_closed():
    # 180 x 75 = 13,500 notional > 50% of 20,000 cash
    router = OptionsRouter(price_source=_provider(_NIFTY_CE, premium=180.0))
    with pytest.raises(OptionsRoutingError):
        router.route_to_options(
            _underlying_request("NIFTY", OrderSide.BUY), current_price=24310.0, available_cash=20000.0
        )


def test_provider_without_real_chain_fails_closed():
    """Mock-mode providers expose no option chain; the router must refuse to
    fabricate a contract rather than fall back to anything synthetic."""
    class _NoChainProvider:
        pass

    router = OptionsRouter(price_source=_NoChainProvider())
    with pytest.raises(OptionsRoutingError):
        router.route_to_options(
            _underlying_request("NIFTY", OrderSide.BUY), current_price=24310.0
        )


def test_non_routed_symbol_passes_through_unchanged():
    router = OptionsRouter(price_source=_provider(_NIFTY_CE))
    original = _underlying_request("TCS", OrderSide.BUY)
    assert router.route_to_options(original, current_price=4100.0) is original


def test_routes_registry():
    assert OptionsRouter.routes("NIFTY")
    assert OptionsRouter.routes("CRUDE_OIL")
    assert OptionsRouter.routes("crudeoil")
    assert not OptionsRouter.routes("TCS")
