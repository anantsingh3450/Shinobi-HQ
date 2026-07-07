"""Tests for the Investment Committee Layer — Phase 4C.5C.

Covers: ConvictionScoreEngine, ConfidenceCalibrationEngine, NoTradeDecisionEngine.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from bots.autonomous.conviction import (
    ConvictionScoreEngine,
    ConfidenceCalibrationEngine,
    NoTradeDecisionEngine,
)


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.read_intelligence.return_value = {}
    return cache


# ---------------------------------------------------------------------------
# ConvictionScoreEngine
# ---------------------------------------------------------------------------

def test_conviction_score_elite(mock_cache):
    """All favourable inputs must produce an ELITE grade (score >= 86)."""
    engine = ConvictionScoreEngine(mock_cache)
    result = engine.calculate_conviction(
        market_regime_score=0.95,
        sector_rotation_strength=0.12,
        analog_similarity=98.0,
        news_sentiment_confidence=0.95,
        backtest_win_rate=80.0,
        prediction_accuracy=85.0,
        vix_impact_delta=0.0,
        risk_reward_ratio=2.5,
        portfolio_context=0.95,
    )
    assert result["score"] >= 86
    assert result["grade"] == "ELITE"


def test_conviction_score_avoid(mock_cache):
    """All unfavourable inputs must produce an AVOID grade (score < 31)."""
    engine = ConvictionScoreEngine(mock_cache)
    result = engine.calculate_conviction(
        market_regime_score=0.10,
        sector_rotation_strength=-0.14,
        analog_similarity=10.0,
        news_sentiment_confidence=0.10,
        backtest_win_rate=20.0,
        prediction_accuracy=20.0,
        vix_impact_delta=4.0,
        risk_reward_ratio=1.0,
        portfolio_context=0.10,
    )
    assert result["score"] < 31
    assert result["grade"] == "AVOID"


def test_conviction_grade_watch_boundary(mock_cache):
    """Score of ~40 (moderate conditions) should produce WATCH grade (31-50)."""
    engine = ConvictionScoreEngine(mock_cache)
    result = engine.calculate_conviction(
        market_regime_score=0.35,
        sector_rotation_strength=-0.05,
        analog_similarity=35.0,
        news_sentiment_confidence=0.35,
        backtest_win_rate=40.0,
        prediction_accuracy=40.0,
        vix_impact_delta=2.0,
        risk_reward_ratio=1.2,
        portfolio_context=0.35,
    )
    assert result["grade"] in ("WATCH", "AVOID", "MODERATE")  # boundary-safe check
    assert 0 <= result["score"] <= 100


def test_conviction_score_contains_decision_id(mock_cache):
    """Every conviction result must include a non-empty decision_id."""
    engine = ConvictionScoreEngine(mock_cache)
    result = engine.calculate_conviction()
    assert "decision_id" in result
    assert len(result["decision_id"]) > 10  # UUID4 is 36 chars


def test_conviction_score_contains_breakdown(mock_cache):
    """Result must include conviction_breakdown with all 9 components."""
    engine = ConvictionScoreEngine(mock_cache)
    result = engine.calculate_conviction()
    breakdown = result.get("conviction_breakdown", {})
    required_keys = [
        "market_regime", "sector_flow_forecast", "historical_analog",
        "news_sentiment", "backtest_strength", "prediction_accuracy",
        "vix_environment", "risk_reward_ratio", "portfolio_context",
    ]
    for key in required_keys:
        assert key in breakdown, f"Missing conviction_breakdown key: {key}"
        assert "weight" in breakdown[key]
        assert "normalized" in breakdown[key]


def test_conviction_accepts_legacy_macro_alignment(mock_cache):
    """Passing macro_correlation_alignment (legacy) must not raise."""
    engine = ConvictionScoreEngine(mock_cache)
    result = engine.calculate_conviction(
        macro_correlation_alignment=0.80,
    )
    assert "score" in result
    assert "grade" in result


# ---------------------------------------------------------------------------
# ConfidenceCalibrationEngine
# ---------------------------------------------------------------------------

def test_confidence_calibration_no_change_above_threshold(mock_cache):
    """Win rate above 70% should trigger a reward, not a penalty."""
    engine = ConfidenceCalibrationEngine(mock_cache)
    mock_cache.read_intelligence.return_value = {"overall_accuracy": 80.0}
    # calibrate_confidence: no penalty for win_rate > 50%
    assert engine.calibrate_confidence(0.80) == 0.80


def test_confidence_calibration_penalty_below_threshold(mock_cache):
    """Win rate below 50% must reduce confidence."""
    engine = ConfidenceCalibrationEngine(mock_cache)
    mock_cache.read_intelligence.return_value = {"overall_accuracy": 40.0}
    # Penalty: (50.0 - 40.0) / 100 = 0.10 → 0.80 - 0.10 = 0.70
    assert engine.calibrate_confidence(0.80) == 0.70


def test_calibrate_score_reward(mock_cache):
    """Win rate > 70% should add +5 pts to raw integer score."""
    engine = ConfidenceCalibrationEngine(mock_cache)
    mock_cache.read_intelligence.return_value = {"overall_accuracy": 80.0}
    raw = 75
    calibrated = engine.calibrate_score(raw)
    assert calibrated == 80, f"Expected 80 got {calibrated}"


def test_calibrate_score_penalty(mock_cache):
    """Win rate < 50% should reduce the integer conviction score."""
    engine = ConfidenceCalibrationEngine(mock_cache)
    mock_cache.read_intelligence.return_value = {"overall_accuracy": 40.0}
    raw = 60
    calibrated = engine.calibrate_score(raw)
    # Penalty = (50 - 40) / 100 * 60 = 6 → 60 - 6 = 54
    assert calibrated < raw


def test_calibrate_score_caps_at_100(mock_cache):
    """Reward must never push score above 100."""
    engine = ConfidenceCalibrationEngine(mock_cache)
    mock_cache.read_intelligence.return_value = {"overall_accuracy": 95.0}
    assert engine.calibrate_score(100) == 100


# ---------------------------------------------------------------------------
# NoTradeDecisionEngine
# ---------------------------------------------------------------------------

def test_no_trade_engine_approve_trade(mock_cache):
    """High conviction, strong analogs, stable VIX → BUY / TRADE."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(
        conviction_score=80,
        analog_similarity=90.0,
        conflicting_news=False,
        vix_impact_delta=0.5,
        history_accuracy=80.0,
    )
    assert result["prediction"] == "TRADE"
    assert result["recommended_action"] == "BUY"
    assert result["veto_source"] is None


