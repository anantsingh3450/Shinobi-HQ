"""Tests for PositionReviewEngine — Phase 4C.5D.

Covers: review_trade output schema, entry quality grading,
exit quality classification, sizing quality, stop quality,
R:R calculation, lesson generation, persistence to JSONL,
and load_reviews.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from bots.autonomous.position_review import PositionReviewEngine, PositionReview


@pytest.fixture
def engine(tmp_path: Path) -> PositionReviewEngine:
    return PositionReviewEngine(memory_manager=None, brain_root=tmp_path)


def _review(engine: PositionReviewEngine, **kwargs) -> PositionReview:
    defaults = dict(
        symbol="ONGC",
        entry_price=185.0,
        exit_price=198.5,
        stop_price=175.0,
        target_price=210.0,
        conviction_score=84,
        position_size_pct=2.0,
        holding_days=3,
        exit_reason="Take Profit Triggered",
        pnl=1200.0,
        decision_id="test-uuid-001",
        return_pct=0.073,
    )
    defaults.update(kwargs)
    return engine.review_trade(**defaults)


# ---------------------------------------------------------------------------
# Return type and schema
# ---------------------------------------------------------------------------

def test_review_returns_position_review(engine):
    r = _review(engine)
    assert isinstance(r, PositionReview)


def test_review_contains_decision_id(engine):
    r = _review(engine, decision_id="my-uuid-xyz")
    assert r.decision_id == "my-uuid-xyz"


def test_review_contains_symbol(engine):
    r = _review(engine, symbol="ONGC")
    assert r.symbol == "ONGC"


def test_review_contains_all_quality_fields(engine):
    r = _review(engine)
    assert r.entry_quality in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert r.exit_quality in ("ON_TARGET", "STOP_HIT", "PREMATURE", "TRAILING")
    assert r.sizing_quality in ("OVERSIZED", "CORRECT", "UNDERSIZED")
    assert r.stop_quality in ("TIGHT", "CORRECT", "WIDE")


def test_review_rr_achieved_is_float(engine):
    r = _review(engine)
    assert isinstance(r.risk_reward_achieved, float)


def test_review_lesson_is_non_empty_string(engine):
    r = _review(engine)
    assert isinstance(r.lesson, str)
    assert len(r.lesson) > 0


def test_review_pnl_stored(engine):
    r = _review(engine, pnl=1200.0)
    assert r.pnl == 1200.0


def test_review_timestamp_stored(engine):
    r = _review(engine)
    assert "T" in r.timestamp  # ISO 8601 format


# ---------------------------------------------------------------------------
# Exit quality classification
# ---------------------------------------------------------------------------

def test_exit_quality_take_profit(engine):
    r = _review(engine, exit_reason="Take Profit Triggered")
    assert r.exit_quality == "ON_TARGET"


def test_exit_quality_stop_hit(engine):
    # Exit below entry — stop hit as a loss
    r = _review(engine, exit_price=170.0, exit_reason="Stop-Loss Triggered", pnl=-800.0)
    assert r.exit_quality in ("STOP_HIT", "TRAILING")


def test_exit_quality_trailing(engine):
    r = _review(engine, exit_reason="Trailing Stop-Loss Triggered", exit_price=195.0)
    assert r.exit_quality == "TRAILING"


def test_exit_quality_premature(engine):
    r = _review(engine, exit_reason="Manual Exit", exit_price=190.0)
    assert r.exit_quality == "PREMATURE"


# ---------------------------------------------------------------------------
# Sizing quality
# ---------------------------------------------------------------------------

def test_sizing_quality_correct(engine):
    # 2.0 / 84 * 100 = 2.38 → within (0.5, 3.0) range = CORRECT
    r = _review(engine, position_size_pct=2.0, conviction_score=84)
    assert r.sizing_quality == "CORRECT"


def test_sizing_quality_oversized(engine):
    # 5.0 / 30 * 100 = 16.7 → > 3.0 → OVERSIZED
    r = _review(engine, position_size_pct=5.0, conviction_score=30)
    assert r.sizing_quality == "OVERSIZED"


def test_sizing_quality_undersized(engine):
    # 0.2 / 90 * 100 = 0.22 → < 0.5 → UNDERSIZED
    r = _review(engine, position_size_pct=0.2, conviction_score=90)
    assert r.sizing_quality == "UNDERSIZED"


# ---------------------------------------------------------------------------
# Stop quality
# ---------------------------------------------------------------------------

def test_stop_quality_correct(engine):
    # Stop 5% from entry: 185 * 0.05 = 9.25 → stop = 175 (5.4%) → CORRECT
    r = _review(engine, entry_price=185.0, stop_price=175.0)
    assert r.stop_quality == "CORRECT"


def test_stop_quality_tight(engine):
    # Stop < 3% from entry: 185 - 2 = 183 → 1.08%
    r = _review(engine, entry_price=185.0, stop_price=183.0)
    assert r.stop_quality == "TIGHT"


def test_stop_quality_wide(engine):
    # Stop > 10% from entry: 185 - 25 = 160 → 13.5%
    r = _review(engine, entry_price=185.0, stop_price=160.0)
    assert r.stop_quality == "WIDE"


# ---------------------------------------------------------------------------
# R:R computation
# ---------------------------------------------------------------------------

def test_rr_achieved_profitable(engine):
    # reward = 198.5 - 185 = 13.5, risk = 185 - 175 = 10 → R:R = 1.35
    r = _review(engine, entry_price=185.0, exit_price=198.5, stop_price=175.0)
    assert r.risk_reward_achieved == pytest.approx(1.35, abs=0.01)


def test_rr_achieved_loss(engine):
    # reward = 170 - 185 = -15, risk = 185 - 175 = 10 → R:R = -1.5
    r = _review(engine, entry_price=185.0, exit_price=170.0, stop_price=175.0, pnl=-800.0)
    assert r.risk_reward_achieved == pytest.approx(-1.5, abs=0.01)


def test_rr_zero_risk(engine):
    # stop_price == entry_price → risk = 0 → return 0
    r = _review(engine, entry_price=185.0, stop_price=185.0, exit_price=200.0)
    assert r.risk_reward_achieved == 0.0


# ---------------------------------------------------------------------------
# Lesson generation
# ---------------------------------------------------------------------------

def test_lesson_contains_symbol(engine):
    r = _review(engine, symbol="ONGC")
    assert "ONGC" in r.lesson


def test_lesson_mentions_pnl(engine):
    r = _review(engine, pnl=-400.0, exit_price=170.0, stop_price=175.0, exit_reason="Stop-Loss Triggered")
    assert "-400" in r.lesson or "loss" in r.lesson.lower()


def test_lesson_flags_oversized(engine):
    r = _review(engine, position_size_pct=5.0, conviction_score=30)
    assert "oversized" in r.lesson.lower() or "reduce" in r.lesson.lower()


def test_lesson_flags_tight_stop(engine):
    r = _review(engine, entry_price=185.0, stop_price=183.0)
    assert "tight" in r.lesson.lower() or "stop" in r.lesson.lower()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_review_persists_to_jsonl(engine, tmp_path):
    _review(engine, symbol="ONGC", decision_id="persist-test")
    assert engine.get_reviews_path().exists()


def test_load_reviews_returns_records(engine):
    _review(engine, symbol="ONGC")
    _review(engine, symbol="BEL")
    reviews = engine.load_reviews()
    assert len(reviews) == 2
    symbols = {r["symbol"] for r in reviews}
    assert "ONGC" in symbols
    assert "BEL" in symbols


def test_load_reviews_empty_when_no_file(tmp_path: Path):
    e = PositionReviewEngine(brain_root=tmp_path)
    assert e.load_reviews() == []


def test_reviews_jsonl_valid_per_line(engine):
    _review(engine, symbol="ONGC", decision_id="line-check-001")
    path = engine.get_reviews_path()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    for line in lines:
        obj = json.loads(line)
        assert "symbol" in obj
        assert "lesson" in obj
        assert "entry_quality" in obj
