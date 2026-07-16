"""Plain-language EOD report a non-trader can understand. Numbers are never
invented — every figure comes straight from the trade record."""
from __future__ import annotations

from bots.autonomous.plain_report import (
    humanize_instrument,
    explain_exit_reason,
    build_plain_report,
)


def test_humanize_call_and_put():
    assert "Nifty CALL" in humanize_instrument("NIFTY2672124150CE")
    assert "go UP" in humanize_instrument("NIFTY2672124150CE")
    assert "Bank Nifty PUT" in humanize_instrument("BANKNIFTY2672150000PE")
    assert "go DOWN" in humanize_instrument("BANKNIFTY2672150000PE")


def test_explain_exit_reasons_are_plain():
    assert "market closed" in explain_exit_reason("Time-Based Square-Off (EOD)")
    assert "profit target" in explain_exit_reason("TARGET_HIT: premium ...")
    assert "locked in" in explain_exit_reason("PROFIT_LOCK(+20% armed) ...")
    assert "cut the loss" in explain_exit_reason("Underlying Thesis Stop ...") or "wrong way" in explain_exit_reason("Underlying Thesis Stop ...")
    assert "yourself" in explain_exit_reason("Commander instant-exit (hard sell)")


def test_report_no_trades():
    out = build_plain_report([], [], "Friday, 17 Jul 2026")
    assert "No trades today" in out


def test_report_counts_winners_and_net():
    closed = [
        {"symbol": "NIFTY2672124150CE", "entry_price": 124.0, "exit_price": 96.75, "quantity": 65, "pnl": -1771.25, "exit_reason": "Underlying Thesis Stop"},
        {"symbol": "BANKNIFTY2672150000PE", "entry_price": 100.0, "exit_price": 130.0, "quantity": 30, "pnl": 900.0, "exit_reason": "TARGET_HIT"},
    ]
    out = build_plain_report(closed, [], "Friday, 17 Jul 2026")
    assert "1 of 2 made money" in out
    # Net: -1771.25 + 900 = -871.25 -> lost
    assert "lost" in out
    assert "871" in out
    # Each trade explained in plain language
    assert "Nifty CALL" in out
    assert "Bank Nifty PUT" in out


def test_report_shows_open_positions():
    out = build_plain_report(
        [],
        [{"symbol": "NIFTY2672124100PE", "entry_price": 133.85, "current_price": 140.0, "quantity": 65, "unrealized_pnl": 400.0}],
        "Friday, 17 Jul 2026",
    )
    assert "Still open" in out
    assert "up ₹400" in out
