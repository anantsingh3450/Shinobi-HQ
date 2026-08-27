"""Hokage may retire his own failures. He may not promote himself.

The ImprovementBot wrote 430 autopsies and applied ZERO improvements — wired to
a strategy id in neither portfolio, writing to fields nothing reads, and
ignoring its own strategy_id argument. Phase 2 replaces it with a policy whose
central property is ASYMMETRY:

    reducing risk  -> may act alone (an archived strategy cannot open anything)
    raising risk   -> always asks, at any confidence

A loop allowed to reduce risk on its own can be wrong and cost opportunity. A
loop allowed to raise risk on its own can be wrong and cost the account.
"""
from __future__ import annotations

from bots.autonomous import evolution as ev


def _snap(day: str, rows: dict, lineup: dict, bar: float = 2.0) -> dict:
    """rows: {(module, asset): t}"""
    measurements: dict[str, dict] = {}
    for (module, asset), t in rows.items():
        measurements.setdefault(asset, {})[module] = {
            "n": 300, "t": t, "edge_atr": 0.2, "accuracy": 50.0
        }
    return {"date": day, "ship_bar": bar, "lineup": lineup,
            "measurements": measurements}


#: Two live strategies, so archiving one never orphans an asset by default.
TWO_LIVE = {
    "mod-a": {"strategy_id": "s-a", "name": "Alpha", "status": "SHADOW_MODE",
              "scope": ["GOLDM"]},
    "mod-b": {"strategy_id": "s-b", "name": "Beta", "status": "SHADOW_MODE",
              "scope": ["GOLDM"]},
}


def test_one_bad_week_retires_nothing():
    """One week below the bar is noise; acting on it would churn the lineup
    every quiet fortnight."""
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 2.6}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    assert [d for d in ev.plan([now, prev]) if d.action == "archive"] == []


def test_two_consecutive_bad_weeks_retires_AUTONOMOUSLY():
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    archives = [d for d in ev.plan([now, prev]) if d.action == "archive"]
    assert len(archives) == 1
    d = archives[0]
    assert d.is_autonomous
    assert d.strategy_id == "s-a"
    assert d.evidence["t_previous"] == 1.8 and d.evidence["t_now"] == 1.2


def test_it_will_NOT_leave_an_asset_with_no_live_strategy():
    """RAIL 2, the most important one. Ceasing to trade an asset silently is a
    worse failure than trading it badly, and nothing alarms when nothing
    happens."""
    only_live = {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                           "status": "SHADOW_MODE", "scope": ["GOLDM"]}}
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, only_live)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, only_live)
    d, = [x for x in ev.plan([now, prev]) if x.action == "archive"]
    assert not d.is_autonomous
    assert d.tier == ev.TIER_PROPOSE
    assert "no live strategy" in d.blocked_reason


def test_only_one_strategy_is_retired_per_run():
    """RAIL 3. A correlated measurement error across a league must not empty
    the arena in a single pass."""
    lineup = {
        f"mod-{k}": {"strategy_id": f"s-{k}", "name": k.upper(),
                     "status": "SHADOW_MODE", "scope": ["GOLDM", "SILVERM"]}
        for k in ("a", "b", "c")
    }
    rows_prev = {("mod-a", "GOLDM"): 1.1, ("mod-b", "GOLDM"): 1.2,
                 ("mod-c", "GOLDM"): 1.3}
    rows_now = {("mod-a", "GOLDM"): 0.9, ("mod-b", "GOLDM"): 1.0,
                ("mod-c", "GOLDM"): 1.1}
    decisions = ev.plan([_snap("2026-08-21", rows_now, lineup),
                         _snap("2026-08-14", rows_prev, lineup)])
    archives = [d for d in decisions if d.action == "archive"]
    assert len(archives) == 3, "all three should be identified"
    assert sum(1 for d in archives if d.is_autonomous) == 1
    blocked = [d for d in archives if not d.is_autonomous]
    assert all("per run" in d.blocked_reason for d in blocked)


def test_the_WORST_measured_strategy_is_the_one_retired():
    lineup = {
        "mod-a": {"strategy_id": "s-a", "name": "Alpha", "status": "SHADOW_MODE",
                  "scope": ["GOLDM"]},
        "mod-b": {"strategy_id": "s-b", "name": "Beta", "status": "SHADOW_MODE",
                  "scope": ["GOLDM"]},
        "mod-c": {"strategy_id": "s-c", "name": "Gamma", "status": "SHADOW_MODE",
                  "scope": ["GOLDM"]},
    }
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.9, ("mod-b", "GOLDM"): 0.2}, lineup)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.8, ("mod-b", "GOLDM"): 0.1}, lineup)
    acting = [d for d in ev.plan([now, prev]) if d.is_autonomous]
    assert len(acting) == 1
    assert acting[0].strategy_name == "Beta", "the worst performer should go first"


