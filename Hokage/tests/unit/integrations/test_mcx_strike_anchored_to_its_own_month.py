"""An MCX strike must be measured against the month it is bought from.

2026-10-22. NATURALGAS could not resolve a contract for an entire session:

    No NATURALGAS CE strike at 2026-11-20 carries open interest >= 100.
    Standing aside rather than buying a contract with no market.

The open-interest floor was doing exactly its job. Its INPUT was wrong.
Measured against the live venue that morning:

    MCX:NATURALGAS26OCTFUT   262.1   <- what get_price("NATURALGAS") returns
    MCX:NATURALGAS26NOVFUT   304.2   <- what the NOV option chain prices off
                             +16.1%

The October OPTIONS expired 2026-10-23, one day out, so `_MIN_DAYS_TO_EXPIRY`
correctly skipped them and selected the November chain. The strike reference
still came from the front-month FUTURE, so distance-to-ATM was measured from
262 across a chain whose money sat at 304. The nine-strike window landed on
deep in-the-money November calls that nobody trades:

    anchored 262.1                      anchored 304.2
      strike 260  oi    0                 strike 300  oi 1505
      strike 265  oi    0                 strike 310  oi 1027
      strike 270  oi   10                 strike 320  oi 1621
      max OI 10  -> REFUSED               max OI 1621 -> PASS

THIS IS NOT A GAS BUG. Every MCX asset hits it for the few days around each
option roll, whenever the near option expiry falls inside the 2-DTE floor.
Gas merely has the largest calendar spread — a seasonal curve — so it failed
loudly instead of quietly buying a strike a little off the money. The old
code's comment, "MCX options are options on futures and correctly keep the
reference passed in", is true only while the option expiry and the reference
future are the SAME contract month.

The fix mirrors the one already here for indices: NFO/BFO re-anchor to the
index those options settle on, and MCX now re-anchors to the FUTURE THE
SELECTED OPTION EXPIRY SETTLES AGAINST. Fails open the same way, and says so
at WARNING, because a check that silently stops checking is worse than one
that was never added.
"""
from __future__ import annotations

from datetime import date

import pytest

from integrations.brokers.kite_market_data_provider import (
    KiteMarketDataProvider as Provider,
)

#: The real curve on 2026-10-22, from the live instruments dump.
OCT_FUT, NOV_FUT, DEC_FUT = 262.1, 304.2, 347.0

CONTRACTS = [
    {"name": "NATURALGAS", "instrument_type": "FUT",
     "tradingsymbol": "NATURALGAS26OCTFUT", "expiry": date(2026, 10, 27), "strike": 0},
    {"name": "NATURALGAS", "instrument_type": "FUT",
     "tradingsymbol": "NATURALGAS26NOVFUT", "expiry": date(2026, 11, 24), "strike": 0},
    {"name": "NATURALGAS", "instrument_type": "FUT",
     "tradingsymbol": "NATURALGAS26DECFUT", "expiry": date(2026, 12, 28), "strike": 0},
    # A different product's future, to prove the lookup is scoped by name.
    {"name": "CRUDEOIL", "instrument_type": "FUT",
     "tradingsymbol": "CRUDEOIL26NOVFUT", "expiry": date(2026, 11, 19), "strike": 0},
]

PRICES = {
    "MCX:NATURALGAS26OCTFUT": OCT_FUT,
    "MCX:NATURALGAS26NOVFUT": NOV_FUT,
    "MCX:NATURALGAS26DECFUT": DEC_FUT,
    "MCX:CRUDEOIL26NOVFUT": 5000.0,
}


class _Client:
    def __init__(self, fail: bool = False, prices: dict | None = None):
        self.fail = fail
        self.prices = PRICES if prices is None else prices
        self.asked: list[list[str]] = []

    def quote(self, symbols):
        self.asked.append(list(symbols))
        if self.fail:
            raise ConnectionError("kt-quotes unreachable")
        return {s: {"last_price": self.prices.get(s, 0.0)} for s in symbols
                if s in self.prices}


def _provider(client):
    p = object.__new__(Provider)

    class _CM:
        def get_kite_client(self_inner):
            return client

    p._connection_manager = _CM()
    return p


# ----------------------------------------------- picking the right future
def test_it_anchors_to_the_future_the_option_expiry_settles_against():
    """The November option settles on the November future, not October's."""
    p = _provider(_Client())
    assert p._mcx_future_for_expiry(
        "NATURALGAS", date(2026, 11, 20), CONTRACTS) == NOV_FUT


