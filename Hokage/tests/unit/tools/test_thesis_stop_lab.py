"""The thesis-stop replay must not invent a price or flatter the stop.

Two ways this measurement could lie, both tested:

  1. BY PRICING THE COUNTERFACTUAL. Saying what a wider stop would have PAID
     needs the option priced at an exit that never happened - a synthetic
     price. The tool reports ATR on the underlying only.
  2. BY COUNTING A STOP IT CANNOT REPRODUCE AS 'DID NOT RECOVER'. Five of the
     37 real stops show less than 1.25 ATR of adverse move on 15-minute
     candles, so production was watching finer data. Treating those as
     non-recoveries would push the recovery rate down and make the stop look
     better than the tape supports.

The ATR is parsed from the production exit reason rather than recomputed,
because a re-derived ATR is a different ruler from the one that fired the
stop - the mistake that reset the audit's retirement clock.
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


SRC = _repo_root() / "tools" / "research" / "thesis_stop_lab.py"


def _module():
    sys.modules.pop("thesis_stop_lab", None)
    spec = importlib.util.spec_from_file_location("thesis_stop_lab", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TS = _module()
IST = TS.IST


# ===================================================== the parsers
@pytest.mark.parametrize("reason,expected", [
    ("Underlying Thesis Stop: NIFTY moved 55.00 against position"
     " (>= 1.25 x ATR 42.82)", 42.82),
    ("Underlying Thesis Stop: CRUDE_OIL moved 40.00 (>= 1.25 x ATR 31.64)",
     31.64),
    ("Underlying Thesis Stop: no atr here", None),
])
def test_the_atr_is_read_from_production(reason, expected):
    assert TS.parse_atr(reason) == expected


@pytest.mark.parametrize("market,expected", [
    ("NIFTY2672124150CE", True),
    ("GOLDM26NOV141000PE", False),
    ("GOLDM26NOV141000XX", None),
])
def test_the_option_type_is_the_direction(market, expected):
    assert TS.bullish(market) is expected


# ============================================ the replay arithmetic
def _dbs(tmp_path, *, market, opened, closed, reason, candles, pnl=-1000.0):
    hpath = tmp_path / "hokage.db"
    con = sqlite3.connect(hpath)
    con.execute("""CREATE TABLE positions (market TEXT, realized_pnl REAL,
        opened_at TEXT, closed_at TEXT, status TEXT, failure_reason TEXT)""")
    con.execute("""CREATE TABLE decision_outcomes (timestamp TEXT,
        exit_reason TEXT)""")
    con.execute("INSERT INTO positions VALUES (?,?,?,?,'CLOSED',NULL)",
                (market, pnl, opened, closed))
    con.execute("INSERT INTO decision_outcomes VALUES (?,?)", (closed, reason))
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


#: Entry at 10:00 IST = 04:30 UTC. ATR 100, so 1.25 ATR = 125 points.
OPENED = "2026-11-10T04:30:00+00:00"
CLOSED = "2026-11-10T05:30:00+00:00"
REASON = ("Underlying Thesis Stop: NIFTY moved 130.00 against position"
          " (>= 1.25 x ATR 100.00)")


def test_a_recovery_after_the_stop_is_detected(tmp_path):
    """Long CE at 25000. It falls to 24850 (-150, past 1.25 ATR = 125),
    then climbs back through 25000. That is the stop cutting off a
    recovery, and it must be counted as one."""
    candles = [
        ("NIFTY", "2026-11-10 10:00:00", 25010.0, 24990.0, 25000.0),
        ("NIFTY", "2026-11-10 10:15:00", 25000.0, 24850.0, 24860.0),
        ("NIFTY", "2026-11-10 10:30:00", 25100.0, 24900.0, 25080.0),
    ]
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000CE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=candles)
    rows, quality = TS.replay_all(h, c)
    assert quality["replayed"] == 1
    row = rows[0]
    assert row.recovered[30] is True
    assert row.recovered["session"] is True
    assert row.mae_atr == pytest.approx(1.5)      # 150 points / ATR 100


def test_no_recovery_is_not_reported_as_one(tmp_path):
    candles = [
        ("NIFTY", "2026-11-10 10:00:00", 25010.0, 24990.0, 25000.0),
        ("NIFTY", "2026-11-10 10:15:00", 25000.0, 24850.0, 24860.0),
        ("NIFTY", "2026-11-10 10:30:00", 24880.0, 24800.0, 24810.0),
    ]
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000CE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=candles)
    rows, _q = TS.replay_all(h, c)
    assert rows[0].recovered[30] is False
    assert rows[0].recovered["session"] is False


def test_a_put_measures_adverse_the_other_way(tmp_path):
    """A long PE loses when the underlying RISES. Getting this backwards
    would invert every number in the report."""
    candles = [
        ("NIFTY", "2026-11-10 10:00:00", 25010.0, 24990.0, 25000.0),
        ("NIFTY", "2026-11-10 10:15:00", 25150.0, 25000.0, 25140.0),
    ]
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000PE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=candles)
    rows, _q = TS.replay_all(h, c)
    assert rows[0].up is False
    assert rows[0].mae_atr == pytest.approx(1.5)   # rose 150 against the put


def test_a_wider_stop_that_still_fires_is_reported_as_firing(tmp_path):
    candles = [
        ("NIFTY", "2026-11-10 10:00:00", 25010.0, 24990.0, 25000.0),
        ("NIFTY", "2026-11-10 10:15:00", 25000.0, 24700.0, 24710.0),
    ]
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000CE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=candles)
    rows, _q = TS.replay_all(h, c)
    hit = rows[0].hit_wider
    assert hit[1.25] is True and hit[2.0] is True   # 300 points = 3.0 ATR
    assert hit[2.5] is True


def test_a_stop_that_does_not_reproduce_is_excluded_not_counted_against(tmp_path):
    """THE FLATTERING TRAP. Production stopped this out, but 15-minute bars
    show only 50 points of adverse move - half the 1.25 ATR threshold. It
    must not be scored as 'did not recover'."""
    candles = [
        ("NIFTY", "2026-11-10 10:00:00", 25010.0, 24990.0, 25000.0),
        ("NIFTY", "2026-11-10 10:15:00", 25005.0, 24950.0, 24960.0),
    ]
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000CE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=candles)
    rows, _q = TS.replay_all(h, c)
    assert rows[0].hit_wider[1.25] is False
    assert not rows[0].recovered, "no fire means no recovery verdict"
    text = TS.report(h, c)
    assert "DO NOT REPRODUCE" in text
    assert "would flatter the stop" in text


def test_a_day_with_no_candles_is_counted_not_dropped(tmp_path):
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000CE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=[])
    rows, quality = TS.replay_all(h, c)
    assert quality["no_candles"] == 1
    assert quality["replayed"] == 0
    assert rows and rows[0].note == "no candles for that day"


def test_the_report_says_nothing_rather_than_guessing(tmp_path):
    h, c = _dbs(tmp_path, market="NIFTY26NOV25000CE", opened=OPENED,
                closed=CLOSED, reason=REASON, candles=[])
    text = TS.report(h, c)
    assert "No conclusion is available" in text
    assert "not the same as the stop being fine" in text


# =================================== it must not price the counterfactual
def test_it_never_prices_the_option_at_a_hypothetical_exit():
    """Rupees for an exit that never happened is a synthetic price."""
    text = SRC.read_text(encoding="utf-8")
    assert "synthetic price" in text
    # the only money it reports is realised pnl straight from the ledger
    import ast

    tree = ast.parse(text)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for forbidden in ("black_scholes", "implied_vol", "price_option",
                      "theoretical_premium"):
        assert forbidden not in names


def test_it_proposes_no_stop_multiple():
    text = SRC.read_text(encoding="utf-8")
    assert "proposes nothing" in text.lower() or "proposes no" in text.lower()
    assert "commander-approved risk constant" in text


def test_the_candidate_multiples_include_production():
    """1.25 has to be in the list or the comparison has no baseline."""
    assert 1.25 in TS.CANDIDATE_MULTIPLES
    assert TS.CANDIDATE_MULTIPLES == tuple(sorted(TS.CANDIDATE_MULTIPLES))


def test_recovery_windows_include_the_audits_horizon():
    """The weekly audit measures a 60-minute horizon, so a recovery inside
    it is one the system could plausibly have held for."""
    assert 60 in TS.RECOVERY_WINDOWS_MIN
