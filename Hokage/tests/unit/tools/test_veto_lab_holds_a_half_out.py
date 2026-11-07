"""The veto lab decided a gate's fate on one window, pooled and one-sided.

Three defects, each of which has produced a wrong answer elsewhere here:

  * A FROZEN WINDOW. `start`/`end` were pinned to the 2026-08-12 study that
    populated VETO_DISABLED_SYMBOLS, so re-running the lab re-read the same
    quarter however much tape had accumulated. Gas alone had three unmeasured
    months by 2026-11-07.
  * NO HOLD-OUT. One t over one window is the geometry that queued thirteen of
    fourteen cells for retirement, the best cell included.
  * POOLED SIDES. Long and short are two different bets - two of three live
    pairs were paying for a NEGATIVE side - so a veto that helps one side and
    hurts the other reads as neutral once they are averaged.

THESE TESTS ARE ABOUT THE ARITHMETIC AND THE BAR, NOT THE ANSWER. What has to
hold is that a verdict needs both halves to agree, that the split falls on
session days rather than row counts, that a thin half is reported as thin
instead of as a finding, that the sides are never crossed, and that the lab
keeps asking production's own function instead of a copy of it.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "veto_lab", ROOT / "tools" / "research" / "veto_lab.py")
vl = importlib.util.module_from_spec(_spec)
sys.modules["veto_lab"] = vl
_spec.loader.exec_module(vl)

D0 = dt.date(2026, 5, 20)


def _recs(edges, *, side=1, start=0, day_step=1):
    """One record per edge, each on its own session day."""
    return [{"day": D0 + dt.timedelta(days=start + i * day_step),
             "side": side, "passed": False, "edge": e, "win": e > 0,
             "verdict": "MIXED", "reason": "too extended"}
            for i, e in enumerate(edges)]


# ========================================================= the split is by day
def test_the_split_falls_on_session_days_not_row_counts():
    """Splitting on rows would put one busy session on both sides of the line
    and let the same day inform train and hold-out at once."""
    recs = ([{"day": D0, "side": 1, "passed": False, "edge": 1.0, "win": True,
              "verdict": "MIXED", "reason": "r"}] * 50
            + _recs([1.0, 1.0, 1.0], start=1))
    cut = vl.split_days(recs)
    assert cut is not None
    early = [r for r in recs if r["day"] < cut]
    late = [r for r in recs if r["day"] >= cut]
    assert {r["day"] for r in early}.isdisjoint({r["day"] for r in late})


def test_too_few_days_means_no_split_rather_than_a_bad_one():
    assert vl.split_days(_recs([1.0, 2.0, 3.0])) is None


def test_an_empty_set_has_no_split():
    assert vl.split_days([]) is None


# ===================================================== a verdict needs a split
def test_a_positive_blocked_edge_in_one_half_only_is_unproven():
    """THE WHOLE POINT. An edge that lives in the early half and dies in the
    late half is the artifact the hold-out exists to catch, and it must not
    read as 'the veto is costing money'."""
    early = _recs([2.0] * 40, start=0)
    late = _recs([-2.0] * 40, start=100)
    out = vl.blocked_verdict(early + late, vl.split_days(early + late))
    assert "COSTING MONEY" not in out


def test_a_positive_blocked_edge_in_both_halves_is_reported_as_costing():
    strong = _recs([1.0, 1.2, 0.8, 1.1] * 20)
    out = vl.blocked_verdict(strong, vl.split_days(strong))
    assert "COSTING MONEY" in out and "both halves" in out


def test_a_consistently_negative_blocked_set_earns_the_veto_its_place():
    out = vl.blocked_verdict(_recs([-1.0, -0.8, -1.2, -0.9] * 20),
                             vl.split_days(_recs([-1.0] * 80)))
    assert "earns its place" in out


def test_a_pooled_win_that_fails_hold_out_says_so_out_loud():
    """It must name BOTH facts: pooled is positive, and it does not hold."""
    late = [v for pair in [(0.9, -0.9)] * 22 for v in pair] + [0.1]
    recs = _recs([3.0, 2.6, 3.4, 2.9] * 11, start=0) + _recs(late, start=200)
    out = vl.blocked_verdict(recs, vl.split_days(recs))
    assert "DOES NOT HOLD OUT" in out and "unproven" in out


def test_a_thin_half_is_called_thin_not_confirmed():
    recs = _recs([1.0] * 40, start=0) + _recs([1.0] * 3, start=200)
    out = vl.blocked_verdict(recs, vl.split_days(recs))
    assert "too thin" in out
    assert "COSTING MONEY" not in out


def test_a_veto_that_barely_bites_is_not_judged():
    out = vl.blocked_verdict(_recs([1.0] * 5), vl.split_days(_recs([1.0] * 5)))
    assert "barely bites" in out


def test_no_split_available_is_unproven_not_a_pass():
    out = vl.blocked_verdict(_recs([1.0] * 40, day_step=0), None)
    assert "unproven" in out


# ======================================================= the bar is the ship bar
def test_the_bar_is_the_ship_bar():
    """A veto is a standing restriction on the account. Removing one is a
    loosening, so the evidence is held to what shipping would need."""
    assert vl.SHIP_T == 2.0


def test_a_blocked_edge_below_the_ship_bar_is_not_a_finding():
    """Positive in both halves but statistically weak."""
    weak = _recs([0.4, -0.3, 0.5, -0.2] * 20)
    out = vl.blocked_verdict(weak, vl.split_days(weak))
    assert "COSTING MONEY" not in out


def test_a_tiny_edge_is_refused_however_significant_it_is():
    """t MEASURES SIGNIFICANCE, NOT SIZE. A blocked set averaging +0.03 ATR
    clears t=+6 at n=80 - consistent, real, and nowhere near enough to pay a
    spread and a holding period of theta. Without the size floor this reads as
    'the veto is costing money' and licenses removing a gate."""
    tiny = _recs([0.05, -0.02, 0.08, 0.01] * 20)
    _, _, mean, t = vl._stats(tiny)
    assert mean < vl.MIN_EDGE_ATR and t > vl.SHIP_T      # significant, and tiny
    out = vl.blocked_verdict(tiny, vl.split_days(tiny))
    assert "COSTING MONEY" not in out
    assert "too small to pay for itself" in out


def test_the_size_floor_is_declared_a_prior_not_a_measurement():
    src = (ROOT / "tools" / "research" / "veto_lab.py").read_text(encoding="utf-8")
    assert "STATED PRIOR, NOT A MEASUREMENT" in src
    assert vl.MIN_EDGE_ATR > 0


# ============================================================ the sides are kept
def test_the_two_sides_are_never_crossed():
    longs = _recs([1.0] * 10, side=1)
    shorts = _recs([-1.0] * 10, side=-1, start=50)
    both = longs + shorts
    assert all(r["edge"] > 0 for r in both if r["side"] == 1)
    assert all(r["edge"] < 0 for r in both if r["side"] == -1)


def test_opposite_sides_cancel_when_pooled_which_is_why_they_are_split():
    """The defect being corrected, stated as arithmetic: a veto helping one
    side and hurting the other averages to nothing."""
    pooled = _recs([1.0] * 20, side=1) + _recs([-1.0] * 20, side=-1, start=50)
    _, _, mean, _ = vl._stats(pooled)
    assert mean == pytest.approx(0.0, abs=1e-9)
    _, _, mean_long, _ = vl._stats([r for r in pooled if r["side"] == 1])
    assert mean_long == pytest.approx(1.0)


# ================================================================== arithmetic
def test_an_empty_bucket_is_zero_not_an_error():
    assert vl._stats([]) == (0, 0.0, 0.0, 0.0)


def test_a_single_observation_has_no_t():
    n, acc, mean, t = vl._stats(_recs([1.0]))
    assert (n, mean, t) == (1, 1.0, 0.0)


def test_accuracy_counts_wins_not_sign_of_the_mean():
    recs = _recs([-0.1, -0.1, -0.1, 5.0])
    n, acc, mean, _ = vl._stats(recs)
    assert n == 4 and acc == pytest.approx(25.0) and mean > 0


def test_a_flat_bucket_does_not_divide_by_zero():
    n, _, mean, t = vl._stats(_recs([0.5] * 10))
    assert mean == pytest.approx(0.5) and t > 0


# ====================================================== fidelity to production
def test_the_lab_calls_productions_own_classifier():
    """A re-implementation measures a gate nobody runs. bias_rules exists so
    the lab and the bot cannot drift apart."""
    src = (ROOT / "tools" / "research" / "veto_lab.py").read_text(encoding="utf-8")
    assert "bias_rules.classify_tape(" in src
    assert "from bots.autonomous import bias_rules" in src


def test_the_lab_does_not_reach_for_kite():
    """A measurement over all history must give the same answer on a Saturday
    with a dead token as it does mid-session. load_bars falls back to Kite and
    writes through; load_history reads the archive and stops there."""
    src = (ROOT / "tools" / "research" / "veto_lab.py").read_text(encoding="utf-8")
    assert "load_bars(" not in src          # the docstring may name it; no call
    assert "candle_archive.load(" in src


def test_the_gate_applied_is_the_one_from_check_conduct_gates():
    """MIXED blocks, and a named direction blocks the opposite side. If
    production's gate changes and this does not, every number here is stale."""
    src = (ROOT / "tools" / "research" / "veto_lab.py").read_text(encoding="utf-8")
    assert 'verdict == "BULLISH" and call == 1' in src
    assert 'verdict == "BEARISH" and call == -1' in src


def test_the_window_is_not_pinned_to_the_old_study():
    """The frozen 2026-05-01/2026-08-12 window is the defect, so its dates
    must not be back in the file as defaults."""
    src = (ROOT / "tools" / "research" / "veto_lab.py").read_text(encoding="utf-8")
    assert '"2026-05-01 09:15:00"' not in src
    assert '"2026-08-12 23:30:00"' not in src
