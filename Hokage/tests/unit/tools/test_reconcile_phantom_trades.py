"""The `trades` table claimed 101 open positions that were never positions.

Every row in it carried `strategy_name = "AutonomousExit"` and
`status = "OPEN"`, and the newest was 2026-08-17. AutonomousExit is the EXIT
writer, so these are closing legs filed as fresh entries; 85 of them landed on
2026-07-15 within seconds on one CRUDEOIL strike, alternating LONG and SHORT,
which is the reduce_only runaway where exits could open positions.

The real ledger is `positions` - 382 rows, all CLOSED, with prices and
realised P&L. Nothing was unaccounted for.

MARKING THEM CLOSED WOULD HAVE BEEN WORSE THAN LEAVING THEM. calibration_engine
selects `WHERE t.status = 'CLOSED'` and bins what it finds by the confidence
the strategy predicted, publishing forecast-versus-realised. With all 101 OPEN
that query matches nothing and it honestly returns empty; flipping them to
CLOSED would hand it 101 invented round trips and it would publish a
calibration curve computed from them. A number built from fabricated trades
cannot be told apart from a measured one.

So they are archived out, and an empty table says what is true: nothing was
recorded here.

These tests pin the three things that make that safe - the selection cannot
widen, the archive is complete before anything is deleted, and a mismatch
stops the delete.
"""
from __future__ import annotations

import ast
import gzip
import importlib.util
import json
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

# Same idiom as test_liveness_probe: tools/ops is not an importable package,
# and registering before exec_module keeps annotation resolution working.
_spec = importlib.util.spec_from_file_location(
    "reconcile_phantom_trades", ROOT / "tools" / "ops" / "reconcile_phantom_trades.py"
)
tool = importlib.util.module_from_spec(_spec)
sys.modules["reconcile_phantom_trades"] = tool
_spec.loader.exec_module(tool)

TRADES_DDL = """
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY, proposal_id TEXT, market TEXT, direction TEXT,
    quantity REAL, entry_price REAL, simulated_value REAL, mode TEXT,
    status TEXT, strategy_name TEXT, sources_cited TEXT, executed_at TEXT,
    playbook_id TEXT, failure_reason TEXT, volatility_regime TEXT
);
"""
POSITIONS_DDL = "CREATE TABLE positions (position_id TEXT PRIMARY KEY, status TEXT);"


def _row(trade_id, strategy, status, executed_at="2026-07-15T13:56:37+00:00"):
    return (
        trade_id, "prop-1", "CRUDEOIL26JUL7750CE", "LONG", 100.0, 67.2, 6720.0,
        "PAPER", status, strategy, "", executed_at, None, None, None,
    )


