"""Tests for DecisionJournalSystem — Phase 4C.5C + 4C.5D.

Covers: journal persistence, accepted/rejected logging, Phase 4C.5C schema fields,
backward-compatible legacy fields, load_journal_entries, filter helpers,
reasoning_chain (Phase 4C.5D), update_decision_outcome (immutable outcomes file),
get_summary_stats, and JSON Lines format validity.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from bots.autonomous.decision_journal import DecisionJournalSystem


@pytest.fixture
def journal(tmp_path: Path) -> DecisionJournalSystem:
    return DecisionJournalSystem(brain_root=tmp_path)


# ---------------------------------------------------------------------------
# Schema and basic write tests
# ---------------------------------------------------------------------------

def test_journal_file_created_on_record(journal: DecisionJournalSystem):
    journal.record_decision(symbol="ONGC", decision="ACCEPTED", conviction=88)
    assert journal.get_journal_path().exists()


def test_accepted_entry_schema(journal: DecisionJournalSystem):
    entry = journal.record_decision(
        symbol="RELIANCE",
        decision="ACCEPTED",
        conviction=82,
        conviction_breakdown={"market_regime": {"weight": 0.15, "normalized": 85.0}},
        reason="Investment Committee authorized.",
        veto_source=None,
        market_regime="BULL_RISK-ON",
        sector_flow="Energy → Financials",
        expected_holding_days=4,
        expected_return_pct=3.5,
        expected_risk_pct=1.2,
        decision_id="test-uuid-0001",
    )
    assert entry["decision"] == "ACCEPTED"
    assert entry["conviction"] == 82
    assert entry["decision_id"] == "test-uuid-0001"
    assert entry["veto_source"] is None
    assert entry["market_regime"] == "BULL_RISK-ON"
    assert entry["sector_flow"] == "Energy → Financials"
    assert entry["expected_holding_days"] == 4
    assert entry["expected_return_pct"] == 3.5
    assert entry["expected_risk_pct"] == 1.2
    assert "conviction_breakdown" in entry


def test_rejected_entry_schema(journal: DecisionJournalSystem):
    entry = journal.record_decision(
        symbol="HDFCBANK",
        decision="REJECTED",
        conviction=35,
        reason="Conviction score too low.",
        veto_source="ConvictionScoreEngine",
        decision_id="test-uuid-0002",
    )
    assert entry["decision"] == "REJECTED"
    assert entry["veto_source"] == "ConvictionScoreEngine"
    assert "Conviction score" in entry["reason"]


def test_journal_persists_to_disk(journal: DecisionJournalSystem):
    journal.record_decision(symbol="TCS", decision="ACCEPTED", conviction=90, decision_id="abc-123")
    journal.record_decision(symbol="INFY", decision="REJECTED", conviction=42, veto_source="RiskBot")
    entries = journal.load_journal_entries()
    assert len(entries) == 2
    symbols = {e["symbol"] for e in entries}
    assert "TCS" in symbols
    assert "INFY" in symbols


def test_load_journal_returns_empty_when_no_file(tmp_path: Path):
    j = DecisionJournalSystem(brain_root=tmp_path)
    assert j.load_journal_entries() == []


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def test_load_accepted_entries(journal: DecisionJournalSystem):
    journal.record_decision(symbol="ONGC", decision="ACCEPTED", conviction=88)
    journal.record_decision(symbol="BHEL", decision="REJECTED", conviction=30)
    journal.record_decision(symbol="HAL", decision="ACCEPTED", conviction=75)
    accepted = journal.load_accepted_entries()
    assert len(accepted) == 2
    assert all(e["decision"] == "ACCEPTED" for e in accepted)


def test_load_rejected_entries(journal: DecisionJournalSystem):
    journal.record_decision(symbol="ONGC", decision="ACCEPTED", conviction=88)
    journal.record_decision(symbol="BHEL", decision="REJECTED", conviction=30)
    rejected = journal.load_rejected_entries()
    assert len(rejected) == 1
    assert rejected[0]["symbol"] == "BHEL"


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------

def test_legacy_action_field_accept(journal: DecisionJournalSystem):
    entry = journal.record_decision(symbol="BEL", action="ACCEPT", conviction_score=79)
    assert entry["decision"] == "ACCEPTED"
    assert entry["conviction"] == 79


def test_legacy_action_field_reject(journal: DecisionJournalSystem):
    entry = journal.record_decision(symbol="BEL", action="REJECT", conviction_score=25)
    assert entry["decision"] == "REJECTED"
    assert entry["conviction"] == 25


def test_legacy_fields_preserved(journal: DecisionJournalSystem):
    entry = journal.record_decision(
        symbol="ONGC",
        action="ACCEPT",
        conviction_score=80,
        portfolio_health=84,
        trust_score=91,
        market_regime="BULL_RISK-ON",
        personality_mode="BALANCED",
        reason="Authorized.",
        sector="energy",
        analog_match="2022 oil supply shock",
        sector_rotation_state="Energy → Financials",
    )
    assert entry["portfolio_health"] == 84
    assert entry["trust_score"] == 91
    assert entry["analog_match"] == "2022 oil supply shock"
    assert entry["action"] == "ACCEPTED"
    assert entry["conviction_score"] == 80


def test_jsonl_is_valid_json_per_line(journal: DecisionJournalSystem):
    journal.record_decision(symbol="A", decision="ACCEPTED", conviction=75)
    journal.record_decision(symbol="B", decision="REJECTED", conviction=30)
    path = journal.get_journal_path()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    for line in lines:
        obj = json.loads(line)
        assert isinstance(obj, dict)


# ---------------------------------------------------------------------------
# Phase 4C.5D: reasoning_chain
# ---------------------------------------------------------------------------

def test_reasoning_chain_stored(journal: DecisionJournalSystem):
    chain = [
        {"gate": "CapitalPreservation", "decision": "NORMAL", "reason": "Drawdown within limits."},
        {"gate": "PortfolioHealth",      "decision": "HEALTHY", "reason": "Score 84."},
        {"gate": "ConvictionScore",      "decision": 82, "reason": "9-factor weighted score."},
        {"gate": "Calibration",          "decision": 87, "reason": "+5 reward for 78% win rate."},
        {"gate": "NoTrade",              "decision": "BUY", "reason": "All gates passed."},
        {"gate": "Allocation",           "decision": "2.0%", "reason": "ELITE grade."},
        {"gate": "RiskBot",              "decision": "APPROVED", "reason": "Within risk budget."},
    ]
    entry = journal.record_decision(
        symbol="ONGC",
        decision="ACCEPTED",
        conviction=87,
        decision_id="chain-test-001",
        reasoning_chain=chain,
    )
    assert entry["reasoning_chain"] == chain


def test_reasoning_chain_defaults_empty(journal: DecisionJournalSystem):
    entry = journal.record_decision(symbol="TCS", decision="REJECTED", conviction=40)
    assert entry["reasoning_chain"] == []


def test_reasoning_chain_persisted_to_disk(journal: DecisionJournalSystem):
    chain = [{"gate": "ConvictionScore", "decision": 75, "reason": "Moderate conditions."}]
    journal.record_decision(symbol="BEL", decision="ACCEPTED", conviction=75, reasoning_chain=chain)
    entries = journal.load_journal_entries()
    assert entries[0]["reasoning_chain"] == chain


# ---------------------------------------------------------------------------
# Phase 4C.5D: update_decision_outcome (immutable separate file)
# ---------------------------------------------------------------------------

def test_update_outcome_creates_outcomes_file(journal: DecisionJournalSystem):
    journal.update_decision_outcome(
        decision_id="d001",
        outcome="WIN",
        pnl=1200.0,
        exit_reason="Take Profit Triggered",
        holding_days=3,
        return_pct=0.073,
    )
    assert journal.get_outcomes_path().exists()


def test_update_outcome_does_not_modify_journal(journal: DecisionJournalSystem):
    journal.record_decision(symbol="ONGC", decision="ACCEPTED", conviction=88, decision_id="d001")
    journal.update_decision_outcome(decision_id="d001", outcome="WIN", pnl=1200.0)
    # Journal file should still have exactly 1 entry unchanged
    entries = journal.load_journal_entries()
    assert len(entries) == 1
    assert entries[0]["actual_outcome"] == "PENDING"  # original untouched


def test_update_outcome_links_by_decision_id(journal: DecisionJournalSystem):
    journal.update_decision_outcome(
        decision_id="unique-xyz",
        outcome="LOSS",
        pnl=-400.0,
        exit_reason="Stop-Loss Triggered",
    )
    outcomes = journal.load_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0]["decision_id"] == "unique-xyz"
    assert outcomes[0]["outcome"] == "LOSS"
    assert outcomes[0]["pnl"] == -400.0


def test_update_outcome_normalizes_case(journal: DecisionJournalSystem):
    journal.update_decision_outcome(decision_id="d1", outcome="win", pnl=500.0)
    outcomes = journal.load_outcomes()
    assert outcomes[0]["outcome"] == "WIN"


def test_load_outcomes_empty_when_no_file(tmp_path: Path):
    j = DecisionJournalSystem(brain_root=tmp_path)
    assert j.load_outcomes() == []


def test_outcomes_jsonl_valid_per_line(journal: DecisionJournalSystem):
    journal.update_decision_outcome(decision_id="a", outcome="WIN", pnl=100.0)
    journal.update_decision_outcome(decision_id="b", outcome="LOSS", pnl=-50.0)
    path = journal.get_outcomes_path()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    for line in lines:
        obj = json.loads(line)
        assert "decision_id" in obj
        assert "outcome" in obj


# ---------------------------------------------------------------------------
# Phase 4C.5D: get_summary_stats
# ---------------------------------------------------------------------------

def test_summary_stats_empty_journal(journal: DecisionJournalSystem):
    stats = journal.get_summary_stats()
    assert stats["total_decisions"] == 0
    assert stats["acceptance_rate"] == 0.0
    assert stats["most_common_veto"] == "N/A"


def test_summary_stats_acceptance_rate(journal: DecisionJournalSystem):
    journal.record_decision(symbol="A", decision="ACCEPTED", conviction=80)
    journal.record_decision(symbol="B", decision="REJECTED", conviction=40, veto_source="ConvictionScoreEngine")
    journal.record_decision(symbol="C", decision="REJECTED", conviction=35, veto_source="ConvictionScoreEngine")
    journal.record_decision(symbol="D", decision="ACCEPTED", conviction=75)
    stats = journal.get_summary_stats()
    assert stats["total_decisions"] == 4
    assert stats["accepted"] == 2
    assert stats["rejected"] == 2
    assert stats["acceptance_rate"] == 50.0


def test_summary_stats_most_common_veto(journal: DecisionJournalSystem):
    journal.record_decision(symbol="A", decision="REJECTED", conviction=30, veto_source="ConvictionScoreEngine")
    journal.record_decision(symbol="B", decision="REJECTED", conviction=25, veto_source="ConvictionScoreEngine")
    journal.record_decision(symbol="C", decision="REJECTED", conviction=40, veto_source="NoTradeDecisionEngine")
    stats = journal.get_summary_stats()
    assert stats["most_common_veto"] == "ConvictionScoreEngine"


def test_summary_stats_avg_conviction(journal: DecisionJournalSystem):
    journal.record_decision(symbol="A", decision="ACCEPTED", conviction=80)
    journal.record_decision(symbol="B", decision="ACCEPTED", conviction=90)
    journal.record_decision(symbol="C", decision="REJECTED", conviction=30)
    journal.record_decision(symbol="D", decision="REJECTED", conviction=40)
    stats = journal.get_summary_stats()
    assert stats["avg_conviction_accept"] == pytest.approx(85.0, abs=0.1)
    assert stats["avg_conviction_reject"] == pytest.approx(35.0, abs=0.1)
