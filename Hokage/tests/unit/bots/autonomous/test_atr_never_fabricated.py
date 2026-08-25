"""An unknown ATR must stay unknown, and must stop the entry that needs it.

2026-08-25. A Kite rate limit failed GOLDM's ATR calculation twice. The old
fallback returned 1.5% of price:

    GOLDM price 160,907  ->  fabricated ATR 2,413.6
    thesis stop = 1.25 x ATR = 3,017 points
    real GOLDM ATR that week: 345.29 and 246.64
    -> a stop SEVEN TIMES too wide

and if even the price fetch failed, it returned a literal 1.0.

A fabricated risk number is worse than a missing one, because every rung
downstream treats it as measured. The two GOLDM trades the previous week
stopped out after 563 and 321 points; a 3,017-point stop would never have fired
at all, and the position would have looked protected the entire time.

Then, one second after that failure, Hokage OPENED a GOLDM position — because
ATR was fetched after the fill, purely for tracking. The most-used exit in the
system could not be sized, and nothing stopped the entry.

Everything else in the ladder already refuses to guess: the volume gate skips
when its context is unavailable, the liquidity check falls back and says so,
excursions record None rather than 0.0. ATR was the last place still inventing.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Boom:
    """Every data path fails — the rate-limited case."""

    def resolve_instrument(self, symbol):
        raise ConnectionError("Too many requests")

    def get_historical_candles(self, req):
        raise ConnectionError("Too many requests")

    def get_price(self, symbol):
        raise ConnectionError("Too many requests")


class _NoCandlesButPriced:
    """History unavailable, price fine — the case the old fallback served."""

    def resolve_instrument(self, symbol):
        return object()

    def get_historical_candles(self, req):
        raise ConnectionError("Too many requests")

    def get_price(self, symbol):
        return 160907.0


def _bot(source):
    bot = object.__new__(Bot)

    class _Orch:
        price_source = source

    bot.orchestrator = _Orch()
    return bot


# ------------------------------------------------------------ no fabrication
def test_a_total_failure_returns_none_not_one():
    assert _bot(_Boom())._get_atr_for_symbol("GOLDM") is None


def test_a_priced_but_historyless_symbol_returns_none_not_one_and_a_half_percent():
    """The exact 2026-08-25 path. 160907 * 0.015 = 2413.6 must never come back."""
    atr = _bot(_NoCandlesButPriced())._get_atr_for_symbol("GOLDM")
    assert atr is None, f"fabricated {atr} from price instead of admitting ignorance"


def test_the_fabricated_stop_would_have_been_seven_times_too_wide():
    """Why this matters, in the numbers that made it matter."""
    fabricated = 160907.0 * 0.015
    real = 345.29
    assert 1.25 * fabricated == pytest.approx(3017.0, abs=1.0)
    assert 1.25 * real == pytest.approx(431.6, abs=1.0)
    assert (fabricated / real) > 6.5


def test_the_old_constants_are_gone_from_the_source():
    """Guards against the fallback quietly returning."""
    import inspect

    src = inspect.getsource(Bot._get_atr_for_symbol)
    assert "0.015" not in src, "the 1.5%-of-price fallback must not come back"
    assert "return 1.0" not in src, "the literal 1.0 fallback must not come back"
    assert "return None" in src


# ------------------------------------------------ sizing refuses to guess
def test_sizing_stands_aside_when_atr_is_unknown():
    """raw_qty divides by ATR. Without one there is no risk-based quantity, and
    0.0 is what every caller already reads as a stand-aside."""
    bot = _bot(_Boom())
    qty = Bot._calculate_dynamic_lot_size(
        bot, symbol="GOLDM", total_equity=400000.0, entry_price=1664.0,
        alloc_pct=2.0, confidence_score=59.0, direction="short",
    )
    assert qty == 0.0


# ------------------------------------------- the entry gate on the MCX path
def test_the_mcx_entry_path_checks_atr_before_building_the_order():
    """The whole failure was ordering: ATR was fetched AFTER the fill. A gate
    that runs after the order has already been placed is not a gate."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(Bot._scan_and_enter_mcx_opportunities)
    ))
    atr_calls, order_calls = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name == "_get_atr_for_symbol":
            atr_calls.append(node.lineno)
        elif name == "place_order":
            order_calls.append(node.lineno)

    assert atr_calls, "the MCX entry path must fetch ATR"
    assert order_calls, "expected a place_order call to order against"
    assert min(atr_calls) < min(order_calls), (
        "ATR must be checked BEFORE the order is placed, not after the fill"
    )


def test_the_gate_stands_the_entry_down_rather_than_sizing_a_stop_it_cannot_compute():
    import inspect

    src = inspect.getsource(Bot._scan_and_enter_mcx_opportunities)
    assert "_entry_atr" in src
    assert "NoATR" in src, "a refused entry should say why on the bus"
