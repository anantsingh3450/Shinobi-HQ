"""The funding decision was never checked against what the account did.

On 2026-11-09 three cells were funded and four assets parked on one
comparison - a hold-out edge in ATR converted to percent of premium, against
the measured cost of a round trip - and `funded_cells` calls the agreement
between its two methods "the strongest thing in the file". Both methods are
model-side. The ledger holds real fills and was never consulted.

THE DEFECTS THESE TESTS PIN DOWN

1. THE TRANSFER CONSTANT WAS POOLED. Every edge-in-premium figure came from
   one slope, 3.31% of premium per ATR, fitted across all assets at once -
   which `transfer_lab` warns against in its own docstring, and which was
   applied to SILVERM on a fit containing one SILVERM trade. A per-asset fit
   that silently collapsed back to a pooled one would reproduce the defect
   while appearing to have fixed it, so the fit is tested on two assets built
   with deliberately different slopes.

2. NONE IS NOT ZERO. Before schema 10 the ledger records no charges, and a
   missing figure means "estimate it", never "this trade was free" - the same
   lesson as the missing `strategy_id`.

3. A TOOL THAT READS MUST NOT WRITE. The source rail matches SQL statements
   rather than words, because a bare "INSERT" check fires on `sys.path.insert`
   and passes for the wrong reason.

4. THE TWO HALVES HAVE DIFFERENT n. A hold the candle archive cannot span has
   a net percent but no ATR move. One `n` over both overstates the weaker
   half.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sqlite3
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "model_vs_ledger", ROOT / "tools" / "research" / "model_vs_ledger.py")
mvl = importlib.util.module_from_spec(_spec)
sys.modules["model_vs_ledger"] = mvl
_spec.loader.exec_module(mvl)

SOURCE = (ROOT / "tools" / "research" / "model_vs_ledger.py").read_text(
    encoding="utf-8")

COLUMNS = ("position_id, account_id, market, direction, quantity, "
           "entry_price, current_price, unrealized_pnl, realized_pnl, "
           "status, opened_at, closed_at, playbook_id, failure_reason, "
           "volatility_regime, strategy_id")


def _ledger(path: pathlib.Path, rows, with_charges: bool = False):
    """A positions table shaped like the real one, at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = ", charges REAL" if with_charges else ""
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE positions (position_id TEXT, account_id TEXT, "
        "market TEXT, direction TEXT, quantity REAL, entry_price REAL, "
        "current_price REAL, unrealized_pnl REAL, realized_pnl REAL, "
        "status TEXT, opened_at TEXT, closed_at TEXT, playbook_id TEXT, "
        f"failure_reason TEXT, volatility_regime TEXT, strategy_id TEXT{extra})")
    names = COLUMNS + (", charges" if with_charges else "")
    marks = ", ".join("?" * (17 if with_charges else 16))
    con.executemany(
        f"INSERT INTO positions ({names}) VALUES ({marks})", rows)
    con.commit()
    con.close()
    return path


def _row(market="SILVERM26NOV197000PE", qty=5.0, entry=2000.0, exit_=2200.0,
         pnl=1000.0, status="CLOSED", failure=None, strategy="strat-x-v1",
         opened="2026-10-28T06:00:00", closed="2026-10-28T08:00:00",
         charges=None, with_charges=False):
    base = ["p1", "acct", market, "LONG", qty, entry, exit_, 0.0, pnl,
            status, opened, closed, None, failure, None, strategy]
    return tuple(base + ([charges] if with_charges else []))


class _Bars:
    """A candle archive stub: one symbol, evenly spaced closes."""

    def __init__(self, closes, atr=10.0):
        self._closes = closes
        self._atr = atr

    def of(self, symbol):
        return [{"ts": f"2026-10-28 {6 + i:02d}:00:00", "high": c, "low": c,
                 "close": c} for i, c in enumerate(self._closes)]

    def index_at(self, symbol, stamp):
        found = None
        for i, bar in enumerate(self.of(symbol)):
            if bar["ts"] <= stamp:
                found = i
            else:
                break
        return found

    def atr(self, symbol, idx, period=14):
        return None if idx is None else self._atr


