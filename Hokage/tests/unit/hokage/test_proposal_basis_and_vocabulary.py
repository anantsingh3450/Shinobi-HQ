"""The measured proposals were invisible, unappliable, and silencing their own
successors.

Hokage's whole method is: measure, propose, let the commander decide. On
2026-10-16 the last inch of that was broken in three compounding ways, and
three real proposals had been sitting in the gap - a RangeFade knob from
08-26, a SessionShift window and a MeanReversion retirement from 09-22.

1. TWO WORDS FOR PENDING. `improvement_bot` writes "PENDING_APPROVAL";
   `sweep_lab` and `weekly_audit`, the two that produce proposals backed by an
   actual measurement, write "PENDING".

2. SO THEY WERE INVISIBLE. `hokage proposals` filtered on "PENDING_APPROVAL"
   and printed "No pending proposals" while all three sat in the table. There
   is no dashboard view of proposals, so that command was the only surface.

3. AND UNAPPLIABLE. `apply_improvement_proposal` returned False for any status
   that was not "PENDING_APPROVAL" - so had the commander found one and said
   yes, the apply path would have refused and logged that it was "already in
   PENDING status".

4. AND THEY BLOCKED THE FIX. `already_answered` suppresses a re-proposal while
   a PENDING row exists for the same change, which is right: a weekly job that
   re-asks an answered question teaches the commander to stop reading it. But
   all three were measured before the audit moved to full geometry with a
   per-cell stop and raised its bar from 2.0 to 3.16. One says in its own
   rationale that it used "the 1.25 ATR production stop" on GOLDM, which has
   run 3.0 ATR since 2026-08-13. A dead row measured on a retired basis was
   silencing the corrected measurement of the same question.

THE DOCTRINE WAS ALREADY HERE. evolution._same_geometry refuses to treat two
snapshots as consecutive evidence across a change of basis, because there is
no trend across a change of instrument. This applies the same rule to
proposals, and makes the same choice for rows that predate the field: an
unrecorded basis cannot be shown to match the current one, so it is stale.

Nothing rewrites a stored row. The three are the record of questions that were
genuinely asked and never answered.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bots.improvement.improvement_bot import ImprovementBot
from bots.strategy.portfolio import StrategyPortfolioManager
from hokage.memory.resolver import PathResolver
from hokage.research import proposals as pr

CURRENT = pr.stamp(3.16)
RETIRED = "holdout-split+stop1.25+bar2.00"


# ------------------------------------------------------------ one vocabulary
def test_both_spellings_of_pending_are_pending():
    assert pr.is_pending("PENDING")
    assert pr.is_pending("PENDING_APPROVAL")
    assert pr.is_pending("pending")
    assert pr.is_pending(" PENDING ")


def test_an_answered_proposal_is_not_pending():
    for status in ("REJECTED", "APPLIED", "", None, "SUPERSEDED"):
        assert not pr.is_pending(status)


def test_the_labs_and_the_bot_do_not_each_define_pending():
    """Two copies of "what counts as pending" drift, and the half that drifts
    is whichever one nobody ran that week. This file exists because they
    did."""
    import bots.improvement.improvement_bot as ib
    import hokage.router.command_router as cr

    for src in (Path(ib.__file__), Path(cr.__file__)):
        text = src.read_text(encoding="utf-8")
        assert '== "PENDING_APPROVAL"' not in text, (
            f"{src.name} still compares the status against one spelling"
        )


# ------------------------------------------------------- the basis stamp
def test_a_stamp_carries_the_basis_and_the_bar():
    basis, bar = pr.parse_stamp(pr.stamp(3.16))
    assert basis == pr.MEASUREMENT_BASIS
    assert bar == pytest.approx(3.16)


def test_an_unrecorded_basis_is_stale():
    """The same choice _same_geometry makes for snapshots written before its
    geometry field existed. Assuming a match is how a number from a retired
    instrument becomes current evidence."""
    assert pr.is_stale(None)
    assert pr.is_stale("")


def test_a_retired_basis_is_stale():
    assert pr.is_stale(RETIRED)
    assert "RETIRED" in pr.describe(RETIRED)


def test_the_current_basis_is_not_stale():
    assert not pr.is_stale(CURRENT)


def test_a_proposal_judged_at_an_easier_bar_is_stale():
    """A proposal is a claim that something clears the bar. When the bar
    rises, the claim has to be re-made - which is exactly what happened on
    10-14 when it went from 2.0 to 3.16 and both previously confirmed cells
    fell below it."""
    assert pr.is_stale(pr.stamp(2.00), 3.16)
    assert not pr.is_stale(pr.stamp(3.16), 3.16)
    assert not pr.is_stale(pr.stamp(3.90), 3.16), "a harder bar still clears"


def test_a_stamp_with_no_bar_is_stale_once_a_bar_is_demanded():
    assert pr.is_stale(pr.MEASUREMENT_BASIS, 3.16)
    assert not pr.is_stale(pr.MEASUREMENT_BASIS), "basis alone is fine with no bar"


def test_junk_never_reads_as_the_current_basis():
    for junk in ("+bar", "+barabc", "holdout-split+barNaN", "   "):
        assert pr.is_stale(junk), junk


def test_a_drift_proposal_is_not_staled_by_a_bar_it_never_claimed():
    """The improvement bot proposes from drift against a recorded baseline -
    no hold-out split, no production stop, no t. It never claimed to clear a
    bar, so a change of bar says nothing about it."""
    assert not pr.is_stale(pr.DRIFT_BASIS)
    assert not pr.is_stale(pr.DRIFT_BASIS, 3.16)
    assert "no t-statistic" in pr.describe(pr.DRIFT_BASIS)


def test_a_blank_basis_and_a_drift_basis_are_different_facts():
    """"Nobody recorded it" is not "this was never a lab measurement"."""
    assert pr.describe(None) != pr.describe(pr.DRIFT_BASIS)
    assert pr.is_stale(None) and not pr.is_stale(pr.DRIFT_BASIS)


def test_the_audit_builds_its_geometry_from_the_shared_basis():
    """weekly_audit.GEOMETRY is compared against stored snapshots by
    evolution._same_geometry, so a different value RESETS the retirement
    clock. Sharing the string must not have changed it."""
    import sys

    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import weekly_audit as wa

    assert wa.GEOMETRY == "holdout-split+stop-per-cell+target+tradedbars+bar3.16"
    assert wa.GEOMETRY.startswith(pr.MEASUREMENT_BASIS)
    assert not pr.is_stale(wa.GEOMETRY, wa.SHIP_BAR)


# ---------------------------------------------------------------- the ledger
def _bot(tmp_path: Path) -> ImprovementBot:
    resolver = PathResolver(tmp_path)
    return ImprovementBot(portfolio_manager=StrategyPortfolioManager(resolver),
                          resolver=resolver)


def _row(pid: str, status: str, basis: str | None) -> dict:
    return {
        "proposal_id": pid, "strategy_id": "entry-sessionshift-mcx-v1",
        "strategy_name": "SessionShift", "asset": "GOLDM",
        "timestamp": "2026-09-22T09:11:25+00:00", "action": "TUNE_PARAMETER",
        "previous_values": {"WINDOW_END_MIN": 630},
        "new_values": {"WINDOW_END_MIN": 570},
        "rationale": "measured with the 1.25 ATR production stop",
        "expected_improvement": 0.12, "status": status,
        "approving_commander": None, "applied_at": None,
        "actual_post_change_performance": None, "measured_geometry": basis,
    }


def _seed(tmp_path: Path, rows: list[dict]) -> ImprovementBot:
    bot = _bot(tmp_path)
    bot._proposals_file.parent.mkdir(parents=True, exist_ok=True)
    with bot._proposals_file.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return bot


def test_a_lab_written_proposal_is_visible_to_the_commander(tmp_path):
    """THE HEADLINE. `hokage proposals` answered "No pending proposals" with
    three in the table."""
    from hokage.router.command_router import CommandRouter

    bot = _seed(tmp_path, [_row("sweep-abc", "PENDING", CURRENT)])

    class _Orch:
        def get_improvement_proposals(self_inner):
            return bot.load_proposals()

    out = CommandRouter.handle_hokage_proposals(
        type("R", (), {"orchestrator": _Orch()})()
    )
    assert "sweep-abc" in out
    assert "No pending proposals" not in out


def test_a_stale_proposal_is_shown_as_stale(tmp_path):
    from hokage.router.command_router import CommandRouter

    bot = _seed(tmp_path, [_row("sweep-old", "PENDING", None)])

    class _Orch:
        def get_improvement_proposals(self_inner):
            return bot.load_proposals()

    out = CommandRouter.handle_hokage_proposals(
        type("R", (), {"orchestrator": _Orch()})()
    )
    assert "sweep-old" in out
    assert "STALE" in out
    assert "UNRECORDED" in out


def test_applying_a_proposal_measured_on_a_retired_basis_is_refused(tmp_path):
    """Refusing is the cheap error: re-running the lab produces a fresh
    proposal in minutes, while applying a knob justified by a retired
    measurement puts a number from the wrong instrument into production."""
    bot = _seed(tmp_path, [_row("sweep-old", "PENDING", RETIRED)])
    assert bot.apply_improvement_proposal("sweep-old", "Elder Anant") is False


def test_an_unstamped_proposal_is_refused_too(tmp_path):
    bot = _seed(tmp_path, [_row("sweep-blank", "PENDING", None)])
    assert bot.apply_improvement_proposal("sweep-blank", "Elder Anant") is False


def test_an_already_answered_proposal_is_still_refused(tmp_path):
    bot = _seed(tmp_path, [_row("sweep-done", "APPLIED", CURRENT)])
    assert bot.apply_improvement_proposal("sweep-done", "Elder Anant") is False


def test_applying_still_demands_a_commander_name(tmp_path):
    bot = _seed(tmp_path, [_row("sweep-ok", "PENDING", CURRENT)])
    with pytest.raises(ValueError):
        bot.apply_improvement_proposal("sweep-ok", "   ")


# --------------------------------------------------------------- persistence
def test_the_basis_survives_a_save(tmp_path):
    """_save_proposals_atomic is INSERT OR REPLACE over the whole row, so a
    column left out of it is silently stripped on the next save."""
    bot = _seed(tmp_path, [_row("sweep-ok", "PENDING", CURRENT)])
    loaded = bot.load_proposals()
    bot._save_proposals_atomic(loaded)
    assert bot.load_proposals()[0]["measured_geometry"] == CURRENT


def test_the_column_exists_after_migration(tmp_path):
    from shared.persistence.sqlite_engine import SqliteStorageEngine

    engine = SqliteStorageEngine(PathResolver(tmp_path))
    engine.run_migrations()
    conn = engine.get_connection()
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(improvement_proposals)")}
    assert "measured_geometry" in cols


def test_a_database_at_version_8_gains_the_column(tmp_path):
    """The real brain is a migrated database, not a fresh one."""
    from shared.persistence.sqlite_engine import SqliteStorageEngine

    engine = SqliteStorageEngine(PathResolver(tmp_path))
    engine.run_migrations()
    conn = engine.get_connection()
    # Put it back the way a version-8 brain looks.
    conn.execute("ALTER TABLE improvement_proposals "
                 "DROP COLUMN measured_geometry;")
    conn.execute("INSERT OR REPLACE INTO schema_version (version, migrated_at) "
                 "VALUES (8, '2026-10-01T00:00:00+00:00');")
    conn.commit()
    engine.close() if hasattr(engine, "close") else None

    engine2 = SqliteStorageEngine(PathResolver(tmp_path))
    engine2.run_migrations()
    cols = {r[1] for r in engine2.get_connection().execute(
        "PRAGMA table_info(improvement_proposals)")}
    assert "measured_geometry" in cols


def test_an_unmigrated_row_reads_as_unrecorded_rather_than_raising(tmp_path):
    """A brain that has not migrated yet must still load proposals."""
    from shared.persistence.sqlite_engine import SqliteStorageEngine

    engine = SqliteStorageEngine(PathResolver(tmp_path))
    engine.run_migrations()
    conn = engine.get_connection()
    conn.execute("ALTER TABLE improvement_proposals "
                 "DROP COLUMN measured_geometry;")
    conn.execute(
        "INSERT INTO improvement_proposals (proposal_id, strategy_id, "
        "strategy_name, asset, timestamp, action, previous_values, "
        "new_values, rationale, expected_improvement, status) "
        "VALUES ('x','s','S','GOLDM','2026-09-22','TUNE_PARAMETER','{}','{}',"
        "'r',0.0,'PENDING')")
    conn.commit()

    bot = _bot(tmp_path)
    rows = bot.load_proposals()
    assert rows and rows[0]["measured_geometry"] is None
    assert pr.is_stale(rows[0]["measured_geometry"])


# --------------------------------------------------- a dead row stops blocking
def test_a_stale_pending_row_no_longer_suppresses_a_fresh_measurement(tmp_path,
                                                                      monkeypatch):
    """THE WORST OF THE FOUR. The suppression rule is right - a weekly job must
    not re-ask an answered question - but a PENDING row measured on a retired
    basis is not a question waiting, it is a dead row, and it was silencing the
    corrected measurement of the same change."""
    import sys

    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import sweep_lab

    db = tmp_path / "hokage.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE improvement_proposals (proposal_id TEXT PRIMARY KEY, "
        "strategy_id TEXT, asset TEXT, new_values TEXT, status TEXT, "
        "measured_geometry TEXT)")
    want = json.dumps({"WINDOW_END_MIN": 570})
    conn.executemany(
        "INSERT INTO improvement_proposals VALUES (?,?,?,?,?,?)",
        [("old", "s1", "GOLDM", want, "PENDING", RETIRED),
         ("no", "s2", "SILVERM", want, "REJECTED", RETIRED),
         ("cur", "s3", "CRUDEOIL", want, "PENDING", pr.stamp(3.09))])
    conn.commit()
    conn.close()

    monkeypatch.setattr(sweep_lab, "DB", db)
    monkeypatch.setattr(sweep_lab, "ship_bar", lambda: 3.09)

    row = {"strategy_id": "s1", "asset": "GOLDM", "new": {"WINDOW_END_MIN": 570}}
    assert sweep_lab.already_answered(row) is None, (
        "a proposal measured on a retired basis must not block its own "
        "corrected re-measurement"
    )

    row["strategy_id"], row["asset"] = "s2", "SILVERM"
    assert sweep_lab.already_answered(row) == "REJECTED", (
        "a REJECTED proposal is the commander's answer, whatever the basis"
    )

    row["strategy_id"], row["asset"] = "s3", "CRUDEOIL"
    assert sweep_lab.already_answered(row) == "PENDING", (
        "a proposal on the CURRENT basis is a decision genuinely waiting"
    )


def test_sweep_lab_stamps_what_it_writes():
    import ast

    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "tools" / "research" / "sweep_lab.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "write_proposal")
    dumped = ast.dump(fn)
    assert "measured_geometry" in dumped
    assert "stamp" in dumped


def test_the_weekly_audit_stamps_its_retirements():
    import ast

    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "tools" / "research" / "weekly_audit.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_record_retirements")
    dumped = ast.dump(fn)
    assert "measured_geometry" in dumped
    assert "GEOMETRY" in dumped


# ------------------------------------- the brain migrates at Hokage's next boot
def test_a_lab_run_before_the_migration_writes_unstamped_and_says_so(
        tmp_path, monkeypatch, capsys):
    """Schema 9 arrives when Hokage next boots. A lab run before that must not
    crash, and must not pretend it stamped a basis it could not store. The row
    then reads as stale and cannot be applied, which is the safe direction -
    but the commander is told at write time rather than at the apply gate."""
    import sys

    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import sweep_lab

    db = tmp_path / "hokage.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE improvement_proposals (proposal_id TEXT PRIMARY KEY, "
        "strategy_id TEXT, strategy_name TEXT, asset TEXT, timestamp TEXT, "
        "action TEXT, previous_values TEXT, new_values TEXT, rationale TEXT, "
        "expected_improvement REAL, status TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(sweep_lab, "DB", db)
    monkeypatch.setattr(sweep_lab, "ship_bar", lambda: 3.09)
    pid = sweep_lab.write_proposal({
        "strategy_id": "s1", "strategy_name": "SessionShift", "asset": "GOLDM",
        "previous": {"WINDOW_END_MIN": 630}, "new": {"WINDOW_END_MIN": 570},
        "rationale": "r", "expected": 0.1,
    })
    assert "schema 8" in capsys.readouterr().out
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT status FROM improvement_proposals WHERE proposal_id=?",
        (pid,)).fetchone()[0] == "PENDING"
    conn.close()


def test_after_the_migration_the_sweep_stamps_the_row(tmp_path, monkeypatch):
    import sys

    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import sweep_lab

    db = tmp_path / "hokage.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE improvement_proposals (proposal_id TEXT PRIMARY KEY, "
        "strategy_id TEXT, strategy_name TEXT, asset TEXT, timestamp TEXT, "
        "action TEXT, previous_values TEXT, new_values TEXT, rationale TEXT, "
        "expected_improvement REAL, status TEXT, measured_geometry TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(sweep_lab, "DB", db)
    monkeypatch.setattr(sweep_lab, "ship_bar", lambda: 3.09)
    pid = sweep_lab.write_proposal({
        "strategy_id": "s1", "strategy_name": "SessionShift", "asset": "GOLDM",
        "previous": {"WINDOW_END_MIN": 630}, "new": {"WINDOW_END_MIN": 570},
        "rationale": "r", "expected": 0.1,
    })
    conn = sqlite3.connect(db)
    basis = conn.execute(
        "SELECT measured_geometry FROM improvement_proposals WHERE proposal_id=?",
        (pid,)).fetchone()[0]
    conn.close()
    assert basis == pr.stamp(3.09)
    assert not pr.is_stale(basis, 3.09)
