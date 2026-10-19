"""Naked is the failure mode, and margin is the wall.

The mandate changed on 2026-10-19 to allow short-premium spreads and never
naked shorts. Two things make that real, and both are here.

DEFINED RISK IS A TYPE, NOT A CONVENTION. A VerticalSpread cannot be built
unless the long leg genuinely caps the short leg. Measured on the live venue
that day, one NIFTY contract:

    naked SELL 22900CE      189,563 margin, UNBOUNDED loss
    as a spread 22900/23000  33,004 margin, loss capped at 2,925

Every way of getting that wrong — mismatched expiry, mismatched type, the
long leg on the wrong side, unequal quantities — leaves a short option
uncapped, so each is refused by construction rather than caught later.

MARGIN IS ASKED, NEVER MODELLED. SPAN plus exposure comes from the exchange's
proprietary risk array; a local reproduction would drift and let Hokage
believe he could afford what he could not. The oracle calls the broker's
calculation endpoint and FAILS CLOSED on every error path. There is
deliberately no fallback estimate: a fallback is consulted exactly when the
real number is missing, which is when being wrong costs most.

AND THE WALL IS REAL. ~31,000-36,000 of margin per index spread, flat across
expiries and widths, against a seed of 30,000. These tests pin the machinery;
they cannot make the account bigger.
"""
from __future__ import annotations

import datetime as dt

import pytest

from bots.execution.margin import MarginOracle, affordable
from bots.execution.spread import CALL, PUT, Leg, NotDefinedRisk, VerticalSpread

EXPIRY = dt.date(2026, 11, 23)
LOT = 65


def _leg(strike, is_short, price, option_type=CALL, expiry=EXPIRY, qty=LOT):
    return Leg(tradingsymbol=f"NIFTY26NOV{strike:.0f}{option_type}",
               exchange="NFO", option_type=option_type, strike=strike,
               expiry=expiry, quantity=qty, is_short=is_short, price=price)


def _spread(short_strike=22900.0, long_strike=23000.0, short_price=320.0,
            long_price=265.0, option_type=CALL, **kw):
    return VerticalSpread.build(
        "NIFTY",
        _leg(short_strike, True, short_price, option_type, **kw),
        _leg(long_strike, False, long_price, option_type, **kw),
        LOT)


# ------------------------------------------------- the arithmetic of "defined"
def test_max_loss_is_width_times_quantity_less_the_credit():
    s = _spread()
    assert s.width == 100.0
    assert s.net_credit == pytest.approx((320.0 - 265.0) * LOT)
    assert s.max_loss == pytest.approx(100.0 * LOT - 55.0 * LOT)
    assert s.max_profit == pytest.approx(s.net_credit)


def test_max_loss_cannot_be_supplied_by_the_caller():
    """A caller that can pass its own max loss can be wrong about it, and the
    one number this structure exists to guarantee would rest on their
    arithmetic."""
    import inspect

    assert "max_loss" not in inspect.signature(VerticalSpread.build).parameters
    assert isinstance(VerticalSpread.__dict__["max_loss"], property)


def test_a_debit_spread_is_recognised_as_one():
    """Not forbidden, but a short-premium strategy asking for one has
    mispriced its legs."""
    s = _spread(short_price=200.0, long_price=240.0)
    assert not s.is_credit
    assert s.net_credit < 0
    assert s.max_loss == pytest.approx(100.0 * LOT + 40.0 * LOT)


def test_a_put_spread_bounds_the_other_way():
    s = _spread(short_strike=22900.0, long_strike=22800.0, option_type=PUT)
    assert s.max_loss == pytest.approx(100.0 * LOT - 55.0 * LOT)


# --------------------------------------------- every way to leave it naked
def test_a_long_call_below_the_short_call_caps_nothing():
    with pytest.raises(NotDefinedRisk, match="must be higher"):
        _spread(short_strike=22900.0, long_strike=22800.0)


def test_a_long_put_above_the_short_put_caps_nothing():
    with pytest.raises(NotDefinedRisk, match="must be lower"):
        _spread(short_strike=22900.0, long_strike=23000.0, option_type=PUT)


def test_a_different_expiry_is_not_a_vertical():
    """A calendar's loss is not bounded by strike width, so the max_loss
    formula here would quietly return a number that is not the max loss."""
    with pytest.raises(NotDefinedRisk, match="calendar"):
        VerticalSpread.build(
            "NIFTY", _leg(22900.0, True, 320.0),
            _leg(23000.0, False, 265.0, expiry=dt.date(2026, 12, 29)), LOT)


def test_a_call_is_not_capped_by_a_put():
    with pytest.raises(NotDefinedRisk, match="does not cap"):
        VerticalSpread.build(
            "NIFTY", _leg(22900.0, True, 320.0),
            _leg(23000.0, False, 265.0, option_type=PUT), LOT)


def test_unequal_legs_leave_the_difference_naked():
    with pytest.raises(NotDefinedRisk, match="naked"):
        VerticalSpread.build(
            "NIFTY", _leg(22900.0, True, 320.0, qty=LOT * 2),
            _leg(23000.0, False, 265.0), LOT)


def test_two_shorts_are_not_a_spread():
    with pytest.raises(NotDefinedRisk):
        VerticalSpread.build("NIFTY", _leg(22900.0, True, 320.0),
                             _leg(23000.0, True, 265.0), LOT)


def test_two_longs_are_not_a_spread():
    with pytest.raises(NotDefinedRisk):
        VerticalSpread.build("NIFTY", _leg(22900.0, False, 320.0),
                             _leg(23000.0, False, 265.0), LOT)


