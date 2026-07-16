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
from integrations.data.models import AssetClass, Exchange


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


def test_resolve_option_contract_mcx_lot_size_uses_contract_multiplier():
    """MCX reports lot_size=1 (per-contract) for CRUDEOIL options AND its
    underlying futures in the live instruments dump — there is no larger lot
    to borrow from within the dump. The resolver must apply MCX's published
    contract-size multiplier (100 barrels/lot for CRUDEOIL) instead."""
    from datetime import date, timedelta

    today = date.today()
    client = MagicMock()
    client.instruments.return_value = [
        {"name": "CRUDEOIL", "instrument_type": "FUT", "expiry": today + timedelta(days=10),
         "strike": 0, "tradingsymbol": "CRUDEOIL26JULFUT", "lot_size": 1},
        {"name": "CRUDEOIL", "instrument_type": "CE", "expiry": today + timedelta(days=2),
         "strike": 7750.0, "tradingsymbol": "CRUDEOIL26JUL7750CE", "lot_size": 1},
        {"name": "CRUDEOIL", "instrument_type": "CE", "expiry": today + timedelta(days=2),
         "strike": 7800.0, "tradingsymbol": "CRUDEOIL26JUL7800CE", "lot_size": 1},
    ]
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    contract = provider.resolve_option_contract("CRUDEOIL", "CE", spot_price=7747.0)
    assert contract["tradingsymbol"] == "CRUDEOIL26JUL7750CE"
    assert contract["lot_size"] == 100.0
    assert contract["exchange"] == "MCX"


def test_resolve_option_contract_mcx_unlisted_commodity_keeps_dump_lot_size():
    """A MCX commodity with no multiplier entry (not authorised for trading)
    must NOT get a fabricated lot size — the raw dump value passes through."""
    from datetime import date, timedelta

    today = date.today()
    client = MagicMock()
    client.instruments.return_value = [
        {"name": "GOLD", "instrument_type": "CE", "expiry": today + timedelta(days=2),
         "strike": 70000.0, "tradingsymbol": "GOLD26JUL70000CE", "lot_size": 1},
    ]
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    contract = provider.resolve_option_contract("GOLD", "CE", spot_price=70000.0)
    assert contract["lot_size"] == 1.0


def test_historical_candles_request_window_converted_to_ist():
    """Kite reads historical_data timestamps as exchange-local (IST) and drops
    tzinfo. Passing UTC straight through made "now" (e.g. 05:01 UTC) read as
    05:01 IST — before the 09:15 open — silently truncating the whole current
    session, so the bias engine and ATR ran on yesterday's candles."""
    from datetime import datetime, timezone, timedelta
    from integrations.data.models import HistoricalDataRequest, CandleInterval, Instrument, AssetClass, Exchange

    client = MagicMock()
    client.quote.return_value = {"NSE:INFY": {"instrument_token": 123}}
    client.historical_data.return_value = []
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    provider = KiteMarketDataProvider(manager)

    # 05:01 UTC == 10:31 IST (i.e. mid-session, after the 09:15 open)
    end_utc = datetime(2026, 7, 15, 5, 1, tzinfo=timezone.utc)
    start_utc = end_utc - timedelta(days=3)
    provider.get_historical_candles(
        HistoricalDataRequest(
            instrument=Instrument(
                symbol="INFY", asset_class=AssetClass.INDIAN_EQUITY,
                exchange=Exchange.NSE, currency="INR",
            ),
            start=start_utc,
            end=end_utc,
            interval=CandleInterval.FIFTEEN_MINUTES,
        )
    )

    kwargs = client.historical_data.call_args.kwargs
    # The window handed to Kite must be on the exchange clock, not UTC.
    assert kwargs["to_date"].hour == 10 and kwargs["to_date"].minute == 31
    assert kwargs["to_date"].utcoffset() == timedelta(hours=5, minutes=30)
    assert kwargs["from_date"].utcoffset() == timedelta(hours=5, minutes=30)


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


