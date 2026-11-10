"""Every lab here ships against edge_atr, and nothing checked it reached us.

The caveat had been in the docstrings since the beginning - edge_atr measures
the UNDERLYING's forward move, not option P&L - and on 2026-11-10 it turned
out to matter more than anything it qualified. SessionShift/GOLDM measures
+0.496 ATR on the hold-out and had captured +0.013 over fifteen real fills;
SessionShift/SILVERM measures +0.072 and had captured +0.374 over eight. The
only funded MCX cell was returning three percent of its measured edge, and the
asset parked beside it was the only one in the ledger making money.

THE DEFECTS THESE TESTS PIN DOWN

1. THE JOIN IS ACROSS TWO NAMESPACES. The audit scores `entry-...` modules and
   the ledger records `strat-...` strategies, and for the index the stems
   differ too. A join that silently matches nothing reports "no gap anywhere"
   forever - the failure that made my own day-watch blind for four days. So
   LEDGER_ID is a table, every module must be in it, and an unmapped module is
   printed rather than dropped.

2. AN INVENTED IDENTIFIER IS WORSE THAN AN UNMATCHED ONE. Rebuilding
   `strat-{display}-v1` from the shortened display form turned the real ledger
   row `Heuristic BANKNIFTY Strategy` into an id that has never existed, so the
   raw spelling is carried through instead.

3. NONE IS NOT ZERO. A cell with no fills has not been contradicted; writing
   0.0 for its captured edge would claim it captured nothing.

4. A SILENT EXCLUSION READS LIKE AN ABSENCE. Cells below the fill floor are
   named with their counts, because dropping them looks identical to a cell
   that has never traded.

5. IT MUST NEVER ACT. A single-digit fill count cannot retire a module, so the
   gap is a snapshot key the evolution policy does not read.
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
    "weekly_audit", ROOT / "tools" / "research" / "weekly_audit.py")
wa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wa)

AUDIT_SOURCE = (ROOT / "tools" / "research" / "weekly_audit.py").read_text(
    encoding="utf-8")
EVOLUTION_SOURCE = (ROOT / "src" / "bots" / "autonomous" / "evolution.py"
                    ).read_text(encoding="utf-8")

GOLD_CELL = "entry-sessionshift-mcx-v1/GOLDM"
SILVER_CELL = "entry-sessionshift-mcx-v1/SILVERM"


def _measured(edge: float, t: float = 1.5, n: int = 300) -> dict:
    return {"edge_atr": edge, "t": t, "n": n, "accuracy": 50.0}


def _captured(mean: float, n: int, last: str = "2026-11-03") -> dict:
    return {"n": n, "captured_atr": mean, "t": 0.5, "last": last}


# ============================================ the two namespaces are joined
def test_every_audit_module_has_a_ledger_id():
    """Adding a module must force a decision here, not drop it silently."""
    assert wa.unmapped_modules() == []


def test_the_live_mcx_strategies_map_to_their_entry_modules():
    assert wa.LEDGER_ID["entry-sessionshift-mcx-v1"] == "strat-sessionshift-mcx-v1"
    assert wa.LEDGER_ID["entry-trendrider-mcx-v1"] == "strat-trendrider-mcx-v1"


def test_the_index_mapping_is_not_a_prefix_swap():
    """entry-macrobreakout-v1 is traded by strat-macrobreakout-COMMODITIES-v1.
    A string replace would have missed it and reported no fills forever."""
    assert wa.LEDGER_ID["entry-macrobreakout-v1"] != "strat-macrobreakout-v1"
    assert wa.LEDGER_ID["entry-macrobreakout-v1"] == (
        "strat-macrobreakout-commodities-v1")


def test_an_unmapped_module_is_printed_rather_than_dropped(monkeypatch):
    monkeypatch.setattr(wa, "LEDGER_ID", {})
    block = {GOLD_CELL: {"measured_atr": 0.496, "captured_atr": 0.013,
                         "captured_n": 15, "gap": -0.483,
                         "last_fill": "2026-11-03"}}
    text = wa.capture_watch(block, [])
    assert "NOT JOINED TO THE LEDGER AT ALL" in text
    assert "fix LEDGER_ID" in text


# ======================================================= the gap is computed
def test_the_gap_is_captured_less_measured():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    assert block[GOLD_CELL]["gap"] == pytest.approx(-0.483)
    assert block[GOLD_CELL]["captured_n"] == 15


def test_a_cell_can_capture_more_than_it_measures():
    block = wa.capture_block(
        {"SILVERM": {"entry-sessionshift-mcx-v1": _measured(0.072)}},
        {"SILVERM": {"strat-sessionshift-mcx-v1": _captured(0.374, 8)}})
    assert block[SILVER_CELL]["gap"] == pytest.approx(+0.302)


def test_a_cell_with_no_fills_reports_none_not_zero():
    """NONE IS NOT ZERO. No fills means not contradicted, not 'captured
    nothing' - the same lesson as the missing strategy_id."""
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}}, {})
    cell = block[GOLD_CELL]
    assert cell["captured_atr"] is None
    assert cell["gap"] is None
    assert cell["captured_n"] == 0


