"""The spread was not being written down, and it cannot be recovered later.

2026-11-09, Phase 1. The question was what a round trip costs, because the
ledger says profit factor 1.04 and the best cell measures an edge worth about
1.6% of premium - two numbers that only mean something next to each other.

Nothing in Hokage knew what a trade costs:

  * `apply_trade` moves cash by price difference x quantity. No charges are
    deducted anywhere, so every P&L figure in the system is GROSS.
  * The tax ledger stopped writing on 2026-08-17, recorded 0.0144% of traded
    value, and denominated Indian index options in USD.
  * This table stored `last_price` and no depth - and `last_price` is where
    the option last traded, which says nothing about what getting in and out
    would cost right now.

An option's book is gone the moment it stops being quoted: the contract
delists and the number never existed anywhere. Same lesson as the candles,
the VIX and the chain itself, for a fourth time - the only corpus that can
exist is the one that starts being written down.

NULL IS NOT ZERO HERE EITHER. A missing capture and a genuine absence of bids
are different facts, and a zero bid read as a price would make every spread
look like free money.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "research"))

from hokage.memory import option_archive as oa  # noqa: E402


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return oa


def _row(**over):
    row = {"symbol": "NIFTY", "expiry": "2026-11-26", "strike": 24900.0,
           "option_type": "CE", "last_price": 276.5, "spot": 24910.0,
           "bid": 276.10, "ask": 276.95}
    row.update(over)
    return row


# ================================================== the columns are there
def test_the_table_has_a_bid_and_an_ask(archive):
    con = archive.connect()
    cols = {r[1] for r in con.execute("PRAGMA table_info(option_chain)")}
    con.close()
    assert "bid" in cols
    assert "ask" in cols


def test_an_existing_table_gains_the_columns(tmp_path, monkeypatch):
    """CREATE TABLE IF NOT EXISTS does NOTHING to a table already there. The
    live archive had 2,868 rows before this shipped; without an explicit
    migration the columns would silently never appear and every row written
    from then on would be missing the number this was built for."""
    import sqlite3

    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    path = oa.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE option_chain (symbol TEXT NOT NULL, day TEXT NOT NULL, "
        "expiry TEXT NOT NULL, strike REAL NOT NULL, option_type TEXT NOT NULL, "
        "captured_at TEXT NOT NULL, last_price REAL NOT NULL, oi REAL, "
        "volume REAL, spot REAL, PRIMARY KEY (symbol, day, expiry, strike, "
        "option_type))")
    old.commit()
    old.close()

    con = oa.connect()
    cols = {r[1] for r in con.execute("PRAGMA table_info(option_chain)")}
    con.close()
    assert "bid" in cols and "ask" in cols


def test_the_migration_is_idempotent(archive):
    """connect() runs on every call. Adding a column twice is an error."""
    for _ in range(3):
        con = archive.connect()
        con.close()


# ============================================== what gets stored, and what not
def test_a_quoted_book_is_written(archive, monkeypatch):
    import datetime as dt

    monkeypatch.setattr(archive, "market_was_open", lambda *a: True)
    assert archive.remember([_row()], dt.datetime(2026, 11, 9, 16, 0)) == 1
    con = archive.connect()
    bid, ask = con.execute("SELECT bid, ask FROM option_chain").fetchone()
    con.close()
    assert bid == pytest.approx(276.10)
    assert ask == pytest.approx(276.95)


def test_a_missing_book_is_null_not_zero(archive, monkeypatch):
    """A contract we quoted but whose depth came back empty has NO bid. Zero
    would be a price, and a price of zero is a free option."""
    import datetime as dt

    monkeypatch.setattr(archive, "market_was_open", lambda *a: True)
    archive.remember([_row(bid=None, ask=None)], dt.datetime(2026, 11, 9, 16, 0))
    con = archive.connect()
    bid, ask = con.execute("SELECT bid, ask FROM option_chain").fetchone()
    con.close()
    assert bid is None
    assert ask is None


def test_a_row_still_lands_without_a_book(archive, monkeypatch):
    """Depth is an addition, not a new requirement. A row that would have been
    archived before this change must still be archived."""
    import datetime as dt

    monkeypatch.setattr(archive, "market_was_open", lambda *a: True)
    row = _row()
    del row["bid"]
    del row["ask"]
    assert archive.remember([row], dt.datetime(2026, 11, 9, 16, 0)) == 1


def test_a_zero_premium_is_still_refused(archive, monkeypatch):
    """The existing rule, unchanged: a zero last_price is a bad print."""
    import datetime as dt

    monkeypatch.setattr(archive, "market_was_open", lambda *a: True)
    assert archive.remember([_row(last_price=0.0)],
                            dt.datetime(2026, 11, 9, 16, 0)) == 0


# ===================================================== the fetcher asks for it
def test_the_fetcher_reads_the_depth_book():
    src = (ROOT / "tools" / "ops" / "archive_options.py").read_text(encoding="utf-8")
    assert 'q.get("depth")' in src
    assert '"bid": buy.get("price")' in src
    assert '"ask": sell.get("price")' in src


# ============================================ the lab that reads it is honest
def test_the_spread_lab_refuses_a_one_sided_book():
    """Outside market hours the depth is empty. That is absence of data, and
    reporting it as a zero spread would be the cheapest possible lie about
    cost."""
    src = (ROOT / "tools" / "research" / "spread_lab.py").read_text(encoding="utf-8")
    assert "if bid <= 0 or ask <= 0:" in src
    assert "NO TWO-SIDED BOOK" in src
    flat = " ".join(src.split())
    assert "absence of data and not a zero spread" in flat


def test_the_spread_lab_says_what_it_leaves_out():
    """Brokerage and statutory charges ARE now included, from
    `bots.execution.charges` with rates quoted off the broker's own page. What
    is still missing is theta over the holding period, and the lab has to keep
    saying so - a cost figure that silently omits a term gets quoted as if it
    were complete.

    AMENDED 2026-11-09, LATER THE SAME DAY. This used to require the words
    "not yet measurable", and then `theta_lab` measured it. A test that pins a
    true sentence will eventually pin a false one: the claim that has to
    survive is "not included here", not "cannot be known". So the rail now
    requires the omission to be NAMED and POINTED AT, which is the part that
    stops a partial total being quoted as a whole one.
    """
    src = (ROOT / "tools" / "research" / "spread_lab.py").read_text(encoding="utf-8")
    flat = " ".join(src.split())
    assert "zerodha.com/charges" in flat
    assert "Theta over the hold is NOT included" in flat
    assert "theta_lab.py" in flat
    assert "these totals are" in flat.lower()
    assert "not yet measurable" not in flat, (
        "the lab still claims decay cannot be measured; theta_lab measures it")


def test_the_transfer_rate_is_labelled_an_assumption():
    """3.31% of premium per ATR came from n=15 with an unexplained intercept.
    Every number derived from it inherits that, and the label is what keeps
    the inheritance visible."""
    src = (ROOT / "tools" / "research" / "spread_lab.py").read_text(encoding="utf-8")
    block = src.split("PCT_PREMIUM_PER_ATR")[0][-400:]
    assert "n=15" in block or "assumption" in block.lower()