# ======================================================= the statistics hold
def test_t_against_zero_is_the_textbook_figure():
    n, mean, t = mvl._t([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert n == 8
    assert mean == pytest.approx(5.0)
    # sd = 2.138..., se = 0.7559, t = 6.6143
    assert t == pytest.approx(6.6143, abs=1e-3)


def test_a_sample_that_never_varies_reports_t_zero_not_infinity():
    """Every value identical means no spread to divide by, not certainty."""
    _n, mean, t = mvl._t([3.0, 3.0, 3.0])
    assert mean == pytest.approx(3.0)
    assert t == 0.0


def test_one_observation_is_reported_as_one_not_as_a_result():
    n, mean, t = mvl._t([4.5])
    assert (n, mean, t) == (1, 4.5, 0.0)


def test_no_observations_do_not_raise():
    assert mvl._t([]) == (0, 0.0, 0.0)


def test_the_slope_recovers_a_line_it_was_given():
    pairs = [(1.0, 5.0), (2.0, 10.0), (3.0, 15.0), (4.0, 20.0)]
    n, slope, r = mvl._slope(pairs)
    assert n == 4
    assert slope == pytest.approx(5.0)
    assert r == pytest.approx(1.0)


def test_two_points_are_not_a_fit():
    assert mvl._slope([(1.0, 5.0), (2.0, 10.0)]) is None


def test_a_vertical_cloud_has_no_slope_rather_than_a_huge_one():
    """Every x identical: the slope is undefined, not enormous."""
    assert mvl._slope([(2.0, 1.0), (2.0, 5.0), (2.0, 9.0)]) is None


# ============================================ the fit is per asset, not pooled
def test_each_asset_gets_its_own_slope():
    """THE DEFECT. One constant across seven underlyings is what parked
    SILVERM on a fit containing one SILVERM trade."""
    rows = []
    for x in (1.0, 2.0, 3.0, 4.0):
        rows.append(mvl.Row("GOLDM", "s", "2026-10-28", 1000.0,
                            gross_pct=2.0 * x, cost_pct=0.3, atr_move=x))
        rows.append(mvl.Row("SILVERM", "s", "2026-10-28", 1000.0,
                            gross_pct=8.0 * x, cost_pct=0.3, atr_move=x))
    fitted = mvl.slopes_by_asset(rows)
    assert fitted["GOLDM"][1] == pytest.approx(2.0)
    assert fitted["SILVERM"][1] == pytest.approx(8.0)


def test_a_pooled_fit_would_have_given_neither_answer():
    """Mutation guard: collapsing the per-asset fit back to one slope must
    not be able to pass the test above."""
    pairs = []
    for x in (1.0, 2.0, 3.0, 4.0):
        pairs.extend([(x, 2.0 * x), (x, 8.0 * x)])
    _n, pooled, _r = mvl._slope(pairs)
    assert pooled == pytest.approx(5.0)
    assert pooled != pytest.approx(2.0)
    assert pooled != pytest.approx(8.0)


def test_an_asset_with_too_few_rows_is_absent_rather_than_guessed():
    rows = [mvl.Row("SILVERM", "s", "2026-10-28", 1000.0, 1.0, 0.3, 1.0),
            mvl.Row("SILVERM", "s", "2026-10-28", 1000.0, 2.0, 0.3, 2.0)]
    assert "SILVERM" not in mvl.slopes_by_asset(rows)


def test_rows_without_an_atr_move_do_not_enter_the_fit():
    rows = [mvl.Row("GOLDM", "s", "2026-10-28", 1000.0, 2.0 * x, 0.3, x)
            for x in (1.0, 2.0, 3.0)]
    rows.append(mvl.Row("GOLDM", "s", "2026-10-28", 1000.0, 99.0, 0.3, None))
    assert mvl.slopes_by_asset(rows)["GOLDM"] == (3, pytest.approx(2.0),
                                                  pytest.approx(1.0))


# ================================================== the ATR move is signed
def test_a_put_profits_when_the_underlying_falls():
    bars = _Bars([100.0, 95.0, 90.0], atr=10.0)
    move = mvl._atr_move(bars, "SILVERM26NOV197000PE", "SILVERM",
                         "2026-10-28T00:30:00", "2026-10-28T02:30:00")
    assert move == pytest.approx(+1.0)


def test_a_call_on_the_same_fall_is_the_opposite_sign():
    bars = _Bars([100.0, 95.0, 90.0], atr=10.0)
    move = mvl._atr_move(bars, "SILVERM26NOV197000CE", "SILVERM",
                         "2026-10-28T00:30:00", "2026-10-28T02:30:00")
    assert move == pytest.approx(-1.0)


def test_a_hold_inside_one_bar_is_dropped_not_recorded_as_zero_move():
    """A window inside a single bar has a move of exactly zero by
    construction. That is not an observation."""
    bars = _Bars([100.0, 95.0, 90.0], atr=10.0)
    assert mvl._atr_move(bars, "SILVERM26NOV197000PE", "SILVERM",
                         "2026-10-28T00:30:00", "2026-10-28T01:00:00") is None


def test_no_atr_means_no_row_rather_than_a_division():
    class _NoAtr(_Bars):
        def atr(self, symbol, idx, period=14):
            return None
    assert mvl._atr_move(_NoAtr([100.0, 95.0, 90.0]),
                         "SILVERM26NOV197000PE", "SILVERM",
                         "2026-10-28T00:30:00", "2026-10-28T02:30:00") is None


def test_a_missing_timestamp_is_not_measured():
    bars = _Bars([100.0, 95.0, 90.0])
    assert mvl._atr_move(bars, "SILVERM26NOV197000PE", "SILVERM",
                         "", "2026-10-28T02:30:00") is None


def test_the_ledger_stamp_is_converted_to_the_archive_clock():
    """The ledger stamps UTC and the archive stamps naive IST. Without the
    conversion every window lands five and a half hours earlier."""
    bars = _Bars([100.0, 95.0, 90.0], atr=10.0)
    # 00:30 UTC is 06:00 IST, the first bar. Read as IST it precedes every
    # bar, so no index is found and nothing is measured.
    assert mvl._atr_move(bars, "SILVERM26NOV197000PE", "SILVERM",
                         "2026-10-28T00:30:00", "2026-10-28T02:30:00") is not None
    assert bars.index_at("SILVERM", "2026-10-28 00:30:00") is None


# ============================================== the ledger is read faithfully
def test_phantoms_are_excluded_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "a" / "hokage.db", [
        _row(pnl=1000.0),
        _row(pnl=5000.0, failure="PHANTOM: reduce-only runaway"),
    ])
    rows, phantoms, _no_atr = mvl.read_rows(db)
    assert len(rows) == 1
    assert phantoms == 1
    assert rows[0].gross_pct == pytest.approx(10.0)


def test_a_recorded_charge_is_preferred_to_the_estimate(tmp_path, monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "b" / "hokage.db",
                 [_row(charges=500.0, with_charges=True)],
                 with_charges=True)
    rows, _p, _n = mvl.read_rows(db)
    # 500 against a premium of 5 x 2000 = 10,000.
    assert rows[0].cost_pct == pytest.approx(5.0)


def test_a_null_charge_means_estimate_it_not_that_it_was_free(tmp_path,
                                                              monkeypatch):
    """NONE IS NOT ZERO. The column is NULL for every trade before schema 10."""
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "c" / "hokage.db",
                 [_row(charges=None, with_charges=True)], with_charges=True)
    rows, _p, _n = mvl.read_rows(db)
    assert rows[0].cost_pct > 0.0


