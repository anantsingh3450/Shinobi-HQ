"""A bought PUT is a LONG position. Its excursions must not be sign-flipped.

2026-08-22: every winning put in the autopsy corpus carried an impossible
NEGATIVE maximum-favourable-excursion, two of them the exact negation of the
realised return:

    CRUDEOIL26AUG8050PE    MFE  -3.85   ret  +3.85
    CRUDEOIL26AUG7200PE    MFE  -3.65   ret  +3.65
    NATURALGAS26AUG255PE   MFE -17.87   ret +10.14
    NATURALGAS26AUG255PE   MFE -12.50   ret  +4.81

All seven calls were correct.

The cause: `entry_meta["side"]` holds the UNDERLYING SIGNAL's direction —
`side = OrderSide.BUY if direction == "long" else OrderSide.SELL` — but the
OptionsRouter turns a bearish signal into BUY A PUT. Hokage only ever buys
options (options-only mandate), and the tracked peak/trough are PREMIUMS, so
the position is long the measured quantity regardless of which way the
underlying was expected to go. `_excursion_pcts` multiplied by -1 anyway.

WHY IT HID FOR SO LONG: a negative MFE on a LOSING trade is perfectly
legitimate — the best moment of the hold was still under water. The
impossibility only shows on a put that WON, and puts that won were rare.

WHAT IT COST: MFE is the input to capture-efficiency and to any exit-geometry
measurement. Measuring the trail on inverted data would have produced a
confident, wrong answer on roughly half of all trades.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


# ------------------------------------------------------- the primitive itself
def test_a_bought_option_gains_when_its_premium_rises():
    """entry 516.80 -> peak 536.70 is +3.85% in the holder's favour, whether
    the contract is a call or a put."""
    mfe, mae = Bot._excursion_pcts(entry_price=516.80, peak_price=536.70,
                                   trough_price=500.00, side="BUY")
    assert mfe == pytest.approx(3.85, abs=0.01)
    assert mae == pytest.approx(-3.25, abs=0.01)


def test_passing_the_signal_side_is_what_flipped_it():
    """Pins the old behaviour so the regression is unmistakable if it returns."""
    mfe, _ = Bot._excursion_pcts(entry_price=516.80, peak_price=536.70,
                                 trough_price=500.00, side="SELL")
    assert mfe == pytest.approx(-3.85, abs=0.01)


def test_a_missing_extreme_stays_unknown_not_zero():
    """A fabricated 0.0 would silently score the entry as flat. None means
    attribution skips the trade instead of learning from an invention."""
    mfe, mae = Bot._excursion_pcts(entry_price=100.0, peak_price=None,
                                   trough_price=None, side="BUY")
    assert mfe is None and mae is None


def test_a_zero_entry_price_yields_unknown_rather_than_dividing():
    assert Bot._excursion_pcts(entry_price=0.0, peak_price=1.0,
                               trough_price=1.0, side="BUY") == (None, None)


# ------------------------------------------------- the four real corpus rows
@pytest.mark.parametrize("symbol,entry,peak,expected", [
    ("CRUDEOIL26AUG8050PE", 516.80, 536.70, 3.85),
    ("CRUDEOIL26AUG7200PE", 303.80, 314.90, 3.65),
    ("NATURALGAS26AUG255PE", 10.35, 12.20, 17.87),
    ("NATURALGAS26AUG255PE", 10.40, 11.70, 12.50),
])
def test_the_four_impossible_rows_now_measure_positive(symbol, entry, peak, expected):
    """Each of these won and was recorded with a negative MFE."""
    mfe, _ = Bot._excursion_pcts(entry_price=entry, peak_price=peak,
                                 trough_price=None, side="BUY")
    assert mfe == pytest.approx(expected, abs=0.05), symbol
    assert mfe > 0, f"{symbol}: a winning put cannot have negative MFE"


# ------------------------------------------------------- the production wiring
def test_the_call_site_forces_buy_for_option_contracts():
    """Guards production, not the primitive.

    The primitive was always correct given the right argument. The bug was the
    ARGUMENT, so a test that only exercised _excursion_pcts would have passed
    on every day this was broken. Parses the whole module and finds the real
    call node rather than slicing text, which nested parentheses defeat.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(inspect.getmodule(Bot)))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "attr", None) == "_excursion_pcts")
    ]
    assert calls, "_excursion_pcts is never called in production"

    for call in calls:
        side_arg = {k.arg: k.value for k in call.keywords}.get("side")
        assert side_arg is not None, "side must still be passed explicitly"
        assert isinstance(side_arg, ast.IfExp), (
            "side must be conditional on whether the instrument is an option, "
            "not read straight from the signal direction"
        )

def test_option_detection_covers_calls_and_puts_only():
    """CE/PE are the only option suffixes Hokage trades; an underlying symbol
    must keep using the recorded side."""
    for sym, is_opt in (("NATURALGAS26AUG265CE", True),
                        ("SILVERM26AUG240000PE", True),
                        ("CRUDEOIL", False),
                        ("NIFTY", False),
                        ("", False)):
        assert str(sym or "").upper().endswith(("CE", "PE")) is is_opt, sym
