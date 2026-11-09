"""Three cells funded, and the two ways that decision could mean nothing.

Approved 2026-11-09. The bar is corrected for how many cells the audit looked
at - 40 gives t >= 3.22 - and three cells already cleared a flat 2.0, failing
only on that penalty. A family of three earns the bar for three, 2.39, which
moves the nearest answer from 133 sessions to twelve.

THE CHOICE HAD TO COME FROM OUTSIDE THE STATISTICS. Picking the top three by t
is exactly the selection the correction punishes, and a bar lowered around
that choice is lowered around nothing. These three were chosen on COST: only
GOLDM, SENSEX and NIFTY carry a measured edge larger than one full round trip.
That power_lab had independently ranked the same three nearest the bar is
corroboration, not the reason.

TRAP ONE: A LOOSER BAR FOR EVERYTHING. An unfunded cell is still found among
forty and still needs the correction for forty, or the whole exercise is just
a weakened bar wearing a decision's clothes.

TRAP TWO: A STATUS NOTHING HONOURS. The scan loop checks only for ARCHIVED, so
a PARKED status would have changed nothing - and any status outside (ACTIVE,
PRODUCTION, ARCHIVED) is fed to `evaluate_pipeline_transition`, which can
promote it back to ACTIVE by itself. A funding decision the system can quietly
undo is not a decision. The enforcement is `PARKED_ASSETS`, which the scan
loop genuinely skips.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))
sys.path.insert(0, str(ROOT / "tools" / "ops"))

from hokage.research import funded_cells as fc  # noqa: E402

FUNDED = (("strat-sessionshift-mcx-v1", "GOLDM"),
          ("strat-macrobreakout-commodities-v1", "SENSEX"),
          ("strat-macrobreakout-commodities-v1", "NIFTY"))


# ======================================================== the declaration
def test_exactly_three_cells_are_funded():
    assert fc.family_size() == 3
    assert set(fc.FUNDED) == set(FUNDED)


def test_every_funded_cell_states_its_reason():
    """A cell funded without the number that funded it is a decision nobody
    can audit later."""
    for cell, why in fc.FUNDED.items():
        assert why and "%" in why, cell


def test_the_decision_is_attributed_and_dated():
    assert fc.COMMITTED_ON == "2026-11-09"
    assert fc.COMMITTED_BY == "commander"


def test_funded_assets_are_the_three_that_survive_cost():
    assert fc.funded_assets() == {"GOLDM", "SENSEX", "NIFTY"}


def test_the_parked_three_are_recorded_with_their_numbers():
    """Kept rather than deleted: an asset that becomes cheap to trade should
    be reconsidered from the record, not from memory."""
    assert set(fc.PARKED_FOR_COST) == {"BANKNIFTY", "CRUDEOIL", "SILVERM"}
    for asset, why in fc.PARKED_FOR_COST.items():
        assert "%" in why, asset


def test_gas_is_traded_for_the_record_and_says_so():
    """UNPARKED IS NOT FUNDED, and that is the whole reason this category
    exists. Gas failed on cost and trades anyway by directive, to accumulate
    a record; treating "he told me to trade it" as "the evidence bar is
    lower" is how a directive turns into a measurement."""
    assert set(fc.TRADED_FOR_THE_RECORD) == {"NATURALGAS"}
    why = fc.TRADED_FOR_THE_RECORD["NATURALGAS"]
    assert "0.22%" in why and "0.73-0.75%" in why, "the cost must stay stated"
    assert "loses on arrival" in why, "the consequence must stay stated"
    assert "NATURALGAS" not in fc.funded_assets()


def test_the_three_categories_never_overlap():
    funded, parked = fc.funded_assets(), set(fc.PARKED_FOR_COST)
    traded = set(fc.TRADED_FOR_THE_RECORD)
    assert not (funded & parked)
    assert not (funded & traded), (
        "an asset cannot be both funded on edge and traded despite it")
    assert not (parked & traded)


@pytest.mark.parametrize("asset", ["goldm", "GOLDM", "GoldM"])
def test_lookup_is_case_insensitive(asset):
    assert fc.is_funded("strat-sessionshift-mcx-v1", asset)


def test_an_unfunded_cell_is_not_funded():
    assert not fc.is_funded("strat-trendrider-mcx-v1", "CRUDEOIL")
    assert not fc.is_funded("strat-sessionshift-mcx-v1", "SILVERM")


