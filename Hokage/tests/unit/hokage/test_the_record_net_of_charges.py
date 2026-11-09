"""The record Hokage reports has never had the broker paid out of it.

2026-11-09. `apply_trade` does `self.cash += pos.realized_pnl` and stops
there, so every figure the system has produced is GROSS - the per-strategy
expectancies, the sweep results, the retirement decisions, and the profit
factor the go-live gate is judged on. `bots.execution.charges` quotes the
real schedule and deliberately touches nothing; nothing had ever run it over
the ledger, so the size of the gap was simply unknown.

Run across 125 real closed positions it comes to Rs 10,372 of charges against
Rs 3,262 of gross profit: PF 1.03 gross becomes 0.94 net, and the lifetime
record turns negative. Brokerage alone is 48% of it, because it is FLAT -
40 rupees a round trip whatever the size - which means it falls hardest on
exactly the small positions this account can afford.

WHAT THESE TESTS GUARD
That the tool measures and never writes; that phantoms stay out (292 rows
that were never real orders would otherwise be charged brokerage); that the
exit leg is priced on the REAL exit rather than the flat-exit estimate the
charges module falls back to; and that a profit factor is computed on net
and gross separately rather than scaled, since charges push the numerator
down and the denominator up at the same time.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import net_record  # noqa: E402
from bots.execution import charges  # noqa: E402

_SCHEMA = """
CREATE TABLE positions (
    position_id TEXT PRIMARY KEY, account_id TEXT, market TEXT,
    direction TEXT, quantity REAL, entry_price REAL, current_price REAL,
    unrealized_pnl REAL, realized_pnl REAL, status TEXT,
    opened_at TEXT, closed_at TEXT, playbook_id TEXT,
    failure_reason TEXT, volatility_regime TEXT, strategy_id TEXT);
"""


def _ledger(tmp_path: Path, rows: list[dict]) -> Path:
    db = tmp_path / "ledger.db"
    con = sqlite3.connect(str(db))
    con.executescript(_SCHEMA)
    for i, row in enumerate(rows):
        con.execute(
            "INSERT INTO positions (position_id, market, quantity, "
            "entry_price, current_price, realized_pnl, status, closed_at, "
            "failure_reason, strategy_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"p{i}", row["market"], row["quantity"], row["entry"],
             row["exit"], row["pnl"], row.get("status", "CLOSED"),
             row.get("closed_at", f"2026-11-0{i % 9 + 1}T10:00:00+00:00"),
             row.get("failure_reason"), row.get("strategy", "strat-a")))
    con.commit()
    con.close()
    return db


def _gas(entry, exit_, pnl, **kw):
    return dict(market="NATURALGAS26NOV285PE", quantity=1250.0,
                entry=entry, exit=exit_, pnl=pnl, **kw)


# ============================================================ it reads truly
def test_a_real_round_trip_is_priced_on_both_legs(tmp_path):
    """Today's gas trade: 1250 @ 14.70 out at 13.90, gross -1,000."""
    db = _ledger(tmp_path, [_gas(14.70, 13.90, -1000.0)])
    trades = net_record.closed_trades(db)
    assert len(trades) == 1
    t = trades[0]
    assert t.underlying == "NATURALGAS"
    assert t.entry_value == pytest.approx(18_375.0)
    assert t.exit_value == pytest.approx(17_375.0)
    # Within a rupee of what the bot reported on the day.
    assert t.cost == pytest.approx(74.11, abs=1.0)
    assert t.net == pytest.approx(-1074.11, abs=1.0)