def test_a_ledger_without_the_column_still_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "d" / "hokage.db", [_row()])
    rows, _p, _n = mvl.read_rows(db)
    assert rows[0].cost_pct > 0.0


def test_a_position_with_no_premium_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "e" / "hokage.db", [_row(entry=0.0)])
    rows, _p, _n = mvl.read_rows(db)
    assert rows == []


def test_unmeasurable_holds_are_counted_not_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "f" / "hokage.db", [_row(), _row()])
    rows, _p, no_atr = mvl.read_rows(db)
    assert len(rows) == 2 and no_atr == 2
    assert all(r.atr_move is None for r in rows)


def test_the_strategy_id_is_shortened_but_not_invented(tmp_path, monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "g" / "hokage.db", [
        _row(strategy="strat-sessionshift-mcx-v1"),
        _row(strategy=None),
    ])
    rows, _p, _n = mvl.read_rows(db)
    assert {r.strategy for r in rows} == {"sessionshift-mcx", "unattributed"}


def test_net_is_gross_less_cost():
    row = mvl.Row("SILVERM", "s", "2026-10-28", 1000.0, 3.40, 0.34, None)
    assert row.net_pct == pytest.approx(3.06)


# ================================================ it reads, and never writes
def test_the_tool_never_writes():
    """Matches SQL statements, not words: a bare "INSERT" check fires on
    `sys.path.insert` and would pass for the wrong reason."""
    stripped = re.sub(r'(?s)""".*?"""', "", SOURCE)
    stripped = re.sub(r"#.*", "", stripped)
    forbidden = re.compile(
        r"""(?ix) (?: ^ | ["'\s(] )
            (?: INSERT \s+ INTO | UPDATE \s+ \w | DELETE \s+ FROM
              | DROP \s+ TABLE | ALTER \s+ TABLE | CREATE \s+ TABLE )""")
    assert not forbidden.search(stripped)


