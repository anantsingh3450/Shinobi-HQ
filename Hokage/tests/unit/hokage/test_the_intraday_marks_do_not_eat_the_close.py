"""The 15-minute recorder was writing into a table keyed by the DAY.

Shipped 2026-11-12, caught 2026-11-13 by reading its own output instead of
trusting that it ran. `option_chain`'s primary key is
(symbol, day, expiry, strike, option_type) — one row per contract per day,
which is exactly right for a once-a-day close and exactly wrong for a path.
Two silent failures at once, both visible in the tape:

    09:03   336 rows archived
    09:18   168 rows archived     (the index segment opening)
    09:49    20 rows archived
    10:34     8
    10:50     4
    11:20    16                   <- only strikes the band had not seen

  1. THE PATH WAS DISCARDED. Every mark after a contract's first was
     INSERT OR IGNOREd. Twelve captures produced one snapshot - the thing
     the recorder already had.
  2. THE CLOSE WAS BLOCKED. The 09:03 row owns the key, so the 23:40 archive
     could not write, and `closing_snapshots` - which keeps only rows taken
     after the session ended - would have found NOTHING usable for
     2026-11-13. A day's premium that is not written down that day cannot be
     fetched back, so this quietly destroys the corpus it was built to
     enrich.

AND THE DAY GRAIN IS LOAD-BEARING. `theta_lab` joins `option_chain` to
itself across days on (symbol, expiry, strike, option_type). A second row for
the same contract on the same day multiplies that day's pairs, so "just add
captured_at to the key" would have inflated every decay estimate in the lab
without erroring once. Marks get their own table.
"""
from __future__ import annotations

import ast
import datetime as dt
import inspect
import textwrap
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import option_archive as oa

IST = ZoneInfo("Asia/Kolkata")
DAY = dt.date(2026, 11, 13)
NEAR = dt.date(2026, 11, 26)
FAR = dt.date(2026, 12, 29)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return oa


def _row(price=14.2, strike=315.0, option_type="CE", symbol="NATURALGAS",
         expiry=NEAR):
    return {"symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "last_price": price,
            "oi": 1000.0, "volume": 50.0, "spot": 314.8}


def _at(hour, minute=0):
    return dt.datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=IST)


# =================================================== the path is kept
def test_every_capture_of_the_same_contract_is_kept(archive):
    """FAILURE 1. Three marks of one contract are three rows, because the
    premium at 09:03 and the premium at 11:20 are different facts."""
    for hour, price in ((9, 14.2), (10, 13.4), (11, 12.1)):
        archive.mark([_row(price=price)], _at(hour))

    path = archive.marks(symbol="NATURALGAS")
    assert [r["last_price"] for r in path] == [14.2, 13.4, 12.1]
    assert len({r["captured_at"] for r in path}) == 3


def test_a_mark_never_touches_the_daily_book(archive):
    archive.mark([_row()], _at(9))
    assert archive.closing_snapshots() == []
    with archive.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM option_chain").fetchone()[0] == 0


def test_the_same_capture_recorded_twice_stores_one_row(archive):
    """A retry inside one tick is one mark, not two."""
    for _ in range(3):
        archive.mark([_row()], _at(9))
    assert len(archive.marks()) == 1


# =============================================== the close still lands
def test_a_close_lands_even_when_an_intraday_mark_holds_the_key(archive):
    """FAILURE 2, and the self-healing part. A Hokage carrying the broken
    build keeps writing marks into the daily book until the commander
    restarts him, which is his call. The close must still get in."""
    archive.remember([_row(price=14.2)], _at(9, 3))      # the broken writer
    assert archive.closing_snapshots() == []

    archive.remember([_row(price=11.0)], _at(23, 40))    # tonight's archive

    closes = archive.closing_snapshots()
    assert len(closes) == 1
    assert closes[0]["last_price"] == pytest.approx(11.0)


def test_the_evicted_mark_is_moved_not_deleted(archive):
    """It belonged in the marks table; the eviction puts it there."""
    archive.remember([_row(price=14.2)], _at(9, 3))
    archive.remember([_row(price=11.0)], _at(23, 40))

    moved = archive.marks()
    assert len(moved) == 1
    assert moved[0]["last_price"] == pytest.approx(14.2)
    assert moved[0]["captured_at"].startswith("2026-11-13T09:03")