def test_a_cell_under_the_fill_floor_is_not_compared():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1":
                   _captured(2.0, wa.MIN_FILLS - 1)}})
    cell = block[GOLD_CELL]
    assert cell["gap"] is None
    # ...but its count survives, so it can be named rather than vanishing.
    assert cell["captured_n"] == wa.MIN_FILLS - 1


def test_exactly_the_fill_floor_is_compared():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.1, wa.MIN_FILLS)}})
    assert block[GOLD_CELL]["gap"] is not None


def test_the_measured_side_is_carried_so_the_snapshot_stands_alone():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496, t=2.19,
                                                          n=288)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    cell = block[GOLD_CELL]
    assert cell["measured_atr"] == pytest.approx(0.496)
    assert cell["measured_t"] == pytest.approx(2.19)
    assert cell["measured_n"] == 288
    assert cell["last_fill"] == "2026-11-03"


# ================================================ the report says what it is
def test_a_shortfall_is_named_with_the_share_it_returned():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    text = wa.capture_watch(block, [])
    assert "returned 3% of its measured edge over 15 fills" in text


def test_a_sign_flip_is_reported_as_a_sign_flip_not_a_percentage():
    """"-48% of its edge" hides the only thing that matters: the module
    called a direction and the tape went the other way."""
    block = wa.capture_block(
        {"NATURALGAS": {"entry-rangefade-mcx-v1": _measured(0.065)}},
        {"NATURALGAS": {"strat-rangefade-mcx-v1": _captured(-0.031, 10)}})
    text = wa.capture_watch(block, [])
    assert "OPPOSITE sign" in text
    assert "-48%" not in text


def test_a_large_overshoot_is_named_too():
    block = wa.capture_block(
        {"SILVERM": {"entry-sessionshift-mcx-v1": _measured(0.072)}},
        {"SILVERM": {"strat-sessionshift-mcx-v1": _captured(0.374, 8)}})
    assert "5.2x its measured edge" in wa.capture_watch(block, [])


def test_a_small_gap_on_a_small_edge_is_tabled_but_not_called_out():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.400)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.320, 9)}})
    text = wa.capture_watch(block, [])
    assert GOLD_CELL in text
    assert "has returned" not in text


def test_thin_cells_are_named_with_their_counts():
    """A silent exclusion reads exactly like a cell that never traded."""
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496),
                   "entry-trendrider-mcx-v1": _measured(0.110)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15),
                   "strat-trendrider-mcx-v1": _captured(-0.475, 2)}})
    text = wa.capture_watch(block, [])
    assert f"below the {wa.MIN_FILLS}-fill floor" in text
    assert "entry-trendrider-mcx-v1/GOLDM (2)" in text


def test_cells_with_no_fills_at_all_are_counted():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496),
                   "entry-eiareaction-mcx-v1": _measured(0.040)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    text = wa.capture_watch(block, [])
    assert "no fills on record at all: 1 cell " in text


def test_last_week_s_gap_is_shown_beside_this_week_s():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    text = wa.capture_watch(block, [{"capture": {GOLD_CELL: {"gap": -0.400}}}])
    assert "-0.400" in text


def test_an_empty_history_prints_a_dash_rather_than_a_number():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    assert "MEASURED EDGE AGAINST CAPTURED EDGE" in wa.capture_watch(block, [])


