"""The funded family was approved on 2026-11-09 and the audit never used it.

TWO FAULTS, FOUND 2026-11-10 WHILE PRICING A THIRD DECISION.

1. TWO NAMESPACES FOR ONE MODULE, FOR THE FOURTH TIME. `funded_cells.FUNDED`
   is keyed by the ledger's `strat-*` ids. `weekly_audit.main()` re-keys every
   module to its `entry-*` module_id before measuring, because that is the
   spelling five snapshots of history are written in and `_get` matches last
   week's row by it. So the live audit asked
   `is_funded("entry-macrobreakout-v1", "NIFTY")`, got False, and judged every
   funded cell at the full family's bar of 3.22 instead of 2.39.

   The decision was inverted in both directions: a funded cell could not be
   CONFIRMED at its own bar, and it was eligible for DEMOTION on the very bar
   it was exempted from - which the comment beside that check says must not
   happen. Every snapshot row since carries `funded: false`, so the report's
   [FUNDED] tag has never printed once.

   Nothing failed, which is the whole problem. A cross-namespace lookup that
   matches nothing returns a clean, confident answer for ever.

2. POWER_LAB PRICED EVERY CELL ON ITS BETTER HALF. `classify` requires the bar
   to be cleared on BOTH halves - that rule is why every session count in the
   file is doubled - and then the requirement itself was computed from the
   hold-out half alone. MacroBreakout/SENSEX reads t +2.31 hold-out and +1.00
   train; priced on the hold-out alone it printed "11 more sessions", three
   weeks, for a cell whose other half is nowhere near. Pooled over both
   halves it is about ten times that.

   This matters more than the arithmetic: those were the numbers put in front
   of the commander as the case for lowering the bar.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "research"))
sys.path.insert(0, str(ROOT / "src"))

import power_lab as pl  # noqa: E402
import weekly_audit as audit  # noqa: E402
from hokage.research import funded_cells  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

ALL_MODULES = {**ENTRY_MODULES, **MCX_ENTRY_MODULES}


# ============================================ 1. the namespace that lost it
def test_the_audit_asks_in_the_namespace_it_actually_measures_in():
    """THE BUG, as a single assertion. main() measures under `entry-*`."""
    assert audit.bar_for("entry-macrobreakout-v1", "NIFTY") == audit.FUNDED_BAR
    assert audit.bar_for("entry-sessionshift-mcx-v1", "GOLDM") == audit.FUNDED_BAR


def test_both_spellings_of_every_module_agree_on_every_asset():
    """THE GENERALISABLE RAIL. Whatever a caller spells a module, the bar it
    gets back must be the same - otherwise which bar a cell answers to depends
    on which file asked."""
    for key, module in ALL_MODULES.items():
        module_id = getattr(module, "module_id", key)
        for symbol in audit.UNIVERSE:
            assert audit.bar_for(key, symbol) == audit.bar_for(module_id, symbol), (
                f"{key} and {module_id} disagree on {symbol}")
            assert (audit.is_funded_cell(key, symbol)
                    is audit.is_funded_cell(module_id, symbol))


def test_an_unfunded_cell_still_answers_to_the_full_family():
    """The fix must not hand the easier bar to everything. A number found
    among forty needs the correction for forty."""
    assert audit.bar_for("entry-macrobreakout-v1", "BANKNIFTY") == audit.SHIP_BAR
    assert audit.bar_for("entry-rangefade-mcx-v1", "NATURALGAS") == audit.SHIP_BAR
    assert audit.FUNDED_BAR < audit.SHIP_BAR


def test_a_missing_module_or_asset_gets_the_wide_bar():
    """Unknown must fall to the STRICTER bar. The opposite default would hand
    an exemption to anything the table does not recognise."""
    assert audit.bar_for(None, "NIFTY") == audit.SHIP_BAR
    assert audit.bar_for("entry-macrobreakout-v1", None) == audit.SHIP_BAR
    assert audit.bar_for("entry-nonexistent-v9", "NIFTY") == audit.SHIP_BAR
    assert audit.is_funded_cell(None, None) is False


def test_every_funded_cell_names_a_module_that_exists():
    """A typo in FUNDED empties the family silently - the same failure as the
    namespace, arriving from the other end."""
    known = set(ALL_MODULES) | set(audit.LEDGER_ID.values())
    for module_id, asset in funded_cells.FUNDED:
        assert module_id in known, f"FUNDED names an unknown module: {module_id}"
        assert asset in audit.UNIVERSE, f"FUNDED names an unmeasured asset: {asset}"


def test_every_funded_cell_resolves_to_the_funded_bar_from_both_ends():
    """Not just that the id exists - that the lookup the audit performs on it
    actually returns the funded bar."""
    assert funded_cells.family_size() > 0
    for module_id, asset in funded_cells.FUNDED:
        assert audit.bar_for(module_id, asset) == audit.FUNDED_BAR
        entry_ids = [e for e, s in audit.LEDGER_ID.items() if s == module_id]
        for entry_id in entry_ids:
            assert audit.bar_for(entry_id, asset) == audit.FUNDED_BAR


def test_the_namespace_table_still_covers_every_module():
    """`unmapped_modules` is what forces a decision here when a module is
    added, instead of quietly dropping it out of one namespace."""
    assert audit.unmapped_modules() == []


def test_the_snapshot_row_asks_through_the_translating_helper():
    """Source rail. The row's `funded` field is what the report's [FUNDED] tag
    and every later reader trust; calling `funded_cells.is_funded` directly
    there is the original bug."""
    src = (ROOT / "tools" / "research" / "weekly_audit.py").read_text(encoding="utf-8")
    body = src.split("def measure_split")[1].split("\ndef ")[0]
    assert '"funded": is_funded_cell(' in body
    assert '"funded": funded_cells.is_funded(' not in body


# ================================== a funded cell is not a demotion candidate
def _snapshot(date: str, t: float) -> dict:
    """One funded cell, measured at `t`, with a lineup that makes it live."""
    return {
        "date": date,
        "geometry": audit.GEOMETRY,
        "parked_assets": [],
        "lineup": {"entry-macrobreakout-v1": {
            "strategy_id": "strat-macrobreakout-commodities-v1",
            "name": "MacroBreakout", "status": "ACTIVE",
            "scope": ["NIFTY"], "chest": 100000.0}},
        "measurements": {"NIFTY": {"entry-macrobreakout-v1": {
            "n": 60, "accuracy": 55.0, "edge_atr": 0.35, "t": t,
            "n_train": 50, "edge_train": 0.3, "t_train": t,
            "train_below_min_n": False,
            "bar": audit.bar_for("entry-macrobreakout-v1", "NIFTY"),
            "funded": audit.is_funded_cell("entry-macrobreakout-v1", "NIFTY"),
            "confirmed": False}}},
    }


def test_a_funded_cell_above_its_own_bar_is_not_demoted():
    """THE INVERSION. Two weeks between 2.39 and 3.22 would have demoted a
    cell for failing a bar it was exempted from - undoing the funding decision
    from the other side, and only ever downward."""
    between = (audit.FUNDED_BAR + audit.SHIP_BAR) / 2.0
    assert audit.FUNDED_BAR < between < audit.SHIP_BAR
    report = audit.build_report(_snapshot("2026-11-13", between),
                                [_snapshot("2026-11-06", between)])
    assert report["demotions"] == []


def test_a_funded_cell_below_its_own_bar_is_still_demoted():
    """The exemption is a different bar, not an immunity."""
    report = audit.build_report(_snapshot("2026-11-13", 1.0),
                                [_snapshot("2026-11-06", 1.1)])
    assert [d["symbol"] for d in report["demotions"]] == ["NIFTY"]


# ======================================= 2. power_lab prices the real bar
def test_power_lab_prices_a_funded_cell_at_the_funded_bar():
    assert pl.bar_for_cell("entry-sessionshift-mcx-v1", "GOLDM") == audit.FUNDED_BAR
    assert pl.bar_for_cell("strat-sessionshift-mcx-v1", "GOLDM") == audit.FUNDED_BAR
    assert pl.bar_for_cell("entry-rangefade-mcx-v1", "NATURALGAS") == audit.SHIP_BAR


def test_there_is_no_single_bar_left_in_power_lab():
    """A module-level `BAR` reads as universal and every caller that forgets
    to ask gets the widest one silently. It is deleted, not corrected."""
    assert not hasattr(pl, "BAR")
    assert pl.EXPLORATORY_BAR == audit.SHIP_BAR
    assert pl.FUNDED_BAR == audit.FUNDED_BAR
    assert pl.FAMILY_OVERRIDE is None


def test_the_bar_is_a_required_argument_not_a_default():
    for fn in (pl.required_n, pl.classify):
        params = list(inspect.signature(fn).parameters.values())
        assert params[-1].name == "bar"
        assert params[-1].default is inspect.Parameter.empty, (
            f"{fn.__name__} has a default bar, which is how the caller that "
            f"forgets gets the wrong one and never finds out")


def test_the_same_cell_is_underpowered_at_one_bar_and_confirmed_at_another():
    cell = {"n": 100, "edge_atr": 0.3, "t": 2.5}
    assert pl.classify(cell, cell, audit.FUNDED_BAR) == "CONFIRMED"
    assert pl.classify(cell, cell, audit.SHIP_BAR) == "UNDERPOWERED"


def test_main_prices_each_row_at_its_own_bar():
    """Source rail: the loop must ask per cell, not once per run."""
    src = (ROOT / "tools" / "research" / "power_lab.py").read_text(encoding="utf-8")
    body = src.split("def main(")[1]
    assert "cell_bar = bar_for_cell(name, symbol)" in body
    assert "classify(hold, train, cell_bar)" in body


# ======================================= the half that actually binds
def test_the_effect_size_divides_out_the_sample():
    """t grows with sqrt(n); the effect size is what a projection holds fixed."""
    assert pl.effect(100, 2.0) == pytest.approx(0.2)
    assert pl.effect(400, 4.0) == pytest.approx(0.2)
    assert pl.effect(0, 2.0) is None
    assert pl.effect(100, None) is None


def test_the_requirement_pools_both_halves_weighted_by_n():
    hold = {"n": 44, "edge_atr": 0.36, "t": 2.31}
    train = {"n": 37, "edge_atr": 0.18, "t": 1.00}
    d_hold, d_train = pl.effect(44, 2.31), pl.effect(37, 1.00)
    expected = (d_hold * 44 + d_train * 37) / 81
    assert pl.pooled_effect(hold, train) == pytest.approx(expected)
    # strictly between the two halves, and nearer the heavier one
    assert d_train < pl.pooled_effect(hold, train) < d_hold


def test_the_sensex_case_is_not_three_weeks():
    """THE REGRESSION, with the real numbers, in the unit it was quoted in.

    MacroBreakout/SENSEX: hold-out t +2.31 over 44 signals, train half +1.00
    over 37, firing 0.65 a session, 135 sessions already banked. Priced on the
    hold-out half alone it printed "11 more sessions" - three weeks.

    Note how the error AMPLIFIES on the way to sessions. The requirement
    itself rises 1.7x, but the answer is a requirement MINUS what is already
    banked, so a modest change in the first can be a tenfold change in the
    second. That is why this test asserts in sessions: n_req is not the number
    anybody quotes."""
    hold = {"n": 44, "edge_atr": 0.364, "t": 2.31}
    train = {"n": 37, "edge_atr": 0.181, "t": 1.00}
    bar, rate, banked = audit.FUNDED_BAR, 0.65, 135

    def extra(need):
        return max(0.0, 2.0 * need / rate - banked)

    hold_only = extra(pl.required_n(hold["n"], hold["t"], bar))
    pooled = extra(pl.required_n_pooled(hold, train, bar))
    assert hold_only < 15          # the three weeks that was quoted
    assert pooled > 5 * hold_only  # what both halves actually ask for


def test_halves_that_disagree_in_sign_have_no_projection():
    """Averaging a positive half with a negative one to a small positive
    manufactures exactly the hope this file refuses."""
    hold = {"n": 50, "edge_atr": 0.1, "t": 1.5}
    train = {"n": 50, "edge_atr": -0.1, "t": -1.5}
    assert pl.pooled_effect(hold, train) is None
    assert pl.required_n_pooled(hold, train, 2.39) is None


def test_agreeing_halves_are_not_flagged_as_disagreeing():
    same = {"n": 100, "edge_atr": 0.3, "t": 2.0}
    assert pl.halves_disagree(same, same) is False
    weak = {"n": 100, "edge_atr": 0.1, "t": 0.5}
    assert pl.halves_disagree(same, weak) is True


def test_the_report_says_the_requirement_is_pooled():
    """It will be quoted, so the page it is quoted from has to say which
    halves it used."""
    src = (ROOT / "tools" / "research" / "power_lab.py").read_text(encoding="utf-8")
    flat = " ".join(src.split())
    assert "POOLED" in flat
    assert "both have to" in flat
    # and a cell already at its requirement must not print as a schedule
    assert "already AT the pooled" in flat
