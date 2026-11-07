"""Reading the gate's refusals in premium, which has never been possible.

veto_lab answers in edge_atr and Hokage buys options. transfer_lab converted
the two (+3.31% of premium per 1.0 ATR, n=15), but a conversion is not a
measurement, and the gate could not be measured directly because a blocked
trade is never bought and nothing had ever priced one.

`shadow_marks` now records those contracts. THESE TESTS ARE ABOUT THE READING,
NOT THE ANSWER - the table will be empty for days. What has to hold from the
start is that an empty archive says so out loud rather than printing nothing,
that a slice describes the window it claims to (and not 29 or 61 minutes), that
a missing mark stays missing instead of becoming a zero that reads as "flat",
that the sign convention is stated, and that nothing is concluded under the
bar.
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
    "shadow_lab", ROOT / "tools" / "research" / "shadow_lab.py")
sl = importlib.util.module_from_spec(_spec)
sys.modules["shadow_lab"] = sl
_spec.loader.exec_module(sl)

#: The real refusal of 2026-11-06 19:15 on gas.
REFUSED = "NATURALGAS26NOV280PE"
ENTRY = 13.35
SCAN = "2026-11-06T19:15:10+05:30"
DAY = "2026-11-06"


@pytest.fixture
def con(tmp_path):
    db = sqlite3.connect(tmp_path / "candles.db")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE shadow_marks (
        symbol TEXT, observed_at TEXT, day TEXT, premium REAL, entry REAL,
        underlying TEXT, direction TEXT, blocked_by TEXT, module_id TEXT,
        decision_id TEXT, scanned_at TEXT,
        PRIMARY KEY (symbol, scanned_at, observed_at));
    """)
    return db


def _mark(con, minute, premium, symbol=REFUSED, scan=SCAN, entry=ENTRY,
          underlying="NATURALGAS", hour=19):
    con.execute(
        "INSERT INTO shadow_marks (symbol, observed_at, day, premium, entry,"
        " underlying, direction, blocked_by, scanned_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (symbol, f"{DAY}T{hour:02d}:{minute:02d}:10+05:30", DAY, premium, entry,
         underlying, "short", "Bias engine: underlying tape is MIXED.", scan))
    con.commit()


# =========================================== an empty archive says so out loud
def test_an_empty_table_is_reported_not_skipped(con):
    out = sl.report(con)
    assert "No refused trade has a priced path yet" in out
    assert "CANNOT BE BACKFILLED" in out


def test_an_archive_without_the_table_does_not_crash(tmp_path):
    db = sqlite3.connect(tmp_path / "bare.db")
    db.row_factory = sqlite3.Row
    assert sl.shadows(db) == []
    assert "CANNOT BE BACKFILLED" in sl.report(db)


def test_no_brain_at_all_is_reported_not_crashed():
    assert "CANNOT BE BACKFILLED" in sl.report(None)


# ====================================================== the slice is the window
def test_a_slice_takes_the_first_mark_at_or_after_its_offset(con):
    """A 29-minute mark must not answer for 30 minutes, nor a 61-minute one for
    60: that quietly shortens or lengthens the window the number describes."""
    _mark(con, 15, ENTRY)            # t = 0
    _mark(con, 44, 14.00)            # t = 29  -> too early for the 30m slice
    _mark(con, 46, 12.50)            # t = 31  -> this one answers
    (s,) = sl.shadows(con)
    assert s["pct_30"] == pytest.approx(100 * (12.50 - ENTRY) / ENTRY)


def test_a_horizon_with_no_mark_yet_stays_missing(con):
    """A path 30 minutes old has no 120-minute number, and a zero there would
    read as 'the refusal was flat'."""
    _mark(con, 15, ENTRY)
    _mark(con, 46, 12.50)
    (s,) = sl.shadows(con)
    assert s["pct_30"] is not None
    assert s["pct_60"] is None and s["pct_120"] is None
    assert "      -" in sl.report(con)


def test_every_horizon_is_filled_once_the_path_is_long_enough(con):
    _mark(con, 15, ENTRY)
    _mark(con, 46, 12.50)
    _mark(con, 16, 12.00, hour=20)
    _mark(con, 16, 11.00, hour=21)
    (s,) = sl.shadows(con)
    assert all(s[f"pct_{m}"] is not None for m in (30, 60, 120))


def test_the_slices_are_the_same_horizons_the_underlying_lab_uses():
    """So the two measurements of one gate can be read side by side."""
    assert sl.SLICES == (30, 60, 120)


# ============================================== one refusal is one observation
def test_each_refusal_is_its_own_row(con):
    _mark(con, 15, ENTRY)
    _mark(con, 30, ENTRY, scan="2026-11-06T19:30:20+05:30")
    assert len(sl.shadows(con)) == 2