def test_nothing_measurable_says_so_rather_than_printing_an_empty_table():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.5, 1)}})
    text = wa.capture_watch(block, [])
    assert "Nothing to compare" in text
    assert "closest:" in text


def test_no_cells_at_all_produces_no_section():
    assert wa.capture_watch({}, []) == ""


def test_the_section_states_that_it_decides_nothing():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    text = wa.capture_watch(block, [])
    assert "nothing here" in text
    assert "confirms, retires, funds or un-parks" in text


# ==================================================== the telegram trigger
def test_a_new_shortfall_is_news():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    assert wa.capture_news(block, []) == [GOLD_CELL]


def test_a_shortfall_that_was_already_there_is_not_news_again():
    """A gap sitting in the report for weeks must not break every quiet
    week's silence; a new one must."""
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}},
        {"GOLDM": {"strat-sessionshift-mcx-v1": _captured(0.013, 15)}})
    history = [{"capture": {GOLD_CELL: {"gap": -0.470}}}]
    assert wa.capture_news(block, history) == []


def test_an_overshoot_is_not_news():
    """Capturing MORE than measured is in the table; it is not an alarm."""
    block = wa.capture_block(
        {"SILVERM": {"entry-sessionshift-mcx-v1": _measured(0.072)}},
        {"SILVERM": {"strat-sessionshift-mcx-v1": _captured(0.374, 8)}})
    assert wa.capture_news(block, []) == []


def test_a_cell_with_no_fills_is_not_news():
    block = wa.capture_block(
        {"GOLDM": {"entry-sessionshift-mcx-v1": _measured(0.496)}}, {})
    assert wa.capture_news(block, []) == []


def test_the_trigger_is_wired_into_the_telegram_decision():
    assert "or fresh_gaps" in AUDIT_SOURCE
    assert "capture_news(current.get(\"capture\")" in AUDIT_SOURCE


# ================================================ it reports and never acts
def test_the_evolution_policy_does_not_read_the_capture_key():
    """A single-digit fill count cannot retire a module. The gap is a
    snapshot key the policy must not consult."""
    assert "capture" not in EVOLUTION_SOURCE.replace("captured", "")


def test_the_audit_stamps_the_gap_into_the_snapshot():
    """Stamped, not recomputed later: the ledger grows, so a gap re-derived
    from a different set of fills is not what this snapshot reported."""
    assert 'current["capture"] = capture_block(' in AUDIT_SOURCE


def test_the_ledger_is_opened_read_only_because_hokage_is_running():
    import model_vs_ledger as mvl
    source = (ROOT / "tools" / "research" / "model_vs_ledger.py").read_text(
        encoding="utf-8")
    assert "mode=ro" in source
    assert mvl.read_rows is not None


def test_a_missing_ledger_is_no_fills_rather_than_a_crash(tmp_path):
    assert wa.ledger_capture(tmp_path / "absent.db") == {}


# =========================================== the raw identifier is preserved
def test_the_ledger_spelling_is_carried_not_rebuilt():
    """Rebuilding `strat-{display}-v1` turned the real row `Heuristic
    BANKNIFTY Strategy` into an identifier that has never existed."""
    import model_vs_ledger as mvl
    row = mvl.Row(asset="BANKNIFTY", strategy="Heuristic BANKNIFTY Strategy",
                  strategy_id="Heuristic BANKNIFTY Strategy",
                  closed_on="2026-08-24", premium=1000.0, gross_pct=1.0,
                  cost_pct=0.3, atr_move=0.5)
    assert row.strategy_id == "Heuristic BANKNIFTY Strategy"
    assert not row.strategy_id.startswith("strat-")


def test_a_strat_id_is_shortened_for_display_but_kept_for_the_join():
    import model_vs_ledger as mvl
    row = mvl.Row(asset="GOLDM", strategy="sessionshift-mcx",
                  strategy_id="strat-sessionshift-mcx-v1",
                  closed_on="2026-11-03", premium=1000.0, gross_pct=1.0,
                  cost_pct=0.3, atr_move=0.5)
    # The display form is NOT what the join uses: it would match nothing.
    assert row.strategy not in wa.LEDGER_ID.values()
    assert row.strategy_id == wa.LEDGER_ID["entry-sessionshift-mcx-v1"]
