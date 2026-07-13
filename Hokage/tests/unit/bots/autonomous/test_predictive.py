from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from bots.autonomous.cache import IntelligenceCache
from bots.autonomous.conviction import ConvictionScoreEngine, NoTradeDecisionEngine
from bots.autonomous.predictive import (
    MarketRegimeEngine,
    MacroCorrelationEngine,
    EventImpactPredictor,
    SectorFlowForecastEngine,
    PredictionAccuracyTracker,
)
from bots.autonomous.discovery import OpportunityDiscoveryEngine


@pytest.fixture
def mock_cache(tmp_path):
    return IntelligenceCache(brain_root=tmp_path)


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.price_source.get_price.return_value = 23500.0
    return orch


def test_confidence_calculations(mock_orchestrator, mock_cache):
    # 1. MarketRegimeEngine
    regime_engine = MarketRegimeEngine(mock_orchestrator, mock_cache)
    regime_res = regime_engine.classify_regime()
    
    assert "prediction" in regime_res
    assert isinstance(regime_res["confidence"], float)
    assert 0.0 <= regime_res["confidence"] <= 1.0
    assert isinstance(regime_res["reasoning_factors"], list)
    
    # Verify predictions directory persistence
    pred_regime_file = mock_cache.get_cache_file_path("predictions/market_regime.json")
    assert pred_regime_file.exists()
    with pred_regime_file.open("r", encoding="utf-8") as fh:
        saved = json.load(fh)
        assert saved["confidence"] == regime_res["confidence"]

    # 2. EventImpactPredictor
    event_predictor = EventImpactPredictor(mock_cache)
    news = [{"title": "RBI rate cut planned", "description": "RBI governor announced rate cut potential."}]
    impact_res = event_predictor.predict_event_impact(news)
    
    assert "prediction" in impact_res
    assert impact_res["confidence"] == 0.70  # matched 'rbi' and 'rate cut'
    assert len(impact_res["reasoning_factors"]) > 0
    
    pred_event_file = mock_cache.get_cache_file_path("predictions/event_impact.json")
    assert pred_event_file.exists()

    # 3. SectorFlowForecastEngine
    macro_engine = MacroCorrelationEngine(mock_cache)
    flow_engine = SectorFlowForecastEngine(macro_engine, event_predictor, mock_cache)
    flow_res = flow_engine.forecast_flows(regime_res, impact_res)
    
    assert "prediction" in flow_res
    assert "forecast_flows" in flow_res["prediction"]
    assert isinstance(flow_res["confidence"], float)
    
    pred_flow_file = mock_cache.get_cache_file_path("predictions/sector_flow.json")
    assert pred_flow_file.exists()

    # 4. Opportunity Discovery Rankings confidence and persistence
    mock_scanner = MagicMock()
    mock_scanner.get_market_opportunity_universe.return_value = ["TCS", "INFY", "ONGC"]
    discovery_engine = OpportunityDiscoveryEngine(mock_scanner, mock_cache)
    
    opps = discovery_engine.discover_opportunities("OPEN_MARKET")
    assert len(opps) == 3
    
    pred_opp_file = mock_cache.get_cache_file_path("predictions/opportunity_rankings.json")
    assert pred_opp_file.exists()
    with pred_opp_file.open("r", encoding="utf-8") as fh:
        saved_opps = json.load(fh)
        assert saved_opps["confidence"] == 0.85
        assert saved_opps["prediction"] == ["TCS", "INFY", "ONGC"]


