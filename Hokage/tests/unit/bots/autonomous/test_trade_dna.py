"""Tests for TradeDNAEngine — Phase 4C.5D.

Covers: record_dna schema, conviction grade classification,
result normalization, query filters (regime/sector/grade/period/result),
query_win_rate, query_avg_return, summarize, JSONL persistence.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from bots.autonomous.trade_dna import TradeDNAEngine


@pytest.fixture
def engine(tmp_path: Path) -> TradeDNAEngine:
    return TradeDNAEngine(brain_root=tmp_path)


def _seed(engine: TradeDNAEngine) -> None:
    """Seed 6 DNA records across different regimes, sectors, grades, and results."""
    engine.record_dna(
        decision_id="d001", symbol="ONGC", market_regime="BULL_RISK-ON",
        sector="energy", conviction_score=89, holding_period_days=3,
        result="WIN", return_pct=0.073, pnl=1200.0,
    )
    engine.record_dna(
        decision_id="d002", symbol="BEL", market_regime="BULL_RISK-ON",
        sector="defence", conviction_score=84, holding_period_days=2,
        result="WIN", return_pct=0.087, pnl=800.0,
    )
    engine.record_dna(
        decision_id="d003", symbol="HAL", market_regime="HIGH_VOLATILITY",
        sector="defence", conviction_score=78, holding_period_days=4,
        result="LOSS", return_pct=-0.033, pnl=-400.0,
    )
    engine.record_dna(
        decision_id="d004", symbol="HDFCBANK", market_regime="BEAR_RISK-OFF",
        sector="banking", conviction_score=45, holding_period_days=1,
        result="LOSS", return_pct=-0.028, pnl=-600.0,
    )
    engine.record_dna(
        decision_id="d005", symbol="TCS", market_regime="BULL_RISK-ON",
        sector="it", conviction_score=92, holding_period_days=5,
        result="WIN", return_pct=0.058, pnl=2000.0,
    )
    engine.record_dna(
        decision_id="d006", symbol="INFY", market_regime="SIDEWAYS_RISK-ON",
        sector="it", conviction_score=55, holding_period_days=2,
        result="BREAKEVEN", return_pct=0.0, pnl=0.0,
    )


# ---------------------------------------------------------------------------
# Basic record / load
# ---------------------------------------------------------------------------

def test_record_creates_dna_file(engine, tmp_path):
    engine.record_dna(
        decision_id="x1", symbol="ONGC", market_regime="BULL",
        sector="energy", conviction_score=89, holding_period_days=3,
        result="WIN", return_pct=0.07,
    )
    assert engine.get_dna_path().exists()


def test_record_contains_minimum_schema(engine):
    dna = engine.record_dna(
        decision_id="d001", symbol="ONGC", market_regime="BULL_RISK-ON",
        sector="energy", conviction_score=89, holding_period_days=3,
        result="WIN", return_pct=0.073,
    )
    required = ["decision_id", "symbol", "market_regime", "sector",
                "conviction_grade", "holding_period_days", "result", "return_pct"]
    for key in required:
        assert key in dna, f"Missing DNA schema key: {key}"


def test_record_classifies_conviction_grade_elite(engine):
    dna = engine.record_dna(
        decision_id="x", symbol="TCS", market_regime="BULL",
        sector="it", conviction_score=92, holding_period_days=2,
        result="WIN", return_pct=0.05,
    )
    assert dna["conviction_grade"] == "ELITE"


def test_record_classifies_conviction_grade_watch(engine):
    dna = engine.record_dna(
        decision_id="x", symbol="BHEL", market_regime="SIDEWAYS",
        sector="manufacturing", conviction_score=40, holding_period_days=1,
        result="LOSS", return_pct=-0.02,
    )
    assert dna["conviction_grade"] == "WATCH"


def test_record_normalizes_result_from_pnl(engine):
    """If result is invalid, should be inferred from pnl."""
    dna = engine.record_dna(
        decision_id="x", symbol="X", market_regime="BULL",
        sector="it", conviction_score=75, holding_period_days=1,
        result="UNKNOWN_VALUE", return_pct=0.05, pnl=500.0,
    )
    assert dna["result"] == "WIN"


def test_load_all_returns_all_records(engine):
    _seed(engine)
    records = engine.load_all()
    assert len(records) == 6


def test_load_all_empty_when_no_file(tmp_path: Path):
    e = TradeDNAEngine(brain_root=tmp_path)
    assert e.load_all() == []


def test_dna_jsonl_valid_per_line(engine):
    _seed(engine)
    lines = engine.get_dna_path().read_text(encoding="utf-8").strip().split("\n")
    for line in lines:
        obj = json.loads(line)
        assert "decision_id" in obj
        assert "conviction_grade" in obj


# ---------------------------------------------------------------------------
# Query by regime
# ---------------------------------------------------------------------------

def test_query_by_regime(engine):
    _seed(engine)
    results = engine.query(regime="BULL_RISK-ON")
    assert len(results) == 3  # ONGC, BEL, TCS
    assert all("BULL_RISK-ON" in r["market_regime"] for r in results)


def test_query_by_regime_case_insensitive(engine):
    _seed(engine)
    results = engine.query(regime="bull_risk-on")
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Query by sector
# ---------------------------------------------------------------------------

def test_query_by_sector(engine):
    _seed(engine)
    results = engine.query(sector="defence")
    assert len(results) == 2
    assert all(r["sector"] == "defence" for r in results)


def test_query_by_sector_no_match(engine):
    _seed(engine)
    results = engine.query(sector="pharma")
    assert results == []


# ---------------------------------------------------------------------------
# Query by conviction grade
# ---------------------------------------------------------------------------

def test_query_by_grade_elite(engine):
    _seed(engine)
    results = engine.query(conviction_grade="ELITE")
    # ONGC(89), TCS(92) → 2 ELITE records
    assert len(results) == 2


def test_query_by_grade_moderate(engine):
    _seed(engine)
    results = engine.query(conviction_grade="MODERATE")
    # INFY(55) only
    assert len(results) == 1
    assert results[0]["symbol"] == "INFY"


# ---------------------------------------------------------------------------
# Query by holding period
# ---------------------------------------------------------------------------

def test_query_by_holding_period_min(engine):
    _seed(engine)
    results = engine.query(holding_period_min=4)
    # HAL(4), TCS(5) → 2
    assert len(results) == 2


def test_query_by_holding_period_max(engine):
    _seed(engine)
    results = engine.query(holding_period_max=2)
    # BEL(2), HDFCBANK(1), INFY(2) → 3
    assert len(results) == 3


def test_query_by_holding_period_range(engine):
    _seed(engine)
    results = engine.query(holding_period_min=2, holding_period_max=3)
    # ONGC(3), BEL(2), INFY(2) → 3
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Query by result
# ---------------------------------------------------------------------------

def test_query_by_result_win(engine):
    _seed(engine)
    results = engine.query(result="WIN")
    assert len(results) == 3


def test_query_by_result_loss(engine):
    _seed(engine)
    results = engine.query(result="LOSS")
    assert len(results) == 2


def test_query_by_result_breakeven(engine):
    _seed(engine)
    results = engine.query(result="BREAKEVEN")
    assert len(results) == 1
    assert results[0]["symbol"] == "INFY"


# ---------------------------------------------------------------------------
# Combined multi-filter queries
# ---------------------------------------------------------------------------

def test_query_combined_regime_and_result(engine):
    _seed(engine)
    results = engine.query(regime="BULL_RISK-ON", result="WIN")
    assert len(results) == 3  # ONGC, BEL, TCS all WIN in BULL_RISK-ON


def test_query_combined_sector_and_grade(engine):
    _seed(engine)
    results = engine.query(sector="defence", conviction_grade="HIGH")
    # HAL (78) → HIGH, BEL (84) → HIGH  both in defence
    assert len(results) == 2


# ---------------------------------------------------------------------------
# query_win_rate and query_avg_return
# ---------------------------------------------------------------------------

def test_query_win_rate_regime(engine):
    _seed(engine)
    wr = engine.query_win_rate(regime="BULL_RISK-ON")
    assert wr == 100.0


def test_query_win_rate_sector_defence(engine):
    _seed(engine)
    wr = engine.query_win_rate(sector="defence")
    assert wr == 50.0


def test_query_win_rate_no_match(engine):
    _seed(engine)
    wr = engine.query_win_rate(sector="pharma")
    assert wr == 0.0


def test_query_avg_return_elite(engine):
    _seed(engine)
    avg = engine.query_avg_return(conviction_grade="ELITE")
    # ONGC 0.073, TCS 0.058 → avg ≈ 0.0655
    assert avg == pytest.approx((0.073 + 0.058) / 2.0, abs=0.001)


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------

def test_summarize_keys(engine):
    _seed(engine)
    s = engine.summarize()
    assert "total_dna_records" in s
    assert "by_conviction_grade" in s
    assert "by_regime" in s
    assert "by_sector" in s
    assert s["total_dna_records"] == 6


def test_summarize_empty(engine):
    s = engine.summarize()
    assert s["total_dna_records"] == 0
    assert s["by_conviction_grade"] == {}