def test_the_exit_leg_uses_the_real_exit_not_a_flat_assumption(tmp_path):
    """`charges.option_round_trip` assumes a flat exit when none is given.
    Here the exit is known, and a halved exit must cost less STT."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cheap = _ledger(tmp_path / "a", [_gas(14.70, 7.00, -9625.0)])
    flat = _ledger(tmp_path / "b", [_gas(14.70, 14.70, 0.0)])
    assert (net_record.closed_trades(cheap)[0].cost
            < net_record.closed_trades(flat)[0].cost)


def test_phantoms_are_not_charged_brokerage(tmp_path):
    """292 rows that were never real orders would otherwise pay 40 rupees
    each and drown the real record two to one."""
    db = _ledger(tmp_path, [
        _gas(14.70, 13.90, -1000.0),
        _gas(14.70, 13.90, 0.0,
             failure_reason="PHANTOM: 2026-07-15 reduce-only runaway"),
    ])
    assert len(net_record.closed_trades(db)) == 1


def test_open_positions_are_not_in_the_record(tmp_path):
    db = _ledger(tmp_path, [_gas(14.70, 13.90, 0.0, status="OPEN")])
    assert net_record.closed_trades(db) == []


def test_a_zero_entry_row_is_skipped_rather_than_dividing_by_it(tmp_path):
    db = _ledger(tmp_path, [_gas(0.0, 0.0, 0.0)])
    assert net_record.closed_trades(db) == []


# ================================================================= the maths
def test_profit_factor_is_gross_profit_over_gross_loss():
    assert net_record.profit_factor([100.0, -50.0]) == pytest.approx(2.0)
    assert net_record.profit_factor([-10.0, -10.0]) == pytest.approx(0.0)


def test_profit_factor_is_none_when_nothing_was_lost():
    """None, not infinity and not zero - a PF with no denominator is not a
    number, and printing 0.00 there would read as a total loss."""
    assert net_record.profit_factor([5.0, 5.0]) is None
    assert net_record.profit_factor([]) is None


def test_charges_move_the_profit_factor_more_than_the_rupee_total(tmp_path):
    """THE REASON THIS IS NOT A FLAT HAIRCUT. A cost is subtracted from the
    winners AND added to the losers, so it hits both sides of the ratio."""
    db = _ledger(tmp_path, [
        _gas(14.70, 15.00, 375.0),
        _gas(14.70, 14.40, -375.0),
    ])
    trades = net_record.closed_trades(db)
    gross_pf = net_record.profit_factor([t.gross for t in trades])
    net_pf = net_record.profit_factor([t.net for t in trades])
    assert gross_pf == pytest.approx(1.0)
    assert net_pf < 0.85


def test_a_thin_win_becomes_a_loss(tmp_path):
    """A 50-rupee win does not survive a 40-rupee brokerage plus taxes."""
    db = _ledger(tmp_path, [_gas(14.70, 14.74, 50.0)])
    t = net_record.closed_trades(db)[0]
    assert t.gross > 0 > t.net


def test_summarise_counts_winners_on_both_bases(tmp_path):
    db = _ledger(tmp_path, [
        _gas(14.70, 14.74, 50.0),      # gross win, net loss
        _gas(14.70, 16.70, 2500.0),    # win on both
        _gas(14.70, 13.90, -1000.0),   # loss on both
    ])
    s = net_record.summarise("x", net_record.closed_trades(db))
    assert s.n == 3
    assert s.gross_wins == 2
    assert s.net_wins == 1
    assert s.net_total < s.gross_total


# ================================================ flat brokerage, not a rate
def test_the_same_trade_costs_more_as_a_percentage_when_it_is_smaller():
    """Brokerage is 40 rupees whatever the size, so trading smaller does not
    make it cheaper - it makes it dearer. This is why the figure cannot be
    carried as a single percentage anywhere."""
    small = charges.option_round_trip(5_000.0, "SENSEX").pct_of_premium
    large = charges.option_round_trip(50_000.0, "SENSEX").pct_of_premium
    assert small > large * 2


def test_brokerage_is_the_largest_line_at_this_account_size(tmp_path):
    trip = charges.option_round_trip(18_375.0, "NATURALGAS",
                                     exit_value=17_375.0)
    biggest = trip.breakdown()[0]
    assert biggest[0] == "brokerage"


# ========================================================= it changes nothing
def test_the_tool_never_writes(tmp_path):
    """It reads `positions` and prints. A research tool that mutates the
    ledger is how a measurement becomes a decision nobody made.

    Matched on SQL STATEMENTS, not on words: a bare "INSERT" check fires on
    `sys.path.insert`, which is the same mistake as a source rail tripping on
    the prose that explains the trap it guards (2026-11-09, four times)."""
    import re

    src = (ROOT / "tools" / "research" / "net_record.py").read_text(
        encoding="utf-8")
    writes = re.compile(
        r'"\s*(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|REPLACE)\b',
        re.IGNORECASE)
    assert not writes.search(src), "a write statement reached a read-only tool"
    assert ".commit()" not in src
    assert "executescript" not in src


def test_it_says_the_number_is_a_floor(tmp_path):
    """One row per position, but a split fill is two orders and another 40
    rupees. Reporting a floor as an exact figure understates the cost."""
    src = (ROOT / "tools" / "research" / "net_record.py").read_text(
        encoding="utf-8")
    flat = " ".join(src.split())
    assert "FLOOR on charges, never a ceiling" in flat


def test_the_rates_carry_the_date_they_were_read():
    assert charges.RATES_READ_ON == "2026-11-09"
    assert "zerodha.com" in charges.RATES_SOURCE


def test_the_report_runs_end_to_end(tmp_path, capsys):
    db = _ledger(tmp_path, [
        _gas(14.70, 16.70, 2500.0),
        _gas(14.70, 13.90, -1000.0),
        dict(market="NIFTY26NOV26000CE", quantity=65.0, entry=261.90,
             exit=250.00, pnl=-773.5),
    ])
    assert net_record.report(db) == 0
    out = capsys.readouterr().out
    assert "THE RECORD, NET OF CHARGES" in out
    assert "BY UNDERLYING" in out
    assert "NATURALGAS" in out and "NIFTY" in out
    assert "brokerage" in out


def test_an_empty_ledger_says_so_rather_than_dividing_by_zero(tmp_path):
    db = _ledger(tmp_path, [])
    assert net_record.report(db) == 1