def test_the_front_month_is_used_when_the_front_chain_is_the_one_chosen():
    """Nothing changes on an ordinary day. The October option expiring
    2026-10-23 settles on the October future."""
    p = _provider(_Client())
    assert p._mcx_future_for_expiry(
        "NATURALGAS", date(2026, 10, 23), CONTRACTS) == OCT_FUT


def test_a_future_settling_before_the_option_is_never_its_underlying():
    """December options cannot settle on a November future. The only valid
    answer is a future expiring on or after the option."""
    p = _provider(_Client())
    assert p._mcx_future_for_expiry(
        "NATURALGAS", date(2026, 12, 23), CONTRACTS) == DEC_FUT


def test_the_lookup_is_scoped_to_the_right_product():
    """CRUDEOIL26NOVFUT expires 2026-11-19, BEFORE the gas option — and is a
    different product besides. Matching on expiry alone would have taken it."""
    p = _provider(_Client())
    assert p._mcx_future_for_expiry(
        "NATURALGAS", date(2026, 11, 20), CONTRACTS) == NOV_FUT


# ------------------------------------------------------- failing open, loudly
def test_a_quote_failure_keeps_the_reference_rather_than_refusing(caplog):
    """No evidence is not evidence of a wrong month. Starving the arena on an
    API hiccup is the fault this codebase keeps paying for, so it falls back
    to the caller's reference — and says so."""
    p = _provider(_Client(fail=True))
    with caplog.at_level("WARNING"):
        assert p._mcx_future_for_expiry(
            "NATURALGAS", date(2026, 11, 20), CONTRACTS) is None
    assert "may be the wrong month" in caplog.text


def test_no_matching_future_at_all_returns_none_rather_than_guessing():
    p = _provider(_Client())
    assert p._mcx_future_for_expiry(
        "NATURALGAS", date(2027, 6, 1), CONTRACTS) is None


def test_a_zero_price_is_not_an_anchor():
    """A future quoting 0.00 is a dead read, not a free contract — the same
    rule the premium archive applies."""
    p = _provider(_Client(prices={"MCX:NATURALGAS26NOVFUT": 0.0}))
    assert p._mcx_future_for_expiry(
        "NATURALGAS", date(2026, 11, 20), CONTRACTS) is None


def test_it_prices_exactly_one_future_not_the_whole_curve():
    """Each quote costs a call inside the entry path."""
    client = _Client()
    _provider(client)._mcx_future_for_expiry(
        "NATURALGAS", date(2026, 11, 20), CONTRACTS)
    assert client.asked == [["MCX:NATURALGAS26NOVFUT"]]


# --------------------------------------------------- the failure, reproduced
#: The real November CE chain around the money, open interest from the live
#: venue on 2026-10-22. Anchored to October this window is all zeros; anchored
#: to November it clears the floor with an order of magnitude to spare.
NOV_CE_OI = {
    240.0: 0, 245.0: 0, 250.0: 0, 255.0: 0, 260.0: 0, 265.0: 0,
    270.0: 10, 275.0: 0, 280.0: 0, 285.0: 0, 290.0: 158, 295.0: 5,
    300.0: 1505, 305.0: 54, 310.0: 1027, 315.0: 32, 320.0: 1621, 325.0: 105,
}


def _window(reference: float) -> list[float]:
    """The strikes the resolver would consider, nearest-first."""
    return sorted(NOV_CE_OI, key=lambda s: abs(s - reference))[
        : Provider._LIQUIDITY_STRIKE_WINDOW]


@pytest.mark.parametrize("reference,expected", [(OCT_FUT, False), (NOV_FUT, True)])
def test_the_anchor_decides_whether_gas_can_trade_at_all(reference, expected):
    """The whole bug in one assertion: same chain, same floor, same day — only
    the reference month differs, and it is the difference between a liquid
    at-the-money call and a refusal."""
    best = max(NOV_CE_OI[s] for s in _window(reference))
    cleared = best >= Provider._MIN_OPTION_OPEN_INTEREST
    assert cleared is expected, (
        f"anchored at {reference}, best open interest in the window was {best} "
        f"against a floor of {Provider._MIN_OPTION_OPEN_INTEREST}"
    )


def test_the_open_interest_floor_itself_is_untouched():
    """This was never a liquidity-rule problem, and the fix must not quietly
    become one. The 2-DTE floor is likewise unchanged — it chose the right
    chain; only the ruler was wrong."""
    assert Provider._MIN_OPTION_OPEN_INTEREST == 100
    assert Provider._MIN_DAYS_TO_EXPIRY == 2
    assert Provider._LIQUIDITY_STRIKE_WINDOW == 9