def test_a_second_close_never_overwrites_the_first(archive):
    """NOTHING IS EVER OVERWRITTEN is the rule the whole archive rests on.
    Only a PRE-close row may be evicted, and only by a genuine close."""
    archive.remember([_row(price=11.0)], _at(23, 40))
    archive.remember([_row(price=99.0)], _at(23, 50))

    closes = archive.closing_snapshots()
    assert len(closes) == 1
    assert closes[0]["last_price"] == pytest.approx(11.0)
    assert archive.marks() == []


def test_an_intraday_write_never_evicts_anything(archive):
    """Eviction is a privilege of the close. Were it not, the 09:03 mark
    would evict the 09:00 one and the day grain would be the LAST mark."""
    archive.remember([_row(price=14.2)], _at(9, 3))
    archive.remember([_row(price=13.1)], _at(10, 34))

    with archive.connect() as conn:
        rows = conn.execute(
            "SELECT captured_at, last_price FROM option_chain").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == pytest.approx(14.2)


def test_the_daily_book_keeps_one_row_per_contract_per_day(archive):
    """What theta_lab's self-join depends on. A second row for a contract on
    one day multiplies that day's pairs and inflates every decay estimate."""
    for hour in range(9, 16):
        archive.remember([_row(price=14.0 - hour / 10)], _at(hour))
        archive.mark([_row(price=14.0 - hour / 10)], _at(hour))

    with archive.connect() as conn:
        worst = conn.execute(
            "SELECT MAX(n) FROM (SELECT COUNT(*) n FROM option_chain "
            "GROUP BY symbol, day, expiry, strike, option_type)").fetchone()[0]
    assert worst == 1
    assert len(archive.marks()) == 7


# ================================================ what a mark refuses
def test_only_the_nearest_expiry_is_marked(archive):
    """A full sweep is ~500 contracts; at one capture per 15-minute tick
    across the MCX evening that is ~29,000 rows a day. The far month's
    intraday path is the part worth giving up - the close still has it."""
    archive.mark([_row(expiry=NEAR), _row(expiry=FAR, price=30.0)], _at(10))

    kept = archive.marks()
    assert [r["expiry"] for r in kept] == [NEAR.isoformat()]


def test_the_nearest_expiry_is_decided_per_underlying(archive):
    """GOLDM's near month is not NIFTY's. One global minimum would silently
    drop every contract of whichever underlying expires later."""
    archive.mark([_row(symbol="NATURALGAS", expiry=NEAR),
                  _row(symbol="GOLDM", expiry=FAR, strike=138500.0)], _at(10))
    assert {r["symbol"] for r in archive.marks()} == {"NATURALGAS", "GOLDM"}


def test_a_mark_with_no_price_is_dropped_not_stored_as_zero(archive):
    row = _row()
    row["last_price"] = None
    archive.mark([row], _at(10))
    assert archive.marks() == []


def test_a_mark_on_a_day_the_market_was_shut_is_refused(archive):
    """Same guard as the close. A quote coming back is not evidence the
    market was open - on 2026-10-20 the broker answered every one of them
    with Monday's last print."""
    shut = dt.datetime(2026, 10, 20, 11, 0, tzinfo=IST)
    archive.mark([_row(symbol="NIFTY", strike=22900.0)], shut)
    assert archive.marks() == []


# ====================================== the recorder writes to the right one
def test_the_intraday_recorder_calls_mark_and_not_remember():
    """The bug in one line. Asked of the AST, because this module's own
    prose names `remember` and a text search has fired on explanatory
    comments three times this month."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "mark" in called
    assert "remember" not in called, (
        "the daily book is keyed by the day - an intraday writer in it "
        "throws the path away AND blocks that day's close")


def test_the_marks_coverage_reports_the_file_size(archive):
    """An intraday corpus is the shape of thing that took hokage.db to
    1.5 GB. Growth that is not printed is growth nobody reads."""
    archive.mark([_row()], _at(10))
    cover = archive.marks_coverage()
    assert cover["rows"] == 1
    assert cover["captures"] == 1
    assert cover["db_mb"] >= 0
