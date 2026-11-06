"""The first version of this experiment ran eleven days and was never read.

That is the actual finding of 2026-11-05: `signal_archive` recorded the mirror
faithfully from 2026-10-26 and no tool in the repo ever opened the table to
ask what it showed. `mirror_lab` was written to close that, and could still
only score DIRECTION on the underlying - where a mirror's edge is exactly
minus its original's, so the flip creates no information at all.

Since 2026-11-06 the losing side gets a premium path beside the winner's, on
the same tick, which is the only place the real question lives: both sides BUY
options, so a mirror wins where its original was wrong about DIRECTION and
loses anyway where it was wrong about MOVEMENT.

THESE TESTS ARE ABOUT THE READING, NOT THE ANSWER. The pairs table will be
empty for days. What has to hold from the start is that an empty archive says
so out loud rather than printing nothing, that the two sides are never crossed
over, that a window is one position's and not two merged, and that a missing
number stays missing instead of becoming a zero that reads as "flat".
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "mirror_lab", ROOT / "tools" / "research" / "mirror_lab.py"
)
ml = importlib.util.module_from_spec(_spec)
sys.modules["mirror_lab"] = ml
_spec.loader.exec_module(ml)

#: The real 16:15 gas pair of 2026-11-06.
HELD = "NATURALGAS26NOV285CE"
MIRROR = "NATURALGAS26NOV285PE"
DAY = "2026-11-06"


@pytest.fixture
def con(tmp_path):
    db = sqlite3.connect(tmp_path / "candles.db")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE mirror_marks (
        symbol TEXT, observed_at TEXT, day TEXT, premium REAL, entry REAL,
        held_symbol TEXT, held_premium REAL, held_entry REAL,
        module_id TEXT, decision_id TEXT, scanned_at TEXT,
        PRIMARY KEY (held_symbol, symbol, observed_at));
    """)
    return db


def _mark(con, minute, mirror_prem, held_prem, held=HELD, mirror=MIRROR,
          day=DAY, mirror_entry=16.00, held_entry=13.90):
    con.execute(
        "INSERT INTO mirror_marks (symbol, observed_at, day, premium, entry,"
        " held_symbol, held_premium, held_entry, module_id) VALUES"
        " (?,?,?,?,?,?,?,?,?)",
        (mirror, f"{day}T16:{minute:02d}:00+05:30", day, mirror_prem,
         mirror_entry, held, held_prem, held_entry,
         "entry-faderange-mcx-v1"))
    con.commit()


# =========================================== an empty archive says so out loud
def test_an_empty_table_is_reported_not_skipped(con):
    """The whole defect being corrected: eleven days of silence read as
    nothing to see."""
    out = ml.report_pairs(con)
    assert "no paired path yet" in out
    assert "cannot be backfilled" in out


def test_an_archive_without_the_table_does_not_crash(tmp_path):
    """An older brain, read by a newer lab."""
    db = sqlite3.connect(tmp_path / "bare.db")
    db.row_factory = sqlite3.Row
    assert ml.pairs_scored(db) == []
    assert "no paired path yet" in ml.report_pairs(db)


# ================================================= the window is one position
def test_a_pair_is_scored_from_its_last_mark(con):
    """The real position's window: entry to where the ladder closed it."""
    _mark(con, 16, 16.00, 13.90)
    _mark(con, 31, 15.60, 14.40)
    _mark(con, 49, 15.10, 14.65)

    (p,) = ml.pairs_scored(con)
    assert p["marks"] == 3
    assert p["held_pct"] == pytest.approx(100 * (14.65 - 13.90) / 13.90, abs=1e-6)
    assert p["mirror_pct"] == pytest.approx(100 * (15.10 - 16.00) / 16.00, abs=1e-6)


def test_the_two_sides_are_never_crossed_over(con):
    """held_pct must come from the CALL that was bought and mirror_pct from
    the PUT that was not. Swapping them would invert the verdict."""
    _mark(con, 16, 15.10, 14.65)
    (p,) = ml.pairs_scored(con)
    assert p["held"] == HELD and p["mirror"] == MIRROR
    assert p["held_pct"] > 0 > p["mirror_pct"]