def test_conviction_grading(mock_cache):
    conv_engine = ConvictionScoreEngine(mock_cache)
    
    # High signals -> A+
    grade_1 = conv_engine.grade_conviction(
        confidence_score=0.95,
        analog_similarity=98.0,
        sector_flow_strength=0.15,
        regime_certainty=0.95,
        news_consistency=0.95,
        symbol="ONGC"
    )
    assert grade_1 == "A+"
    
    # Moderate signals -> B
    grade_2 = conv_engine.grade_conviction(
        confidence_score=0.70,
        analog_similarity=80.0,
        sector_flow_strength=0.03,
        regime_certainty=0.70,
        news_consistency=0.65,
        symbol="TCS"
    )
    assert grade_2 in ("B", "C")
    
    # Low signals -> D
    grade_3 = conv_engine.grade_conviction(
        confidence_score=0.40,
        analog_similarity=40.0,
        sector_flow_strength=-0.05,
        regime_certainty=0.30,
        news_consistency=0.20
    )
    assert grade_3 == "D"
    
    # Check conviction cache file exists
    conv_file = mock_cache.get_cache_file_path("conviction_scores.json")
    assert conv_file.exists()
    with conv_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
        assert "ONGC" in data
        assert "TCS" in data
        assert "overall" in data
        assert data["ONGC"]["conviction"] == "A+"


def test_no_trade_generation(mock_cache):
    no_trade_engine = NoTradeDecisionEngine(mock_cache)
    
    # Test Normal conditions -> PAPER TRADE
    res_normal = no_trade_engine.evaluate_no_trade(
        regime_confidence=0.80,
        flow_confidence=0.75,
        vix_impact_delta=0.5
    )
    assert res_normal["prediction"] == "TRADE"
    assert res_normal["recommended_action"] == "PAPER TRADE"
    
    # Test High VIX delta -> NO TRADE
    res_vix = no_trade_engine.evaluate_no_trade(
        regime_confidence=0.80,
        flow_confidence=0.75,
        vix_impact_delta=3.5
    )
    assert res_vix["prediction"] == "NO TRADE"
    assert res_vix["recommended_action"] == "NO TRADE"
    assert any("VIX" in r for r in res_vix["reasoning_factors"])
    
    # Test Low confidence -> NO TRADE
    res_low_conf = no_trade_engine.evaluate_no_trade(
        regime_confidence=0.50,
        flow_confidence=0.75,
        vix_impact_delta=0.5
    )
    assert res_low_conf["prediction"] == "NO TRADE"
    assert res_low_conf["recommended_action"] == "NO TRADE"
    
    # Test conflicting signals -> NO TRADE
    res_conflict = no_trade_engine.evaluate_no_trade(
        regime_confidence=0.80,
        flow_confidence=0.75,
        vix_impact_delta=0.5,
        conflicting_signals=True
    )
    assert res_conflict["prediction"] == "NO TRADE"
    assert res_conflict["recommended_action"] == "NO TRADE"
    assert "Conflicting macro signals." in res_conflict["reasoning_factors"]


def test_prediction_accuracy_tracker(mock_cache):
    tracker = PredictionAccuracyTracker(mock_cache)
    
    # Record a correct regime prediction
    tracker.record_prediction(
        category="market_regime",
        prediction_val="BULL_RISK-ON",
        confidence=0.85,
        outcome_val="BULL_RISK-ON",
        correct=True
    )
    
    # Record an incorrect event impact prediction
    tracker.record_prediction(
        category="event_impact",
        prediction_val={"banking": 0.05},
        confidence=0.70,
        outcome_val={"banking": -0.02},
        correct=False
    )
    
    # Verify rolling stats
    assert tracker.stats["total_predictions"] == 2
    assert tracker.stats["correct_predictions"] == 1
    assert tracker.stats["overall_accuracy"] == 50.0
    
    assert tracker.stats["regime_prediction_accuracy"] == 100.0
    assert tracker.stats["event_prediction_accuracy"] == 0.0
    
    # Verify persistence file
    acc_file = mock_cache.get_cache_file_path("prediction_accuracy.json")
    assert acc_file.exists()
    with acc_file.open("r", encoding="utf-8") as fh:
        saved_stats = json.load(fh)
        assert saved_stats["overall_accuracy"] == 50.0
        assert saved_stats["regime_prediction_accuracy"] == 100.0
        assert len(saved_stats["history"]) == 2