def test_reviving_an_archived_strategy_is_NEVER_autonomous():
    """Bringing a strategy back ADDS risk. That is Tier 3 behaviour and must
    always reach the commander, however good the measurement."""
    lineup = {"mod-z": {"strategy_id": "s-z", "name": "Zeta",
                        "status": "ARCHIVED", "scope": ["GOLDM"]}}
    now = _snap("2026-08-21", {("mod-z", "GOLDM"): 4.9}, lineup)
    revivals = [d for d in ev.plan([now]) if d.action == "revive"]
    assert len(revivals) == 1
    assert not revivals[0].is_autonomous
    assert "ADDS risk" in revivals[0].blocked_reason


def test_an_archived_strategy_is_never_archived_again():
    lineup = {"mod-z": {"strategy_id": "s-z", "name": "Zeta",
                        "status": "ARCHIVED", "scope": ["GOLDM"]}}
    prev = _snap("2026-08-14", {("mod-z", "GOLDM"): 0.1}, lineup)
    now = _snap("2026-08-21", {("mod-z", "GOLDM"): 0.2}, lineup)
    assert [d for d in ev.plan([now, prev]) if d.action == "archive"] == []


def test_a_module_out_of_scope_on_an_asset_is_not_judged_on_it():
    """SessionShift measures negative on NATURALGAS and is deliberately not
    scoped there. Retiring it for ground it never trades would archive a module
    doing exactly what it was told."""
    lineup = {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                        "status": "SHADOW_MODE", "scope": ["GOLDM"]},
              "mod-b": {"strategy_id": "s-b", "name": "Beta",
                        "status": "SHADOW_MODE", "scope": ["GOLDM"]}}
    prev = _snap("2026-08-14", {("mod-a", "NATURALGAS"): -1.0}, lineup)
    now = _snap("2026-08-21", {("mod-a", "NATURALGAS"): -1.2}, lineup)
    assert [d for d in ev.plan([now, prev]) if d.action == "archive"] == []


def test_a_single_snapshot_acts_on_nothing():
    """With no prior week there is no trend, so nothing may be autonomous."""
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 0.1}, TWO_LIVE)
    assert [d for d in ev.plan([now]) if d.is_autonomous] == []


def test_no_snapshots_is_not_an_error():
    assert ev.plan([]) == []


def test_a_strategy_above_the_bar_is_left_alone():
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 3.1}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 3.4}, TWO_LIVE)
    assert ev.plan([now, prev]) == []


def test_the_summary_separates_acting_from_asking(monkeypatch):
    monkeypatch.setattr(ev, "AUTONOMOUS_ENABLED", True)
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    text = ev.summarise(ev.plan([now, prev]))
    # The two sections must stay distinguishable — what Tier 1 has cleared on
    # its own, and what needs the commander. The heading wording changed on
    # 2026-08-28 (see test_the_summary_never_claims_an_archive_that_nothing
    # _performs); what this test guards is the SEPARATION, not the phrasing.
    assert "RETIRE" in text.upper()
    assert "reduces risk" in text
    assert "NEEDS YOUR DECISION" not in text, (
        "a lone Tier 1 decision must not also appear as a question"
    )


def test_two_readings_DAYS_apart_are_not_two_weeks_of_evidence():
    """Caught on a 2026-08-17 dry run: the policy compared that day's
    re-measurement against the 2026-08-15 baseline and called two readings TWO
    DAYS apart "two consecutive weeks below the bar". They are largely the same
    tape measured twice, so one bad week would masquerade as a trend."""
    prev = _snap("2026-08-15", {("mod-a", "GOLDM"): 1.46}, TWO_LIVE)
    now = _snap("2026-08-17", {("mod-a", "GOLDM"): 1.24}, TWO_LIVE)
    assert [d for d in ev.plan([now, prev]) if d.action == "archive"] == []


def test_a_full_week_apart_DOES_count():
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.46}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.24}, TWO_LIVE)
    assert len([d for d in ev.plan([now, prev]) if d.action == "archive"]) == 1


