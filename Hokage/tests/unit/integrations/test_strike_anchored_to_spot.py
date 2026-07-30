"""Index option strikes must be measured from the INDEX, not the futures.

`get_price("NIFTY")` returns the NFO futures price, because _FUTURES_UNDERLYINGS
maps NIFTY to the futures chain. Index options are cash-settled on the index, so
choosing a strike off the futures price skews ATM by the basis. On 2026-07-30 the
entry anchor was 24,321.60 while spot NIFTY's 09:45 bar high was 24,285.55 — a
~45-point basis against a 50-point strike interval, i.e. nearly a full strike:
calls further OTM, puts further ITM, on every index trade.

MCX is the opposite case and must NOT be changed: commodity options there are
options ON the futures contract and exercise into a futures position, so the
futures price is already their correct reference.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider


def _provider(chain, spot_quote=None):
    client = MagicMock()
    client.instruments.return_value = chain
    if spot_quote is None:
        client.quote.side_effect = Exception("no spot feed")
    else:
        client.quote.return_value = spot_quote
    manager = MagicMock()
    manager.get_kite_client.return_value = client
    return KiteMarketDataProvider(manager), client


def _nifty_chain():
    expiry = date.today() + timedelta(days=5)
    return [
        {"name": "NIFTY", "instrument_type": "CE", "expiry": expiry,
         "strike": float(s), "tradingsymbol": f"NIFTY_W_{s}CE", "lot_size": 75}
        for s in (24200, 24250, 24300, 24350)
    ]


def test_strike_follows_spot_not_the_futures_reference():
    """A 45-point basis — the size actually observed on 2026-07-30 — against a
    50-point strike ladder is enough to move the ATM choice a full step."""
    provider, client = _provider(
        _nifty_chain(), spot_quote={"NSE:NIFTY 50": {"last_price": 24260.00}}
    )
    contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24305.00)

    # Futures 24,305 is nearest 24,300 (5.0 vs 55.0). True spot 24,260 is
    # nearest 24,250 (10.0 vs 40.0). The old code bought the wrong one.
    assert contract["strike"] == 24250.0
    client.quote.assert_called_once_with(["NSE:NIFTY 50"])


def test_banknifty_uses_its_own_index_symbol():
    expiry = date.today() + timedelta(days=5)
    chain = [
        {"name": "BANKNIFTY", "instrument_type": "PE", "expiry": expiry,
         "strike": float(s), "tradingsymbol": f"BANKNIFTY_W_{s}PE", "lot_size": 30}
        for s in (56900, 57000, 57100)
    ]
    provider, client = _provider(chain, spot_quote={"NSE:NIFTY BANK": {"last_price": 56923.10}})
    contract = provider.resolve_option_contract("BANKNIFTY", "PE", spot_price=57147.50)

    assert contract["strike"] == 56900.0
    client.quote.assert_called_once_with(["NSE:NIFTY BANK"])


def test_mcx_keeps_the_futures_reference_and_never_asks_for_a_spot():
    """Commodity options are options ON futures — futures IS the right anchor."""
    expiry = date.today() + timedelta(days=10)
    chain = [
        {"name": "CRUDEOIL", "instrument_type": "CE", "expiry": expiry,
         "strike": float(s), "tradingsymbol": f"CRUDEOIL26AUG{s}CE", "lot_size": 1}
        for s in (7700, 7750, 7800)
    ]
    provider, client = _provider(chain, spot_quote={"IRRELEVANT": {"last_price": 1.0}})
    contract = provider.resolve_option_contract("CRUDEOIL", "CE", spot_price=7747.0)

    assert contract["strike"] == 7750.0
    client.quote.assert_not_called()


def test_missing_spot_quote_falls_back_instead_of_refusing_to_trade():
    """A ~0.2% basis is a reason to pick a slightly worse strike, not to halt."""
    provider, _ = _provider(_nifty_chain(), spot_quote=None)
    contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24321.60)
    assert contract["strike"] == 24300.0


def test_absurd_spot_quote_is_rejected_rather_than_anchoring_a_wild_strike():
    """A MagicMock-shaped 1.0, or a bad tick, must not buy the lowest strike."""
    provider, _ = _provider(_nifty_chain(), spot_quote={"NSE:NIFTY 50": {"last_price": 1.0}})
    contract = provider.resolve_option_contract("NIFTY", "CE", spot_price=24321.60)

    assert contract["strike"] == 24300.0   # fell back to the reference
    assert contract["strike"] != 24200.0   # would have been the wild pick


def test_basis_guard_threshold_is_five_percent():
    assert KiteMarketDataProvider._MAX_SPOT_BASIS_PCT == 0.05


def test_mcx_is_deliberately_absent_from_the_spot_table():
    table = KiteMarketDataProvider._OPTION_STRIKE_SPOT_SYMBOLS
    for commodity in ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM", "GOLD", "SILVER"):
        assert commodity not in table
    for index in ("NIFTY", "BANKNIFTY", "SENSEX", "BANKEX"):
        assert index in table
