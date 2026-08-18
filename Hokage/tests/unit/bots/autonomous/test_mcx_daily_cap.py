"""The MCX Arena counted its daily entries and then ignored the count.

2026-08-18: `_scan_and_enter_mcx_opportunities` called
`strategy_engine.record_trade(...)` after every fill but never called
`strategy_engine.is_entry_allowed(...)` before one. The index league was capped
at 3 entries per symbol and 5 unique symbols per day; the commodity league was
capped at nothing, while its counter dutifully incremented.

It bit the same evening. SessionShift entered SILVERM three times, losing twice
in a row — the second trade lasted two minutes and gave back 1,195. The cap's
own docstring says why it exists: "churn on one symbol is revenge trading, not
data collection."

The cap is checked BEFORE the order is built, so a blocked entry costs no
options-routing work and leaves no half-state behind.
"""
from __future__ import annotations

import inspect
import textwrap

from bots.strategy.strategy_engine import StrategyEngine


def test_the_cap_stops_the_fourth_entry_on_one_symbol():
    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    day = "2026-08-18"
    pb = "MCX_SessionShift"

    for expected in range(3):
        allowed, _ = engine.is_entry_allowed(pb, "SILVERM", day)
        assert allowed, f"entry {expected + 1} of 3 should be allowed"
        engine.record_trade(pb, "SILVERM", day)

    allowed, reason = engine.is_entry_allowed(pb, "SILVERM", day)
    assert not allowed
    assert "re-entry cap" in reason
    assert "SILVERM" in reason


def test_the_three_silverm_entries_of_2026_08_18_were_within_cap():
    """The bug was not that the cap was breached — it is that nothing checked.

    Three entries is exactly the cap, so an enforced gate would have allowed
    all three and stopped the fourth. This pins that the fix does not
    retroactively forbid what actually happened; it forbids the next one.
    """
    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    day = "2026-08-18"
    pb = "MCX_SessionShift"
    for _ in range(3):
        allowed, _ = engine.is_entry_allowed(pb, "SILVERM", day)
        assert allowed
        engine.record_trade(pb, "SILVERM", day)
    assert not engine.is_entry_allowed(pb, "SILVERM", day)[0]


def test_the_rotation_quota_is_per_playbook_not_shared():
    """RangeFade's crude entries must not consume SessionShift's quota."""
    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    day = "2026-08-18"
    engine.record_trade("MCX_RangeFade", "CRUDEOIL", day)
    engine.record_trade("MCX_RangeFade", "NATURALGAS", day)

    allowed, _ = engine.is_entry_allowed("MCX_SessionShift", "SILVERM", day)
    assert allowed


def test_a_different_symbol_is_unaffected_by_a_capped_one():
    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    day = "2026-08-18"
    pb = "MCX_SessionShift"
    for _ in range(3):
        engine.record_trade(pb, "SILVERM", day)
    assert not engine.is_entry_allowed(pb, "SILVERM", day)[0]
    assert engine.is_entry_allowed(pb, "GOLDM", day)[0]


def _cap_calls_in_mcx_path():
    """(call_name, lineno) for the two cap calls, found by AST not by text.

    A text scan cannot tell a rule from a description of one. An earlier
    version of this test read the source as a string and failed on the fix's
    own COMMENT, which mentions record_trade before is_entry_allowed. The same
    trap was recorded once before, on a read-only test that tripped over a
    module docstring. Parse the code, not the prose.
    """
    import ast

    from bots.autonomous.autonomous_bot import AutonomousTradingBot

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(AutonomousTradingBot._scan_and_enter_mcx_opportunities)
    ))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name in ("is_entry_allowed", "record_trade"):
            found.append((name, node.lineno, node))
    found.sort(key=lambda f: f[1])
    return found


def test_the_mcx_path_actually_calls_the_gate():
    """Guards production, not a stand-in.

    The whole bug was a missing call. A test that only exercised StrategyEngine
    would have passed happily for every week this was broken.
    """
    calls = _cap_calls_in_mcx_path()
    names = [c[0] for c in calls]
    assert "is_entry_allowed" in names, (
        "the MCX entry path must CHECK the daily cap, not only record against it"
    )
    assert "record_trade" in names
    assert names.index("is_entry_allowed") < names.index("record_trade"), (
        "the cap must be checked before the entry is recorded"
    )


def test_the_checked_and_recorded_playbook_ids_are_the_same_variable():
    """If the check and the record use different ids, the cap counts one
    bucket and enforces another — indistinguishable from having no cap.

    Compares the first ARGUMENT of each call at the AST level, so renaming the
    variable is fine and passing two different expressions is not.
    """
    import ast

    calls = {name: node for name, _lineno, node in _cap_calls_in_mcx_path()}
    checked = calls["is_entry_allowed"].args[0]
    recorded = calls["record_trade"].args[0]
    assert isinstance(checked, ast.Name) and isinstance(recorded, ast.Name), (
        "both calls should pass the same prepared variable, not an inline expression"
    )
    assert checked.id == recorded.id, (
        f"cap is checked with {checked.id!r} but recorded against {recorded.id!r}"
    )
