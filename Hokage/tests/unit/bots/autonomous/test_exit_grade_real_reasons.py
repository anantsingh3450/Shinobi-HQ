"""Grade exits by the strings production actually emits, not paraphrases of them.

2026-08-19: a CRUDEOIL call hit its adaptive target to the rupee — entry 429.70,
exit 460.00, target 459.09 — and the position review filed it as
`exit=PREMATURE`. So did the previous day's winner. Both looked like evidence
that Hokage was taking profit too early. Neither was.

`_grade_exit_quality` matched English phrases ("TAKE PROFIT", "TSL") that the
exit ladder has never emitted. Production emits TOKENS. Across every exit in
Hokage's history:

    Underlying Thesis Stop   26   STOP_HIT    matched by luck, "Stop"
    EOD                      18   PREMATURE   fair
    TARGET_HIT               15   PREMATURE   WRONG, it is ON_TARGET
    Option Hard Backstop     12   STOP_HIT    matched, "stop" in "Backstop"
    TRAIL_LOCK                9   PREMATURE   WRONG, it is TRAILING

24 of 80 exits — 30%, and every single target hit — fell through to the worst
available grade, and `_build_lesson` wrote "Exit was premature" into fifteen
autopsies of trades that closed exactly on target. ImprovementBot learns from
that corpus.

The old tests could not catch this: they fed the grader "Take Profit Triggered"
and "Trailing Stop-Loss Triggered", encoding the same fiction the code held.
These tests use the real strings, copied from the logs.
"""
from __future__ import annotations

import pytest

from bots.autonomous.position_review import PositionReviewEngine


@pytest.fixture()
def engine():
    return PositionReviewEngine()


def _grade(engine, reason, *, exit_price=460.0, target=459.09,
           stop=400.0, entry=429.70):
    return engine._grade_exit_quality(reason, exit_price, target, stop, entry)


# ------------------------------------------------- the real production strings
def test_target_hit_is_on_target_not_premature(engine):
    """The exact reason from the 2026-08-19 CRUDEOIL win."""
    reason = "TARGET_HIT: premium 460.00 reached adaptive target 459.09 (entry 429.70)"
    assert _grade(engine, reason) == "ON_TARGET"


def test_trail_lock_is_trailing_not_premature(engine):
    reason = ("TRAIL_LOCK: gave back ₹1,000 from peak 536.70 "
              "— premium 536.70 hit protective floor 542.64")
    assert _grade(engine, reason) == "TRAILING"


def test_underlying_thesis_stop_is_a_stop(engine):
    reason = ("Underlying Thesis Stop: SILVERM moved 335.00 against position "
              "(>= 1.25 x ATR 266.14)")
    assert _grade(engine, reason, exit_price=380.0, entry=429.70) == "STOP_HIT"


def test_option_hard_backstop_is_a_stop(engine):
    """Matches on "stop" inside "Backstop" — correct, but only by accident, so
    pin it before someone reorders the checks."""
    assert _grade(engine, "Option Hard Backstop breached",
                  exit_price=380.0, entry=429.70) == "STOP_HIT"


def test_eod_squareoff_still_grades_premature(engine):
    """Deliberately unchanged. An EOD square-off really did close before either
    level was reached; whether a MANDATED exit deserves the word "premature" is
    a judgement for the commander, not a silent rename."""
    assert _grade(engine, "EOD square-off at 15:20 IST",
                  exit_price=435.0) == "PREMATURE"


# ------------------------------------------------------------ ordering matters
def test_target_hit_wins_over_a_stop_word_in_the_same_reason(engine):
    """"Option Hard Backstop" contains "stop". If the generic STOP test ran
    first it would swallow every reason checked after it."""
    assert _grade(engine, "TARGET_HIT after trailing stop was raised") == "ON_TARGET"


def test_trail_lock_wins_over_the_generic_stop_test(engine):
    assert _grade(engine, "TRAIL_LOCK: protective floor, stop moved up",
                  exit_price=440.0) == "TRAILING"


# -------------------------------------------------- the old paraphrases still work
def test_english_phrases_are_still_honoured(engine):
    """The previous vocabulary stays supported — the fix ADDS the real tokens
    rather than swapping one guess for another."""
    assert _grade(engine, "Take Profit Triggered") == "ON_TARGET"
    assert _grade(engine, "Trailing Stop-Loss Triggered", exit_price=440.0) == "TRAILING"
    assert _grade(engine, "Manual Exit", exit_price=440.0) == "PREMATURE"


def test_a_bare_tp_no_longer_false_matches(engine):
    """The old matcher accepted "TP" anywhere in the string, so any reason
    containing those two letters graded as a target hit."""
    assert _grade(engine, "HTTP timeout while fetching quote",
                  exit_price=440.0) == "PREMATURE"


def test_a_bare_sl_no_longer_false_matches(engine):
    """"SL" was the same landmine as "TP", still armed after that fix: it was
    a bare substring, so it matched SLIPPAGE and graded a quote problem as a
    stop loss. Whole-word now."""
    assert _grade(engine, "SLIPPAGE guard tripped on the exit quote",
                  exit_price=380.0, entry=429.70) == "PREMATURE"


def test_a_bare_tsl_no_longer_false_matches(engine):
    """"TSL" matched TSLA, and the thesis-stop reason interpolates the
    underlying's own name into its text."""
    assert _grade(engine, "Position closed on the TSLA correlation cap",
                  exit_price=440.0) == "PREMATURE"


def test_the_whole_words_themselves_still_match(engine):
    """Tokenising must not drop the real tokens it was protecting."""
    assert _grade(engine, "TSL raised to 536.70", exit_price=440.0) == "TRAILING"
    assert _grade(engine, "SL hit", exit_price=380.0, entry=429.70) == "STOP_HIT"


# ------------------------------------------------------- the lesson that followed
def test_a_target_hit_no_longer_generates_a_premature_lesson(engine):
    """The grade is not cosmetic — it writes the autopsy ImprovementBot reads."""
    lesson = engine._generate_lesson(
        symbol="CRUDEOIL26SEP8150CE",
        entry_quality="GOOD",
        exit_quality=_grade(
            engine,
            "TARGET_HIT: premium 460.00 reached adaptive target 459.09 (entry 429.70)",
        ),
        sizing_quality="CORRECT",
        stop_quality="CORRECT",
        rr_achieved=1.41,
        pnl=3030.0,
        holding_days=0,
        conviction_score=58,
    )
    assert "premature" not in lesson.lower()