# ==================================================== trap one: the bar
def test_the_funded_bar_is_lower_than_the_exploratory_one():
    import weekly_audit as audit

    assert audit.FUNDED_BAR == 2.39
    assert audit.SHIP_BAR == 3.22
    assert audit.FUNDED_BAR < audit.SHIP_BAR


@pytest.mark.parametrize("module,asset", FUNDED)
def test_a_funded_cell_answers_to_the_funded_bar(module, asset):
    import weekly_audit as audit

    assert audit.bar_for(module, asset) == audit.FUNDED_BAR


@pytest.mark.parametrize("module,asset", [
    ("strat-trendrider-mcx-v1", "CRUDEOIL"),
    ("strat-sessionshift-mcx-v1", "SILVERM"),
    ("strat-macrobreakout-commodities-v1", "BANKNIFTY"),
])
def test_an_unfunded_cell_still_answers_to_the_full_family(module, asset):
    """TRAP ONE. A number found among forty needs the correction for forty."""
    import weekly_audit as audit

    assert audit.bar_for(module, asset) == audit.SHIP_BAR


def test_a_missing_identifier_gets_the_strict_bar():
    import weekly_audit as audit

    assert audit.bar_for(None, "GOLDM") == audit.SHIP_BAR
    assert audit.bar_for("strat-sessionshift-mcx-v1", None) == audit.SHIP_BAR


def test_the_basis_string_records_the_change():
    """Two snapshots either side of a new bar are not consecutive evidence,
    so the retirement clock must reset. That is intended, not incidental."""
    import weekly_audit as audit

    assert "funded3" in audit.GEOMETRY
    # and the bar is still the LAST element, or parse_stamp cannot read it
    from hokage.research import proposals

    basis, bar = proposals.parse_stamp(audit.GEOMETRY)
    assert bar == audit.SHIP_BAR
    assert not proposals.is_stale(audit.GEOMETRY, audit.SHIP_BAR)


# ============================================= trap two: the enforcement
def test_the_cost_failing_assets_are_parked_where_the_scan_loop_looks():
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    for asset in ("BANKNIFTY", "CRUDEOIL", "SILVERM"):
        assert asset in Bot.PARKED_ASSETS, asset
    for asset in ("NIFTY", "SENSEX", "GOLDM"):
        assert asset not in Bot.PARKED_ASSETS, asset
    # Reachable by directive, not by edge.
    assert "NATURALGAS" not in Bot.PARKED_ASSETS


def test_every_parked_asset_carries_its_reason():
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    for asset, why in Bot.PARKED_ASSETS.items():
        assert why and len(why) > 20, asset


