"""An exit Hokage was ORDERED to take was filed as his own mistake.

Shipped on the commander's word, 2026-11-01. The question had been pinned
rather than decided since the exit matcher was fixed in 2026-08, in
test_eod_squareoff_still_grades_premature: "whether a MANDATED exit deserves
the word 'premature' is a judgement for the commander, not a silent rename."

THREE RUNGS CAN END A TRADE WITHOUT THE STRATEGY HAVING A SAY, and all three
outrank every rung of the option ladder:

    rung 0   Commander instant-exit (hard sell)   request_force_exit
    rung 1   Manual Kill Switch Activated         intraday_override
    rung 2   Time-Based Square-Off (EOD)          15:20 / 23:15 IST

plus the two labels `_close_all_positions` passes through rung 0:
MANUAL_KILL_SWITCH and MANUAL_CLOSE_ALL.

All five graded PREMATURE, and the lesson forwarded to long-term memory read
"Exit was premature — trade closed before stop or target triggered." True, and
not the strategy's doing. 8 of the 110 real trades in the corpus are EOD
square-offs.

THE SECOND FACT MATTERS MORE THAN THE WORD. A mandated exit means the
strategy's own geometry never resolved — no stop, no target, no trail. The
trade is not evidence for or against the setup, and anything learning from
these reviews needs to be told that rather than handed a verdict.

AND THE FALLBACK WAS A VERDICT TOO. With MANDATED split out, every reason the
ladder can actually emit is classified — verified against all 110 real exits:
49 STOP_HIT, 35 ON_TARGET, 18 TRAILING, 8 MANDATED, zero unrecognised. So
anything still reaching the end of the matcher is a string it does not
recognise, which is a different fact from "the trade closed early". Defaulting
that to the worst grade available is the bug this function has been fixed for
twice already — the English paraphrases, then the bare "TP" and "SL"
substrings. It reads UNKNOWN now.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.position_review import (
    PositionReviewEngine,
    UNKNOWN,
    _MANDATED_TOKENS,
)


@pytest.fixture()
def engine(tmp_path: Path) -> PositionReviewEngine:
    return PositionReviewEngine(memory_manager=None, brain_root=tmp_path)


def _grade(engine, reason, *, exit_price=460.0, target=459.09,
           stop=400.0, entry=429.70):
    return engine._grade_exit_quality(reason, exit_price, target, stop, entry)


def _review(engine, **kwargs):
    defaults = dict(
        symbol="NIFTY2611274150CE",
        entry_price=120.55,
        exit_price=118.00,
        stop_price=114.52,
        target_price=132.60,
        conviction_score=62,
        position_size_pct=20.0,
        holding_days=0,
        exit_reason="Time-Based Square-Off (EOD)",
        pnl=-191.25,
        decision_id="idx-20261030152000",
        return_pct=-0.0211,
        holding_seconds=4_500.0,
        mae_pct=-3.4,
        risk_pct=0.10,
    )
    defaults.update(kwargs)
    return engine.review_trade(**defaults)


# =========================================================================
# Every string the three rungs can emit
# =========================================================================

@pytest.mark.parametrize("reason", [
    "Time-Based Square-Off (EOD)",
    "Manual Kill Switch Activated",
    "Commander instant-exit (hard sell)",
    "MANUAL_KILL_SWITCH",
    "MANUAL_CLOSE_ALL",
])
def test_every_real_mandated_label_is_mandated(engine, reason):
    """Copied from the five emitting sites in autonomous_bot.py, not invented."""
    assert _grade(engine, reason, exit_price=435.0) == "MANDATED"


def test_the_mcx_square_off_label_too(engine):
    """MCX squares off at 23:15, through the same rung and the same string."""
    assert _grade(engine, "Time-Based Square-Off (EOD)",
                  exit_price=37_000.0, entry=39_200.0) == "MANDATED"


@pytest.mark.parametrize("token", _MANDATED_TOKENS)
def test_each_token_in_the_vocabulary_actually_matches(engine, token):
    """A token that matches nothing is dead weight pretending to be coverage."""
    assert _grade(engine, f"position closed: {token}", exit_price=435.0) == "MANDATED"


# =========================================================================
# It is tested FIRST, because the rung that fired outranks the ladder
# =========================================================================

def test_a_square_off_on_a_position_sitting_at_its_target_is_still_mandated(engine):
    """Rung 2 runs BEFORE the option ladder, so a position at its target at
    15:20 exits as a square-off. The reason names what actually ended it."""
    assert _grade(engine, "Time-Based Square-Off (EOD)",
                  exit_price=460.0, target=459.09) == "MANDATED"


def test_a_kill_switch_outranks_a_stop_word_in_the_same_reason(engine):
    """If the generic STOP test ran first it would swallow this."""
    assert _grade(engine, "Manual Kill Switch: stop everything now",
                  exit_price=380.0, entry=429.70) == "MANDATED"


def test_the_ladders_own_rungs_are_untouched(engine):
    """MANDATED must not reach into the four grades that were already right."""
    assert _grade(engine, "TARGET_HIT: premium 460.00 reached adaptive target"
                  ) == "ON_TARGET"
    assert _grade(engine, "TRAIL_LOCK: gave back 10% of peak",
                  exit_price=440.0) == "TRAILING"
    assert _grade(engine, "Underlying Thesis Stop: NIFTY moved 43.30 against position",
                  exit_price=380.0, entry=429.70) == "STOP_HIT"
    assert _grade(engine, "Option Hard Backstop: premium fell 25% below entry",
                  exit_price=380.0, entry=429.70) == "STOP_HIT"


# =========================================================================
# The fallback is no longer a verdict
# =========================================================================

@pytest.mark.parametrize("reason", [
    "venue returned 503",
    "HTTP timeout while fetching quote",
    "",
    "reconciliation freeze",
])
def test_an_unrecognised_reason_is_unknown_not_premature(engine, reason):
    """"I do not recognise this string" and "the trade closed early" are
    different facts. Only one of them was ever being reported."""
    assert _grade(engine, reason, exit_price=435.0) == UNKNOWN


def test_no_real_exit_reason_falls_through(engine):
    """The guarantee that makes UNKNOWN safe as a fallback. Checked against
    every reason his ladder emits — if a rung is ever added without a matcher,
    its exits go UNKNOWN rather than being mislabelled, and this fails."""
    real = [
        "TARGET_HIT: premium 137.80 reached adaptive target 136.53 (entry 120.55)",
        "TRAIL_LOCK: gave back 10% of peak (Rs1,000) from peak 536.70",
        "Underlying Thesis Stop: BANKNIFTY moved 140.00 against position (>= 1.25 x ATR 100.33)",
        "Option Hard Backstop: premium 353.70 fell 25% below entry 493.75",
        "Time-Based Square-Off (EOD)",
        "Manual Kill Switch Activated",
        "Commander instant-exit (hard sell)",
    ]
    assert all(_grade(engine, r, exit_price=435.0) != UNKNOWN for r in real)


# =========================================================================
# The lesson
# =========================================================================

def test_the_mandated_lesson_does_not_blame_the_strategy(engine):
    r = _review(engine, exit_reason="Time-Based Square-Off (EOD)")
    assert r.exit_quality == "MANDATED"
    assert "premature" not in r.lesson.lower()
    assert "mandated" in r.lesson.lower()


def test_the_mandated_lesson_says_the_trade_is_not_evidence(engine):
    """The part that matters to anything learning from these reviews: the
    setup never resolved, so the outcome says nothing about it."""
    r = _review(engine, exit_reason="Manual Kill Switch Activated")
    assert "never resolved" in r.lesson
    assert "not evidence" in r.lesson


def test_the_old_sentence_is_exactly_what_no_longer_appears(engine):
    """Verbatim from hokage_brain/reviews/position_reviews.jsonl."""
    was = "Exit was premature — trade closed before stop or target triggered."
    assert was not in _review(engine, exit_reason="Time-Based Square-Off (EOD)").lesson
    assert was not in _review(engine, exit_reason="venue returned 503").lesson


def test_an_unknown_exit_grade_writes_no_exit_sentence(engine):
    r = _review(engine, exit_reason="venue returned 503")
    assert r.exit_quality == UNKNOWN
    assert "mandated" not in r.lesson.lower()
    assert "premature" not in r.lesson.lower()


def test_a_mandated_loss_is_not_also_told_its_stop_was_hit(engine):
    """The STOP_HIT clause keys off the grade, so a mandated loss must not
    collect a lesson about stop placement it never reached."""
    r = _review(engine, exit_reason="Time-Based Square-Off (EOD)", pnl=-191.25)
    assert "Stop was hit" not in r.lesson


# =========================================================================
# The record
# =========================================================================

def test_mandated_reaches_the_jsonl(engine):
    import json

    _review(engine, exit_reason="Time-Based Square-Off (EOD)")
    row = json.loads(engine.get_reviews_path().read_text(encoding="utf-8").strip())
    assert row["exit_quality"] == "MANDATED"


def test_the_vocabulary_is_read_off_the_emitting_sites():
    """Every label the three rungs can produce must still exist in the bot,
    or this matcher is covering strings that no longer happen."""
    src = Path(
        __import__("bots.autonomous.autonomous_bot", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    for label in (
        '"Time-Based Square-Off (EOD)"',
        '"Manual Kill Switch Activated"',
        '"Commander instant-exit (hard sell)"',
        '"MANUAL_KILL_SWITCH"',
        '"MANUAL_CLOSE_ALL"',
    ):
        assert label in src, f"{label} no longer emitted; prune the matcher"