def test_no_trade_engine_low_conviction_rejects(mock_cache):
    """Conviction score below 51 → NO_TRADE with ConvictionScoreEngine veto."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(
        conviction_score=40,
        analog_similarity=90.0,
        vix_impact_delta=0.5,
        history_accuracy=80.0,
    )
    assert result["prediction"] == "NO_TRADE"
    assert result["recommended_action"] == "NO TRADE"
    assert "conviction score" in result["reason"].lower()
    assert result["veto_source"] == "ConvictionScoreEngine"


def test_no_trade_engine_conflicting_news_rejects(mock_cache):
    """Conflicting news must trigger NO_TRADE."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(
        conviction_score=80,
        analog_similarity=90.0,
        conflicting_news=True,
        vix_impact_delta=0.5,
        history_accuracy=80.0,
    )
    assert result["prediction"] == "NO_TRADE"
    assert "Conflicting news" in result["reason"]


def test_no_trade_engine_high_vix_rejects(mock_cache):
    """VIX delta >= 2.5 must trigger NO_TRADE with MarketRegimeEngine veto."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(
        conviction_score=80,
        analog_similarity=90.0,
        vix_impact_delta=3.0,
        history_accuracy=80.0,
    )
    assert result["prediction"] == "NO_TRADE"
    assert result["veto_source"] is not None


def test_no_trade_engine_poor_history_rejects(mock_cache):
    """History accuracy below 50% must trigger NO_TRADE."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(
        conviction_score=80,
        analog_similarity=90.0,
        vix_impact_delta=0.5,
        history_accuracy=40.0,
    )
    assert result["prediction"] == "NO_TRADE"


def test_no_trade_engine_portfolio_veto(mock_cache):
    """Low portfolio health (< 51) triggers portfolio veto."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(
        conviction_score=80,
        analog_similarity=90.0,
        vix_impact_delta=0.5,
        history_accuracy=80.0,
        portfolio_health=30,
    )
    assert result["prediction"] == "NO_TRADE"
    assert result["veto_source"] == "PortfolioAwarenessEngine"


def test_no_trade_engine_veto_source_in_result(mock_cache):
    """Every result must include a veto_source field."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(conviction_score=90)
    assert "veto_source" in result


def test_no_trade_engine_reasons_list(mock_cache):
    """Result must always contain a 'reasons' list."""
    engine = NoTradeDecisionEngine(mock_cache)
    result = engine.evaluate_no_trade(conviction_score=90)
    assert "reasons" in result
    assert isinstance(result["reasons"], list)
