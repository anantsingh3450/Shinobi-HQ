"""Unit tests for the Investment Committee & Institutional Decision Engine."""
from __future__ import annotations


import pytest

from bots.autonomous.committee import (
    InvestmentCommittee,
    CommitteeLedger,
    CommitteePerformanceTracker,
    Vote,
    CommitteeDecision,
)
from bots.strategy.models import StrategyProposal
from bots.backtest.models import BacktestResult
from hokage.memory.resolver import PathResolver


@pytest.fixture
def temp_brain_resolver(tmp_path):
    """Fixture returning a PathResolver pointed to a temp dir."""
    return PathResolver(tmp_path)


def test_vote_serialization():
    v = Vote(
        vote="APPROVE",
        confidence=85.0,
        reasoning="Strong setup.",
        evidence={"param": 10},
        uncertainty=0.15,
        veto_status=False
    )
    d = v.to_dict()
    assert d["vote"] == "APPROVE"
    assert d["confidence"] == 85.0
    assert d["reasoning"] == "Strong setup."
    assert d["evidence"] == {"param": 10}
    assert d["uncertainty"] == 0.15
    assert d["veto_status"] is False

    v2 = Vote.from_dict(d)
    assert v2.vote == "APPROVE"
    assert v2.confidence == 85.0
    assert v2.reasoning == "Strong setup."
    assert v2.uncertainty == 0.15


def test_committee_veto_override(temp_brain_resolver):
    ic = InvestmentCommittee(temp_brain_resolver)
    
    proposal = StrategyProposal(
        name="TestStrategy",
        description="test description",
        market="INFY",
        entry_rule="long",
        exit_rule="none",
        stop_loss_rule="none",
        take_profit_rule="none",
        timeframe="15m",
        confidence_score=0.85,
        sources_cited=()
    )
    
    br = BacktestResult(
        proposal_id="proposal-123",
        total_trades=10,
        win_rate=60.0,
        net_profit=5000.0,
        max_drawdown=5.0,
        profit_factor=2.0,
        passed=True,
        summary="Passed",
        after_tax_net_profit=4500.0,
        tax_estimate=500.0,
        provider="HistoricalBacktestEngine"
    )

    # 1. Test Approved Flow (no vetoes, high score)
    context = {
        "market_regime": "NORMAL",
        "vix_impact_delta": 0.5,
        "sector_flow_strength": 0.08,
        "preservation_mode": "NORMAL",
        "drawdown_pct": 1.2,
        "cash_available": True,
        "valid_price": True,
        "risk_approved": True,
        "risk_reason": "Approved",
        "strategy_confidence": 75.0,
        "strategy_name": "TestStrategy",
    }
    
    decision = ic.evaluate_proposal(proposal, br, context)
    assert decision.final_verdict == "APPROVED"
    assert decision.veto_triggered is False
    assert decision.decision_confidence > 70.0

    # 2. Test Vetoed Flow (Risk vetoes even though trend/macro approve)
    context["risk_approved"] = False
    context["risk_reason"] = "Position exceeds single sector exposure limit."
    
    decision_veto = ic.evaluate_proposal(proposal, br, context)
    assert decision_veto.final_verdict == "REJECTED"
    assert decision_veto.veto_triggered is True
    assert "Risk" in decision_veto.veto_committees


def test_committee_ledger_atomic_writes(temp_brain_resolver):
    ledger = CommitteeLedger(temp_brain_resolver)
    
    # Verify starting state
    assert len(ledger.load_entries()) == 0

    # Setup dummy decision
    mock_votes = {
        "Research": Vote("APPROVE", 90.0, "reason", {}, 0.1),
        "Trend": Vote("APPROVE", 80.0, "reason", {}, 0.2),
        "Risk": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
        "CapitalPreservation": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
        "LiquidityExecution": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
    }
    from bots.autonomous.committee import CommitteeDecision
    dec = CommitteeDecision(
        final_verdict="APPROVED",
        votes=mock_votes,
        approval_percentage=100.0,
        decision_confidence=94.0,
        veto_triggered=False,
        rejecting_committees=[],
        veto_committees=[],
        evidence_references={"drawdown": 1.5}
    )

    # Record first decision
    ledger.record_decision("dec-1", "strat-1", "INFY", dec)
    entries = ledger.load_entries()
    assert len(entries) == 1
    assert entries[0]["opportunity_id"] == "dec-1"
    assert entries[0]["symbol"] == "INFY"
    assert entries[0]["final_verdict"] == "APPROVED"

    # Record second decision
    dec.final_verdict = "REJECTED"
    dec.veto_triggered = True
    dec.veto_committees = ["Risk"]
    ledger.record_decision("dec-2", "strat-1", "TCS", dec)
    
    entries_after = ledger.load_entries()
    assert len(entries_after) == 2
    assert entries_after[1]["opportunity_id"] == "dec-2"
    assert entries_after[1]["symbol"] == "TCS"
    assert entries_after[1]["final_verdict"] == "REJECTED"


def test_performance_tracking_and_calibration(temp_brain_resolver):
    ledger = CommitteeLedger(temp_brain_resolver)
    tracker = CommitteePerformanceTracker(temp_brain_resolver)
    
    # Log 2 trades
    mock_votes_1 = {
        "Research": Vote("APPROVE", 90.0, "reason", {}, 0.1),
        "Trend": Vote("APPROVE", 80.0, "reason", {}, 0.2),
        "Risk": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
        "CapitalPreservation": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
        "LiquidityExecution": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
    }
    dec1 = CommitteeDecision(
        final_verdict="APPROVED",
        votes=mock_votes_1,
        approval_percentage=100.0,
        decision_confidence=94.0,
        veto_triggered=False,
        rejecting_committees=[],
        veto_committees=[],
        evidence_references={"drawdown": 1.5}
    )
    ledger.record_decision("dec-1", "strat-1", "INFY", dec1)

    mock_votes_2 = {
        "Research": Vote("APPROVE", 90.0, "reason", {}, 0.1),
        # Trend votes REJECT on a trade that will actually win (incorrect)
        "Trend": Vote("REJECT", 80.0, "reason", {}, 0.2),
        "Risk": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
        "CapitalPreservation": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
        "LiquidityExecution": Vote("APPROVE", 100.0, "reason", {}, 0.0, veto_status=True),
    }
    dec2 = CommitteeDecision(
        final_verdict="APPROVED",
        votes=mock_votes_2,
        approval_percentage=80.0,
        decision_confidence=92.0,
        veto_triggered=False,
        rejecting_committees=[],
        veto_committees=[],
        evidence_references={"drawdown": 1.5}
    )
    ledger.record_decision("dec-2", "strat-1", "TCS", dec2)

    # dummy actual outcomes
    outcomes = [
        {"decision_id": "dec-1", "outcome": "WIN"},
        {"decision_id": "dec-2", "outcome": "WIN"}, # dec-2 is a WIN, so Trend's REJECT vote was incorrect
    ]

    stats = tracker.compute_stats(outcomes)
    # Research voted APPROVE on both, and both were WINs -> 100% accuracy
    assert stats["Research"]["accuracy"] == 100.0
    # Trend voted APPROVE on dec-1 (correct) and REJECT on dec-2 (incorrect) -> 50% accuracy
    assert stats["Trend"]["accuracy"] == 50.0

    # Calibrate weights
    new_weights = tracker.calibrate_weights(outcomes)
    # Research weight should evolve upwards (baseline is 1.0)
    assert new_weights["Research"] > 1.0
    # Trend weight should evolve downwards
    assert new_weights["Trend"] < 1.0
