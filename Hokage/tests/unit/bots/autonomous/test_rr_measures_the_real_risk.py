"""R:R was measured against a stop that moved, then against one that stops nothing.

TWO CHAPTERS. The file was `test_rr_uses_entry_stop.py` for the first one.

CHAPTER ONE — 2026-10-30, commit 9f0d6f4.
GOLDM26NOV141000PE was bought at 3152.50, ran 71 minutes and exited ON_TARGET
at 3586.00 for +4,335 — a 13.8% gain. It was reviewed as:

    entry=GOOD exit=ON_TARGET sizing=CORRECT stop=TIGHT R:R=0.00

and the lesson forwarded to long-term memory read "Stop was placed too
tightly" and "Low R:R of 0.00 despite profit — tighten target or improve exit
timing." Both wrong, on the best trade of the day.

ONE CAUSE, BOTH SYMPTOMS. `tracking["stop_price"]` is a live trailing floor
with four writers; the ladder sets it to `average_price` at Target 1. By exit
the floor sat ON entry, so risk was zero: `risk == 0` returned 0.00, and a
stop distance of zero graded TIGHT.

IT ONLY BIT WINNERS. SILVERM26NOV184000PE, entered the same evening and held
six minutes, scored 1.96 — its floor never had time to ratchet. The longer a
trade won, the more certainly its review was corrupted, which is the worst
possible direction for a bias in a system that learns from reviews.

The fix froze `initial_stop_price` at entry and divided by that instead.

CHAPTER TWO — 2026-11-01.
The frozen number was not the risk either. Every entry path sets
`initial_stop_price = entry * (1 - tsl_percent)`, so the denominator was
**5% of premium on every trade in both leagues** — a constant. And it stops
nothing: on a bought option that field is the TRAIL_LOCK profit floor, which
arms only after +5% and can never fire below entry. Freezing it made R:R
STABLE, not CORRECT. Chapter one removed a bias; it did not notice the
denominator was the wrong quantity.

Every "Excellent R:R achieved: X" in every lesson Hokage has ever written was
reward divided by 5% of premium.

The real risk is `_risk_pct_for` — min(premium backstop tier, the ATR thesis
stop through the ATM delta) — already in production and validated against real
fills. Frozen at entry as `risk_pct_at_entry` and passed to the review.

That makes the number structural: the thesis stop is 1.0 R by construction, so
a loss that runs to it reads exactly -1.00, and the adaptive target is floored
at 1.5 R, so a TARGET_HIT reads +1.50 or better.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.position_review import PositionReviewEngine

# The real trade, to the paisa.
ENTRY, EXIT, ENTRY_STOP, TARGET = 3152.50, 3586.00, 2994.875, 3539.28

#: What `initial_stop_price` always worked out to: tsl_percent, every trade.
FROZEN_STOP_FRACTION = 0.05


@pytest.fixture
def engine(tmp_path):
    return PositionReviewEngine(brain_root=tmp_path)


def _review(engine, risk_pct, **kwargs):
    defaults = dict(
        symbol="GOLDM26NOV141000PE", entry_price=ENTRY, exit_price=EXIT,
        stop_price=ENTRY_STOP, target_price=TARGET, conviction_score=59,
        position_size_pct=20.0, holding_days=0,
        exit_reason="TARGET_HIT: premium 3586.00 reached adaptive target",
        pnl=4335.0, decision_id="mcx-20261030113054", return_pct=0.1375,
        risk_pct=risk_pct,
    )
    defaults.update(kwargs)
    return engine.review_trade(**defaults)


# =================================================== chapter two: the number
def test_the_old_answer_was_reward_over_five_percent_of_premium(engine):
    """2.75 was not this trade's reward:risk. It was its reward divided by
    tsl_percent, which every entry path hardcodes into the same field."""
    r = _review(engine, FROZEN_STOP_FRACTION)
    assert r.risk_reward_achieved == pytest.approx(2.75, abs=0.01)


def test_the_real_risk_gives_a_different_answer(engine):
    """Where the ATR thesis stop binds it is tighter than 5%, so the trade
    earned MORE per unit risked than the old number said."""
    r = _review(engine, 0.0446)
    assert r.risk_reward_achieved == pytest.approx(3.08, abs=0.01)
    assert "Excellent R:R achieved: 3.08x" in r.lesson


def test_where_the_backstop_binds_the_answer_goes_the_other_way(engine):
    """The 12% premium backstop is WIDER than 5%, so the old number flattered
    the trade. The fix is not a uniform improvement, it is a correction."""
    r = _review(engine, 0.12)
    assert r.risk_reward_achieved == pytest.approx(1.15, abs=0.01)
    assert "Excellent R:R" not in r.lesson


def test_a_thesis_stop_loss_reads_exactly_minus_one_r(engine):
    """The structural property that proves the denominator. The thesis stop IS
    the risk, so running to it is -1.00 R and nothing else."""
    risk = 0.0446
    r = _review(
        engine, risk,
        exit_price=ENTRY * (1 - risk), pnl=-1581.0, return_pct=-risk,
        exit_reason="Underlying Thesis Stop: GOLDM moved 625.00 against position",
    )
    assert r.risk_reward_achieved == pytest.approx(-1.0, abs=0.001)


# ====================================== the floor cannot reach it any more
def test_the_trail_lock_floor_no_longer_touches_the_ratio(engine):
    """Chapter one's broken input, swept across its whole range. The grade does
    not read this field at all now, so none of it can move the answer."""
    ratios = {
        _review(engine, 0.0446, stop_price=stop).risk_reward_achieved
        for stop in (ENTRY, ENTRY_STOP, 0.0, -1.0, ENTRY * 0.5)
    }
    assert len(ratios) == 1


def test_the_old_lesson_is_exactly_what_no_longer_appears(engine):
    """Verbatim from hokage_brain/reviews/position_reviews.jsonl, 2026-10-30."""
    was = ("Low R:R of 0.00 despite profit — tighten target or improve exit "
           "timing.")
    assert was not in _review(engine, 0.0446).lesson
    assert was not in _review(engine, None).lesson


# ============================================== unmeasurable is not a ratio
@pytest.mark.parametrize("bad", [None, 0.0, -0.05, "wide"])
def test_an_unrecorded_risk_reports_unknown_not_zero(engine, bad):
    r = _review(engine, bad)
    assert r.risk_reward_achieved == 0.0   # field stays float for old readers
    # but nothing pretends it measured a ratio of zero
    assert "Low R:R" not in r.lesson
    assert "0.00" not in r.lesson
    assert "Excellent R:R" not in r.lesson


def test_there_is_no_fallback_to_the_old_arithmetic(engine):
    """A plausible wrong number is what kept this broken through one fix
    already. With no risk on record the answer is silence, even though
    entry_price and stop_price are both right there."""
    r = _review(engine, None, stop_price=ENTRY_STOP)
    assert r.risk_reward_achieved == 0.0


def test_a_real_low_ratio_is_still_called_out(engine):
    """Silence is only for UNMEASURABLE. A genuinely poor ratio must still
    earn its lesson, or this fix would have hidden the thing it protects."""
    r = engine.review_trade(
        symbol="X", entry_price=100.0, exit_price=102.0, stop_price=50.0,
        target_price=200.0, conviction_score=50, position_size_pct=20.0,
        holding_days=0, exit_reason="Take Profit", pnl=2.0, risk_pct=0.40,
    )
    assert r.risk_reward_achieved == pytest.approx(0.05, abs=0.01)
    assert "Low R:R" in r.lesson
    assert "one unit of what it risked" in r.lesson


# ========================================== the entry path still freezes it
def test_the_entry_path_records_a_stop_that_never_ratchets():
    """`initial_stop_price` is no longer an input to any grade, but it is still
    what the post-mortem reports, so it must still be frozen."""
    import bots.autonomous.autonomous_bot as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    # three creation sites (manual, MCX, index) plus the ATR fallback
    assert src.count('"initial_stop_price": tracked_entry_price') == 3
    assert 'tracking.setdefault("initial_stop_price"' in src
    # and nothing ratchets it afterwards
    assert 'tracking["initial_stop_price"] =' not in src


def test_the_review_is_handed_the_risk_not_a_stop_distance():
    src = Path(
        __import__("bots.autonomous.position_review", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    assert "self._compute_rr_achieved(entry_price, exit_price, risk_pct)" in src
    # the two forms this has already been wrong in
    assert "_compute_rr_achieved(entry_price, exit_price, stop_price)" not in src
    assert "abs(entry_price - stop_price)" not in src


def test_no_grade_reads_the_stop_price_or_the_target_any_more():
    """Both are recomputed or ratcheted live, so neither can carry an
    entry-time fact. They stay in the signatures for the record only, and the
    docstrings still discuss them - so this reads the AST, not the text."""
    import ast

    src = Path(
        __import__("bots.autonomous.position_review", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    graders = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and (node.name.startswith("_grade_") or node.name == "_compute_rr_achieved")
    }
    assert set(graders) == {
        "_grade_entry_quality", "_grade_exit_quality",
        "_grade_sizing_quality", "_grade_stop_quality", "_compute_rr_achieved",
    }, f"grader set changed: {sorted(graders)}"
    for name, node in graders.items():
        loaded = {
            n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        }
        assert "stop_price" not in loaded, f"{name} reads stop_price again"
        assert "target_price" not in loaded, f"{name} reads target_price again"


def test_the_exit_grade_is_invariant_to_both_as_well(engine):
    """The behavioural half of the same guard."""
    grades = {
        _review(engine, 0.0446, stop_price=stop, target_price=tgt).exit_quality
        for stop in (0.0, ENTRY, ENTRY * 2)
        for tgt in (0.0, TARGET, ENTRY * 0.5)
    }
    assert grades == {"ON_TARGET"}
