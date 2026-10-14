"""A wider stop holds longer, and Hokage buys premium that decays while it waits.

stop_lab found the 1.25 ATR thesis stop amputating edge on the UNDERLYING, and
said so honestly: "permission to test, not proof". It models the underlying
only. Hokage buys ATM options, so the extra holding time a wider stop buys is
paid for in theta.

There is no option premium history anywhere in the brain - candle_archive
holds seven underlyings and nothing else - so theta CANNOT be measured today.
Modelling a premium with Black-Scholes would be a synthetic price, and this
project does not trade on those or research on them.

So this lab does not invent the answer. It reduces the unknown to one number:

    the wider stop pays  <=>  decay over the extra hold < delta x extra gain

The right-hand side is measured from real candles. The left is the unknown.
The output is the decay rate at which the decision flips - checkable against a
single live option chain, instead of a question nobody can answer.

These tests pin the two things that make that honest: the arithmetic is right,
and the assumption is never presented as a measurement.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "theta_breakeven_lab", ROOT / "tools" / "research" / "theta_breakeven_lab.py"
)
tb = importlib.util.module_from_spec(_spec)
sys.modules["theta_breakeven_lab"] = tb
_spec.loader.exec_module(tb)


def _bars(closes, highs=None, lows=None):
    from datetime import datetime, timedelta

    t0 = datetime(2026, 6, 1, 9, 0)
    out = []
    for i, c in enumerate(closes):
        out.append({
            "date": t0 + timedelta(minutes=15 * i),
            "open": c, "close": c,
            "high": (highs[i] if highs else c),
            "low": (lows[i] if lows else c),
            "volume": 100,
        })
    return out


# ------------------------------------------------- the walk reports WHEN
def test_the_walk_returns_the_exit_bar_not_just_whether_it_stopped():
    """stop_lab returns whether the stop fired. WHEN it fired is the entire
    question here, because the cost of a wider stop is the waiting."""
    bars = _bars([100, 101, 102, 103, 104])
    edge, held = tb.walk(bars, 0, call=1, atr=10.0, k=3.0)
    assert held == tb.HORIZON, "an unstopped trade must run to the horizon"
    assert edge == pytest.approx(0.4)


def test_a_stop_that_fires_early_reports_the_early_bar():
    # long from 100, atr 10, k=1.0 -> stop at 90; bar 2 trades down to 89
    bars = _bars([100, 99, 95, 94, 93], lows=[100, 99, 89, 94, 93])
    edge, held = tb.walk(bars, 0, call=1, atr=10.0, k=1.0)
    assert held == 2, "the exit bar must be where the stop was hit"
    assert edge == pytest.approx(-1.0)


def test_a_wider_stop_on_the_same_path_holds_at_least_as_long():
    """The core premise. If this ever inverts, the break-even is nonsense."""
    bars = _bars([100, 99, 95, 94, 93], lows=[100, 99, 89, 94, 93])
    _, tight = tb.walk(bars, 0, call=1, atr=10.0, k=1.0)
    _, wide = tb.walk(bars, 0, call=1, atr=10.0, k=3.0)
    assert wide >= tight


def test_a_short_stops_on_the_high_not_the_low():
    bars = _bars([100, 101, 105, 106, 107], highs=[100, 101, 111, 106, 107])
    edge, held = tb.walk(bars, 0, call=-1, atr=10.0, k=1.0)
    assert held == 2
    assert edge == pytest.approx(-1.0)


# ----------------------------------------- the assumption stays an assumption
def test_delta_is_a_band_not_a_single_number():
    """Presenting one delta would read as a measurement. Hokage buys ATM, so
    0.5 is the centre and the band is the honesty."""
    assert tb.DELTA_LOW < tb.DELTA_CENTRE < tb.DELTA_HIGH
    assert tb.DELTA_CENTRE == 0.50


def test_the_module_says_theta_is_not_measured():
    """If this file ever starts claiming to measure decay without option data
    existing, the claim is false."""
    doc = tb.__doc__ or ""
    assert "cannot be MEASURED" in doc or "CANNOT" in doc.upper()
    assert "synthetic price" in doc.lower()


def test_no_black_scholes_anywhere():
    """A modelled premium is a synthetic price. The data doctrine forbids
    trading on those; researching on them is the same fiction one step back."""
    src = (ROOT / "tools" / "research" / "theta_breakeven_lab.py").read_text(
        encoding="utf-8"
    )
    lowered = src.lower()
    for banned in ("black_scholes", "blackscholes", "norm.cdf", "math.erf"):
        assert banned not in lowered, f"a premium model crept in: {banned}"


# ------------------------------------------------- comparable with stop_lab
def test_the_horizon_and_sample_floor_are_shared_with_stop_lab():
    """Two tables the commander will read side by side must not quietly be
    measuring different things."""
    import stop_lab

    assert tb.HORIZON is stop_lab.HORIZON
    assert tb.MIN_N is stop_lab.MIN_N
    assert tb.LIVE_SCOPE is stop_lab.LIVE_SCOPE


def test_the_production_stop_is_resolved_per_asset_not_assumed():
    """THE MISTAKE THIS EXISTS TO STOP. Production has run SessionShift/GOLDM
    at 3.0 ATR since 2026-08-13, while SILVERM stays at 1.25. A lab holding a
    single PRODUCTION_STOP = 1.25 prices a change that shipped two months ago
    and reports a break-even for a decision already made - which is exactly
    how "the stop is amputating GOLDM's edge" was concluded on 2026-10-14."""
    gold = tb.production_stop_for("entry-sessionshift-mcx-v1", "GOLDM")
    silver = tb.production_stop_for("entry-sessionshift-mcx-v1", "SILVERM")
    assert gold != silver, "the per-asset stop table is not being consulted"
    assert gold == 3.0
    assert silver == 1.25


def test_the_lab_holds_no_copy_of_a_production_constant():
    src = (ROOT / "tools" / "research" / "theta_breakeven_lab.py").read_text(
        encoding="utf-8"
    )
    assert "PRODUCTION_STOP = " not in src, (
        "a hardcoded production stop is back; ask the bot instead"
    )
    assert "_thesis_atr_mult_for" in src


def test_the_resolver_matches_the_bot_for_every_live_cell():
    """Whatever the tables say today, the lab must agree with the bot."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    for module_id, assets in tb.LIVE_SCOPE.items():
        for asset in assets:
            strategy_id = module_id.replace("entry-", "strat-", 1)
            assert tb.production_stop_for(module_id, asset) == (
                Bot._thesis_atr_mult_for(Bot, strategy_id, asset)
            ), f"{module_id}/{asset} disagrees with production"


def test_stop_lab_also_labels_the_real_production_row():
    """It printed '<- production' against 1.25 on every row, including GOLDM
    where production runs 3.0. That mislabel is what produced the wrong
    reading; the fix belongs in both labs or the next reader repeats it."""
    src = (ROOT / "tools" / "research" / "stop_lab.py").read_text(encoding="utf-8")
    assert "if k == 1.25 else" not in src
    assert "_production_stop_for" in src


def test_modules_are_keyed_by_module_id():
    """THE SILENT FAILURE. The registry is keyed 'strat-sessionshift-mcx-v1'
    while LIVE_SCOPE speaks 'entry-sessionshift-mcx-v1'. Keyed wrongly, every
    scope lookup returns None and the lab prints a header and no rows - which
    reads as 'no edge anywhere' rather than as a bug."""
    src = (ROOT / "tools" / "research" / "theta_breakeven_lab.py").read_text(
        encoding="utf-8"
    )
    assert 'getattr(m, "module_id", k)' in src
