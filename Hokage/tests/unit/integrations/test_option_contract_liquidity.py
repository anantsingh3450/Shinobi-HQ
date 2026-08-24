"""Never buy an option contract that has no market.

2026-08-24. SILVERM26AUG expired that day, so the 2-DTE floor correctly pushed
selection to the September chain. ATM-only strike picking then chose:

    SILVERM26SEP251000CE    volume 0    open interest 1

and that 1 was Hokage's own paper position. He put 63,805 into it — 29.6% of
SessionShift's chest, the largest bet he has ever placed. The underlying then
moved 934 points against him and the premium never ticked, so every
premium-based rung (adaptive target, trail lock, hard backstop) was blind. Only
the UNDERLYING thesis stop could see anything, and the trade closed at exactly
0.00.

A LIQUID STRIKE WAS ONE STEP AWAY:

    SILVERM26SEP250000CE    volume 5,122    open interest 1,794

0.4% further from ATM.

Measured ATM open interest across every asset Hokage trades:

    NIFTY 2,674,100   SENSEX 306,520   BANKNIFTY 80,460
    GOLDM     1,432   CRUDEOIL  1,335  NATURALGAS   945
    SILVERM       1   <- the only failure

So the floor separates dead from live with three orders of magnitude to spare
and changes nothing about the other six.
"""
from __future__ import annotations

from datetime import date

import pytest

from integrations.brokers.kite_market_data_provider import (
    KiteMarketDataProvider as Provider,
)

FLOOR = Provider._MIN_OPTION_OPEN_INTEREST
WINDOW = Provider._LIQUIDITY_STRIKE_WINDOW


class _Client:
    def __init__(self, book: dict, fail: bool = False):
        self._book = book
        self._fail = fail
        self.calls = 0

    def quote(self, symbols):
        self.calls += 1
        if self._fail:
            raise ConnectionError("kt-quotes unreachable")
        return {s: {"oi": self._book.get(s.split(":")[1], 0)} for s in symbols}


def _provider(book, fail=False):
    p = object.__new__(Provider)

    class _CM:
        def get_kite_client(self_inner):
            return client

    client = _Client(book, fail)
    p._connection_manager = _CM()
    return p, client


def _cand(symbol, distance):
    """(expiry, distance_from_atm, strike, instrument) as the resolver builds it."""
    return (date(2026, 9, 24), distance, 0.0, {"tradingsymbol": symbol})


# ------------------------------------------------------- the 2026-08-24 chain
SILVERM_CHAIN = [
    _cand("SILVERM26SEP251000CE", 399),
    _cand("SILVERM26SEP250000CE", 601),
    _cand("SILVERM26SEP252000CE", 1399),
    _cand("SILVERM26SEP249000CE", 1601),
]
SILVERM_BOOK = {
    "SILVERM26SEP251000CE": 1,
    "SILVERM26SEP250000CE": 1794,
    "SILVERM26SEP252000CE": 5,
    "SILVERM26SEP249000CE": 1,
}


def test_the_dead_atm_strike_is_skipped_for_the_liquid_one():
    p, _ = _provider(SILVERM_BOOK)
    chosen = p._closest_liquid(SILVERM_CHAIN, "MCX")
    assert chosen is not None
    assert chosen[3]["tradingsymbol"] == "SILVERM26SEP250000CE"


def test_a_healthy_atm_strike_is_still_taken_first():
    """GOLDM's ATM had 1,432 OI. Nothing about it should change."""
    chain = [_cand("GOLDM26AUG162500CE", 238), _cand("GOLDM26AUG162000CE", 262)]
    p, _ = _provider({"GOLDM26AUG162500CE": 1432, "GOLDM26AUG162000CE": 3041})
    assert p._closest_liquid(chain, "MCX")[3]["tradingsymbol"] == "GOLDM26AUG162500CE"


@pytest.mark.parametrize("symbol,oi", [
    ("NIFTY2690124700CE", 2674100),
    ("SENSEX26AUG80500CE", 306520),
    ("BANKNIFTY26SEP57400CE", 80460),
    ("CRUDEOIL26SEP8250CE", 1335),
    ("NATURALGAS26SEP265CE", 945),
])
def test_every_healthy_asset_still_clears_the_floor(symbol, oi):
    p, _ = _provider({symbol: oi})
    assert p._closest_liquid([_cand(symbol, 10)], "MCX") is not None, symbol


def test_a_chain_with_no_market_anywhere_returns_nothing():
    """Standing aside is the correct answer. Buying the least-dead strike is
    not a fallback, it is the same mistake with extra steps."""
    p, _ = _provider({c[3]["tradingsymbol"]: 1 for c in SILVERM_CHAIN})
    assert p._closest_liquid(SILVERM_CHAIN, "MCX") is None


def test_exactly_at_the_floor_is_accepted():
    p, _ = _provider({"X": FLOOR})
    assert p._closest_liquid([_cand("X", 1)], "MCX") is not None


def test_one_below_the_floor_is_rejected():
    p, _ = _provider({"X": FLOOR - 1})
    assert p._closest_liquid([_cand("X", 1)], "MCX") is None


# ------------------------------------------------------------- failure modes
def test_a_quote_failure_falls_back_to_atm_rather_than_starving():
    """No liquidity evidence either way. Refusing every trade on a transient API
    hiccup would starve the arena — the same reasoning the volume gate uses when
    its context is unavailable."""
    p, _ = _provider(SILVERM_BOOK, fail=True)
    chosen = p._closest_liquid(SILVERM_CHAIN, "MCX")
    assert chosen[3]["tradingsymbol"] == "SILVERM26SEP251000CE"


def test_a_missing_or_junk_oi_field_counts_as_no_market():
    p = object.__new__(Provider)

    class _CM:
        def get_kite_client(self_inner):
            class _C:
                def quote(self, symbols):
                    return {s: {"oi": None} for s in symbols}
            return _C()

    p._connection_manager = _CM()
    assert p._closest_liquid([_cand("X", 1)], "MCX") is None


def test_an_empty_chain_returns_nothing():
    p, _ = _provider({})
    assert p._closest_liquid([], "MCX") is None


def test_the_quote_call_is_bounded_by_the_strike_window():
    """Each candidate costs a quote; a 176-strike chain must not be priced in
    full on every entry."""
    chain = [_cand(f"S{i}", i) for i in range(50)]
    p, client = _provider({f"S{i}": 0 for i in range(50)})
    p._closest_liquid(chain, "MCX")
    assert client.calls == 1


def test_the_resolver_stands_aside_when_nothing_is_liquid():
    """Guards the call site: _closest_liquid returning None must abort the
    resolution, not fall through to the old ATM pick."""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(Provider.resolve_option_contract))
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "_closest_liquid"]
    assert calls, "resolve_option_contract must consult _closest_liquid"
    assert "if atm is None:" in src, "a None result must abort the resolution"