def test_the_rail_above_would_catch_a_real_write():
    stripped = 'con.execute("UPDATE positions SET charges = 0")'
    forbidden = re.compile(
        r"""(?ix) (?: ^ | ["'\s(] )
            (?: INSERT \s+ INTO | UPDATE \s+ \w | DELETE \s+ FROM
              | DROP \s+ TABLE | ALTER \s+ TABLE | CREATE \s+ TABLE )""")
    assert forbidden.search(stripped)


def test_the_rail_above_ignores_a_path_insert():
    forbidden = re.compile(
        r"""(?ix) (?: ^ | ["'\s(] )
            (?: INSERT \s+ INTO | UPDATE \s+ \w | DELETE \s+ FROM
              | DROP \s+ TABLE | ALTER \s+ TABLE | CREATE \s+ TABLE )""")
    assert not forbidden.search('sys.path.insert(0, str(ROOT / "src"))')


def test_the_ledger_is_opened_read_only():
    assert "mode=ro" in SOURCE


# ============================================ the basis is stated, not recalled
def test_the_carried_numbers_say_where_they_came_from():
    assert "power_lab" in mvl.BASIS and "2026-11-09" in mvl.BASIS


def test_every_underlying_in_the_universe_has_an_edge_and_a_spread():
    assert set(mvl.BEST_EDGE_ATR) == set(mvl.SPREAD_PCT)


def test_the_pooled_constant_is_kept_so_the_per_asset_fit_can_be_read_against_it():
    assert mvl.POOLED_SLOPE == 3.31


# ===================================================== it runs end to end
def test_the_report_runs_and_names_the_asset(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mvl.TL, "Bars",
                        lambda: _Bars([100.0, 95.0, 90.0, 85.0], atr=10.0))
    rows = [_row(pnl=float(p), opened="2026-10-28T00:30:00",
                 closed="2026-10-28T02:30:00") for p in (900, 1100, -400, 700)]
    db = _ledger(tmp_path / "h" / "hokage.db", rows)
    assert mvl.report(db) == 0
    out = capsys.readouterr().out
    assert "SILVERM" in out
    assert "THE MODEL AGAINST THE LEDGER" in out
    assert "4 real closed positions" in out


def test_an_empty_ledger_says_so_rather_than_printing_a_verdict(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(mvl.TL, "Bars", lambda: _Bars([]))
    db = _ledger(tmp_path / "i" / "hokage.db", [])
    assert mvl.report(db) == 1


def test_a_missing_ledger_is_reported_rather_than_crashing(tmp_path):
    assert mvl.main(["--db", str(tmp_path / "nope.db")]) == 1
