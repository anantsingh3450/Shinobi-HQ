"""Judging an exit on its aftermath, without becoming a regret machine.

Commander-approved 2026-11-12: "what if after his exit option again goes up
and reached his target, or what if it goes further down".

The measurement is easy. Not lying with it is the hard part, and these tests
pin the five guards:

  1. HINDSIGHT. A tool that only reports "sold too early" is a regret
     machine - you notice the recoveries and forget the collapses. NO
     DIFFERENCE is a first-class verdict and all three counts print together.
  2. NOT LOOKING IS NOT A VERDICT. An exit with no observations means the
     capture was off, not that the exit was fine. Excluded from every rate.
  3. MATERIALITY. A move smaller than the cheapest measured round trip
     (0.47% on GOLDM) is not a difference worth a verdict.
  4. IT JUDGES THE EXIT, NOT THE ENTRY, and the report says so.
  5. NO TUNING. The arm threshold, floor and backstop are commander-approved
     risk constants; a change read off this table is fitted to the past.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


SRC = _repo_root() / "tools" / "research" / "post_exit_lab.py"
_RESEARCH = str(_repo_root() / "tools" / "research")
if _RESEARCH not in sys.path:
    sys.path.insert(0, _RESEARCH)

import post_exit_lab as PEL  # noqa: E402


def _row(exit_price=100.0, marks=(), target=None, stop=None, reason="TRAIL_LOCK"):
    return {
        "position_id": "p1", "contract": "GOLDM26NOV138500PE",
        "underlying": "GOLDM", "strategy_id": "strat-sessionshift-mcx-v1",
        "exit_reason": reason, "exit_price": exit_price,
        "target_price": target, "stop_price": stop, "gross_pnl": -610.0,
        "observations": [{"captured_at": f"t{i}", "last_price": p,
                          "bid": None, "ask": None}
                         for i, p in enumerate(marks)],
    }


# ============================================= the three verdicts
def test_a_recovery_after_the_exit_is_exit_cost_us():
    """Sold at 100, it climbed to 120. We left money behind."""
    j = PEL.judge(_row(100.0, marks=(105.0, 120.0, 112.0)))
    assert j["verdict"] == PEL.Verdict.COST
    assert j["high_after"] == 120.0
    assert j["best_pct"] == pytest.approx(20.0)


def test_a_collapse_after_the_exit_is_exit_saved_us():
    j = PEL.judge(_row(100.0, marks=(95.0, 70.0, 75.0)))
    assert j["verdict"] == PEL.Verdict.SAVED
    assert j["low_after"] == 70.0
    assert j["worst_pct"] == pytest.approx(-30.0)


def test_a_flat_aftermath_is_no_difference(monkeypatch):
    """GUARD 3. Smaller than the cheapest round trip measured on this book,
    so acting on it would cost more than it is worth."""
    j = PEL.judge(_row(100.0, marks=(100.2, 99.8, 100.1)))
    assert j["verdict"] == PEL.Verdict.SAME


def test_the_bigger_excursion_decides_when_it_went_both_ways():
    """It usually goes both ways. The verdict follows the larger move, and
    the report carries both numbers so the reader is not told only one."""
    up = PEL.judge(_row(100.0, marks=(90.0, 125.0)))
    assert up["verdict"] == PEL.Verdict.COST
    down = PEL.judge(_row(100.0, marks=(60.0, 104.0)))
    assert down["verdict"] == PEL.Verdict.SAVED
    assert down["best_pct"] == pytest.approx(4.0)
    assert down["worst_pct"] == pytest.approx(-40.0)


# ============================= guard 2: not looking is not a verdict
def test_an_exit_with_no_observations_is_not_judged():
    j = PEL.judge(_row(100.0, marks=()))
    assert j["verdict"] == PEL.Verdict.UNWATCHED
    assert j["best_pct"] is None and j["worst_pct"] is None


def test_a_zero_exit_price_is_not_judged():
    """Dividing by it would produce an infinite percentage and a verdict."""
    j = PEL.judge(_row(0.0, marks=(10.0, 20.0)))
    assert j["verdict"] == PEL.Verdict.UNWATCHED


def test_null_marks_are_skipped_not_read_as_zero():
    row = _row(100.0, marks=(110.0,))
    row["observations"].append({"captured_at": "t9", "last_price": None,
                                "bid": None, "ask": None})
    j = PEL.judge(row)
    assert j["low_after"] == 110.0, "a None must not become a price of 0"
    assert j["verdict"] == PEL.Verdict.COST


# ============================================ the abandoned target
def test_reaching_the_abandoned_target_is_recorded():
    """The commander's exact question: did it go on to reach the target?"""
    j = PEL.judge(_row(100.0, marks=(118.0,), target=115.0))
    assert j["reached_target"] is True


