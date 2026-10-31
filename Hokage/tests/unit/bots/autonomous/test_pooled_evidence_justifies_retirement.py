"""A module-wide action was justified by a single cell, and the cell it picked
was on an asset Hokage does not trade.

`plan()` retires a MODULE - RAIL 3 asks what survives if the module were
retired OUTRIGHT, not merely descoped from one asset - but the evidence
attached to the decision was one (module, asset) CELL, and the single
autonomous slot went to whichever cell measured worst. On 2026-10-31, with the
retirement bar separated from the ship bar, that cleared EventRider justified
like this:

    EventRider  CRUDEOIL  -1.95 -> -1.51   *** CLEARED TO RETIRE ***
    EventRider  NATURALGAS -1.05 -> -1.18  queued behind the 1-per-run cap

CRUDEOIL has been parked since the seven sweeps that all failed out of sample.
So the sentence the commander was meant to rule on cited tape Hokage does not
trade and never has, while the NATURALGAS cell - real tape, a real chest - sat
in the queue behind it. The outcome was right and the reason was the
weakest-relevance one available: EventRider measures -1.49 pooled across the
MCX Arena on n=494 at 39.7% accuracy, negative on all four of its assets
across both snapshots. That number existed in the same snapshot, under
`pooled`, and `plan()` did not read it - deliberately, with a comment in
weekly_audit saying "pooling cannot move Tier 1 until someone deliberately
wires it in".

THE SHAPE OF THE WIRING MATTERS. A league's assets move together, so pooled
signals are correlated and the effective sample is far below the printed n;
POOLED_CAVEAT calls the pooled t an UPPER BOUND on significance, "never enough
on its own to move capital". So it is wired as a VETO: the per-cell two-week
rule must still clear first, and the pooled reading can only CONTRADICT it. It
can block a retirement. It can never clear one.
"""
from __future__ import annotations

from bots.autonomous import evolution as ev
from tests.unit.bots.autonomous.test_evolution_tiers import (
    FIXTURE_LEAGUE, _snap,
)

#: Two live modules on GOLDM, so retiring either never orphans the asset and
#: RAIL 3 stays out of the way of what these tests are measuring.
PAIR = {
    "mod-a": {"strategy_id": "s-a", "name": "Alpha", "status": "SHADOW_MODE",
              "scope": ["GOLDM"]},
    "mod-b": {"strategy_id": "s-b", "name": "Beta", "status": "SHADOW_MODE",
              "scope": ["GOLDM"]},
}


def _pool(modules: dict[str, float]) -> dict:
    """A pooled table stating each module's module-wide t outright.

    n and accuracy are EventRider's real pooled figures from the 2026-10-30
    snapshot, so the strings these tests assert on are the strings the
    commander would actually have read.
    """
    return {FIXTURE_LEAGUE: {
        mod: {"n": 494, "t": t, "edge_atr": -0.093, "accuracy": 39.7}
        for mod, t in modules.items()
    }}


def _archives(now_t, prev_t, *, lineup=PAIR, asset="GOLDM",
              pooled_now=None, pooled_prev=None, **extra):
    prev = _snap("2026-10-23", {("mod-a", asset): prev_t}, lineup,
                 pooled=pooled_prev)
    now = _snap("2026-10-30", {("mod-a", asset): now_t}, lineup,
                pooled=pooled_now)
    now.update(extra)
    return [d for d in ev.plan([now, prev]) if d.action == "archive"]


# --------------------------------------------------- the veto, in both halves
def test_a_module_that_pools_POSITIVE_is_not_retired_on_one_bad_asset():
    """The case the rail exists for: one bad cell inside a module whose
    league-wide reading is fine is a SCOPE question, and rescoping is Tier 2.
    """
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": 1.08}),
                   pooled_prev=_pool({"mod-a": 1.72}))
    assert not d.is_autonomous
    assert d.tier == ev.TIER_PROPOSE
    assert "not module-wide" in d.blocked_reason
    assert "SCOPE question" in d.blocked_reason


