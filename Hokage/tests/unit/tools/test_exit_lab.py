"""The exit lab must not invent attribution, and must not read gross as net.

Two traps this tool sits directly on top of:

  1. `decision_outcomes.decision_id` and `positions.position_id` are
     different UUID namespaces - 0 of 127 join. The outcome row is written
     about a second after the close, so the join is a TIMESTAMP MATCH. A
     per-cell number built on a silent drop is a fabricated verdict, so the
     unmatched count is reported and the rows are kept as UNMATCHED.

  2. `positions.charges` is populated on 1 of 126 real rows. Reading it would
     report a "net" that is gross for 125 of them, which is exactly what
     "every P&L number is gross" names. Charges come from the schedule.
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


SRC = _repo_root() / "tools" / "research" / "exit_lab.py"


def _module():
    sys.modules.pop("exit_lab", None)
    spec = importlib.util.spec_from_file_location("exit_lab", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EL = _module()


def _db(tmp_path, positions, outcomes):
    path = tmp_path / "hokage.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE positions (
        position_id TEXT, market TEXT, quantity REAL, entry_price REAL,
        realized_pnl REAL, status TEXT, closed_at TEXT, strategy_id TEXT,
        failure_reason TEXT, charges REAL)""")
    con.execute("""CREATE TABLE decision_outcomes (
        decision_id TEXT, timestamp TEXT, outcome TEXT, pnl REAL,
        return_pct REAL, exit_reason TEXT, holding_days INTEGER)""")
    con.executemany(
        "INSERT INTO positions (position_id, market, quantity, entry_price,"
        " realized_pnl, status, closed_at, strategy_id, failure_reason,"
        " charges) VALUES (?,?,?,?,?,?,?,?,?,?)", positions)
    con.executemany(
        "INSERT INTO decision_outcomes (decision_id, timestamp, exit_reason,"
        " pnl) VALUES (?,?,?,?)", outcomes)
    con.commit()
    con.close()
    return path


CLOSE = "2026-11-11T13:17:30.081855+00:00"
OUT_T = "2026-11-11T13:17:31.318134+00:00"      # ~1.2s later, as in the record


def _pos(market="GOLDM26NOV141000PE", pnl=-170.0, closed=CLOSE,
         failure=None, qty=10.0, price=2512.5):
    return ("p1", market, qty, price, pnl, "CLOSED", closed,
            "strat-sessionshift-mcx-v1", failure, 85.2)


# ======================================================= classification
@pytest.mark.parametrize("reason,expected", [
    ("Underlying Thesis Stop: CRUDE_OIL moved 40.00 (>= 1.25 x ATR 31.64)",
     "THESIS STOP (1.25 ATR on underlying)"),
    ("Option hard backstop: premium 2934.00 fell 12%",
     "HARD BACKSTOP (premium floor)"),
    ("Target hit at 2889.29", "TARGET HIT"),
    ("Trailing stop: floor 2512.50", "TRAILING"),
    ("Session close square-off", "SESSION CLOSE"),
])
def test_the_mechanism_is_read_not_the_sentence(reason, expected):
    """The reasons embed the premium and the move, so grouping on the raw
    string gives one bucket per trade and tells you nothing."""
    assert EL.classify(reason) == expected


def test_an_unrecorded_reason_is_its_own_bucket():
    assert EL.classify(None) == "UNRECORDED"
    assert EL.classify("   ") == "UNRECORDED"


@pytest.mark.parametrize("market,expected", [
    ("GOLDM26NOV141000PE", "GOLDM"),
    ("NATURALGAS26NOV285PE", "NATURALGAS"),
    ("BANKNIFTY26NOV52000CE", "BANKNIFTY"),
    ("WHAT26NOV1CE", None),
])
def test_the_underlying_is_parsed_from_the_contract(market, expected):
    assert EL.underlying_of(market) == expected


# ================================================= the timestamp match
def test_an_outcome_a_second_later_is_the_same_event(tmp_path):
    db = _db(tmp_path, [_pos()],
             [("d1", OUT_T, "Option hard backstop: premium 2512.50 fell 12%", -170.0)])
    matches, quality = EL.load(db)
    assert quality["matched"] == 1
    assert quality["unmatched"] == 0
    assert matches[0].mechanism == "HARD BACKSTOP (premium floor)"


