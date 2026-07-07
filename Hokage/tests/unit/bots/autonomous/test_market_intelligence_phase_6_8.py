"""Unit tests for Phase 6.8: Market Intelligence."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from bots.autonomous.cache import IntelligenceCache
from bots.autonomous.conviction import ConvictionScoreEngine
from bots.autonomous.economic_calendar import EconomicCalendarEngine
from bots.autonomous.earnings_calendar import EarningsCalendarEngine
from bots.autonomous.fii_dii_engine import FIIDIIEngine
from bots.autonomous.options_intelligence import OptionsIntelligenceEngine
from bots.autonomous.breadth_engine import BreadthEngine
from bots.autonomous.market_intelligence import MarketIntelligenceEngine


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock(spec=IntelligenceCache)
    cache.read_intelligence.return_value = {}
    return cache


@pytest.fixture
def mock_orchestrator(tmp_path) -> MagicMock:
    orch = MagicMock()
    orch.resolver = MagicMock()
    # Return a real temporary directory path so exists() etc. work properly
    orch.resolver.resolve_brain_root.return_value = tmp_path
    return orch


def test_economic_calendar_engine():
    engine = EconomicCalendarEngine({"type": "mock_economic"})
    events = engine.fetch_events()
    assert len(events) > 0
    assert any(e["severity"] == "HIGH" for e in events)
    
    score = engine.compute_impact_score(events)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


def test_earnings_calendar_engine():
    engine = EarningsCalendarEngine({"type": "mock_earnings"})
    releases = engine.fetch_releases(["TCS", "INFY"])
    assert len(releases) > 0
    assert any(r["symbol"] == "TCS" for r in releases)


def test_fii_dii_flows_engine():
    engine = FIIDIIEngine({"type": "mock_flows"})
    flows = engine.fetch_flows()
    assert "fii_net_crores" in flows
    assert "dii_net_crores" in flows
    
    regime = engine.determine_regime(flows)
    assert regime in ("BULLISH", "BEARISH", "NEUTRAL")


def test_options_intelligence():
    engine = OptionsIntelligenceEngine({"type": "mock_options"})
    metrics = engine.fetch_options_metrics("NIFTY")
    assert "pcr" in metrics
    
    regime = engine.classify_sentiment(metrics)
    assert regime in ("BULLISH", "BEARISH", "NEUTRAL", "OVERBOUGHT", "OVERSOLD")


def test_breadth_intelligence():
    engine = BreadthEngine({"type": "mock_breadth"})
    breadth = engine.fetch_breadth()
    assert "ad_ratio" in breadth
    
    score = engine.get_market_health_score(breadth)
    assert 0.0 <= score <= 100.0


def test_market_intelligence_orchestrator(mock_orchestrator, mock_cache):
    # Setup scanner mock
    scanner_mock = MagicMock()
    scanner_mock.scan_indices.return_value = {"NIFTY 50": 23500.0}
    mock_orchestrator.market_scanner = scanner_mock
    
    engine = MarketIntelligenceEngine(mock_orchestrator, mock_cache)
    
    # Mock cache read/write behavior
    mock_cache.read_intelligence.return_value = None
    
    # Compute unified report
    report = engine.compute_unified_report()
    
    assert report["enabled"] is True
    assert 0 <= report["confidence"] <= 100
    assert report["macro_regime"] in ("RISK-ON", "RISK-OFF", "INFLATION SHOCK", "STATIONARY")
    assert isinstance(report["economic_events"], list)
    assert isinstance(report["earnings_releases"], list)
    assert "sector_rotation" in report
    
    # Verify cache write was called
    mock_cache.write_intelligence.assert_called_with("market_intelligence.json", report)


def test_conviction_score_adjustments(mock_cache):
    conv_engine = ConvictionScoreEngine(mock_cache)
    
    # Test 1: No market intelligence report exists
    mock_cache.read_intelligence.return_value = None
    res1 = conv_engine.calculate_conviction(
        market_regime_score=0.8,
        sector_rotation_strength=0.05,
        symbol="TCS",
        sector="it"
    )
    assert res1["market_intelligence"]["adjustment"] == 0.0
    assert "No market intelligence adjustments applied." in res1["market_intelligence"]["reason"]

    # Test 2: Low confidence report (below 50%) -> no adjustments applied
    mock_cache.read_intelligence.return_value = {
        "enabled": True,
        "confidence": 45.0,
        "macro_regime": "RISK-ON",
        "sector_rotation": {"strongest": ["it"], "weakest": ["metals"]}
    }
    res2 = conv_engine.calculate_conviction(
        market_regime_score=0.8,
        sector_rotation_strength=0.05,
        symbol="TCS",
        sector="it"
    )
    assert res2["market_intelligence"]["adjustment"] == 0.0
    assert "below minimum threshold" in res2["market_intelligence"]["reason"]

    # Test 3: RISK-ON macro regime + top sector rotation adjustment (+3 for RISK-ON IT, +5 for top rotation = +8)
    mock_cache.read_intelligence.return_value = {
        "enabled": True,
        "confidence": 85.0,
        "macro_regime": "RISK-ON",
        "sector_rotation": {"strongest": ["it"], "weakest": ["metals"]}
    }
    res3 = conv_engine.calculate_conviction(
        market_regime_score=0.8,
        sector_rotation_strength=0.05,
        symbol="TCS",
        sector="it"
    )
    assert res3["market_intelligence"]["adjustment"] == 8.0
    assert "RISK-ON macro regime favors growth sectors (+3)" in res3["market_intelligence"]["reason"]
    assert "Sector it ranks in top rotation strength (+5)" in res3["market_intelligence"]["reason"]

    # Test 4: RISK-OFF macro regime + bottom sector rotation adjustment (-4 for RISK-OFF IT, -5 for bottom rotation = -9)
    mock_cache.read_intelligence.return_value = {
        "enabled": True,
        "confidence": 90.0,
        "macro_regime": "RISK-OFF",
        "sector_rotation": {"strongest": ["energy"], "weakest": ["it"]}
    }
    res4 = conv_engine.calculate_conviction(
        market_regime_score=0.8,
        sector_rotation_strength=0.05,
        symbol="TCS",
        sector="it"
    )
    assert res4["market_intelligence"]["adjustment"] == -9.0
    assert "RISK-OFF macro regime penalizes speculative sectors (-4)" in res4["market_intelligence"]["reason"]
    assert "Sector it ranks in bottom rotation strength (-5)" in res4["market_intelligence"]["reason"]


def test_cli_command_router(mock_orchestrator, mock_cache, tmp_path):
    from hokage.router.command_router import CommandRouter
    
    # Mock report
    mock_report = {
        "macro_regime": "RISK-ON",
        "confidence": 85.0,
        "event_impact_score": 1.25,
        "breadth_health_score": 75.0,
        "flows_regime": "BULLISH",
        "options_regime": "BULLISH",
        "explainable_summary": "Test Summary Narrative",
        "sector_rotation": {
            "sector_details": {
                "it": {"momentum_score": 12.5, "capital_flow_coefficient": 0.05}
            }
        },
        "economic_events": [
            {"severity": "HIGH", "event": "RBI Rate Stance", "country": "IN", "actual": "6.5%", "forecast": "6.5%"}
        ],
        "earnings_releases": [
            {"symbol": "TCS", "surprise_pct": 2.5, "eps_estimate": "35.5", "eps_actual": "36.4"}
        ]
    }
    mock_cache.read_intelligence.return_value = mock_report
    
    router = CommandRouter(mock_orchestrator)
    # Stub orchestrator resolver/brain root
    mock_orchestrator.resolver.resolve_brain_root.return_value = tmp_path
    
    # Patch get_or_compute_report to avoid local instantiations failing
    with patch("bots.autonomous.market_intelligence.MarketIntelligenceEngine.get_or_compute_report", return_value=mock_report):
        output = router.handle_command("hokage market-intelligence")
        assert "=== Hokage Market Intelligence ===" in output
        assert "Macro Regime:           RISK-ON" in output
        assert "Report Confidence:      85%" in output
        assert "Event Impact Score:     +1.25" in output
        assert "FII/DII Flows Regime:   BULLISH" in output
        assert "Test Summary Narrative" in output
        assert "it" in output
        assert "RBI Rate" in output
        assert "TCS" in output
