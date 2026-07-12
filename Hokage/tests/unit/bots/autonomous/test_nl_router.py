"""Unit tests for NaturalLanguageRouter.

Verifies pattern matching, keyword association, and fallback routing logic.
"""
from __future__ import annotations

from hokage.router.nl_router import NaturalLanguageRouter


def test_nl_router_status_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("What is our status?") == "hokage status"
    assert router.parse_query("system state") == "hokage status"
    assert router.parse_query("are we trading?") == "hokage status"


def test_nl_router_portfolio_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("What is my cash balance?") == "hokage portfolio"
    assert router.parse_query("how much money do we have?") == "hokage portfolio"
    assert router.parse_query("portfolio equity") == "hokage portfolio"


def test_nl_router_positions_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("show positions") == "hokage positions"
    assert router.parse_query("list open positions") == "hokage positions"
    assert router.parse_query("what are our holdings?") == "hokage positions"


def test_nl_router_decisions_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("decisions today") == "hokage decisions today"
    assert router.parse_query("what decisions did we make today?") == "hokage decisions today"


def test_nl_router_why_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("Why TCS?") == "hokage why TCS"
    assert router.parse_query("why did we reject INFY today?") == "hokage why INFY"
    assert router.parse_query("Why did we buy RELIANCE?") == "hokage why RELIANCE"


def test_nl_router_performance_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("how are we performing?") == "hokage performance"
    assert router.parse_query("expectancy and Sharpe ratio") == "hokage performance"
    assert router.parse_query("what is our drawdown?") == "hokage performance"


def test_nl_router_lessons_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("what lessons did we learn recently?") == "hokage lessons"
    assert router.parse_query("structured lessons learned") == "hokage lessons"
    assert router.parse_query("recent trade reviews") == "hokage lessons"


def test_nl_router_dna_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("show trade dna") == "hokage dna"
    assert router.parse_query("regime stats fingerprint") == "hokage dna"


def test_nl_router_briefing_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("morning briefing") == "hokage briefing"
    assert router.parse_query("show pre-market briefing") == "hokage briefing"


def test_nl_router_review_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("generate daily review template") == "hokage review"
    assert router.parse_query("eod review template") == "hokage review"


def test_nl_router_knowledge_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("what are the rules on risk?") == "hokage knowledge risk"
    assert router.parse_query("doctrines on psychology") == "hokage knowledge psychology"
    assert router.parse_query("what does graham say about margin of safety") == "hokage knowledge margin of safety"


def test_nl_router_unmapped_fallback() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("this is some unmappable text") == "unmapped"
    assert router.parse_query("hello world") == "unmapped"


def test_nl_router_opportunities_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("where is the best opportunity today?") == "hokage opportunities"
    assert router.parse_query("best opportunity in approved universe") == "hokage opportunities"
    assert router.parse_query("show opportunity radar") == "hokage opportunities"


def test_nl_router_strategy_mapping() -> None:
    router = NaturalLanguageRouter()
    assert router.parse_query("Show strategy notifications.") == "hokage strategy notifications"
    assert router.parse_query("pipeline notifications") == "hokage strategy notifications"
    assert router.parse_query("Show strategy pipeline.") == "hokage strategy pipeline"
    assert router.parse_query("candidate strategies") == "hokage strategy pipeline"

