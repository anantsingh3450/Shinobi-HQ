"""KiteMarketDataProvider quote normalization.

Regression guard for the depth-extraction bug: the provider read top-level
"buy"/"sell" keys that do not exist in the Kite quote payload, so bid and ask
always fell back to last_price. Every quote therefore showed a 0.0% spread and
the liquidity gate never saw a real spread. Depth lives under data["depth"];
book totals under buy_quantity/sell_quantity.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider


def _provider_with_payload(payload: dict) -> KiteMarketDataProvider:
    client = MagicMock()
    client.quote.return_value = {"NSE:INFY": payload}
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    return KiteMarketDataProvider(manager)


def test_quote_extracts_real_depth_and_book_totals():
    provider = _provider_with_payload(
        {
            "last_price": 24300.0,
            "volume": 123456.0,
            "buy_quantity": 500000.0,
            "sell_quantity": 250000.0,
            "ohlc": {"close": 24250.0},
            "depth": {
                "buy": [{"price": 24299.0, "quantity": 100, "orders": 5}],
                "sell": [{"price": 24301.0, "quantity": 80, "orders": 3}],
            },
        }
    )
    quote = provider.get_quote("INFY")

    assert quote.price == 24300.0
    assert quote.bid == 24299.0
    assert quote.ask == 24301.0
    assert quote.bid_qty == 500000.0
    assert quote.ask_qty == 250000.0
    assert quote.previous_close == 24250.0
    assert quote.provider == "kite"


def test_quote_missing_depth_reports_none_not_zero_spread():
    """No depth data must surface as bid/ask None (gate skipped downstream),
    never as bid == ask == last_price which fakes a perfect 0.0% spread."""
    provider = _provider_with_payload({"last_price": 24300.0, "volume": 10.0})
    quote = provider.get_quote("INFY")

    assert quote.bid is None
    assert quote.ask is None
    assert quote.bid_qty is None
    assert quote.ask_qty is None


def test_quote_book_totals_fall_back_to_depth_level_sums():
    provider = _provider_with_payload(
        {
            "last_price": 100.0,
            "depth": {
                "buy": [
                    {"price": 99.9, "quantity": 40},
                    {"price": 99.8, "quantity": 60},
                ],
                "sell": [{"price": 100.1, "quantity": 20}],
            },
        }
    )
    quote = provider.get_quote("INFY")

    assert quote.bid_qty == 100.0
    assert quote.ask_qty == 20.0


def test_quote_zero_price_rejected():
    provider = _provider_with_payload({"last_price": 0.0})
    with pytest.raises(ValueError):
        provider.get_quote("INFY")


def test_universe_symbols_map_to_front_month_futures():
    """Hokage trades futures, never spot. NIFTY/CRUDE_OIL quotes must resolve
    to the nearest-expiry futures contract (old code asked Kite for
    "NSE:NIFTY" and "NSE:CRUDE_OIL", neither of which exists — every quote in
    kite mode failed and the provenance guard blocked all entries)."""
    from datetime import date, timedelta

    client = MagicMock()
    today = date.today()
    client.instruments.return_value = [
        {"name": "CRUDEOIL", "instrument_type": "FUT", "expiry": today - timedelta(days=3), "tradingsymbol": "CRUDEOIL_EXPIRED_FUT"},
        {"name": "CRUDEOIL", "instrument_type": "FUT", "expiry": today + timedelta(days=10), "tradingsymbol": "CRUDEOIL_FRONT_FUT"},
        {"name": "CRUDEOIL", "instrument_type": "FUT", "expiry": today + timedelta(days=40), "tradingsymbol": "CRUDEOIL_BACK_FUT"},
        {"name": "CRUDEOIL", "instrument_type": "CE", "expiry": today + timedelta(days=10), "tradingsymbol": "CRUDEOIL_OPTION"},
    ]
    client.quote.return_value = {
        "MCX:CRUDEOIL_FRONT_FUT": {"last_price": 6800.0}
    }
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    quote = provider.get_quote("CRUDE_OIL")

    client.quote.assert_called_with(["MCX:CRUDEOIL_FRONT_FUT"])
    assert quote.price == 6800.0
    # Internal symbol stays CRUDE_OIL so tracking/risk keys are stable
    assert quote.instrument.symbol == "CRUDE_OIL"
    assert quote.instrument.exchange.value == "MCX"


def test_resolve_option_contract_picks_nearest_expiry_atm_strike():
    from datetime import date, timedelta

    today = date.today()
    client = MagicMock()
    client.instruments.return_value = [
        # expired — must be ignored
        {"name": "NIFTY", "instrument_type": "CE", "expiry": today - timedelta(days=2), "strike": 24300.0, "tradingsymbol": "NIFTY_EXPIRED_CE", "lot_size": 75},
        # nearest expiry, three strikes
        {"name": "NIFTY", "instrument_type": "CE", "expiry": today + timedelta(days=2), "strike": 24200.0, "tradingsymbol": "NIFTY_W_24200CE", "lot_size": 75},
        {"name": "NIFTY", "instrument_type": "CE", "expiry": today + timedelta(days=2), "strike": 24300.0, "tradingsymbol": "NIFTY_W_24300CE", "lot_size": 75},
        {"name": "NIFTY", "instrument_type": "CE", "expiry": today + timedelta(days=2), "strike": 24400.0, "tradingsymbol": "NIFTY_W_24400CE", "lot_size": 75},
        # later expiry closer strike — nearest expiry must still win
        {"name": "NIFTY", "instrument_type": "CE", "expiry": today + timedelta(days=30), "strike": 24310.0, "tradingsymbol": "NIFTY_M_24310CE", "lot_size": 75},
        # wrong type
        {"name": "NIFTY", "instrument_type": "PE", "expiry": today + timedelta(days=2), "strike": 24300.0, "tradingsymbol": "NIFTY_W_24300PE", "lot_size": 75},
    ]
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24310.0)

    assert contract["tradingsymbol"] == "NIFTY_W_24300CE"
    assert contract["strike"] == 24300.0
    assert contract["lot_size"] == 75.0
    assert contract["exchange"] == "NFO"


def test_resolve_option_contract_returns_none_when_chain_empty():
    client = MagicMock()
    client.instruments.return_value = []
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)
    assert provider.resolve_option_contract("NIFTY", "CE", 24310.0) is None


def test_option_tradingsymbols_map_to_derivative_exchanges():
    client = MagicMock()
    client.quote.return_value = {"NFO:NIFTY25JUL24300CE": {"last_price": 180.0}}
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    quote = provider.get_quote("NIFTY25JUL24300CE")
    client.quote.assert_called_with(["NFO:NIFTY25JUL24300CE"])
    assert quote.price == 180.0

    client.quote.return_value = {"MCX:CRUDEOIL25JUL6800PE": {"last_price": 95.0}}
    quote = provider.get_quote("CRUDEOIL25JUL6800PE")
    client.quote.assert_called_with(["MCX:CRUDEOIL25JUL6800PE"])
    assert quote.price == 95.0


def test_index_benchmark_quotes_directly():
    client = MagicMock()
    client.quote.return_value = {"NSE:NIFTY 50": {"last_price": 24300.0}}
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    quote = provider.get_quote("NIFTY 50")

    client.quote.assert_called_with(["NSE:NIFTY 50"])
    assert quote.price == 24300.0
    client.instruments.assert_not_called()
