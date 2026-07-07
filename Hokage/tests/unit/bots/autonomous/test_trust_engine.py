from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from bots.autonomous.trust_engine import ElderTrustEngine


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    return cache


def test_elder_trust_score_calculation(mock_cache):
    engine = ElderTrustEngine(mock_cache)
    
    # 1. Optimal conditions -> Grade A
    res_high = engine.calculate_trust_score(
        prediction_accuracy=90.0,
        drawdown_pct=2.0,
        consistency_score=95.0,
        risk_compliance=98.0,
        conviction_accuracy=90.0
    )
    # Drawdown control = 100 - 2*4 = 92
    # Weighted score: (90*0.25) + (92*0.25) + (95*0.20) + (98*0.15) + (90*0.15)
    # = 22.5 + 23.0 + 19.0 + 14.7 + 13.5 = 92.7 -> rounded 93
    assert res_high["trust_score"] == 93
    assert res_high["grade"] == "A"
    
    # 2. Degraded conditions (High drawdown, lower accuracy) -> Grade D/F
    res_low = engine.calculate_trust_score(
        prediction_accuracy=60.0,
        drawdown_pct=10.0,
        consistency_score=50.0,
        risk_compliance=90.0,
        conviction_accuracy=60.0
    )
    # Drawdown control = 100 - 10*4 = 60
    # Weighted: (60*0.25) + (60*0.25) + (50*0.20) + (90*0.15) + (60*0.15)
    # = 15.0 + 15.0 + 10.0 + 13.5 + 9.0 = 62.5 -> rounded 63
    assert res_low["trust_score"] == 63
    assert res_low["grade"] == "D"
