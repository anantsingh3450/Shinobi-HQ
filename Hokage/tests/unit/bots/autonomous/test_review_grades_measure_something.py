"""Two of the four review grades were constants, and one pointed backwards.

Found 2026-11-01, auditing the three grades left unchecked when the R:R grade
was fixed (9f0d6f4).

ENTRY QUALITY was a readout of the risk config, not of the entry. All three
entry paths derive both levels from the entry itself —

    stop   = entry * (1 - tsl_percent)
    target = entry * (1 + tp_percent)

— so the entry price cancelled out of `deviation` completely, leaving
(0.9*tsl - 0.1*tp)/(tsl + tp) = 0.2333 at the production 5%/10% geometry, past
the 0.20 FAIR bound. POOR for every trade ever taken. The corpus:

    POOR 436 / 488 reviews

The 52 that read otherwise were records where entry_price and the levels it
was supposed to have generated had come apart. So on the 110 reviews with real
money attached:

    EXCELLENT   n= 5   win   0.0%   net  -7,721.75
    GOOD        n= 9   win  66.7%   net +11,262.50
    FAIR        n=32   win  21.9%   net -27,576.50
    POOR        n=64   win  54.7%   net +40,646.25

EXCELLENT lost money on every single trade it was given to. POOR made all of
it. And `_generate_lesson` forwarded "entry was placed too far from the ideal
entry zone" into long-term memory on every winner Hokage has ever had.

SIZING QUALITY read `allocation_pct`, which only ONE of the three entry paths
has ever written. MCX and manual entries fell to the `1.0` default, and
1.0/conviction*100 is inside the CORRECT band for every conviction he scores:

    CORRECT 487 / 488,  OVERSIZED 1

Both now grade from facts recorded on live tape, and both return UNKNOWN
rather than invent one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.position_review import (
    PositionReviewEngine,
    UNKNOWN,
    _ENTRY_MAE_EXCELLENT,
    _ENTRY_MAE_FAIR,
    _ENTRY_MAE_GOOD,
)
from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION


@pytest.fixture()
def engine(tmp_path: Path) -> PositionReviewEngine:
    return PositionReviewEngine(memory_manager=None, brain_root=tmp_path)


def _review(engine: PositionReviewEngine, **kwargs):
    defaults = dict(
        symbol="SILVERM26NOV184000PE",
        entry_price=39200.0,
        exit_price=43040.0,
        stop_price=37240.0,
        target_price=43120.0,
        conviction_score=70,
        position_size_pct=20.0,
        holding_days=0,
        exit_reason="TARGET_HIT: premium 43040.00 reached adaptive target",
        pnl=3840.0,
        decision_id="mcx-20261030130054",
        return_pct=0.098,
        holding_seconds=372.0,
        mae_pct=-1.2,
    )
    defaults.update(kwargs)
    return engine.review_trade(**defaults)


# =========================================================================
# ENTRY QUALITY: the price no longer cancels out
# =========================================================================

def test_the_entry_price_no_longer_decides_nothing(engine):
    """The defect itself, pinned at the production geometry.

    Under the old formula these five entries - five orders of magnitude apart,
    each with the stop and target its own path would have derived - all scored
    deviation 0.2333 and graded POOR. The grade could not distinguish them
    because the entry cancelled out.
    """
    tsl, tp = 0.05, 0.10
    grades = set()
    for entry in (1.0, 57.5, 1664.0, 6839.5, 184000.0):
        r = _review(
            engine,
            entry_price=entry,
            stop_price=entry * (1 - tsl),
            target_price=entry * (1 + tp),
            exit_price=entry * 1.05,
            # Same geometry, DIFFERENT heat taken.
            mae_pct=-1.0 if entry < 1000 else -20.0,
        )
        grades.add(r.entry_quality)
    assert grades == {"EXCELLENT", "POOR"}


def test_the_same_entry_graded_by_the_heat_it_took(engine):
    """One entry price, four grades, because the hold differed."""
    seen = [
        _review(engine, mae_pct=mae).entry_quality
        for mae in (-0.5, -5.0, -11.0, -22.0)
    ]
    assert seen == ["EXCELLENT", "GOOD", "FAIR", "POOR"]


@pytest.mark.parametrize("mae,expected", [
    (0.0, "EXCELLENT"),
    (_ENTRY_MAE_EXCELLENT, "EXCELLENT"),
    (_ENTRY_MAE_EXCELLENT - 0.01, "GOOD"),
    (_ENTRY_MAE_GOOD, "GOOD"),
    (_ENTRY_MAE_GOOD - 0.01, "FAIR"),
    (_ENTRY_MAE_FAIR, "FAIR"),
    (_ENTRY_MAE_FAIR - 0.01, "POOR"),
])
def test_the_band_edges_are_inclusive_of_the_better_grade(engine, mae, expected):
    assert engine._grade_entry_quality(mae) == expected


def test_an_unrecorded_excursion_is_unknown_not_a_grade(engine):
    """A trade that was never surveilled has no entry grade. It does not have
    an average one."""
    assert engine._grade_entry_quality(None) == UNKNOWN
    assert _review(engine, mae_pct=None).entry_quality == UNKNOWN


def test_a_positive_excursion_is_unknown_not_excellent(engine):
    """Hokage only ever BUYS premium, so the worst point of a hold cannot sit
    ABOVE the entry: a positive MAE is a broken record, not a clean entry.

    16 of the 110 real trades carry one - together -26,671.75 at a 6% win rate
    - and grading those EXCELLENT would rebuild the exact bug this replaces,
    where the best grade appeared only on losers.
    """
    assert engine._grade_entry_quality(0.19) == UNKNOWN
    assert engine._grade_entry_quality(16.80) == UNKNOWN
    assert _review(engine, mae_pct=16.80).entry_quality == UNKNOWN


def test_a_non_numeric_excursion_is_unknown(engine):
    assert engine._grade_entry_quality("deep") == UNKNOWN


# =========================================================================
# ENTRY QUALITY: the lesson it writes
# =========================================================================

def test_a_clean_winner_is_no_longer_told_its_entry_was_bad(engine):
    """SILVERM26NOV184000PE, 2026-10-30: +3,840 in six minutes, ON_TARGET,
    reviewed `entry=POOR` and handed the lesson "entry was placed too far from
    the ideal entry zone". It never went more than 1.2% underwater."""
    r = _review(engine, mae_pct=-1.2)
    assert r.entry_quality == "EXCELLENT"
    assert "ideal entry zone" not in r.lesson
    assert "suboptimal" not in r.lesson.lower()