def test_the_same_strike_twice_is_not_a_spread():
    with pytest.raises(NotDefinedRisk, match="same strike"):
        _spread(short_strike=22900.0, long_strike=22900.0)


def test_a_zero_quantity_leg_hedges_nothing():
    with pytest.raises(NotDefinedRisk):
        VerticalSpread.build("NIFTY", _leg(22900.0, True, 320.0, qty=0),
                             _leg(23000.0, False, 265.0, qty=0), LOT)


def test_an_unknown_option_type_is_refused():
    with pytest.raises(NotDefinedRisk):
        VerticalSpread.build(
            "NIFTY", _leg(22900.0, True, 320.0, option_type="XX"),
            _leg(23000.0, False, 265.0, option_type="XX"), LOT)


# --------------------------------------------------------- the basket order
def test_the_protective_leg_is_ordered_first():
    """If a basket is ever placed leg by leg and the second fails, what is
    left behind must be the protection, never the naked short."""
    basket = _spread().basket()
    assert basket[0]["transaction_type"] == "BUY"
    assert basket[1]["transaction_type"] == "SELL"


def test_the_basket_carries_what_the_broker_needs():
    leg = _spread().basket()[0]
    for key in ("exchange", "tradingsymbol", "transaction_type", "variety",
                "product", "order_type", "quantity"):
        assert key in leg


# ------------------------------------------------------- margin is asked for
class _Client:
    def __init__(self, reply=None, boom=None):
        self.reply = reply
        self.boom = boom
        self.calls = 0

    def basket_order_margins(self, params, consider_positions=True, mode=None):
        self.calls += 1
        if self.boom:
            raise self.boom
        return self.reply


def _reply(initial=214913.0, final=33004.0):
    return {"initial": {"total": initial}, "final": {"total": final}}


def test_the_hedged_total_is_the_one_used():
    """`initial` prices the legs separately and is six times larger. Reading
    it where `final` is meant would refuse every spread this account could
    actually hold."""
    oracle = MarginOracle(_Client(_reply()))
    assert oracle.required(_spread().basket()) == pytest.approx(33004.0)
    assert oracle.detail(_spread().basket())["hedge_benefit"] == pytest.approx(
        214913.0 - 33004.0)


def test_a_broker_error_fails_closed():
    oracle = MarginOracle(_Client(boom=RuntimeError("no session")))
    assert oracle.required(_spread().basket()) is None


def test_no_client_at_all_fails_closed():
    assert MarginOracle(None).required(_spread().basket()) is None


def test_an_empty_basket_has_no_margin_to_report():
    assert MarginOracle(_Client(_reply())).required([]) is None


def test_a_reply_missing_the_hedged_block_fails_closed():
    """If the reply shape changes, guessing which other number meant `final`
    is how an unhedged figure gets used as a hedged one."""
    oracle = MarginOracle(_Client({"initial": {"total": 1.0}}))
    assert oracle.required(_spread().basket()) is None


def test_a_zero_margin_on_a_short_leg_is_not_believed():
    """Not a gift. A broken reply that would make every spread look free."""
    oracle = MarginOracle(_Client(_reply(final=0.0)))
    assert oracle.required(_spread().basket()) is None


def test_a_non_numeric_total_fails_closed():
    oracle = MarginOracle(_Client(_reply(final="lots")))
    assert oracle.required(_spread().basket()) is None


def test_there_is_no_fallback_estimate_anywhere():
    """A fallback is consulted exactly when the real number is missing,
    which is when being wrong is least recoverable."""
    import pathlib

    import bots.execution.margin as m

    src = pathlib.Path(m.__file__).read_text(encoding="utf-8").lower()
    for banned in ("span_estimate", "approx_margin", "def _estimate",
                   "fallback_margin"):
        assert banned not in src, f"an estimate crept in: {banned}"


# ------------------------------------------------------------ the short memory
def test_a_margin_is_reused_only_briefly():
    """SPAN moves intraday with volatility. A figure from this morning is
    not evidence about this afternoon."""
    clock = [0.0]
    client = _Client(_reply())
    oracle = MarginOracle(client, clock=lambda: clock[0], max_age_seconds=180)
    basket = _spread().basket()

    oracle.required(basket)
    clock[0] = 100.0
    oracle.required(basket)
    assert client.calls == 1, "a fresh figure should have been reused"

    clock[0] = 400.0
    oracle.required(basket)
    assert client.calls == 2, "a stale figure must be asked again"


def test_a_different_basket_is_not_served_from_cache():
    client = _Client(_reply())
    oracle = MarginOracle(client)
    oracle.required(_spread().basket())
    oracle.required(_spread(long_strike=23100.0).basket())
    assert client.calls == 2


# ------------------------------------------------------------- affordability
def test_an_unknown_margin_is_never_treated_as_a_small_one():
    ok, why = affordable(_spread(), 1_000_000.0,
                         MarginOracle(_Client(boom=RuntimeError("down"))), 0.33)
    assert ok is False
    assert "could not be read" in why


def test_the_real_seed_cannot_hold_one_index_spread():
    """THE WALL, as a test. 33,004 of margin against a 30,000 seed, and the
    33% ceiling means it does not come close."""
    ok, why = affordable(_spread(), 30_000.0, MarginOracle(_Client(_reply())),
                         0.33)
    assert ok is False
    assert "exceeds" in why


def test_a_large_enough_account_can():
    ok, why = affordable(_spread(), 150_000.0, MarginOracle(_Client(_reply())),
                         0.33)
    assert ok is True


def test_an_empty_account_is_refused_before_anything_else():
    ok, why = affordable(_spread(), 0.0, MarginOracle(_Client(_reply())), 0.33)
    assert ok is False
    assert "no cash" in why
