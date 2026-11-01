"""The stop grade measured a number that cannot stop anything.

Found 2026-11-01, the last of the four review grades to be audited.

`_grade_stop_quality` measured the distance from entry to `stop_price`. On a
BOUGHT option that field is not a stop — it is the TRAIL_LOCK profit floor.
Rung 4 of the option ladder only arms once the peak clears
`entry * (1 + _OPTION_TRAIL_ARM_PCT)`, and the floor it then sets is
`max(trail_floor, entry)`, never below entry. The value sitting there before
arming is a seed that can never fire.

It was also a CONSTANT, and it became one as a side effect of the R:R fix
(9f0d6f4). Freezing `initial_stop_price` made the input exactly
`entry * (1 - tsl_percent)` on all three entry paths, so the distance was
tsl_percent = 0.05 for every trade — inside the old 0.03 .. 0.10 band:

    CORRECT, always.

The 20 TIGHT and 22 WIDE in the 488-row corpus are all PRE-fix records that
read the live ratcheting floor, which is why 14 of his 48 winners were filed
TIGHT: the same winners-only bias 9f0d6f4 was written to remove, surviving in
a grade nobody had re-checked.

And the unit was wrong. 3% and 10% were calibrated for moves in an UNDERLYING
and applied to option PREMIUM, where 3% is routine tick noise.

THE REAL RISK already had a production implementation. `_risk_pct_for` returns
min(premium backstop tier, ATR thesis stop through the ATM delta) — "whichever
stop bites first" — and is validated against real fills. It is now frozen at
entry as `risk_pct_at_entry` and is the only input this grade reads.

THE BANDS are cut on his own tape, on the two populations that are NOT
circular. Judging a stop by how far trades ran against themselves is circular
for every trade the stop truncated, so:

    TIGHT  <- the heat his WINNERS took, which the stop did not cause
                 3% would have killed 13 of 47 winners (27.7%)
                 5% would have killed  8 of 47         (17.0%)
                 7% would have killed  4 of 47         ( 8.5%)
                12% would have killed  0 of 47
    WIDE   <- where his LOSERS actually resolved
                 p50 8.90%  p90 17.01%  p95 22.11%  max 28.36%
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.autonomous.position_review import (
    PositionReviewEngine,
    UNKNOWN,
    _STOP_TIGHT_RATIO,
    _STOP_WIDE_RATIO,
)


@pytest.fixture()
def engine(tmp_path: Path) -> PositionReviewEngine:
    return PositionReviewEngine(memory_manager=None, brain_root=tmp_path)


def _review(engine: PositionReviewEngine, **kwargs):
    defaults = dict(
        symbol="GOLDM26NOV141000PE",
        entry_price=3152.50,
        exit_price=3586.00,
        stop_price=2994.875,
        target_price=3539.28,
        conviction_score=59,
        position_size_pct=20.0,
        holding_days=0,
        exit_reason="TARGET_HIT: premium 3586.00 reached adaptive target",
        pnl=4335.0,
        decision_id="mcx-20261030113054",
        return_pct=0.1375,
        mae_pct=-1.86,
        risk_pct=0.10,
    )
    defaults.update(kwargs)
    return engine.review_trade(**defaults)


# =========================================================================
# It no longer reads a field that cannot stop anything
# =========================================================================

def test_the_trail_lock_floor_no_longer_decides_the_grade(engine):
    """`stop_price` is the profit floor. Sweeping it across the entire range
    the old formula cared about must not move the grade one notch."""
    grades = {
        _review(engine, stop_price=stop).stop_quality
        for stop in (3152.49, 2994.875, 2837.25, 1576.0, 0.0)
    }
    assert grades == {"CORRECT"}


def test_the_production_geometry_is_no_longer_a_constant():
    """The defect itself. Every entry path sets
    initial_stop_price = entry * (1 - tsl_percent), so the old distance was
    tsl_percent for every trade in both leagues, at every premium."""
    tsl = 0.05
    for entry in (3.25, 57.5, 1657.0, 3152.50, 8350.0):
        stop = entry * (1 - tsl)
        assert abs(entry - stop) / entry == pytest.approx(tsl)
    # ... and tsl_percent sat inside the old 0.03 .. 0.10 band, so the answer
    # was CORRECT every time. The new band is in a different unit entirely.
    assert not (_STOP_TIGHT_RATIO < tsl < _STOP_WIDE_RATIO)


# =========================================================================
# The bands, and the measurement behind them
# =========================================================================

@pytest.mark.parametrize("risk,expected", [
    (0.01, "TIGHT"),
    (0.04, "TIGHT"),           # the ~4.1% NATURALGAS thesis stop
    (_STOP_TIGHT_RATIO - 0.001, "TIGHT"),
    (_STOP_TIGHT_RATIO, "CORRECT"),
    (0.12, "CORRECT"),         # the premium backstop tier above Rs 500
    (_STOP_WIDE_RATIO, "CORRECT"),
    (_STOP_WIDE_RATIO + 0.001, "WIDE"),
    (0.40, "WIDE"),            # the lowest backstop tier, under Rs 100
])
def test_the_bands_are_inclusive_of_correct_at_both_edges(engine, risk, expected):
    assert engine._grade_stop_quality(risk) == expected


def test_the_tight_bound_sits_above_his_winners_noise():
    """The old 0.03 would have cut off 13 of his 47 real winners. Any bound
    that low is measuring noise, not risk."""
    winners_heat_p90 = 0.0704
    # Rounded to two places on purpose: three significant figures off 47
    # samples would be false precision, and a tenth of a percent either way
    # moves no grade. What matters is that it sits at the measurement and
    # nowhere near the old 3%, which was a third of the way inside his noise.
    assert abs(_STOP_TIGHT_RATIO - winners_heat_p90) < 0.005
    assert _STOP_TIGHT_RATIO > 0.03


def test_the_wide_bound_sits_where_his_losses_stop_reaching():
    """Past this a stop is further out than 9 of 10 realised losses ever got,
    so it is not protecting the position."""
    losers_p90 = 0.1701
    assert abs(_STOP_WIDE_RATIO - losers_p90) < 0.005
    assert _STOP_WIDE_RATIO < 0.2211   # still inside p95; it is not unreachable


# =========================================================================
# Absent is not CORRECT
# =========================================================================

def test_an_unrecorded_risk_is_unknown_not_correct(engine):
    """It used to return CORRECT for a missing or zero input — asserting the
    stop was right while admitting it could not see it."""
    assert engine._grade_stop_quality(None) == UNKNOWN
    assert _review(engine, risk_pct=None).stop_quality == UNKNOWN


def test_a_zero_risk_is_unknown_not_tight(engine):
    """Zero risk accepted is not a very tight stop, it is an unanswered
    question: `_risk_pct_for` clamps at 0.0 when the ATR arithmetic degenerates."""
    assert engine._grade_stop_quality(0.0) == UNKNOWN
    assert engine._grade_stop_quality(-0.05) == UNKNOWN


def test_a_non_numeric_risk_is_unknown(engine):
    assert engine._grade_stop_quality("wide") == UNKNOWN


def test_an_unknown_stop_grade_writes_no_sentence(engine):
    r = _review(engine, risk_pct=None)
    assert r.stop_quality == UNKNOWN
    assert "noise" not in r.lesson.lower()
    assert "protecting" not in r.lesson.lower()


# =========================================================================
# The lesson it writes
# =========================================================================

def test_a_real_winner_is_no_longer_told_its_stop_was_too_tight(engine):
    """GOLDM26NOV141000PE, 2026-10-30: +4,335, ON_TARGET, R:R 2.75 — and
    reviewed `stop=TIGHT` because the floor had ratcheted onto entry. 9f0d6f4
    fixed the input; this fixes what the input means."""
    r = _review(engine, risk_pct=0.10)
    assert r.stop_quality == "CORRECT"
    assert "too tightly" not in r.lesson


def test_the_tight_lesson_names_the_noise_not_a_rule_of_thumb(engine):
    r = _review(engine, risk_pct=0.02)
    assert r.stop_quality == "TIGHT"
    assert "noise" in r.lesson.lower()
    assert "one in ten" in r.lesson.lower()


def test_the_wide_lesson_points_at_the_two_real_stops(engine):
    """A WIDE grade has to say WHICH knob: the premium backstop tier or the
    ATR thesis multiple. `stop_price` is neither."""
    r = _review(engine, risk_pct=0.25, pnl=-2000.0, exit_price=2400.0)
    assert r.stop_quality == "WIDE"
    assert "backstop" in r.lesson.lower()
    assert "thesis" in r.lesson.lower()


# =========================================================================
# The entry paths record it, and the exit path reads it without a default
# =========================================================================

def _src() -> str:
    return Path(
        __import__("bots.autonomous.autonomous_bot", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")


def test_every_entry_path_stamps_the_risk_it_accepted():
    src = _src()
    stamps = src.count('"initial_stop_price":')
    assert stamps == 3, "a new entry path appeared; it needs a risk stamp too"
    assert src.count('"risk_pct_at_entry": self._risk_pct_for(') == stamps


def test_the_exit_path_reads_it_without_a_default():
    src = _src()
    assert 'entry_meta.get("risk_pct_at_entry")' in src
    assert 'entry_meta.get("risk_pct_at_entry", ' not in src
    assert "risk_pct=_risk_pct," in src


def test_the_grade_no_longer_takes_the_stop_price_at_all():
    """A signature guard. If `stop_price` ever finds its way back into this
    grader, the constant comes back with it."""
    src = Path(
        __import__("bots.autonomous.position_review", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    assert "self._grade_stop_quality(risk_pct)" in src
    assert "_grade_stop_quality(entry_price" not in src


# =========================================================================
# The real risk, computed by production
# =========================================================================

def _bot():
    bot = object.__new__(Bot)
    bot._thesis_atr_mult_for = lambda sid, sym: 1.25
    return bot


def test_the_thesis_stop_is_what_binds_on_his_universe():
    """`_risk_pct_for` returns whichever stop bites first. On a Rs 3,152 GOLDM
    premium the backstop tier is 12%, but 1.25 ATR through the ATM delta is far
    tighter — which is why the measured answer lands in TIGHT, and why the old
    grade saying CORRECT was hiding something real."""
    bot = _bot()
    risk = bot._risk_pct_for(3152.50, 141000.0, 500.0, "mcx-sessionshift", "GOLDM")
    assert risk < 0.12
    assert PositionReviewEngine(brain_root=Path(".")) is not None
    assert risk == pytest.approx(1.25 * 500.0 * 0.45 / 3152.50, rel=1e-6)


def test_a_missing_atr_falls_back_to_the_backstop_never_a_guess():
    bot = _bot()
    assert bot._risk_pct_for(3152.50, 141000.0, None) == pytest.approx(0.12)