def test_an_unknown_entry_grade_writes_no_sentence_at_all(engine):
    """Silence is the honest output. This text is forwarded to long-term
    memory, where a guess cannot be taken back."""
    r = _review(engine, mae_pct=None)
    assert r.entry_quality == UNKNOWN
    assert "entry" not in r.lesson.lower()


def test_a_genuinely_bad_entry_still_says_so(engine):
    r = _review(engine, mae_pct=-22.0)
    assert r.entry_quality == "POOR"
    assert "heat" in r.lesson.lower()


# =========================================================================
# SIZING QUALITY: it stops fabricating its own input
# =========================================================================

def test_an_unrecorded_size_is_unknown_not_correct(engine):
    """The whole defect. `allocation_pct` was absent on the MCX and manual
    paths, the review defaulted it to 1.0, and 1.0/conviction*100 lands in the
    CORRECT band for every conviction Hokage scores - 487 of 488 reviews."""
    assert engine._grade_sizing_quality(None, 70) == UNKNOWN
    assert _review(engine, position_size_pct=None).sizing_quality == UNKNOWN


def test_an_unknown_size_writes_no_sizing_sentence(engine):
    r = _review(engine, position_size_pct=None)
    assert r.sizing_quality == UNKNOWN
    assert "oversized" not in r.lesson.lower()
    assert "undersized" not in r.lesson.lower()


def test_sizing_is_graded_against_the_cap_the_router_enforces(engine):
    """Not an invented threshold: entitlement is MAX_PREMIUM_CHEST_FRACTION
    scaled by conviction, so a full-conviction trade may use the whole cap."""
    cap_pct = MAX_PREMIUM_CHEST_FRACTION * 100.0
    assert engine._grade_sizing_quality(cap_pct, 100) == "CORRECT"
    assert engine._grade_sizing_quality(cap_pct, 50) == "OVERSIZED"


def test_the_same_premium_grades_differently_against_different_conviction(engine):
    """Which is the point: sizing quality is a question about proportion."""
    assert engine._grade_sizing_quality(25.0, 90) == "CORRECT"
    assert engine._grade_sizing_quality(25.0, 30) == "OVERSIZED"
    assert engine._grade_sizing_quality(2.0, 90) == "UNDERSIZED"


def test_a_zero_size_is_unknown_not_undersized(engine):
    """A recorded size of zero is not a tiny position, it is a position whose
    cost could not be computed."""
    assert engine._grade_sizing_quality(0.0, 70) == UNKNOWN


def test_a_missing_conviction_is_unknown_not_correct(engine):
    """It used to return CORRECT, which asserted the size was right while
    admitting it did not know what it was being judged against."""
    assert engine._grade_sizing_quality(20.0, 0) == UNKNOWN


def test_a_non_numeric_size_is_unknown(engine):
    assert engine._grade_sizing_quality("large", 70) == UNKNOWN


# =========================================================================
# The record that goes to disk and to memory
# =========================================================================

def test_unknown_reaches_the_jsonl_as_unknown(engine):
    """Readers must be able to see that a grade was not computed. Writing a
    neutral grade instead would make an absence indistinguishable from a
    measurement."""
    import json

    _review(engine, mae_pct=None, position_size_pct=None)
    line = engine.get_reviews_path().read_text(encoding="utf-8").strip()
    row = json.loads(line)
    assert row["entry_quality"] == UNKNOWN
    assert row["sizing_quality"] == UNKNOWN


def test_both_grades_survive_a_full_review_round_trip(engine):
    r = _review(engine, mae_pct=-9.4, position_size_pct=30.0, conviction_score=30)
    assert r.entry_quality == "FAIR"
    assert r.sizing_quality == "OVERSIZED"
    assert r.exit_quality == "ON_TARGET"
    assert r.stop_quality == "CORRECT"
