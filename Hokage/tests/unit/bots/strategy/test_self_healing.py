from __future__ import annotations

from bots.strategy.strategy_engine import StrategyEngine

def test_strategy_engine_playbook_mapping():
    engine = StrategyEngine(max_unique_assets=5)
    assert engine.get_playbook_id("MacroBreakout") == "SCARECROW_EMA"
    assert engine.get_playbook_id("AutoTrend") == "KONOHA_ORB"
    assert engine.get_playbook_id("CustomStrategy") == "CUSTOMSTRATEGY"

def test_strategy_engine_same_day_reentry_allowed_up_to_cap():
    """Re-entries on the same symbol are allowed after exits (evolution needs
    repetition) — but only up to the daily cap. The old once-per-day rule
    ended the trading day by mid-morning on a 3-asset universe."""
    engine = StrategyEngine(max_unique_assets=2, max_entries_per_symbol=3)
    date_str = "2026-07-05"

    for i in range(3):
        allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "TCS", date_str)
        assert allowed is True, f"entry #{i + 1} should be allowed: {msg}"
        engine.record_trade("KONOHA_ORB", "TCS", date_str)

    # Fourth entry on TCS hits the re-entry cap
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "TCS", date_str)
    assert allowed is False
    assert "re-entry cap" in msg


def test_strategy_engine_uniqueness_limits():
    engine = StrategyEngine(max_unique_assets=2)
    date_str = "2026-07-05"

    # First entry on TCS is allowed
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "TCS", date_str)
    assert allowed is True
    engine.record_trade("KONOHA_ORB", "TCS", date_str)

    # Second unique asset INFY is allowed
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "INFY", date_str)
    assert allowed is True
    engine.record_trade("KONOHA_ORB", "INFY", date_str)

    # Third unique asset RELIANCE is blocked (exceeds unique assets limit of 2)
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "RELIANCE", date_str)
    assert allowed is False
    assert "exhausted its daily rotation quota" in msg

    # ...but a re-entry on an already-used symbol still passes the quota
    allowed, msg = engine.is_entry_allowed("KONOHA_ORB", "TCS", date_str)
    assert allowed is True