def test_not_reaching_the_target_is_false_not_unknown():
    j = PEL.judge(_row(100.0, marks=(110.0,), target=115.0))
    assert j["reached_target"] is False


def test_no_target_recorded_stays_unknown():
    """Absent is not false. A position with no target on record cannot be
    said to have missed one."""
    j = PEL.judge(_row(100.0, marks=(110.0,)))
    assert j["reached_target"] is None
    assert j["reached_stop"] is None


def test_reaching_the_avoided_stop_is_recorded():
    j = PEL.judge(_row(100.0, marks=(80.0,), stop=85.0))
    assert j["reached_stop"] is True


# ====================================== the report cannot be a regret machine
def _corpus(monkeypatch, rows, cover=None):
    monkeypatch.setattr(PEL.exit_followup, "followups", lambda limit=None: rows)
    monkeypatch.setattr(PEL.exit_followup, "coverage",
                        lambda: cover or {
                            "exits": len(rows),
                            "with_observations": sum(
                                1 for r in rows if r["observations"]),
                            "without_observations": sum(
                                1 for r in rows if not r["observations"]),
                            "marks": sum(len(r["observations"]) for r in rows)})


def test_all_three_verdicts_are_printed_together(monkeypatch):
    """GUARD 1. Printing only the premature count is how this becomes a
    machine for regret."""
    _corpus(monkeypatch, [
        _row(100.0, marks=(130.0,)),
        _row(100.0, marks=(70.0,)),
        _row(100.0, marks=(100.1,)),
    ])
    text = PEL.report()
    assert PEL.Verdict.COST in text
    assert PEL.Verdict.SAVED in text
    assert PEL.Verdict.SAME in text


def test_unwatched_exits_are_counted_and_excluded(monkeypatch):
    _corpus(monkeypatch, [_row(100.0, marks=(130.0,)), _row(100.0, marks=())])
    text = PEL.report()
    assert "WITHOUT any observation" in text
    assert "excluded from every rate" in text


def test_a_corpus_with_no_aftermath_refuses_to_conclude(monkeypatch):
    _corpus(monkeypatch, [_row(100.0, marks=()), _row(100.0, marks=())])
    text = " ".join(PEL.report().split())
    assert "none with an aftermath" in text or "none has an aftermath" in text
    assert "NOT a clean bill of health" in text


def test_an_empty_corpus_explains_why_it_can_never_be_backfilled(monkeypatch):
    _corpus(monkeypatch, [])
    text = " ".join(PEL.report().split())
    assert "Nothing recorded yet" in text
    assert "dies with the contract" in text


def test_the_report_splits_by_exit_mechanism(monkeypatch):
    """The question this exists to answer: is TRAIL_LOCK leaving money while
    the backstop saves it, or the reverse?"""
    _corpus(monkeypatch, [
        _row(100.0, marks=(130.0,), reason="TRAIL_LOCK: breakeven floor held"),
        _row(100.0, marks=(70.0,), reason="Option hard backstop: premium fell"),
    ])
    text = PEL.report()
    assert "BY EXIT MECHANISM" in text
    assert "TRAIL_LOCK" in text and "HARD BACKSTOP" in text


# ======================================= guards 4 and 5, stated in the report
def test_the_report_says_it_judges_the_exit_not_the_entry(monkeypatch):
    _corpus(monkeypatch, [_row(100.0, marks=(130.0,))])
    text = " ".join(PEL.report().split())
    assert "JUDGES THE EXIT, NOT THE ENTRY" in text


def test_the_report_states_that_theta_is_not_charged(monkeypatch):
    """GUARD: 'it went back up' flatters holding unless decay is charged.
    theta_lab has no MCX figure, so none is invented."""
    _corpus(monkeypatch, [_row(100.0, marks=(130.0,))])
    text = " ".join(PEL.report().split())
    assert "THETA IS NOT CHARGED HERE" in text
    assert "nothing on MCX yet" in text


def test_it_proposes_no_exit_rule():
    import ast

    text = SRC.read_text(encoding="utf-8")
    assert "PROPOSES NOTHING" in text or "proposes nothing" in text.lower()
    assert "commander-approved risk constants" in text
    tree = ast.parse(text)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for forbidden in ("write_proposal", "set_stop", "apply_change"):
        assert forbidden not in names


def test_the_materiality_floor_is_tied_to_a_measured_cost():
    """Not a round number picked by feel: the cheapest round trip measured
    on this book is GOLDM at 0.47%."""
    assert PEL.MATERIAL_PCT == pytest.approx(0.5, abs=0.05)
    assert "cheapest round trip" in SRC.read_text(encoding="utf-8")