class TestMinimumDaysToExpiry:
    """Hokage BUYS options, so theta is already working against it.

    The resolver picks the NEAREST expiry, and the exchanges list contracts
    expiring the SAME DAY. On 2026-07-15 that bought CRUDEOIL26JUL7750CE — OTM
    with one day of life — for ~Rs 63 a barrel. It was cheap because it was
    nearly dead, and it exited at breakeven. A 0-1 DTE option is a lottery
    ticket whose premium decays to zero within hours.
    """

    @staticmethod
    def _client(*expiry_offsets):
        from datetime import date, timedelta

        today = date.today()
        client = MagicMock()
        client.instruments.return_value = [
            {
                "name": "NIFTY", "instrument_type": "CE",
                "expiry": today + timedelta(days=d), "strike": 24300.0,
                "tradingsymbol": f"NIFTY_D{d}_24300CE", "lot_size": 65,
            }
            for d in expiry_offsets
        ]
        manager = MagicMock()
        manager.get_kite_client.return_value = client
        return KiteMarketDataProvider(manager)

    def test_same_day_expiry_is_refused(self):
        """0 DTE must never be selected, even though it is the nearest."""
        provider = self._client(0, 7)
        contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24300.0)
        assert contract["tradingsymbol"] == "NIFTY_D7_24300CE"

    def test_next_day_expiry_is_refused(self):
        """1 DTE — the exact crude contract bought on 2026-07-15."""
        provider = self._client(1, 9)
        contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24300.0)
        assert contract["tradingsymbol"] == "NIFTY_D9_24300CE"

    def test_two_days_is_the_accepted_floor(self):
        provider = self._client(2, 30)
        contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24300.0)
        assert contract["tradingsymbol"] == "NIFTY_D2_24300CE"

    def test_no_contract_with_enough_life_returns_none_not_a_dying_one(self):
        """Doctrine: fail closed. No tradable expiry means no trade — never
        fall back to the expiring contract just to have something to buy."""
        provider = self._client(0, 1)
        assert provider.resolve_option_contract("NIFTY", "CE", spot_price=24300.0) is None

    def test_expired_contracts_still_ignored(self):
        from datetime import date, timedelta

        today = date.today()
        client = MagicMock()
        client.instruments.return_value = [
            {"name": "NIFTY", "instrument_type": "CE", "expiry": today - timedelta(days=3),
             "strike": 24300.0, "tradingsymbol": "NIFTY_EXPIRED_CE", "lot_size": 65},
            {"name": "NIFTY", "instrument_type": "CE", "expiry": today + timedelta(days=5),
             "strike": 24300.0, "tradingsymbol": "NIFTY_LIVE_CE", "lot_size": 65},
        ]
        manager = MagicMock()
        manager.get_kite_client.return_value = client
        provider = KiteMarketDataProvider(manager)
        contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24300.0)
        assert contract["tradingsymbol"] == "NIFTY_LIVE_CE"


class TestBseIndexOptionRouting:
    """SENSEX options live on BFO, a different segment from NFO.

    Kite reports TRUE lot sizes for NFO/BFO (NIFTY=65, SENSEX=20) but reports 1
    for every MCX chain — which is why the tradable universe is index options.
    """

    def test_sensex_resolves_on_bfo_with_the_dump_lot_size(self):
        from datetime import date, timedelta

        today = date.today()
        client = MagicMock()
        client.instruments.return_value = [
            {"name": "SENSEX", "instrument_type": "CE", "expiry": today + timedelta(days=7),
             "strike": 77300.0, "tradingsymbol": "SENSEX2672377300CE", "lot_size": 20},
        ]
        manager = MagicMock()
        manager.get_kite_client.return_value = client
        provider = KiteMarketDataProvider(manager)

        contract = provider.resolve_option_contract("SENSEX", "CE", spot_price=77342.0)

        assert contract["exchange"] == "BFO"
        assert contract["lot_size"] == 20.0
        client.instruments.assert_called_once_with("BFO")

    def test_sensex_instrument_is_a_bse_index_not_an_nse_equity(self):
        provider = KiteMarketDataProvider(MagicMock())
        inst = provider.resolve_instrument("SENSEX")
        assert inst.exchange == Exchange.BSE
        assert inst.asset_class == AssetClass.INDEX

    def test_bse_option_symbol_quotes_on_bfo(self):
        provider = KiteMarketDataProvider(MagicMock())
        assert provider._kite_quote_symbol("SENSEX2672377300CE") == "BFO:SENSEX2672377300CE"

    def test_banknifty_symbol_does_not_match_the_shorter_nifty_prefix(self):
        """Prefix order matters: BANKNIFTY must not be shadowed by NIFTY."""
        provider = KiteMarketDataProvider(MagicMock())
        assert provider._kite_quote_symbol("BANKNIFTY26JUL57800CE") == "NFO:BANKNIFTY26JUL57800CE"
        assert provider._kite_quote_symbol("NIFTY2672124150CE") == "NFO:NIFTY2672124150CE"
