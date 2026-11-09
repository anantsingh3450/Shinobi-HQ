"""The arithmetic behind "how far are we", because it will be quoted.

2026-11-09. The commander asked how many sessions each cell needs before it
could clear the bar. That number is going to be read as a schedule, so the two
ways it can lie have to be closed first:

  1. A NEGATIVE cell is not under-powered. More data drives its t further from
     the bar, not closer. Reporting "needs N sessions" for a cell measuring
     -0.129 ATR would be a fabricated hope - a date for something that is not
     coming. Nine of the twenty-nine live cells are in that state, and
     EventRider is negative on all four MCX assets.

  2. The bar applies to BOTH halves, and the halves split whatever tape
     exists. A cell needing n_req signals per half therefore needs
     2 * n_req / rate SESSIONS, not n_req / rate. Forgetting the factor of two
     halves every answer in this file.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "research"))
sys.path.insert(0, str(ROOT / "src"))

import power_lab as pl  # noqa: E402


# ======================================================== the core formula
def test_required_n_is_the_square_of_the_shortfall():
    """t scales with sqrt(n), so the sample scales with the SQUARE of how far
    short t falls. A cell at half the bar needs four times the data, not two."""
    bar = pl.BAR
    assert pl.required_n(100, bar) == pytest.approx(100)
    assert pl.required_n(100, bar / 2) == pytest.approx(400)
    assert pl.required_n(100, bar / 3) == pytest.approx(900)


def test_a_cell_already_at_the_bar_needs_nothing_more():
    assert pl.required_n(50, pl.BAR) == pytest.approx(50)


def test_a_non_positive_t_has_no_required_n():
    """THE DISTINCTION THAT MATTERS MOST. There is no sample size at which a
    negative mean produces a positive t, so the honest answer is None rather
    than a very large number that reads as 'eventually'."""
    assert pl.required_n(100, 0.0) is None
    assert pl.required_n(100, -1.5) is None
    assert pl.required_n(0, 2.0) is None


# ==================================================== the sessions formula
def test_sessions_needed_doubles_for_the_hold_out_rule():
    """Both halves must clear, and each half is half the tape. This is the
    factor of two that a naive n_req / rate silently drops."""
    n, t, rate = 44, 2.31, 0.64
    need = pl.required_n(n, t)
    naive = need / rate
    honest = 2.0 * need / rate
    assert honest == pytest.approx(2 * naive)
    # and it is the honest one the tool prints
    src = (ROOT / "tools" / "research" / "power_lab.py").read_text(encoding="utf-8")
    assert "2.0 * need_n / rate" in src


def test_a_faster_firing_cell_answers_sooner_at_the_same_t():
    """Two cells equally short of the bar are not equally far away: the one
    that fires more often banks its sample faster. This is why the ranking is
    by sessions and not by t."""
    slow = 2.0 * pl.required_n(50, 1.5) / 0.5
    fast = 2.0 * pl.required_n(50, 1.5) / 5.0
    assert fast < slow


# ============================================================ the verdicts
def _cell(n=100, edge=0.1, t=2.0):
    return {"n": n, "edge_atr": edge, "t": t}


def test_a_negative_hold_out_is_wrong_sign_not_underpowered():
    assert pl.classify(_cell(edge=-0.129, t=-1.28), _cell()) == "WRONG SIGN"


def test_a_zero_edge_is_also_wrong_sign():
    """Exactly zero is not a small positive. It must not get a projection."""
    assert pl.classify(_cell(edge=0.0, t=0.0), _cell()) == "WRONG SIGN"


def test_clearing_both_halves_is_confirmed():
    high = _cell(t=pl.BAR + 0.1)
    assert pl.classify(high, high) == "CONFIRMED"


def test_clearing_only_the_hold_out_is_not_confirmed():
    """One half is not evidence - the whole reason the split exists."""
    assert pl.classify(_cell(t=pl.BAR + 1), _cell(t=1.0)) == "UNDERPOWERED"


def test_a_thin_half_is_too_thin_rather_than_a_verdict():
    assert pl.classify(_cell(n=pl.MIN_N - 1), _cell()) == "TOO THIN"
    assert pl.classify(_cell(), _cell(n=pl.MIN_N - 1)) == "TOO THIN"


def test_a_missing_train_half_is_no_reading_not_a_failure():
    """MISSING IS NOT ZERO. The audit stores None for a train half that never
    reached MIN_N; reading that as 0.0 once printed a module which had fired
    16 times as 'fired nothing, measured flat'."""
    assert pl.classify(_cell(), None) == "NO READING"
    assert pl.classify(None, _cell()) == "NO READING"


# ======================================================= the family lever
def test_a_smaller_family_lowers_the_bar():
    assert pl.bar_for_family(4) < pl.bar_for_family(40)


def test_the_family_bar_never_goes_below_the_base():
    """A narrow search does not earn an easier bar than everything else in
    this system ships against."""
    from signal_lab import BASE_SHIP_T

    assert pl.bar_for_family(1) == pytest.approx(BASE_SHIP_T)
    assert pl.bar_for_family(2) >= BASE_SHIP_T


def test_the_family_lever_is_worth_what_the_plan_claims():
    """The claim put to the commander: testing 40 cells instead of 4 costs
    about 1.7x the data to prove the SAME edge. Checked here so the number in
    the plan cannot drift from the function that produced it."""
    wide, narrow = pl.bar_for_family(40), pl.bar_for_family(4)
    ratio = (wide / narrow) ** 2
    assert 1.6 <= ratio <= 1.8


def test_the_default_bar_is_the_audits_own():
    """The tool must not invent a gentler bar than the ship decision uses."""
    import weekly_audit as audit

    assert pl.BAR == audit.SHIP_BAR
    assert pl.MIN_N == audit.MIN_N


# =================================================== it cannot promise a date
def test_the_report_says_the_numbers_are_a_floor():
    src = (ROOT / "tools" / "research" / "power_lab.py").read_text(encoding="utf-8")
    # Whitespace-normalised: the prose wraps, and a rail that breaks on a line
    # break tests the formatting rather than the warning.
    flat = " ".join(src.split())
    assert "FLOOR" in flat
    assert "never as a date" in flat
    # and the hypothetical family run must label itself as hypothetical
    assert "HYPOTHETICAL" in src


def test_a_hypothetical_family_cannot_be_chosen_from_the_results():
    """Picking the four cells by their current t is precisely the selection
    the correction exists to punish. The tool has to say so where it is used,
    not only in its header."""
    src = (ROOT / "tools" / "research" / "power_lab.py").read_text(encoding="utf-8")
    body = src.split("def bar_for_family")[1].split("def ")[0]
    assert "BEFORE" in body or "before" in body
    assert "selection" in body
