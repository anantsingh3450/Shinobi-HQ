"""The daily caps must survive a restart, or they are not caps.

2026-08-18: StrategyEngine's caps (3 entries per symbol, 5 unique symbols per
day) live in memory. `load_daily_trades_from_db` exists to restore them at boot
and IS wired at autonomous_bot.py:286 — but it read the `trades` table, where:

  * the newest row was 2026-08-17, so today had no rows at all
  * `playbook_id` was NULL on every row
  * `strategy_name` read "AutonomousExit" on every row — the EXIT writer

so it matched no live playbook id and restored nothing, while logging success
either way. Hokage was restarted twice that day and the counters reset both
times, handing SessionShift a fresh allowance on a symbol it had already lost
on twice.

The entries are in `positions`, one row per opened position, carrying
`opened_at` and `playbook_id`. MCX positions had a NULL playbook_id because the
MCX order path never set it (the index path always did); that is fixed
alongside, and covered by test_mcx_daily_cap.py.
"""
from __future__ import annotations

import sqlite3

import pytest

from bots.strategy.strategy_engine import StrategyEngine


class _Engine:
    """Minimal stand-in for SqliteStorageEngine: only get_connection is used."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def get_connection(self):
        return self._conn


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE positions ("
        " position_id TEXT, account_id TEXT, market TEXT, opened_at TEXT,"
        " status TEXT, playbook_id TEXT, strategy_id TEXT)"
    )
    return conn


def _add(conn, market, opened_at, playbook_id, status="CLOSED", account="paper_mcx"):
    conn.execute(
        "INSERT INTO positions (position_id, account_id, market, opened_at, status,"
        " playbook_id, strategy_id) VALUES (?,?,?,?,?,?,?)",
        (market + opened_at, account, market, opened_at, status, playbook_id, "s1"),
    )


def test_the_exact_2026_08_18_evening_is_restored(db):
    """Three SILVERM entries that day. After recovery the fourth is refused."""
    _add(db, "SILVERM", "2026-08-18T11:30:12", "MCX_SessionShift")
    _add(db, "SILVERM", "2026-08-18T13:30:25", "MCX_SessionShift")
    _add(db, "SILVERM", "2026-08-18T14:10:00", "MCX_SessionShift")
    _add(db, "CRUDEOIL", "2026-08-18T10:45:44", "MCX_RangeFade")

    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")

    allowed, reason = engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")
    assert not allowed
    assert "re-entry cap" in reason
    # A different playbook is untouched by SessionShift's exhausted allowance.
    assert engine.is_entry_allowed("MCX_RangeFade", "CRUDEOIL", "2026-08-18")[0]


def test_yesterdays_entries_do_not_consume_todays_allowance(db):
    _add(db, "SILVERM", "2026-08-17T11:30:12", "MCX_SessionShift")
    _add(db, "SILVERM", "2026-08-17T13:30:25", "MCX_SessionShift")
    _add(db, "SILVERM", "2026-08-17T14:10:00", "MCX_SessionShift")

    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")

    assert engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")[0]


def test_a_closed_position_still_counts_as_an_entry(db):
    """The cap limits ENTRIES per day, not concurrent exposure. Three round
    trips on one symbol is exactly the churn it exists to stop, and every one
    of them is CLOSED by the time the next is considered."""
    for i, t in enumerate(("11:30:12", "13:30:25", "14:10:00")):
        _add(db, "SILVERM", f"2026-08-18T{t}", "MCX_SessionShift", status="CLOSED")

    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")

    assert not engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")[0]


def test_a_position_without_a_playbook_id_is_skipped_not_guessed(db):
    """An invented id would count against a bucket nothing enforces — it would
    look enforced and not be. A known gap is safer than a fake fill."""
    _add(db, "SILVERM", "2026-08-18T11:30:12", None)
    _add(db, "SILVERM", "2026-08-18T13:30:25", "MCX_SessionShift")

    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")

    # One counted, one skipped: two entries of the three remain available.
    assert engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")[0]
    engine.record_trade("MCX_SessionShift", "SILVERM", "2026-08-18")
    engine.record_trade("MCX_SessionShift", "SILVERM", "2026-08-18")
    assert not engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")[0]


def test_the_unique_asset_quota_is_restored_too(db):
    for market in ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM", "COPPER"):
        _add(db, market, "2026-08-18T11:00:00", "MCX_RangeFade")

    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")

    allowed, reason = engine.is_entry_allowed("MCX_RangeFade", "ZINC", "2026-08-18")
    assert not allowed
    assert "rotation quota" in reason


def test_both_leagues_recover_from_the_same_table(db):
    """The index path already wrote playbook_id; MCX now does too. One query
    must restore both, or a restart half-protects."""
    _add(db, "NIFTY", "2026-08-18T09:30:00", "HEURISTIC_NIFTY_STRATEGY", account="paper")
    _add(db, "SILVERM", "2026-08-18T11:30:12", "MCX_SessionShift")

    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=1)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")

    assert not engine.is_entry_allowed("HEURISTIC_NIFTY_STRATEGY", "NIFTY", "2026-08-18")[0]
    assert not engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")[0]


def test_a_broken_query_never_takes_the_boot_down(db):
    """Recovery runs during startup. It may fail to restore; it may not stop
    Hokage from starting."""
    db.execute("DROP TABLE positions")
    engine = StrategyEngine(max_unique_assets=5, max_entries_per_symbol=3)
    engine.load_daily_trades_from_db(_Engine(db), "2026-08-18")  # must not raise
    assert engine.is_entry_allowed("MCX_SessionShift", "SILVERM", "2026-08-18")[0]


def test_recovery_reads_positions_and_not_trades():
    """Guards the table name, which was the whole bug.

    Reading `trades` restored nothing while logging success — a silent
    no-op is the failure mode this must never return to.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(StrategyEngine.load_daily_trades_from_db)
    ))
    sql = " ".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ).upper()
    assert "FROM POSITIONS" in sql
    assert "FROM TRADES" not in sql
