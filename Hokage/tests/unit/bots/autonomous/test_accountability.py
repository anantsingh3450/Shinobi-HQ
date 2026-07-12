"""Unit tests for Execution Accountability & Event-Driven Surveillance — Phase 5B.3/A/A.1."""
from __future__ import annotations

import json
from pathlib import Path


from bots.autonomous.models import AssetDecisionState, TradeAuthorization, NoTradeDecision, AssetSurveillanceState
from bots.autonomous.decision_journal import DecisionJournalSystem
from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


def test_trade_authorization_model():
    auth = TradeAuthorization(
        asset="CRUDE_OIL",
        timestamp="2026-06-24T20:28:00Z",
        direction="LONG",
        conviction_score=85,
        risk_reward=2.5,
        trend_validation=True,
        volatility_validation=True,
        capital_preservation_validation=True,
        universe_validation=True,
        execution_reason="Breakout trend confirmed",
        authorised_by="Elder Anant"
    )
    d = auth.to_dict()
    assert d["asset"] == "CRUDE_OIL"
    assert d["direction"] == "LONG"
    assert d["conviction_score"] == 85
    assert d["authorised_by"] == "Elder Anant"

    auth2 = TradeAuthorization.from_dict(d)
    assert auth2.asset == "CRUDE_OIL"
    assert auth2.direction == "LONG"
    assert auth2.conviction_score == 85
    assert auth2.authorised_by == "Elder Anant"


def test_no_trade_decision_model():
    dec = NoTradeDecision(
        asset="CRUDE_OIL",
        timestamp="2026-06-24T20:28:00Z",
        decision="NO_TRADE",
        confidence=91,
        reasons=("Risk/reward below threshold", "Conflicting trend signals"),
        supporting_evidence={"signal": "bearish_divergence"},
        invalidated_setups=("breakout_setup",),
        next_review_time="15:00"
    )
    d = dec.to_dict()
    assert d["asset"] == "CRUDE_OIL"
    assert d["confidence"] == 91
    assert d["reasons"] == ["Risk/reward below threshold", "Conflicting trend signals"]
    assert d["next_review_time"] == "15:00"

    dec2 = NoTradeDecision.from_dict(d)
    assert dec2.asset == "CRUDE_OIL"
    assert dec2.confidence == 91
    assert dec2.reasons == ("Risk/reward below threshold", "Conflicting trend signals")
    assert dec2.next_review_time == "15:00"


def test_asset_surveillance_state_model():
    state = AssetSurveillanceState(
        asset="CRUDE_OIL",
        state=AssetDecisionState.WAITING,
        conviction_score=75,
        risk_score=1.5,
        current_blockers=("VIX spike",),
        missing_confirmations=("trend breakout",),
        next_review_time="15:00",
        what_would_trigger="breakout above 75.50",
        last_changed_at="2026-06-24T20:28:00Z"
    )
    d = state.to_dict()
    assert d["asset"] == "CRUDE_OIL"
    assert d["state"] == "WAITING"
    assert d["current_blockers"] == ["VIX spike"]
    
    state2 = AssetSurveillanceState.from_dict(d)
    assert state2.asset == "CRUDE_OIL"
    assert state2.state == AssetDecisionState.WAITING
    assert state2.current_blockers == ("VIX spike",)


def test_cli_command_router_accountability_handlers(tmp_path: Path):
    # Setup mock folders for orchestrator
    orchestrator = HokageOrchestrator(brain_root=tmp_path)
    router = CommandRouter(orchestrator)
    
    # 1. Test wait-reason output when no state exists
    res = router.handle_command("hokage wait-reason")
    assert "No active surveillance state exists" in res

    # Create dummy surveillance state file
    auton_dir = tmp_path / "autonomous"
    auton_dir.mkdir(parents=True, exist_ok=True)
    surv_file = auton_dir / "asset_surveillance_state.json"
    
    dummy_state = {
        "CRUDE_OIL": {
            "asset": "CRUDE_OIL",
            "state": "WAITING",
            "conviction_score": 75,
            "risk_score": 1.5,
            "current_blockers": ["VIX spike"],
            "missing_confirmations": ["breakout"],
            "what_would_trigger": "breakout above 75.50",
            "next_review_time": "15:00",
            "last_changed_at": "2026-06-24T20:28:00Z"
        }
    }
    with surv_file.open("w", encoding="utf-8") as f:
        json.dump(dummy_state, f)
        
    res = router.handle_command("hokage wait-reason")
    assert "Asset:                  CRUDE_OIL" in res
    assert "State:                  WAITING" in res
    assert "Current Blockers:       VIX spike" in res

    # 2. Test what-changed output
    res = router.handle_command("hokage what-changed")
    assert "Active State:     WAITING" in res
    assert "Conviction Score: 75/100" in res

    # 3. Test show-authorization output when empty
    res = router.handle_command("hokage show-authorization")
    assert "No trade authorizations" in res

    # Record a trade authorization
    journal = DecisionJournalSystem(brain_root=tmp_path)
    auth = TradeAuthorization(
        asset="CRUDE_OIL",
        timestamp="2026-06-24T20:28:00Z",
        direction="LONG",
        conviction_score=85,
        risk_reward=2.5,
        trend_validation=True,
        volatility_validation=True,
        capital_preservation_validation=True,
        universe_validation=True,
        execution_reason="Breakout trend confirmed",
        authorised_by="Elder Anant"
    )
    journal.record_trade_authorization(auth)

    res = router.handle_command("hokage show-authorization")
    assert "Asset:                  CRUDE_OIL" in res
    assert "Direction:              LONG" in res
    assert "Authorised By:          Elder Anant" in res

    # 4. Test show-rejection output when empty
    res = router.handle_command("hokage show-rejection")
    assert "No rejections" in res

    # Record a no-trade decision
    dec = NoTradeDecision(
        asset="CRUDE_OIL",
        timestamp="2026-06-24T20:28:00Z",
        decision="NO_TRADE",
        confidence=91,
        reasons=("Risk/reward below threshold",),
        supporting_evidence={},
        invalidated_setups=("breakout_setup",),
        next_review_time="15:00"
    )
    journal.record_no_trade_decision(dec)

    res = router.handle_command("hokage show-rejection")
    assert "Asset:                  CRUDE_OIL" in res
    assert "Reasons:\n  * Risk/reward below threshold" in res