def test_a_module_negative_in_BOTH_pooled_readings_is_retired():
    """EventRider's real numbers: -1.60 then -1.49 pooled across the MCX
    Arena, and the cell negative in both weeks too."""
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": -1.49}),
                   pooled_prev=_pool({"mod-a": -1.60}))
    assert d.is_autonomous
    assert d.blocked_reason is None


def test_one_negative_pooled_reading_is_not_enough():
    """Same rule as the cell: a module that has only just turned negative is
    a reading, not a trend. Blocking still reports it."""
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": -1.49}),
                   pooled_prev=_pool({"mod-a": 0.40}))
    assert not d.is_autonomous
    assert "+0.40 then -1.49" in d.blocked_reason


def test_exactly_zero_pooled_is_not_harmful():
    """A zero pooled edge is money going nowhere, not the wrong way - the same
    reading RETIRE_T gives a cell."""
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": 0.0}),
                   pooled_prev=_pool({"mod-a": -1.60}))
    assert not d.is_autonomous


# ------------------------------------------- it can never CLEAR, only contradict
def test_a_dreadful_pooled_reading_cannot_retire_a_harmless_cell():
    """THE INVARIANT. The pooled t is an upper bound on significance, so it
    must never be able to retire anything by itself. Here the module pools
    -4.00 and the cell is positive: RAIL 1 still refuses."""
    d, = _archives(0.10, 0.18,
                   pooled_now=_pool({"mod-a": -4.0}),
                   pooled_prev=_pool({"mod-a": -4.0}))
    assert not d.is_autonomous
    assert "not measurably harmful" in d.blocked_reason, (
        "RAIL 1 must speak first: the pooled reading cannot promote a "
        "harmless cell into a retirement"
    )


def test_a_dreadful_pooled_reading_cannot_manufacture_a_second_week():
    """One week below the bar is noise whatever the module pools at."""
    assert _archives(-1.18, 2.60,
                     pooled_now=_pool({"mod-a": -4.0}),
                     pooled_prev=_pool({"mod-a": -4.0})) == []


def test_a_dreadful_pooled_reading_cannot_orphan_an_asset():
    """RAIL 3 is untouched: coverage outranks any amount of bad measurement."""
    sole = {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                      "status": "SHADOW_MODE", "scope": ["GOLDM"]}}
    d, = _archives(-1.18, -1.05, lineup=sole,
                   pooled_now=_pool({"mod-a": -4.0}),
                   pooled_prev=_pool({"mod-a": -4.0}))
    assert not d.is_autonomous
    assert "no live strategy" in d.blocked_reason


# ----------------------------------------------- not knowing has to block
def test_a_snapshot_with_no_pooled_table_retires_nothing_unattended():
    """Snapshots written before `pooled` existed. Not knowing the module-wide
    picture must never ALLOW a module-wide action."""
    d, = _archives(-1.18, -1.05, pooled_now={}, pooled_prev={})
    assert not d.is_autonomous
    assert "cannot corroborate" in d.blocked_reason


def test_a_module_too_rare_to_pool_is_not_retired_unattended():
    """A module below the audit's reporting floor pooled is absent from the
    table entirely - the same answer the per-cell rule gives a module too rare
    to measure on one asset."""
    d, = _archives(-1.18, -1.05,
                   pooled_now={FIXTURE_LEAGUE: {}},
                   pooled_prev={FIXTURE_LEAGUE: {}})
    assert not d.is_autonomous
    assert "cannot corroborate" in d.blocked_reason


def test_an_AMBIGUOUS_league_blocks_rather_than_picks_one():
    """Without the `leagues` stamp the league is inferred from the pooled
    table, and a module found under two leagues has no single module-wide
    reading. Module ids are league-specific by convention, not by guarantee.
    """
    two = {"League One": {"mod-a": {"n": 400, "t": -2.0, "edge_atr": -0.1,
                                    "accuracy": 40.0}},
           "League Two": {"mod-a": {"n": 400, "t": -2.0, "edge_atr": -0.1,
                                    "accuracy": 40.0}}}
    prev = _snap("2026-10-23", {("mod-a", "GOLDM"): -1.05}, PAIR, pooled=two)
    now = _snap("2026-10-30", {("mod-a", "GOLDM"): -1.18}, PAIR, pooled=two)
    for snap in (prev, now):
        del snap["leagues"]
    d, = [x for x in ev.plan([now, prev]) if x.action == "archive"]
    assert not d.is_autonomous
    assert ev._pooled_stat(now, "GOLDM", "mod-a") is None


