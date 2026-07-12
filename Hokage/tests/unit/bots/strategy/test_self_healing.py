from __future__ import annotations

from bots.strategy.strategy_engine import StrategyEngine

def test_strategy_engine_playbook_mapping():
    engine = StrategyEngine(max_unique_assets=5)
    assert engine.get_playbook_id("MacroBreakout") == "SCARECROW_EMA"
    assert engine.get_playbook_id("AutoTrend") == "KONOHA_ORB"
    assert engine.get_playbook_id("CustomStrategy") == "CUSTOMSTRATEGY"

def test_strategy_engine_uniqueness_limits():
    engine = StrategyEngine(max_unique_assets=2)
    date_str = "2026-07-05"

    # First entry on TCS is allowed
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "TCS", date_str)
    assert allowed is True
    engine.record_trade("KONOHA_ORB", "TCS", date_str)

    # Double entry on TCS is blocked (asset uniqueness)
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "TCS", date_str)
    assert allowed is False
    assert "already utilized" in msg

    # Second unique asset INFY is allowed
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "INFY", date_str)
    assert allowed is True
    engine.record_trade("KONOHA_ORB", "INFY", date_str)

    # Third unique asset RELIANCE is blocked (exceeds unique assets limit of 2)
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "RELIANCE", date_str)
    assert allowed is False
    assert "exhausted its daily rotation quota" in msg