def test_an_unparseable_date_refuses_to_act():
    """Without knowing the gap we cannot claim a trend, and refusing is the
    safe direction."""
    prev = _snap("not-a-date", {("mod-a", "GOLDM"): 1.4}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    assert [d for d in ev.plan([now, prev]) if d.action == "archive"] == []


def test_the_summary_is_empty_when_there_is_nothing_to_say():
    assert ev.summarise([]) == ""


def test_every_decision_carries_the_evidence_that_justified_it():
    """So it can be read back and reversed. An autonomous change with no
    recorded reason is indistinguishable from a bug."""
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    for d in ev.plan([now, prev]):
        assert d.reason
        assert d.evidence.get("measured_on")
        assert "t_now" in d.evidence


def test_only_archiving_is_ever_autonomous():
    """THE INVARIANT THAT OUTLIVES THE ROLLOUT.

    Autonomy was armed on 2026-08-24 after the observed cycle, so asserting the
    flag is False no longer means anything. What must NEVER change is the
    asymmetry: Tier 1 archives and only archives. An archived strategy cannot
    open a position, so a wrong autonomous decision costs opportunity, never a
    larger loss. Reviving or rescoping ADDS risk and stays with the commander
    however good the measurement looks.
    """
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    for d in ev.plan([now, prev]):
        if d.is_autonomous:
            assert d.action == "archive", (
                f"{d.action!r} must never be autonomous - only archiving "
                f"reduces risk on its own"
            )


def test_a_revival_is_never_autonomous_however_well_it_measures():
    lineup = dict(TWO_LIVE)
    lineup["mod-b"] = {**lineup["mod-b"], "status": "ARCHIVED"}
    prev = _snap("2026-08-14", {("mod-b", "GOLDM"): 3.9}, lineup)
    now = _snap("2026-08-21", {("mod-b", "GOLDM"): 4.2}, lineup)
    revivals = [d for d in ev.plan([now, prev]) if d.action == "revive"]
    assert revivals, "a strongly measuring archived module should be raised"
    for d in revivals:
        assert not d.is_autonomous
        assert d.blocked_reason


def test_the_policy_still_reports_its_verdict_while_disarmed(monkeypatch):
    """The switch must gate APPLYING, not THINKING — the observed cycle is
    worthless if the policy stays silent."""
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    d, = [x for x in ev.plan([now, prev]) if x.action == "archive"]

    monkeypatch.setattr(ev, "AUTONOMOUS_ENABLED", False)
    assert d.is_autonomous is True, "the policy's verdict must survive the switch"
    assert d.will_be_applied is False, "nothing may be applied while disarmed"

    monkeypatch.setattr(ev, "AUTONOMOUS_ENABLED", True)
    assert d.will_be_applied is True


def test_the_summary_says_plainly_that_nothing_changed(monkeypatch):
    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    decisions = ev.plan([now, prev])

    monkeypatch.setattr(ev, "AUTONOMOUS_ENABLED", False)
    assert "WOULD RETIRE" in ev.summarise(decisions)
    assert "nothing changed" in ev.summarise(decisions)

    # 2026-08-28: this used to assert "RETIRING (autonomous", which is a claim
    # that something HAPPENED — and nothing did. `plan()` returns Decisions,
    # `weekly_audit` prints `summarise()`, and NOTHING in the codebase writes an
    # archive to a portfolio. AUTONOMOUS_ENABLED only suppressed the caveat, so
    # the Friday report would have announced a retirement that never occurred.
    # A system that reports an action it did not take is worse than one that
    # takes no action, because the commander stops checking.
    monkeypatch.setattr(ev, "AUTONOMOUS_ENABLED", True)
    armed = ev.summarise(decisions)
    assert "NOT YET APPLIED" in armed
    assert "lineup is unchanged" in armed


def test_the_summary_never_claims_an_archive_that_nothing_performs(monkeypatch):
    """Guards the gap directly: while the module exposes no applier, the summary
    must not use language that reads as a completed action. Delete this test the
    day an applier lands — and change the wording in the same commit."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ev.__file__).read_text(encoding="utf-8"))
    functions = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    has_applier = any("apply" in name for name in functions)

    prev = _snap("2026-08-14", {("mod-a", "GOLDM"): 1.8}, TWO_LIVE)
    now = _snap("2026-08-21", {("mod-a", "GOLDM"): 1.2}, TWO_LIVE)
    monkeypatch.setattr(ev, "AUTONOMOUS_ENABLED", True)
    text = ev.summarise(ev.plan([now, prev]))

    if not has_applier:
        assert "RETIRING (autonomous" not in text, (
            "the summary announces a retirement, but no function in evolution.py "
            "applies one — the lineup would be unchanged"
        )


def test_the_module_cannot_write_anything():
    """plan() returns decisions; the caller applies them. Keeps the policy
    testable without a brain, and keeps a policy bug from mutating state."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ev.__file__).read_text(encoding="utf-8"))
    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    for forbidden in ("write_text", "execute", "commit", "save", "place_order",
                      "send_message"):
        assert forbidden not in called, f"policy module performs I/O: {forbidden}()"