def test_the_stamp_is_what_maps_an_asset_to_its_league():
    """With the stamp present the league comes from the asset, not from
    guessing which pooled table happens to mention the module."""
    snap = _snap("2026-10-30", {("mod-a", "GOLDM"): -1.18}, PAIR,
                 pooled=_pool({"mod-a": -1.49}))
    assert ev._pooled_stat(snap, "GOLDM", "mod-a")["league"] == FIXTURE_LEAGUE
    assert ev._pooled_stat(snap, "SILVERM", "mod-a") is None, (
        "an asset outside every stamped league has no module-wide reading"
    )


def test_an_unstamped_leagues_field_is_not_invented():
    assert ev._leagues({}) == {}
    assert ev._leagues({"leagues": None}) == {}
    assert ev._leagues({"leagues": {"L": ["goldm"]}}) == {"L": ("GOLDM",)}


# ------------------------------------------- the sentence he rules on
def test_the_reason_states_the_MODULE_WIDE_number():
    """The whole point. The sentence attached to a module-wide action has to
    carry the module-wide evidence, not only one cell's."""
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": -1.49}),
                   pooled_prev=_pool({"mod-a": -1.60}))
    assert d.is_autonomous
    assert "-1.60 then -1.49" in d.reason
    assert FIXTURE_LEAGUE in d.reason
    assert "n=494" in d.reason
    assert "39.7% accuracy" in d.reason
    # and the cell is still there - it is what triggered the look
    assert "-1.05 then -1.18" in d.reason


def test_a_parked_cell_SAYS_it_is_parked():
    """If the trigger cell is on tape Hokage does not trade, the reason must
    say so. "EventRider on CRUDEOIL" otherwise reads as evidence from a chest
    that was never risked."""
    sole = {"mod-a": {"strategy_id": "s-a", "name": "EventRider",
                      "status": "SHADOW_MODE", "scope": ["CRUDEOIL"]}}
    d, = _archives(-1.51, -1.95, lineup=sole, asset="CRUDEOIL",
                   parked_assets=["CRUDEOIL"],
                   pooled_now=_pool({"mod-a": -1.49}),
                   pooled_prev=_pool({"mod-a": -1.60}))
    assert d.is_autonomous, "a parked asset must not shield a losing module"
    assert "CRUDEOIL is PARKED" in d.reason
    assert "module-wide reading is the substance" in d.reason


def test_a_traded_cell_does_not_carry_the_parked_note():
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": -1.49}),
                   pooled_prev=_pool({"mod-a": -1.60}))
    assert "PARKED" not in d.reason


def test_the_evidence_records_the_pooled_reading_even_when_it_BLOCKED():
    """An autonomous change with no recorded reason is indistinguishable from
    a bug, and so is a blocked one."""
    d, = _archives(-1.18, -1.05,
                   pooled_now=_pool({"mod-a": 1.08}),
                   pooled_prev=_pool({"mod-a": 1.72}))
    assert d.evidence["t_pooled_now"] == 1.08
    assert d.evidence["t_pooled_previous"] == 1.72
    assert d.evidence["n_pooled"] == 494
    assert d.evidence["accuracy_pooled"] == 39.7
    assert d.evidence["league"] == FIXTURE_LEAGUE
    assert d.evidence["asset_is_parked"] is False
    assert d.evidence["retire_bar"] == ev.RETIRE_T


# ------------------------------------------------ which cell takes the slot
def test_the_slot_goes_to_the_module_the_POOLED_reading_condemns():
    """Alpha has the worse CELL (-2.00 against -0.50) but Beta is the worse
    MODULE (-1.90 pooled against -0.20). The action is module-wide, so Beta
    goes."""
    lineup = dict(PAIR)
    pooled = _pool({"mod-a": -0.20, "mod-b": -1.90})
    rows_prev = {("mod-a", "GOLDM"): -2.10, ("mod-b", "GOLDM"): -0.60}
    rows_now = {("mod-a", "GOLDM"): -2.00, ("mod-b", "GOLDM"): -0.50}
    decisions = ev.plan([
        _snap("2026-10-30", rows_now, lineup, pooled=pooled),
        _snap("2026-10-23", rows_prev, lineup, pooled=pooled),
    ])
    acting = [d for d in decisions if d.is_autonomous]
    assert len(acting) == 1
    assert acting[0].strategy_name == "Beta"


