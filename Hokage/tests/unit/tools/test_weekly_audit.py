"""The weekly audit is what replaces Claude as Hokage's evolution loop.

The ImprovementBot wrote 430 autopsies and applied zero improvements, because
it was wired to a strategy id that does not exist and wrote to fields nothing
reads. The labs in tools/research measure correctly but had to be fired by
hand. This tool runs them on a schedule and reports what CHANGED.

The measurement half needs a broker session and is covered by running it. The
DIFF half — which decides what gets flagged for demotion or revival — is pure
and is what these tests cover, because that is the half that will eventually
be allowed to change the lineup.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "weekly_audit", ROOT / "tools" / "research" / "weekly_audit.py"
)
wa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wa)


def _snapshot(day: str, rows: dict, lineup: dict) -> dict:
    """rows: {(module, symbol): t}"""
    measurements: dict[str, dict] = {}
    for (module, symbol), t in rows.items():
        measurements.setdefault(symbol, {})[module] = {
            "n": 200, "accuracy": 52.0, "edge_atr": 0.2, "t": t
        }
    return {"date": day, "lineup": lineup, "measurements": measurements}


LIVE = {"mod-a": {"strategy_id": "s-a", "name": "Alpha", "status": "SHADOW_MODE",
                  "scope": ["GOLDM"]}}
ARCHIVED = {"mod-b": {"strategy_id": "s-b", "name": "Beta", "status": "ARCHIVED",
                      "scope": ["GOLDM"]}}


def test_one_bad_week_is_not_enough_to_demote():
    """A single week below the bar is noise. Acting on it would churn the
    lineup every time a quiet week lowered someone's t."""
    prev = _snapshot("2026-08-08", {("mod-a", "GOLDM"): 2.6}, LIVE)
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 1.4}, LIVE)
    report = wa.build_report(now, [prev])
    assert report["demotions"] == []


def test_two_consecutive_bad_weeks_flags_a_demotion():
    prev = _snapshot("2026-08-08", {("mod-a", "GOLDM"): 1.8}, LIVE)
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 1.4}, LIVE)
    report = wa.build_report(now, [prev])
    assert len(report["demotions"]) == 1
    d = report["demotions"][0]
    assert d["name"] == "Alpha" and d["symbol"] == "GOLDM"
    assert d["t_now"] == 1.4 and d["t_prev"] == 1.8


def test_an_archived_module_back_above_the_bar_is_flagged_for_revival():
    """Archiving is not meant to be permanent — regimes change."""
    prev = _snapshot("2026-08-08", {("mod-b", "GOLDM"): 0.4}, ARCHIVED)
    now = _snapshot("2026-08-15", {("mod-b", "GOLDM"): 2.7}, ARCHIVED)
    report = wa.build_report(now, [prev])
    assert len(report["revivals"]) == 1
    assert report["revivals"][0]["name"] == "Beta"


def test_an_archived_module_is_never_a_demotion_candidate():
    """It already cannot trade. Flagging it would be noise that trains the
    commander to ignore the alert."""
    prev = _snapshot("2026-08-08", {("mod-b", "GOLDM"): 0.2}, ARCHIVED)
    now = _snapshot("2026-08-15", {("mod-b", "GOLDM"): 0.1}, ARCHIVED)
    report = wa.build_report(now, [prev])
    assert report["demotions"] == []


def test_a_module_OUT_OF_SCOPE_on_an_asset_is_not_demoted_for_it():
    """SessionShift measures negative on NATURALGAS and is deliberately not
    scoped there. Demoting it for ground it never trades would archive a
    module that is doing exactly what it was told."""
    lineup = {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                        "status": "SHADOW_MODE", "scope": ["GOLDM"]}}
    prev = _snapshot("2026-08-08", {("mod-a", "NATURALGAS"): -1.0}, lineup)
    now = _snapshot("2026-08-15", {("mod-a", "NATURALGAS"): -1.2}, lineup)
    report = wa.build_report(now, [prev])
    assert report["demotions"] == []


def test_small_wobbles_are_not_reported_as_moves():
    prev = _snapshot("2026-08-08", {("mod-a", "GOLDM"): 3.00}, LIVE)
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 3.40}, LIVE)
    report = wa.build_report(now, [prev])
    assert report["moves"] == []


def test_a_real_decay_IS_reported_even_while_still_above_the_bar():
    """The early warning that matters: still shippable, but falling fast."""
    prev = _snapshot("2026-08-08", {("mod-a", "GOLDM"): 3.40}, LIVE)
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 2.10}, LIVE)
    report = wa.build_report(now, [prev])
    assert len(report["moves"]) == 1
    assert report["moves"][0]["delta"] == pytest.approx(-1.30)
    assert report["demotions"] == []


def test_the_first_run_records_a_baseline_and_flags_nothing():
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 1.1}, LIVE)
    report = wa.build_report(now, [])
    assert report["compared_to"] is None
    assert report["demotions"] == []   # nothing to be a SECOND bad week against
    assert report["moves"] == []
    assert len(report["new"]) == 1
    text = wa.render(now, report)
    assert "FIRST RUN" in text
    assert "as it did last week" not in text


def test_a_newly_measured_pair_is_new_not_a_move():
    prev = _snapshot("2026-08-08", {}, LIVE)
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 2.5}, LIVE)
    report = wa.build_report(now, [prev])
    assert len(report["new"]) == 1
    assert report["moves"] == []


def test_a_pair_that_stopped_measuring_does_not_crash_the_diff():
    """Below MIN_N it is simply absent. That must not raise."""
    prev = _snapshot("2026-08-08", {("mod-a", "GOLDM"): 2.5}, LIVE)
    now = _snapshot("2026-08-15", {}, LIVE)
    report = wa.build_report(now, [prev])
    assert report["demotions"] == [] and report["moves"] == []


def test_the_rendered_report_names_the_below_bar_pairs():
    now = _snapshot("2026-08-15", {("mod-a", "GOLDM"): 1.42}, LIVE)
    text = wa.render(now, wa.build_report(now, []))
    assert "Alpha" in text and "GOLDM" in text and "below bar" in text


def test_the_ship_bar_matches_every_other_lab():
    """t>=2 is the standard the whole research directory ships against. A
    different bar here would quietly create two definitions of 'edge'."""
    assert wa.SHIP_BAR == 2.0
    assert wa.MIN_N == 30
