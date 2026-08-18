"""SENSEX had never once faced the volume gate.

2026-08-18: across 200 volume rejections in Hokage's history, every single one
was NIFTY or BANKNIFTY and not one was SENSEX.

An NSE/BSE index has no traded volume of its own — Kite reports volume 0 on
NIFTY 50 and None on BSE:SENSEX. NIFTY and BANKNIFTY got a real volume series by
ACCIDENT: they sit in _FUTURES_UNDERLYINGS, so _kite_quote_symbol resolves them
to NFO front-month futures. SENSEX is matched earlier by _INDEX_QUOTE_SYMBOLS
and resolves to BSE:SENSEX, the index itself. _get_volume_context saw today's
volume as 0, returned None, and the caller then SKIPPED the gate entirely.

The arena is a tournament whose premise is that strategies face the same test on
every asset. On SENSEX one of the two largest gates silently did not exist.

The old comment on _BSE_INDEX_UNDERLYINGS claimed "there is no BSE index futures
contract". There is: SENSEX26AUGFUT and later months list on BFO with real
volume (11,840 contracts and 46,420 open interest on the day this was found,
with 154 of 155 fifteen-minute bars carrying volume).

VOLUME ONLY. Price, ATR, the bias engine and strike selection still read the
index, because a futures price carries a basis — ~45 points on NIFTY against a
50-point strike interval — and index options settle on the index.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
from integrations.data.models import CandleInterval


class _Kite:
    """Enough of KiteConnect to resolve a front-month future."""

    def __init__(self, contracts=None, rows=None) -> None:
        today = datetime.now().date()
        self._contracts = contracts if contracts is not None else {
            "BFO": [
                {"name": "SENSEX", "instrument_type": "FUT",
                 "expiry": today + timedelta(days=9), "tradingsymbol": "SENSEX26AUGFUT"},
                {"name": "SENSEX", "instrument_type": "FUT",
                 "expiry": today + timedelta(days=37), "tradingsymbol": "SENSEX26SEPFUT"},
            ],
            "NFO": [
                {"name": "NIFTY", "instrument_type": "FUT",
                 "expiry": today + timedelta(days=9), "tradingsymbol": "NIFTY26AUGFUT"},
            ],
            "MCX": [
                {"name": "CRUDEOIL", "instrument_type": "FUT",
                 "expiry": today + timedelta(days=20), "tradingsymbol": "CRUDEOIL26SEPFUT"},
            ],
        }
        self._rows = rows if rows is not None else [
            {"date": datetime(2026, 8, 18, 9, 15), "open": 1.0, "high": 2.0,
             "low": 0.5, "close": 1.5, "volume": 3000},
        ]
        self.historical_calls: list[int] = []

    def instruments(self, exchange):
        return self._contracts.get(exchange, [])

    def quote(self, symbols):
        return {symbols[0]: {"instrument_token": 12345, "last_price": 77515.0}}

    def historical_data(self, instrument_token, from_date, to_date, interval):
        self.historical_calls.append(instrument_token)
        return self._rows


class _CM:
    def __init__(self, kite) -> None:
        self._kite = kite

    def get_kite_client(self):
        return self._kite


def _provider(kite=None):
    return KiteMarketDataProvider(_CM(kite or _Kite()))


# ------------------------------------------------------------ symbol resolution
def test_sensex_now_resolves_to_its_bfo_future():
    """The whole bug in one assertion."""
    assert _provider().volume_series_symbol("SENSEX") == "BFO:SENSEX26AUGFUT"


def test_nifty_keeps_the_nfo_series_it_already_had():
    assert _provider().volume_series_symbol("NIFTY") == "NFO:NIFTY26AUGFUT"


def test_the_front_month_is_chosen_not_just_any_contract():
    assert "AUG" in _provider().volume_series_symbol("SENSEX")


def test_an_mcx_underlying_maps_through_its_kite_name():
    assert _provider().volume_series_symbol("CRUDEOIL") == "MCX:CRUDEOIL26SEPFUT"


def test_an_unknown_symbol_returns_none_rather_than_guessing():
    """None makes the caller SKIP its gate. Measuring zero volume and calling
    that a thin tape would reject every entry on a symbol we simply cannot
    measure."""
    assert _provider().volume_series_symbol("INFY") is None


def test_a_symbol_with_no_live_contract_returns_none():
    kite = _Kite(contracts={"BFO": []})
    assert _provider(kite).volume_series_symbol("SENSEX") is None


# ---------------------------------------------------------------- candle fetch
def test_candles_come_back_with_volume_for_sensex():
    candles = _provider().get_volume_candles(
        "SENSEX",
        datetime.now(timezone.utc) - timedelta(days=14),
        datetime.now(timezone.utc),
        CandleInterval.FIFTEEN_MINUTES,
    )
    assert len(candles) == 1
    assert candles[0].volume == 3000.0


def test_no_series_means_no_candles_and_no_exception():
    candles = _provider().get_volume_candles(
        "INFY",
        datetime.now(timezone.utc) - timedelta(days=1),
        datetime.now(timezone.utc),
        CandleInterval.FIFTEEN_MINUTES,
    )
    assert candles == ()


def test_a_broken_history_call_returns_empty_rather_than_raising():
    """Volume is a gate input, never a reason to crash the entry scan."""

    class _Boom(_Kite):
        def historical_data(self, **kwargs):
            raise RuntimeError("kite is down")

    candles = _provider(_Boom()).get_volume_candles(
        "SENSEX",
        datetime.now(timezone.utc) - timedelta(days=1),
        datetime.now(timezone.utc),
        CandleInterval.FIFTEEN_MINUTES,
    )
    assert candles == ()


# ------------------------------------------------------- the map itself
def test_every_tradable_underlying_has_a_volume_series():
    """A missing entry silently exempts an asset from the gate — exactly how
    SENSEX went unnoticed. Pin the whole tradable universe."""
    mapped = KiteMarketDataProvider._VOLUME_SERIES_EXCHANGES
    for symbol in ("NIFTY", "BANKNIFTY", "SENSEX",
                   "CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"):
        assert symbol in mapped, f"{symbol} has no volume series and would be exempt"


def test_index_price_resolution_is_untouched():
    """Strike selection and every price read must still see the INDEX. If this
    ever resolves to a future, ATM drifts by most of a strike step on every
    index trade."""
    assert KiteMarketDataProvider._OPTION_STRIKE_SPOT_SYMBOLS["SENSEX"] == ("BSE", "SENSEX")
    assert KiteMarketDataProvider._OPTION_STRIKE_SPOT_SYMBOLS["NIFTY"] == ("NSE", "NIFTY 50")
