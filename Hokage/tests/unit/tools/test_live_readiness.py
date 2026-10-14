"""The +19,737 was a bug's accounting artifact, and everyone believed it.

2026-10-14, the commander asked why Hokage cannot generate wealth. The answer
was in his own ledger and nobody had ever assembled it:

    all 382 closed positions          +19,737   PF 1.22   win 62.4%
    excluding the 2026-07-15 cascade   -7,033   PF 0.92   win 39.3%

208 of those 382 were the reduce_only runaway, opening and closing the same
CRUDEOIL strike within two minutes at zero P&L. Strip that one day and the
lifetime record is NEGATIVE. Every "Hokage is up 19,737" reading was an
artifact of a defect that was fixed months ago.

This scorecard exists so that reading cannot happen again, and so "are we
ready for real money" is answered by arithmetic against the commander's own
agreed bar rather than by feeling ready.

THE NUMBER MUST BE READABLE OR IT IS NOT A NUMBER. The first version measured
drawdown against peak PROFIT and printed "150798.9%" - arithmetically correct,
meaningless, and worse than no number at all. A drawdown limit has only ever
meant a fraction of the money at risk.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "live_readiness", ROOT / "tools" / "research" / "live_readiness.py"
)
lr = importlib.util.module_from_spec(_spec)
sys.modules["live_readiness"] = lr
_spec.loader.exec_module(lr)


def _pos(pnl, opened="2026-08-20T10:00:00+00:00", account="paper_mcx"):
    return {
        "realized_pnl": pnl, "opened_at": opened,
        "closed_at": opened, "account_id": account,
    }


# ------------------------------------------- zero-P&L rows are not trades
def test_zero_pnl_rows_are_excluded_from_the_ratios():
    """208 positions opened and closed at the same price inside two minutes.
    Counting them as losses drags the win rate down while no money moved;
    counting them as trades inflates the sample."""
    rows = [_pos(100), _pos(-50)] + [_pos(0) for _ in range(20)]
    m = lr.measure(rows, 250_000)
    assert m["n"] == 2
    assert m["flats"] == 20


def test_the_flats_are_reported_not_silently_dropped():
    """A sample that quietly shrank from 382 to 173 would be its own lie."""
    m = lr.measure([_pos(100)] + [_pos(0) for _ in range(5)], 250_000)
    assert m["flats"] == 5


# --------------------------------------------- drawdown against capital
def test_drawdown_is_measured_against_capital_not_peak_profit():
    """THE UNREADABLE NUMBER. Peak profit of 20 and a drawdown of 32,799 is
    '163995% of peak', which tells nobody anything."""
    rows = [_pos(20), _pos(-32_799)]
    m = lr.measure(rows, 250_000)
    assert m["max_drawdown"] == pytest.approx(32_819, rel=1e-3)
    assert m["max_drawdown_pct"] == pytest.approx(100 * 32_819 / 250_000, rel=1e-3)
    assert m["max_drawdown_pct"] < 100


def test_the_peak_based_figure_is_kept_but_never_the_gate():
    """Useful context, clearly named, not the criterion."""
    m = lr.measure([_pos(20), _pos(-32_799)], 250_000)
    assert m["max_drawdown_pct_of_peak"] > 1000
    assert m["max_drawdown_pct"] < 100


def test_capital_is_the_sum_of_the_accounts_actually_used():
    both = lr.capital_for([_pos(1, account="paper"), _pos(1, account="paper_mcx")])
    assert both == 250_000
    assert lr.capital_for([_pos(1, account="paper")]) == 50_000
    assert lr.capital_for([_pos(1, account="paper_mcx")]) == 200_000


def test_an_unknown_account_does_not_produce_a_zero_base():
    """Dividing by a zero base would make the drawdown check pass by accident,
    which is the one direction this must never fail in."""
    cap = lr.capital_for([_pos(1, account="something_new")])
    assert cap > 0


# ------------------------------------------------------- the ratios
def test_profit_factor_and_expectancy():
    m = lr.measure([_pos(300), _pos(300), _pos(-200)], 250_000)
    assert m["profit_factor"] == pytest.approx(3.0)
    assert m["expectancy"] == pytest.approx(400 / 3)
    assert m["win_rate"] == pytest.approx(200 / 3)


def test_a_losing_record_reports_a_profit_factor_below_one():
    m = lr.measure([_pos(100), _pos(-300)], 250_000)
    assert m["profit_factor"] < 1


def test_sharpe_is_none_on_a_single_trade():
    """One trade has no deviation. A Sharpe from it would be invented."""
    assert lr.measure([_pos(100)], 250_000)["sharpe"] is None


def test_an_empty_record_does_not_invent_numbers():
    m = lr.measure([], 250_000)
    assert m["n"] == 0
    assert "profit_factor" not in m


# ----------------------------------------------- the bar is the commander's
def test_the_bar_matches_what_was_agreed():
    """Sharpe >= 1.20, PF >= 1.30, drawdown <= 8%. If any of these drift, the
    gate stops meaning what the commander agreed to on 2026-07-15."""
    assert lr.MIN_SHARPE == 1.20
    assert lr.MIN_PROFIT_FACTOR == 1.30
    assert lr.MAX_DRAWDOWN_PCT == 8.0


def test_a_confirmed_cell_needs_the_same_t_as_everything_else_ships_on():
    assert lr.SHIP_BAR_T == 2.0


def test_a_verdict_needs_a_sample():
    """89 round trips is already thin. A profit factor from 5 trades is
    arithmetic on noise, and the gate must say so rather than pass."""
    assert lr.MIN_TRADES_FOR_A_VERDICT >= 30


def test_the_cascade_day_is_named_so_it_can_never_be_quietly_included():
    assert lr.CASCADE_DAY == "2026-07-15"


# ----------------------------------------------------- it reads the real audit
def _snapshot(tmp_path, monkeypatch, measurements, ship_bar=2.0):
    """A crafted audit snapshot. Hermetic on purpose: the suite must not read
    the real brain, and a test that passes only on this machine's data proves
    nothing about the code."""
    import json

    d = tmp_path / "snapshots"
    d.mkdir()
    (d / "2026-10-12.json").write_text(
        json.dumps({"ship_bar": ship_bar, "measurements": measurements}),
        encoding="utf-8",
    )
    monkeypatch.setattr(lr, "SNAPSHOTS", d)
    return d


def test_confirmed_cells_reads_the_newest_snapshot(tmp_path, monkeypatch):
    """The one honest claim Hokage can make - one cell at t=+2.15 - must come
    from the audit, never from a constant typed in here."""
    _snapshot(tmp_path, monkeypatch, {
        "SILVERM": {"entry-sessionshift-mcx-v1": {"n": 218, "edge_atr": 0.252, "t": 2.15}},
        "GOLDM": {"entry-sessionshift-mcx-v1": {"n": 85, "edge_atr": 0.247, "t": 1.29}},
    })
    total, names, snap = lr.confirmed_cells()
    assert total == 2
    assert snap == "2026-10-12"
    assert len(names) == 1
    assert "SILVERM" in names[0] and "t=+2.15" in names[0] and "n=218" in names[0]


def test_a_cell_just_under_the_bar_is_not_confirmed(tmp_path, monkeypatch):
    """t=+1.99 is not an edge. The bar is the bar."""
    _snapshot(tmp_path, monkeypatch, {
        "GOLDM": {"entry-sessionshift-mcx-v1": {"n": 85, "edge_atr": 0.2, "t": 1.99}},
    })
    total, names, _ = lr.confirmed_cells()
    assert total == 1 and names == []


def test_a_cell_with_no_t_is_not_counted_as_confirmed(tmp_path, monkeypatch):
    """Unmeasured must never read as passed."""
    _snapshot(tmp_path, monkeypatch, {
        "GOLDM": {"entry-sessionshift-mcx-v1": {"n": 3, "edge_atr": None, "t": None}},
    })
    total, names, _ = lr.confirmed_cells()
    assert total == 1 and names == []


def test_no_snapshots_at_all_reports_zero_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "SNAPSHOTS", tmp_path / "nothing")
    assert lr.confirmed_cells() == (0, [], None)