def test_within_one_module_a_TRADED_cell_is_named_before_a_parked_one():
    """EventRider's real shape. Both cells condemn the module; the one the
    commander is shown should be the one with a chest behind it."""
    lineup = {
        "mod-a": {"strategy_id": "s-a", "name": "EventRider",
                  "status": "SHADOW_MODE", "scope": ["CRUDEOIL", "NATURALGAS"]},
        "mod-b": {"strategy_id": "s-b", "name": "Beta",
                  "status": "SHADOW_MODE", "scope": ["NATURALGAS"]},
    }
    pooled = _pool({"mod-a": -1.49})
    rows_prev = {("mod-a", "CRUDEOIL"): -1.95, ("mod-a", "NATURALGAS"): -1.05}
    rows_now = {("mod-a", "CRUDEOIL"): -1.51, ("mod-a", "NATURALGAS"): -1.18}
    now = _snap("2026-10-30", rows_now, lineup, pooled=pooled)
    now["parked_assets"] = ["CRUDEOIL"]
    prev = _snap("2026-10-23", rows_prev, lineup, pooled=pooled)
    prev["parked_assets"] = ["CRUDEOIL"]

    acting = [d for d in ev.plan([now, prev]) if d.is_autonomous]
    assert len(acting) == 1
    assert acting[0].asset == "NATURALGAS", (
        "CRUDEOIL measures worse, but it is parked - the named evidence must "
        "be tape Hokage actually trades"
    )
    assert "PARKED" not in acting[0].reason


def test_a_parked_cell_still_takes_the_slot_when_it_is_the_only_one():
    """Ordering prefers a traded cell; it does not require one. A module whose
    only condemned cell is parked is still retired on its module-wide
    reading - with the reason saying the cell is parked."""
    sole = {"mod-a": {"strategy_id": "s-a", "name": "EventRider",
                      "status": "SHADOW_MODE", "scope": ["CRUDEOIL"]}}
    d, = _archives(-1.51, -1.95, lineup=sole, asset="CRUDEOIL",
                   parked_assets=["CRUDEOIL"],
                   pooled_now=_pool({"mod-a": -1.49}),
                   pooled_prev=_pool({"mod-a": -1.60}))
    assert d.is_autonomous
    assert d.asset == "CRUDEOIL"


# ------------------------------------------------ the audit stamps what it knew
def test_the_audit_stamps_the_leagues_into_the_snapshot():
    import sys
    from pathlib import Path
    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import weekly_audit

    src = Path(weekly_audit.__file__).read_text(encoding="utf-8")
    assert '"leagues": {name: list(assets) for name, assets in LEAGUES}' in src
    assert {name for name, _ in weekly_audit.LEAGUES} == {"Index Dojo",
                                                          "MCX Arena"}


def test_the_pooled_caveat_says_it_is_a_veto_only():
    """A number whose limitation lives somewhere else gets quoted without it,
    and the caveat is printed beside the table for exactly that reason."""
    import sys
    from pathlib import Path
    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import weekly_audit

    assert "VETO" in weekly_audit.POOLED_CAVEAT
    assert "never clear one" in weekly_audit.POOLED_CAVEAT


def test_every_league_the_audit_pools_is_stamped_with_its_assets():
    """The stamp maps asset -> league, so every pooled league must bring its
    assets or the mapping silently finds nothing."""
    import sys
    from pathlib import Path
    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import weekly_audit

    stamped = {name: list(assets) for name, assets in weekly_audit.LEAGUES}
    snap = {"leagues": stamped}
    for name, assets in weekly_audit.LEAGUES:
        for asset in assets:
            assert [lg for lg, a in ev._leagues(snap).items() if asset in a] \
                == [name]