@pytest.fixture
def db(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    path = tmp_path / "hokage.db"
    con = sqlite3.connect(path)
    con.executescript(TRADES_DDL + POSITIONS_DDL)
    con.executemany(
        "INSERT INTO trades VALUES (" + ",".join("?" * 15) + ");",
        [
            _row("phantom-1", "AutonomousExit", "OPEN"),
            _row("phantom-2", "AutonomousExit", "OPEN", "2026-08-17T09:50:40+00:00"),
            # A genuine entry. If one ever lands in this table, emptying it
            # would destroy the only record of a real trade.
            _row("real-entry", "SessionShift", "OPEN"),
            # An already-closed exit leg: not what this tool is for.
            _row("closed-leg", "AutonomousExit", "CLOSED"),
        ],
    )
    con.execute("INSERT INTO positions VALUES ('p1', 'CLOSED');")
    con.commit()
    con.close()

    monkeypatch.setattr(tool, "DB", path)
    monkeypatch.setattr(tool, "ARCHIVE_DIR", tmp_path / "hokage_brain_archive")
    return path


def _ids(path: pathlib.Path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT trade_id FROM trades;")}
    finally:
        con.close()


# -------------------------------------------------- the selection cannot widen
def test_only_open_exit_legs_are_selected(db):
    con = sqlite3.connect(db)
    try:
        assert {r["trade_id"] for r in tool._rows(con)} == {"phantom-1", "phantom-2"}
    finally:
        con.close()


def test_a_genuine_entry_in_this_table_is_never_touched(db):
    """The tool empties the table in practice only because every row happens to
    be a phantom. It must stay scoped to the exit writer regardless."""
    con = sqlite3.connect(db)
    try:
        tool.reconcile(con)
    finally:
        con.close()
    assert "real-entry" in _ids(db)


def test_an_already_closed_exit_leg_is_left_alone(db):
    con = sqlite3.connect(db)
    try:
        tool.reconcile(con)
    finally:
        con.close()
    assert "closed-leg" in _ids(db)


def test_the_scope_is_the_exit_writers_real_label():
    """A cross-file contract. If the exit writer is renamed in the bot and not
    here, this tool silently selects nothing and reports a clean ledger."""
    src = pathlib.Path("src/bots/autonomous/autonomous_bot.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    labels = {
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "strategy_id" and isinstance(kw.value, ast.Constant)
    }
    assert tool.EXIT_WRITER in labels, (
        f"{tool.EXIT_WRITER!r} is no longer a strategy_id the bot writes; "
        f"found {labels}"
    )


# ------------------------------------------- archive before anything is deleted
def test_every_selected_row_is_archived(db):
    con = sqlite3.connect(db)
    try:
        assert tool.reconcile(con) == 0
    finally:
        con.close()

    archives = list((tool.ARCHIVE_DIR).glob("trades_phantom_exit_legs_*.jsonl.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt", encoding="utf-8") as fh:
        lines = [json.loads(l) for l in fh]
    header, rows = lines[0], lines[1:]
    assert {r["trade_id"] for r in rows} == {"phantom-1", "phantom-2"}
    for r in rows:
        assert r["entry_price"] == 67.2
        assert r["market"] == "CRUDEOIL26JUL7750CE"
    assert header["_table"] == "trades"
    assert "CREATE TABLE trades" in header["_schema"]
    assert "trade_id" in header["_columns"]


def test_the_archive_can_be_read_without_this_repo(db):
    """A schema-less dump of 101 rows is a puzzle in two years. The header
    carries the DDL and the column order."""
    con = sqlite3.connect(db)
    try:
        tool.reconcile(con)
    finally:
        con.close()
    archive = next((tool.ARCHIVE_DIR).glob("*.jsonl.gz"))
    with gzip.open(archive, "rt", encoding="utf-8") as fh:
        header = json.loads(fh.readline())
    assert header["_schema"]
    assert header["_reason"]
    assert header["_archived_at"]


def test_the_rows_are_gone_afterwards(db):
    con = sqlite3.connect(db)
    try:
        tool.reconcile(con)
    finally:
        con.close()
    assert _ids(db) == {"real-entry", "closed-leg"}


def test_reconciling_twice_is_harmless(db):
    for _ in range(2):
        con = sqlite3.connect(db)
        try:
            tool.reconcile(con)
        finally:
            con.close()
    assert _ids(db) == {"real-entry", "closed-leg"}


# ------------------------------------------------ a bad archive stops the delete
def test_nothing_is_deleted_if_the_archive_is_short(db, monkeypatch):
    """THE RAIL. An archive that does not hold every row must leave the
    database exactly as it was - a half-written archive plus a completed
    delete is unrecoverable."""
    real_open = gzip.open

    def truncating_open(path, mode="rb", **kw):
        if "w" in mode:
            class _Swallow:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    # Leave a valid but EMPTY archive behind.
                    with real_open(path, "wt", encoding="utf-8") as fh:
                        fh.write("")
                    return False

                def write(self_inner, _):
                    return None

            return _Swallow()
        return real_open(path, mode, **kw)

    monkeypatch.setattr(tool.gzip, "open", truncating_open)

    before = _ids(db)
    con = sqlite3.connect(db)
    try:
        assert tool.reconcile(con) == 1
    finally:
        con.close()
    assert _ids(db) == before, "rows were deleted despite an incomplete archive"


# --------------------------------------------------------- report changes nothing
def test_report_opens_the_database_read_only(db, monkeypatch, capsys):
    """A measuring run must not be able to change anything, including by taking
    a write lock while Hokage is running."""
    monkeypatch.setattr("sys.argv", ["x", "--report"])
    before = _ids(db)
    assert tool.main() == 0
    assert _ids(db) == before
    out = capsys.readouterr().out
    assert "phantom exit legs   2" in out
    assert "positions holds 1 rows" in out


def test_report_names_the_real_ledger(db, monkeypatch, capsys):
    """Whoever runs this needs to see that the trades are accounted for
    somewhere, or an empty table looks like data loss."""
    monkeypatch.setattr("sys.argv", ["x", "--report"])
    tool.main()
    assert "the real ledger" in capsys.readouterr().out
