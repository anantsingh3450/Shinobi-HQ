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
    # Wording widened 2026-08-28: there are now TWO ways to have nothing to diff
    # against — a genuine first run, and a change of measurement basis that makes
    # last week's numbers incomparable. Both must say so plainly rather than
    # printing a delta between two different rulers.
    assert "NO COMPARABLE PRIOR SNAPSHOT" in text
    assert "clock starts here" in text
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


# ------------------------------------------------- the measurement basis
def test_a_basis_change_suppresses_every_delta():
    """The first run under the 2026-08-28 geometry would otherwise have reported
    RangeFade/NATURALGAS as +4.34 -> +1.08, a 3.26 collapse. Nothing collapsed:
    the stop was included, the sample was split, and the contract had rolled.
    Reporting the ruler moving as the market moving hands the commander a
    decline that did not happen."""
    old = _snapshot("2026-08-21", {("mod-a", "GOLDM"): 4.34}, LIVE)
    old["geometry"] = "pooled-105d-nostop"
    now = _snapshot("2026-08-28", {("mod-a", "GOLDM"): 1.08}, LIVE)

    report = wa.build_report(now, [old])
    assert report["moves"] == [], "a delta across two bases is not a move"
    assert report["demotions"] == [], "and it is not a second bad week either"
    assert report["compared_to"] is None
    assert "NO COMPARABLE PRIOR SNAPSHOT" in wa.render(now, report)


def test_the_same_basis_still_diffs_normally():
    """Suppression is keyed on the bases DIFFERING, so two snapshots agreeing —
    including two legacy ones that both predate the stamp — still diff.

    The report is deliberately more permissive than evolution.plan(), which
    additionally requires a positive stamp on both sides. The report informs a
    human who can weigh it; the policy removes a strategy's capital, and the
    stricter rule belongs on the side that acts."""
    old = _snapshot("2026-08-21", {("mod-a", "GOLDM"): 4.34}, LIVE)
    now = _snapshot("2026-08-28", {("mod-a", "GOLDM"): 1.08}, LIVE)
    report = wa.build_report(now, [old])
    assert report["compared_to"] == "2026-08-21"
    assert report["moves"], "a real week-on-week move must still be reported"


def test_the_policy_is_stricter_than_the_report_about_unstamped_snapshots():
    """Guards the asymmetry above, so a later reader does not 'fix' one to match
    the other and quietly let legacy numbers retire a strategy."""
    from bots.autonomous import evolution as ev

    legacy_pair = [_snapshot("2026-08-28", {("mod-a", "GOLDM"): 1.0},
                             {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                                        "status": "SHADOW_MODE", "scope": ["GOLDM"]}}),
                   _snapshot("2026-08-21", {("mod-a", "GOLDM"): 1.5},
                             {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                                        "status": "SHADOW_MODE", "scope": ["GOLDM"]}})]
    for snap in legacy_pair:
        snap["ship_bar"] = 2.0
    assert ev.plan(legacy_pair) == [], "unstamped snapshots must not retire anything"


def test_a_parked_asset_is_not_reported_as_orphaned():
    """CRUDEOIL was parked 2026-08-26 after six sweeps failed out of sample. The
    boot audit has honoured that since; this report had not, and was about to
    announce 'CRUDEOIL: NO live strategy is scoped to it' every Friday for a
    decision already made."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    assert "CRUDEOIL" in Bot.PARKED_ASSETS
    gaps = wa.coverage_gaps({
        "mod-a": {"strategy_id": "s-a", "name": "Alpha", "status": "SHADOW_MODE",
                  "scope": ["NATURALGAS"], "chest": 100.0},
    })
    assert not any("CRUDEOIL" in g for g in gaps), gaps
    assert any("GOLDM" in g for g in gaps), "an UNPARKED orphan must still scream"


def test_the_geometry_stamp_reaches_the_report():
    now = _snapshot("2026-08-28", {("mod-a", "GOLDM"): 1.1}, LIVE)
    text = wa.render(now, wa.build_report(now, []))
    assert wa.GEOMETRY in text
    assert "ATR stop applied" in text


# ------------------------------------------------------- the parked asset watch
def _stat(t, t_train=None, n=100, confirmed=False):
    return {"n": n, "accuracy": 52.0, "edge_atr": 0.2, "t": t,
            "t_train": t_train, "n_train": None if t_train is None else 80,
            "edge_train": None if t_train is None else 0.2,
            "train_below_min_n": t_train is None, "confirmed": confirmed}


def test_a_parked_asset_is_still_scored_every_week():
    """CRUDEOIL was parked 2026-08-26 and the knob sweep only visits LIVE pairs,
    so nothing was watching it. Parking was a one-way door: an asset with no live
    strategy generates no proposals, so improving evidence would never surface
    and crude could never earn its way back.

    That directly blocks the commander's aim — Hokage is to become a MASTER of
    crude and gas, and mastery of an asset you stopped looking at is not
    reachable."""
    text = wa.parked_watch({"CRUDEOIL": {"entry-trendrider-mcx-v1": _stat(3.60, 1.21)}})
    assert "CRUDEOIL" in text
    assert "entry-trendrider-mcx-v1" in text
    assert "still nothing clears both halves" in text


def test_a_parked_asset_that_now_clears_the_bar_is_named():
    text = wa.parked_watch({
        "CRUDEOIL": {"entry-trendrider-mcx-v1": _stat(3.60, 2.40, confirmed=True)}
    })
    assert "CLEARS BOTH HALVES" in text
    assert "now clears the bar on CRUDEOIL" in text
    assert "Tier 3" in text, "reviving ADDS risk and must always ask"


def test_the_watch_never_revives_anything_itself():
    """Reviving is Tier 3 at any confidence — the tier that keeps a bad
    measurement from becoming a bigger position."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(wa.parked_watch)))
    called = {getattr(n.func, "attr", None) for n in ast.walk(tree)
              if isinstance(n, ast.Call)}
    for forbidden in ("save_portfolio", "write_text", "execute", "commit"):
        assert forbidden not in called, forbidden


def test_a_train_half_below_min_n_is_shown_as_such_not_as_zero():
    """RangeFade/NATURALGAS printed "tr_t +0.00" in the 2026-08-28 snapshot when
    its train half had merely fallen below MIN_N — it read as "measured flat"
    when it had fired 16 times. Missing is not zero."""
    text = wa.parked_watch({"CRUDEOIL": {"mod": _stat(1.5, None)}})
    assert "below min n" in text
    assert "+0.00" not in text


def test_nothing_is_said_when_no_asset_is_parked(monkeypatch):
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    monkeypatch.setattr(Bot, "PARKED_ASSETS", {})
    assert wa.parked_watch({"CRUDEOIL": {"mod": _stat(1.5)}}) == ""


def test_a_parked_asset_with_no_measurement_says_so():
    text = wa.parked_watch({})
    assert "nothing measurable this week" in text