def test_the_funded_list_matches_the_research_record():
    """Two places name the three, so they must agree or one is a lie."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    assert set(Bot.FUNDED_ASSETS) == fc.funded_assets()


def test_the_gas_reversals_are_all_on_the_record():
    """Gas has been decided three times in seven weeks: parked on edge
    (09-22), un-parked for the record (10-21), re-parked on cost and
    un-parked again by directive (both 2026-11-09).

    A reader who sees only the current state cannot tell a considered
    trade-off from an oversight. So every reversal stays in the source WITH
    the numbers that argued the other way - which is the difference between
    a decision and a preference.
    """
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    block = src.split("PARKED 2026-11-09 on cost")[0][-2600:]
    assert "UN-PARKED 2026-10-21" in block
    assert "0.73-0.75%" in block and "0.22%" in block
    assert "UNPARKED IS NOT FUNDED" in block

    import candle_archive

    assert "NATURALGAS" in candle_archive.ASSETS      # tape still accumulates


# ============================================ the plan that moves capital
def _book(tmp_path: Path, name: str, strategies: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"strategies": strategies}), encoding="utf-8")
    return path


def test_a_funded_module_is_activated_and_narrowed(tmp_path):
    import fund_cells

    book = _book(tmp_path, "strategy_portfolio.json", {
        "strat-macrobreakout-commodities-v1": {
            "status": "SHADOW_MODE",
            "supported_assets": ["NIFTY", "BANKNIFTY", "SENSEX"]},
    })
    row = fund_cells.plan_for(book)[0]
    assert row["action"] == "FUND"
    assert row["status_to"] == "ACTIVE"
    assert row["assets_to"] == ["NIFTY", "SENSEX"]


def test_a_strategy_that_would_reach_a_funded_asset_is_archived(tmp_path):
    """EventRider is scoped to GOLDM, which is funded, so parking the other
    three assets is not enough - it would still compete for gold, measuring
    -0.067 on it."""
    import fund_cells

    book = _book(tmp_path, "mcx_strategy_portfolio.json", {
        "strat-eventrider-mcx-v1": {
            "status": "ACTIVE",
            "supported_assets": ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]},
    })
    row = fund_cells.plan_for(book)[0]
    assert row["action"] == "ARCHIVE"
    assert "-0.067" in row["why"]


def test_a_strategy_scoped_only_to_parked_assets_is_left_alone(tmp_path):
    """Already inert. Changing its record would be churn, and churn in a
    portfolio book is how a decision becomes unreadable."""
    import fund_cells

    book = _book(tmp_path, "mcx_strategy_portfolio.json", {
        "strat-rangefade-mcx-v1": {
            "status": "ACTIVE", "supported_assets": ["NATURALGAS"]},
    })
    row = fund_cells.plan_for(book)[0]
    assert row["action"] == "leave"
    assert "already inert" in row["why"]


def test_a_scope_is_never_narrowed_to_nothing(tmp_path):
    """`_strategy_covers` fails OPEN on an empty supported_assets - a missing
    restriction means no restriction - so an empty scope would silently let a
    strategy trade the whole universe."""
    import fund_cells

    book = _book(tmp_path, "strategy_portfolio.json", {
        "whatever-v1": {"status": "ACTIVE", "supported_assets": ["BANKNIFTY"]},
    })
    for row in fund_cells.plan_for(book):
        assert row["assets_to"]


def test_the_plan_is_a_dry_run_unless_asked(tmp_path, monkeypatch, capsys):
    import fund_cells

    monkeypatch.setattr(sys, "argv", ["fund_cells.py"])
    monkeypatch.setattr(fund_cells, "book_paths", lambda: [])
    fund_cells.main()
    assert "dry run" in capsys.readouterr().out


def test_it_refuses_to_write_while_hokage_is_running(tmp_path, monkeypatch,
                                                     capsys):
    """A RUNNING HOKAGE OVERWRITES THE PORTFOLIO JSON FROM MEMORY. He holds
    the book in process and writes it back, so an edit made while he is up
    disappears at the next save with nothing logged."""
    import fund_cells

    book = _book(tmp_path, "strategy_portfolio.json", {
        "strat-macrobreakout-commodities-v1": {
            "status": "SHADOW_MODE", "supported_assets": ["NIFTY", "SENSEX"]},
    })
    before = book.read_text(encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["fund_cells.py", "--apply"])
    monkeypatch.setattr(fund_cells, "book_paths", lambda: [book])
    monkeypatch.setattr(fund_cells, "hokage_is_running", lambda: True)

    assert fund_cells.main() == 1
    assert "REFUSING TO WRITE" in capsys.readouterr().out
    assert book.read_text(encoding="utf-8") == before


def test_an_unanswerable_running_check_blocks_the_write(monkeypatch):
    """Unknown counts as RUNNING. The dangerous direction is writing into a
    race, so a check that cannot answer must block."""
    import fund_cells

    def boom(*a, **k):
        raise OSError("no powershell here")

    monkeypatch.setattr("subprocess.run", boom)
    assert fund_cells.hokage_is_running() is True


def test_applying_backs_the_books_up_first(tmp_path, monkeypatch, capsys):
    """The brain backup task is still not registered, which makes this the
    only copy that will exist if the rewrite is wrong."""
    import fund_cells

    book = _book(tmp_path, "strategy_portfolio.json", {
        "strat-sessionshift-mcx-v1": {
            "status": "ACTIVE", "supported_assets": ["GOLDM", "SILVERM"]},
    })
    monkeypatch.setattr(sys, "argv", ["fund_cells.py", "--apply"])
    monkeypatch.setattr(fund_cells, "book_paths", lambda: [book])
    monkeypatch.setattr(fund_cells, "hokage_is_running", lambda: False)

    assert fund_cells.main() == 0
    copies = list(tmp_path.glob("*.before-funding-*"))
    assert len(copies) == 1
    assert json.loads(copies[0].read_text(encoding="utf-8"))[
        "strategies"]["strat-sessionshift-mcx-v1"]["supported_assets"] == [
        "GOLDM", "SILVERM"]

    after = json.loads(book.read_text(encoding="utf-8"))["strategies"][
        "strat-sessionshift-mcx-v1"]
    assert after["supported_assets"] == ["GOLDM"]
    assert after["funding_decision"]["on"] == "2026-11-09"
