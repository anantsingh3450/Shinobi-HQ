"""Hokage only buys premium, so a high-IV regime switches him off entirely.

On 2026-10-14 the IV guard refused all thirteen signals he found, at VIX
94-96%. On 2026-10-15 it refused eleven more. No amount of tuning fixes that:
a premium-BUYING system cannot act when premium is expensive.

The idea that inverts it is SELLING premium. But there is no option premium
history anywhere in the brain, so decay cannot be measured - which is why this
measures the premise INDIRECTLY and honestly instead. A short-premium position
is a bet that the underlying moves LESS than the market implied, and that
needs no option prices:

    implied   India VIX, from Kite
    realised  what the index actually delivered over the next 5 sessions,
              annualised, from archived candles

THE HYPOTHESIS I PROPOSED WAS WRONG, which is the main thing this lab did.
I suggested selling INTO the high-VIX regime that blocks buying. On the whole
sample that looked decisively refuted - NIFTY -3.4% t-3.79, BANKNIFTY -8.3%
t-5.32, implied falling SHORT of realised exactly where buying is forbidden.
Then the train/hold split showed the high-VIX buckets hold only 8 hold-out
days, so that refutation is not evidence either. Both my hypothesis and my
first reading of its refutation failed the same discipline.

WHAT DID SURVIVE, and it is the first thing in this system to clear a
corrected bar on both halves:

    NIFTY   below the 50th VIX percentile   train +3.8% t+6.28 | hold +3.0% t+5.82
    SENSEX  below the 50th VIX percentile   train +3.3% t+5.37 | hold +2.4% t+5.01

against a bar of t>=2.77 corrected for nine buckets. BANKNIFTY shows nothing
on either half.

A VARIANCE PREMIUM IS COMPENSATION FOR TAIL RISK, NOT FREE MONEY. The mean
being positive is the premium existing. The losses live in the tail the mean
hides, which is why the worst day is reported beside every bucket, and why
nothing here is a strategy: no spread, no margin, no gap risk, no costs.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import sys
from datetime import datetime, timedelta

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "variance_premium_lab", ROOT / "tools" / "research" / "variance_premium_lab.py"
)
vp = importlib.util.module_from_spec(_spec)
sys.modules["variance_premium_lab"] = vp
_spec.loader.exec_module(vp)


# --------------------------------------------------- realised vol is real vol
def test_a_flat_series_has_no_volatility():
    assert vp.realised_vol([100.0] * 10) == pytest.approx(0.0)


def test_realised_vol_is_annualised_onto_the_same_scale_as_vix():
    """VIX is an annualised percent. A daily standard deviation compared
    against it directly would understate realised vol ~16x and make every
    bucket look like a seller's paradise."""
    closes = [100.0]
    for i in range(1, 60):
        closes.append(closes[-1] * (1.01 if i % 2 else 0.99))
    rv = vp.realised_vol(closes)
    daily = rv / math.sqrt(vp.TRADING_DAYS) / 100.0
    assert 0.005 < daily < 0.02, f"daily sigma {daily} is not plausible"
    assert vp.TRADING_DAYS == 252


def test_a_series_too_short_to_measure_returns_none():
    """Missing must stay distinguishable from zero: a zero would read as a
    perfectly calm market and hand the seller the whole premium."""
    assert vp.realised_vol([100.0]) is None
    assert vp.realised_vol([]) is None


def test_a_zero_print_does_not_raise_and_does_not_become_a_return():
    """log(0) would raise, and a zero print in the archive would take the lab
    down mid-run. The pair spanning it is dropped rather than logged - and
    when too few valid pairs survive, the answer is None rather than a number
    built from one observation."""
    assert vp.realised_vol([100.0, 0.0, 101.0, 102.0]) is None

    long_enough = [100.0, 0.0] + [100.0 + i for i in range(10)]
    rv = vp.realised_vol(long_enough)
    assert rv is not None and rv > 0, "valid pairs after a bad print must count"


def test_daily_closes_takes_the_last_bar_of_each_session():
    base = datetime(2026, 6, 1, 9, 15)
    bars = [
        {"date": base, "close": 100.0},
        {"date": base + timedelta(minutes=15), "close": 101.0},
        {"date": base + timedelta(days=1), "close": 200.0},
        {"date": base + timedelta(days=1, minutes=15), "close": 202.0},
    ]
    out = vp.daily_closes(bars)
    assert [c for _, c in out] == [101.0, 202.0]


# ------------------------------------------------- the bar is not self-awarded
def test_the_bar_is_corrected_for_the_buckets_tested():
    """Three VIX buckets across three indices is a search of nine. A lab that
    judged itself at a flat 2.0 would be the multiple-comparisons mistake this
    codebase spent 2026-10-14 removing everywhere else."""
    from signal_lab import corrected_t

    assert vp.BAR == round(corrected_t(9), 2)
    assert vp.BAR > 2.0


def test_the_bar_comes_from_the_shared_function():
    from signal_lab import corrected_t

    assert vp.corrected_t is corrected_t


def test_the_buy_block_is_read_from_production():
    """The whole question is what a SELLER earns where production forbids
    BUYING. A local copy of 0.80 would drift the moment the guard moved."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    assert vp.BUY_BLOCK == Bot._VIX_PERCENTILE_BLOCK


def test_a_bucket_needs_enough_days_on_BOTH_halves():
    """The high-VIX buckets have 31 train days and 8 hold - which is exactly
    how the first, confident reading of this lab was wrong."""
    assert vp.MIN_N >= 20


# ------------------------------------------------- it refuses to oversell
def test_it_states_it_is_not_a_strategy():
    doc = vp.__doc__ or ""
    low = doc.lower()
    assert "not a strategy" in low
    assert "gap risk" in low
    assert "margin" in low


def test_it_names_the_tail_as_where_the_loss_lives():
    """A positive mean IS the premium. Reporting it without the worst day
    would present compensation for tail risk as free money."""
    src = (ROOT / "tools" / "research" / "variance_premium_lab.py").read_text(
        encoding="utf-8"
    )
    assert "worst" in src
    assert "where a seller" in src


def test_no_premium_is_modelled_anywhere():
    """A Black-Scholes premium would be a synthetic price. The entire point of
    using VIX against realised vol is that it needs no option prices."""
    src = (ROOT / "tools" / "research" / "variance_premium_lab.py").read_text(
        encoding="utf-8"
    ).lower()
    for banned in ("black_scholes", "blackscholes", "norm.cdf", "premium ="):
        assert banned not in src, f"a premium model crept in: {banned}"


def test_a_missing_vix_fails_loudly_rather_than_returning_nothing():
    """An empty VIX series makes every percentile None, every bucket empty and
    every verdict silent - the result would look like "no signal" rather than
    "no data". The failure has to be explicit."""
    src = (ROOT / "tools" / "research" / "variance_premium_lab.py").read_text(
        encoding="utf-8"
    )
    assert "could not load India VIX" in src
    assert "tools/ops/archive_vix.py" in src, (
        "the failure must name the one command that fixes it"
    )


def test_vix_comes_from_the_archive_not_a_live_session():
    """The result this lab produced on 2026-10-15 was the first here to clear a
    corrected bar on both halves, and it could only be reproduced while a
    Zerodha token happened to be alive. Evidence that expires with a token is
    an anecdote."""
    from hokage.memory import vix_archive

    import iv_lab

    assert vp.load_vix_closes is iv_lab.load_vix_closes
    assert callable(vix_archive.load)
    src = (ROOT / "tools" / "research" / "iv_lab.py").read_text(encoding="utf-8")
    assert "vix_archive" in src
