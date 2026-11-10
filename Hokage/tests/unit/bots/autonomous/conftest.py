"""Shared fixtures for the autonomous-bot tests.

WHY `seeded_brain` EXISTS. Several tests assert that chat answers name the two
paper leagues ("Index Dojo", "MCX Arena"). They used to pass by reading the
commander's REAL brain: `tests/conftest.py` points HOKAGE_BRAIN_ROOT at a temp
directory for the whole session, but `hokage_tools` computed
`ROOT / "hokage_brain"` for itself and so bypassed that sandbox completely.

They were accidental integration tests against live production data, and they
would have broken the moment his portfolio was empty — or the moment the brain
moved, which it did on 2026-10-09 when a 1.5 GB cloud-synced SQLite file was
relocated out of OneDrive. Seeding the balances here makes them a fact of the
test rather than a fact of whatever Hokage happens to be holding.
"""
from __future__ import annotations

import sqlite3

import pytest

from bots.autonomous import hokage_tools


@pytest.fixture
def seeded_brain(monkeypatch, tmp_path):
    """Both paper leagues, in this test's own sandbox database."""
    db = tmp_path / "hokage.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE portfolio (account_id TEXT, initial_balance REAL, "
        "cash REAL, realized_pnl REAL)"
    )
    conn.executemany("INSERT INTO portfolio VALUES (?,?,?,?)", [
        ("paper", 400000.0, 412500.0, 12500.0),       # -> "Index Dojo"
        ("paper_mcx", 400000.0, 398200.0, -1800.0),   # -> "MCX Arena"
    ])
    conn.execute(
        "CREATE TABLE positions (market TEXT, account_id TEXT, direction TEXT, "
        "quantity REAL, entry_price REAL, current_price REAL, "
        "unrealized_pnl REAL, realized_pnl REAL, opened_at TEXT, "
        # `charges` is part of the real schema (version 10, 2026-11-09). A
        # fixture that omits it tests a brain that no longer exists, and the
        # tools read it.
        "closed_at TEXT, status TEXT, charges REAL)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(hokage_tools, "DB_PATH", db)
    return db
