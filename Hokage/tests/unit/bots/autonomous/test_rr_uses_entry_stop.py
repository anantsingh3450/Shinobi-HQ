"""The review measured risk against a stop that had moved.

On 2026-10-30 GOLDM26NOV141000PE was bought at 3152.50 with a stop at
2994.875, ran 71 minutes, and exited ON_TARGET at 3586.00 for +4,335 — a
13.8% gain at a true 2.75 R:R. It was reviewed as:

    entry=GOOD exit=ON_TARGET sizing=CORRECT stop=TIGHT R:R=0.00

and the lesson forwarded to long-term memory read "Stop was placed too
tightly" and "Low R:R of 0.00 despite profit — tighten target or improve exit
timing." Both wrong, on the best trade of the day.

ONE CAUSE, BOTH SYMPTOMS. `tracking["stop_price"]` is a live trailing floor
with four writers; the ladder sets it to `average_price` at Target 1 ("Stop
moved to breakeven"). By exit the floor sat ON entry, so risk was zero:
`risk == 0` returned 0.00, and a stop distance of zero graded TIGHT.

IT ONLY BIT WINNERS. SILVERM26NOV184000PE, entered the same evening and held
six minutes, was scored 1.96 correctly — its floor never had time to ratchet.
The longer a trade won, the more certainly its review was corrupted, which is
the worst possible direction for a bias in a system that learns from reviews.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.position_review import PositionReviewEngine

# The real trade, to the paisa.
ENTRY, EXIT, ENTRY_STOP, TARGET = 3152.50, 3586.00, 2994.875, 3539.28


@pytest.fixture
def engine(tmp_path):
    return PositionReviewEngine(brain_root=tmp_path)


def _review(engine, stop):
    return engine.review_trade(
        symbol="GOLDM26NOV141000PE", entry_price=ENTRY, exit_price=EXIT,
        stop_price=stop, target_price=TARGET, conviction_score=59,
        position_size_pct=2.0, holding_days=0,
        exit_reason="TARGET_HIT: premium 3586.00 reached adaptive target",
        pnl=4335.0, decision_id="mcx-20261030113054", return_pct=0.1375,
    )


# ------------------------------------------------- the trade, measured right
def test_the_real_trade_scores_its_real_ratio(engine):
    r = _review(engine, ENTRY_STOP)
    assert r.risk_reward_achieved == pytest.approx(2.75, abs=0.01)
    assert r.stop_quality == "CORRECT"      # 5.0% away, not TIGHT
    assert "too tightly" not in r.lesson
    assert "Low R:R" not in r.lesson
    assert "Excellent R:R achieved: 2.75" in r.lesson


# --------------------------------- a floor sitting on entry is UNKNOWN, not 0
def test_a_ratcheted_floor_reports_unknown_not_zero(engine):
    """The exact broken input: break-even floor passed as the stop."""
    r = _review(engine, ENTRY)
    assert r.risk_reward_achieved == 0.0   # field stays float for old readers
    # but nothing pretends it measured a ratio of zero
    assert "Low R:R" not in r.lesson
    assert "0.00" not in r.lesson
    assert "Excellent R:R" not in r.lesson


def test_the_old_lesson_is_exactly_what_no_longer_appears(engine):
    """Verbatim from hokage_brain/reviews/position_reviews.jsonl, 2026-10-30."""
    was = ("Low R:R of 0.00 despite profit — tighten target or improve exit "
           "timing.")
    assert was not in _review(engine, ENTRY).lesson
    assert was not in _review(engine, ENTRY_STOP).lesson


def test_a_real_low_ratio_is_still_called_out(engine):
    """Silence is only for UNMEASURABLE. A genuinely poor ratio must still
    earn its lesson, or this fix would have hidden the thing it protects."""
    r = engine.review_trade(
        symbol="X", entry_price=100.0, exit_price=102.0, stop_price=50.0,
        target_price=200.0, conviction_score=50, position_size_pct=2.0,
        holding_days=0, exit_reason="Take Profit", pnl=2.0,
    )
    assert r.risk_reward_achieved == pytest.approx(0.04, abs=0.01)
    assert "Low R:R" in r.lesson


def test_an_absent_stop_is_unknown_not_zero_risk(engine):
    for bad in (0.0, -1.0):
        r = _review(engine, bad)
        assert r.risk_reward_achieved == 0.0
        assert "Low R:R" not in r.lesson


def test_a_loss_is_unaffected(engine):
    r = engine.review_trade(
        symbol="Y", entry_price=100.0, exit_price=95.0, stop_price=95.0,
        target_price=110.0, conviction_score=50, position_size_pct=2.0,
        holding_days=0, exit_reason="Assassin Stop-Loss Triggered", pnl=-500.0,
    )
    assert r.risk_reward_achieved == pytest.approx(-1.0, abs=0.01)


# --------------------------------------------- the entry path freezes the stop
def test_the_entry_path_records_a_stop_that_never_ratchets():
    import bots.autonomous.autonomous_bot as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    # three creation sites (manual, MCX, index) plus the ATR fallback
    assert src.count('"initial_stop_price": tracked_entry_price') == 3
    assert 'tracking.setdefault("initial_stop_price"' in src
    # and nothing ratchets it afterwards
    assert 'tracking["initial_stop_price"] =' not in src


def test_the_review_prefers_the_frozen_stop_over_the_live_floor():
    import bots.autonomous.autonomous_bot as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert 'entry_meta.get("initial_stop_price")' in src
    # the blind form that caused this must not come back
    assert 'stored_stop_price    = entry_meta.get("stop_price", 0.0)' not in src