def test_an_outcome_far_away_is_not_claimed(tmp_path):
    """A loose tolerance would attribute the PREVIOUS trade's mechanism."""
    far = "2026-11-11T14:00:00+00:00"
    db = _db(tmp_path, [_pos()], [("d1", far, "Target hit", +500.0)])
    matches, quality = EL.load(db)
    assert quality["matched"] == 0
    assert quality["unmatched"] == 1
    assert matches[0].mechanism == "UNMATCHED (no outcome row)"


def test_an_unmatched_position_is_kept_not_dropped(tmp_path):
    """THE TRAP. Dropping it would make the totals disagree with the ledger
    while looking tidier."""
    db = _db(tmp_path, [_pos(pnl=-170.0)], [])
    matches, quality = EL.load(db)
    assert len(matches) == 1
    assert quality["positions"] == 1
    assert matches[0].gross == -170.0


def test_two_outcomes_inside_the_window_are_flagged_ambiguous(tmp_path):
    db = _db(tmp_path, [_pos()], [
        ("d1", OUT_T, "Target hit", +500.0),
        ("d2", "2026-11-11T13:17:32.000000+00:00", "Trailing stop", -10.0)])
    _matches, quality = EL.load(db)
    assert quality["ambiguous"] == 1


def test_outcome_rows_with_no_position_are_counted(tmp_path):
    db = _db(tmp_path, [_pos()], [
        ("d1", OUT_T, "Target hit", +500.0),
        ("d2", "2026-10-01T10:00:00+00:00", "Thesis stop", -99.0)])
    _matches, quality = EL.load(db)
    assert quality["outcomes_unused"] == 1


def test_a_phantom_is_excluded_and_counted(tmp_path):
    db = _db(tmp_path,
             [_pos(), _pos(failure="PHANTOM: 2026-07-15 runaway")],
             [("d1", OUT_T, "Target hit", +500.0)])
    _matches, quality = EL.load(db)
    assert quality["phantoms"] == 1
    assert quality["positions"] == 1


# ============================================ gross is not net, ever
def test_charges_come_from_the_schedule_not_the_ledger_column(tmp_path):
    """The ledger's `charges` is populated on 1 of 126 real rows. Reading it
    would call a gross number net for every other trade."""
    db = _db(tmp_path, [_pos(pnl=-170.0)],
             [("d1", OUT_T, "Option hard backstop: premium fell 12%", -170.0)])
    matches, _q = EL.load(db)
    match = matches[0]
    assert match.charges > 0, "a round trip is never free"
    assert match.charges != 85.2, "that is the ledger column, not the schedule"
    assert match.net == match.gross - match.charges
    assert match.net < match.gross


def test_the_report_states_the_net_and_the_multiple(tmp_path):
    db = _db(tmp_path, [_pos(pnl=+1000.0)],
             [("d1", OUT_T, "Target hit", +1000.0)])
    text = EL.report(db)
    assert "net" in text.lower()
    assert "charges are" in text and "x the absolute gross" in text


def test_the_report_leads_with_attribution_quality(tmp_path):
    """Every number rests on the match, so the match quality is printed
    before any of them."""
    db = _db(tmp_path, [_pos()], [("d1", OUT_T, "Target hit", +1.0)])
    text = EL.report(db)
    assert text.index("ATTRIBUTION QUALITY") < text.index("BY EXIT MECHANISM")
    assert "never dropped" in text


def test_the_report_says_what_it_cannot_answer(tmp_path):
    """The premium path is GONE for closed trades, not missing. A tool that
    stayed quiet about that invites a stop change on no evidence."""
    db = _db(tmp_path, [_pos()], [("d1", OUT_T, "Target hit", +1.0)])
    text = EL.report(db)
    assert "WHAT THIS CANNOT ANSWER" in text
    assert "REPLAYABLE" in text
    assert "NOT replayable" in text


def test_it_proposes_no_stop_value():
    """Every stop here is a commander-approved risk constant. A measurement
    tool that tunes them is the self-evolution loop that was closed."""
    import ast

    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for forbidden in ("write_proposal", "apply", "set_stop"):
        assert forbidden not in names
    text = SRC.read_text(encoding="utf-8")
    assert "proposes nothing" in text.lower() or "proposes no" in text.lower()


def test_a_missing_database_raises_rather_than_reporting_zero(tmp_path):
    """A report of 0 exits on an unreadable ledger reads as 'no exits', which
    is the confident-silence failure this project keeps paying for."""
    with pytest.raises(sqlite3.Error):
        EL.load(tmp_path / "not-here.db")