def test_each_position_is_its_own_pair(con):
    """Two gas trades in one day is the measured case - 10:30 and 16:15 on
    2026-11-06 - and merging them would average two different windows."""
    _mark(con, 31, 15.10, 14.65)
    _mark(con, 35, 15.25, 16.65, held="NATURALGAS26NOV280CE",
          mirror="NATURALGAS26NOV280PE", mirror_entry=15.25, held_entry=14.55)
    assert len(ml.pairs_scored(con)) == 2


def test_the_same_contract_on_another_day_is_another_pair(con):
    _mark(con, 31, 15.10, 14.65)
    _mark(con, 31, 12.00, 15.00, day="2026-11-09")
    assert {p["day"] for p in ml.pairs_scored(con)} == {DAY, "2026-11-09"}


def test_the_peak_of_each_side_is_reported(con):
    """What was ON THE TABLE for both. A mirror that peaked +20% and ended
    flat is a different finding from one that never moved."""
    _mark(con, 16, 16.00, 13.90)
    _mark(con, 20, 17.60, 14.20)
    _mark(con, 49, 15.10, 14.65)
    (p,) = ml.pairs_scored(con)
    assert p["mirror_peak_pct"] == pytest.approx(10.0, abs=1e-6)
    assert p["held_peak_pct"] == pytest.approx(100 * (14.65 - 13.90) / 13.90,
                                               abs=1e-6)


# ================================================ missing stays missing
def test_a_pair_with_no_held_premium_is_not_scored_as_flat(con):
    """A NULL held premium means it was not recorded. Treating it as 0.0 would
    print a 100% loss on the trade that actually paid."""
    con.execute(
        "INSERT INTO mirror_marks (symbol, observed_at, day, premium, entry,"
        " held_symbol, held_premium, held_entry) VALUES (?,?,?,?,?,?,?,?)",
        (MIRROR, f"{DAY}T16:16:00+05:30", DAY, 15.10, 16.00, HELD, None, 13.90))
    con.commit()
    (p,) = ml.pairs_scored(con)
    assert p["held_pct"] is None
    assert "    -" in ml.report_pairs(con)


def test_a_pair_with_no_entry_is_dropped_rather_than_divided_by(con):
    con.execute(
        "INSERT INTO mirror_marks (symbol, observed_at, day, premium, entry,"
        " held_symbol, held_premium, held_entry) VALUES (?,?,?,?,?,?,?,?)",
        (MIRROR, f"{DAY}T16:16:00+05:30", DAY, 15.10, None, HELD, 14.65, 13.90))
    con.commit()
    assert ml.pairs_scored(con) == []


def test_an_unscoreable_pair_is_left_out_of_the_mean(con):
    """One NULL must not make n wrong."""
    _mark(con, 16, 15.10, 14.65)
    con.execute(
        "INSERT INTO mirror_marks (symbol, observed_at, day, premium, entry,"
        " held_symbol, held_premium, held_entry) VALUES (?,?,?,?,?,?,?,?)",
        (MIRROR, f"{DAY}T16:16:00+05:30", DAY, 15.10, 16.00,
         "NATURALGAS26NOV280CE", None, 14.55))
    con.commit()
    assert len(ml.pairs_scored(con)) == 2
    assert "n=1" in ml.report_pairs(con)


# ================================================ the verdict is stated plainly
def test_the_report_says_which_direction_favours_the_arena(con):
    """A column of signed numbers with no stated sign convention is how a
    result gets read backwards."""
    _mark(con, 49, 15.10, 14.65)
    out = ml.report_pairs(con)
    assert "POSITIVE MEANS THE ARENA IS RIGHT" in out
    assert "both pay theta" in out


def test_the_report_carries_its_own_n(con):
    _mark(con, 49, 15.10, 14.65)
    assert "n=1" in ml.report_pairs(con)