def test_the_same_strike_refused_twice_is_not_merged(con):
    """Gas was refused eight times on 2026-11-06, twice on the same contract."""
    _mark(con, 15, ENTRY)
    _mark(con, 46, 12.50)
    _mark(con, 30, ENTRY, scan="2026-11-06T19:30:20+05:30")
    rows = sl.shadows(con)
    assert len(rows) == 2
    assert sorted(r["marks"] for r in rows) == [1, 2]


def test_the_peak_of_the_refused_contract_is_reported(con):
    """A refusal that peaked +20% and ended flat is a different finding from
    one that never moved."""
    _mark(con, 15, ENTRY)
    _mark(con, 20, 16.02)
    _mark(con, 46, 13.35)
    (s,) = sl.shadows(con)
    assert s["peak_pct"] == pytest.approx(20.0, abs=1e-6)


def test_a_path_with_no_entry_is_dropped_rather_than_divided_by(con):
    con.execute(
        "INSERT INTO shadow_marks (symbol, observed_at, day, premium, entry,"
        " underlying, scanned_at) VALUES (?,?,?,?,?,?,?)",
        (REFUSED, f"{DAY}T19:15:10+05:30", DAY, 13.35, None, "NATURALGAS", SCAN))
    con.commit()
    assert sl.shadows(con) == []


# ===================================================== nothing above its bar
def test_a_thin_sample_is_not_a_verdict():
    out = sl.verdict([-5.0] * 4, 60)
    assert "not a result" in out
    assert "SAVED" not in out and "SPENT" not in out


def test_a_consistently_negative_set_says_the_gate_saved_money():
    out = sl.verdict([-4.0, -5.0, -3.0, -6.0] * 10, 60)
    assert "THE GATE SAVED MONEY" in out


def test_a_consistently_positive_set_says_the_gate_spent_money():
    out = sl.verdict([4.0, 5.0, 3.0, 6.0] * 10, 60)
    assert "THE GATE SPENT MONEY" in out


def test_a_noisy_set_is_called_noise():
    out = sl.verdict([5.0, -5.0, 4.0, -4.0] * 10, 60)
    assert "noise in premium" in out


def test_the_bar_is_the_same_as_the_underlying_lab():
    assert sl.SHIP_T == 2.0 and sl.MIN_N == 30


def test_a_horizon_no_path_reaches_says_so():
    assert "no path reaches this horizon yet" in sl.verdict([], 120)


# ================================================= the convention is stated
def test_the_report_states_which_sign_favours_the_gate(con):
    """A column of signed numbers with no stated convention is how a result
    gets read backwards."""
    _mark(con, 15, ENTRY)
    out = sl.report(con)
    assert "Negative means the gate saved" in out
    assert "LONG premium" in out


def test_the_report_names_what_it_cannot_say(con):
    _mark(con, 15, ENTRY)
    out = sl.report(con)
    assert "no stop, no trail and no exit" in out


# ========================================================= assets stay apart
def test_two_assets_are_reported_separately(con):
    """Direction here is per-asset, and one pooled number has hidden that
    before."""
    for i in range(3):
        gas, gold = f"{DAY}T19:1{i}:10+05:30", f"{DAY}T19:2{i}:10+05:30"
        _mark(con, 15, ENTRY, scan=gas)
        _mark(con, 16 + i, 12.50, scan=gas, hour=20)        # t > 60 min
        _mark(con, 15, 3035.50, symbol="GOLDM26NOV138500PE", entry=3035.50,
              underlying="GOLDM", scan=gold)
        _mark(con, 26 + i, 3100.00, symbol="GOLDM26NOV138500PE", entry=3035.50,
              underlying="GOLDM", scan=gold, hour=20)
    out = sl.report(con)
    assert "PER ASSET" in out
    assert "NATURALGAS" in out and "GOLDM" in out


def test_one_asset_alone_does_not_print_a_per_asset_table(con):
    _mark(con, 15, ENTRY)
    _mark(con, 46, 12.50)
    assert "PER ASSET" not in sl.report(con)


# ==================================================== arithmetic at the edges
def test_an_empty_bucket_has_no_t():
    assert sl._stats([]) == (0, 0.0, 0.0)


def test_a_single_observation_has_no_t():
    n, mean, t = sl._stats([-4.0])
    assert (n, mean, t) == (1, -4.0, 0.0)


def test_a_flat_bucket_does_not_divide_by_zero():
    n, mean, t = sl._stats([-4.0] * 10)
    assert mean == pytest.approx(-4.0) and t < 0


def test_an_unparseable_stamp_does_not_crash_the_read(con):
    con.execute(
        "INSERT INTO shadow_marks (symbol, observed_at, day, premium, entry,"
        " underlying, scanned_at) VALUES (?,?,?,?,?,?,?)",
        (REFUSED, "not-a-date", DAY, 13.35, ENTRY, "NATURALGAS", SCAN))
    con.commit()
    assert sl.shadows(con) == []
