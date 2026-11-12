"""Where entries sit in a move, and the two ways that measurement could lie.

  1. BY CONFOUNDING TIMING WITH MODULE. Momentum modules enter late by
     construction. If they happen to own the profitable assets, a gap between
     winners and losers is a MODULE effect wearing a timing costume. The
     report splits within module as well as across, and the finding only
     stands because the gap appears INSIDE each one.
  2. BY FITTING A THRESHOLD. A cut chosen on these 114 trades is in-sample,
     which is the overfitting the whole hold-out/Sidak apparatus exists to
     prevent. This tool reports distributions and names no cut.

The ATR is this tool's own 14-bar ruler and the report says so: absolute
values are not comparable with production's, while the comparison BETWEEN
groups is, because every group is measured the same way.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sqlite3
import sys

import pytest


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


SRC = _repo_root() / "tools" / "research" / "entry_lab.py"


def _module():
    sys.modules.pop("entry_lab", None)
    spec = importlib.util.spec_from_file_location("entry_lab", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EL = _module()


# ========================================================= the parsers
@pytest.mark.parametrize("market,expected", [
    ("NIFTY2672124150CE", True), ("GOLDM26NOV141000PE", False),
    ("GOLDM26NOV141000XX", None),
])
def test_the_option_type_is_the_direction(market, expected):
    assert EL.bullish(market) is expected


@pytest.mark.parametrize("reason,expected", [
    ("Target hit at 2889", "TARGET HIT"),
    ("Underlying Thesis Stop: NIFTY moved 55", "THESIS STOP"),
    ("Option hard backstop: premium fell 12%", "HARD BACKSTOP"),
    ("Trailing stop", "TRAILING"),
    (None, "UNRECORDED"),
])
def test_the_mechanism_is_classified(reason, expected):
    assert EL.classify(reason) == expected


def test_the_true_range_uses_the_previous_close():
    """A range that ignores the gap understates volatility, which inflates
    every ATR-normalised number in the report."""
    bars = [
        (None, 100.0, 90.0, 95.0),
        (None, 120.0, 115.0, 118.0),      # gapped up through the prior close
    ]
    ranges = EL._true_ranges(bars)
    assert ranges == [25.0]               # 120 - 95, not 120 - 115


# ===================================================== the measurement
def _dbs(tmp_path, positions, outcomes, candles):
    hpath = tmp_path / "hokage.db"
    con = sqlite3.connect(hpath)
    con.execute("""CREATE TABLE positions (market TEXT, realized_pnl REAL,
        opened_at TEXT, closed_at TEXT, status TEXT, failure_reason TEXT,
        strategy_id TEXT)""")
    con.execute("CREATE TABLE decision_outcomes (timestamp TEXT, exit_reason TEXT)")
    con.executemany(
        "INSERT INTO positions (market, realized_pnl, opened_at, closed_at,"
        " status, failure_reason, strategy_id) VALUES (?,?,?,?,'CLOSED',NULL,?)",
        positions)
    con.executemany("INSERT INTO decision_outcomes VALUES (?,?)", outcomes)
    con.commit()
    con.close()

    cpath = tmp_path / "candles.db"
    con = sqlite3.connect(cpath)
    con.execute("""CREATE TABLE candles (symbol TEXT, ts TEXT, contract TEXT,
        open REAL, high REAL, low REAL, close REAL, volume REAL)""")
    con.executemany(
        "INSERT INTO candles (symbol, ts, high, low, close) VALUES (?,?,?,?,?)",
        candles)
    con.commit()
    con.close()
    return hpath, cpath


def _session(prices, day="2026-11-10", symbol="NIFTY"):
    """15-minute bars from 09:15, each with a 10-point range."""
    out = []
    when = dt.datetime(2026, 11, 10, 9, 15)
    for close in prices:
        out.append((symbol, when.strftime("%Y-%m-%d %H:%M:%S"),
                    close + 5.0, close - 5.0, close))
        when += dt.timedelta(minutes=15)
    return out


OPEN_UTC = "2026-11-10T04:30:00+00:00"       # 10:00 IST = the 4th bar
CLOSE_UTC = "2026-11-10T05:30:00+00:00"


def test_a_late_entry_into_a_rising_move_reads_positive(tmp_path):
    """Long CE entered after the underlying has already climbed. The prior
    move must be POSITIVE - that is the definition the report rests on."""
    candles = _session([25000.0, 25050.0, 25100.0, 25150.0, 25200.0])
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000CE", +500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [(CLOSE_UTC, "Target hit")], candles)
    rows, quality = EL.measure(h, c)
    assert quality["measured"] == 1
    assert rows[0].prior_move_atr > 0
    assert rows[0].mechanism == "TARGET HIT"


def test_a_put_entered_into_a_falling_move_also_reads_positive(tmp_path):
    """Direction has to be applied, or every PE reads as the opposite of
    what it was and the whole table inverts."""
    candles = _session([25000.0, 24950.0, 24900.0, 24850.0, 24800.0])
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000PE", +500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [(CLOSE_UTC, "Target hit")], candles)
    rows, _q = EL.measure(h, c)
    assert rows[0].up is False
    assert rows[0].prior_move_atr > 0, "a put in a falling market is confirmed"


def test_entering_against_the_session_reads_negative(tmp_path):
    candles = _session([25000.0, 24950.0, 24900.0, 24850.0, 24800.0])
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000CE", -500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [(CLOSE_UTC, "Underlying Thesis Stop: moved 55")], candles)
    rows, _q = EL.measure(h, c)
    assert rows[0].prior_move_atr < 0


def test_a_position_with_no_matched_outcome_is_counted_not_guessed(tmp_path):
    candles = _session([25000.0, 25050.0, 25100.0, 25150.0, 25200.0])
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000CE", +500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [], candles)
    rows, quality = EL.measure(h, c)
    assert quality["no_mechanism"] == 1
    assert quality["measured"] == 0
    assert rows == []


def test_too_few_candles_is_reported_not_estimated(tmp_path):
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000CE", +500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [(CLOSE_UTC, "Target hit")],
                _session([25000.0, 25050.0]))
    rows, quality = EL.measure(h, c)
    assert quality["thin_history"] == 1
    assert rows and rows[0].note == "not enough candles for an ATR"


def test_a_phantom_is_excluded(tmp_path):
    candles = _session([25000.0, 25050.0, 25100.0, 25150.0, 25200.0])
    hpath, cpath = _dbs(tmp_path, [], [(CLOSE_UTC, "Target hit")], candles)
    con = sqlite3.connect(hpath)
    con.execute("INSERT INTO positions (market, realized_pnl, opened_at,"
                " closed_at, status, failure_reason, strategy_id)"
                " VALUES (?,?,?,?,'CLOSED','PHANTOM: runaway',?)",
                ("NIFTY26NOV25000CE", 0.0, OPEN_UTC, CLOSE_UTC, "s1"))
    con.commit()
    con.close()
    _rows, quality = EL.measure(hpath, cpath)
    assert quality["positions"] == 0


# ====================================== it must not hide the confound
def test_the_report_splits_within_module(tmp_path):
    """A gap that appears only BETWEEN modules is about which module trades
    what, not about timing. The report must make that visible."""
    candles = _session([25000.0, 25050.0, 25100.0, 25150.0, 25200.0])
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000CE", +500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [(CLOSE_UTC, "Target hit")], candles)
    text = EL.report(h, c)
    assert "IS IT A MODULE EFFECT INSTEAD?" in text
    assert "within module" in text


def test_the_report_admits_whose_ruler_it_is(tmp_path):
    candles = _session([25000.0, 25050.0, 25100.0, 25150.0, 25200.0])
    h, c = _dbs(tmp_path,
                [("NIFTY26NOV25000CE", +500.0, OPEN_UTC, CLOSE_UTC, "s1")],
                [(CLOSE_UTC, "Target hit")], candles)
    text = EL.report(h, c)
    assert "own 14-bar ruler" in text
    assert "not comparable" in text


def test_an_empty_measurement_draws_no_conclusion(tmp_path):
    h, c = _dbs(tmp_path, [], [], [])
    # Whitespace-normalised: the sentence wraps across lines in the report,
    # so matching the raw text would be a test of the line width.
    text = " ".join(EL.report(h, c).split())
    assert "No conclusion" in text
    assert "not the same as chasing being ruled out" in text


def test_it_names_no_threshold():
    """A cut fitted on these 114 trades is in-sample, which is exactly what
    the hold-out and Sidak machinery exists to prevent."""
    import ast

    text = SRC.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "").isupper() for t in node.targets
                        if isinstance(t, ast.Name))):
            name = next(t.id for t in node.targets if isinstance(t, ast.Name))
            assert "MIN_" not in name and "THRESHOLD" not in name, (
                f"{name} looks like a fitted cut")
    assert "proposes nothing" in text.lower() or "PROPOSES NOTHING" in text
