"""Every lab here scores edge_atr, and Hokage buys options.

The caveat has been in the docstrings since the beginning - "edge_atr measures
the UNDERLYING's forward move, not option P&L" - and nobody had measured the
conversion, so a gate whose blocked set differed by 0.3 ATR sounded decisive
next to a ship bar of t=2 without anyone knowing whether 0.3 ATR was worth a
tick of premium or a rupee.

THE DEFECT THESE TESTS PIN DOWN
The obvious way to measure it is the premium path's first and last mark, and it
is wrong. Marks stop when the position closes, so the last mark is the last
POLL before the exit, not the exit - and the ladder fires ON an adverse move,
so the poll that triggers an exit is usually followed by a worse fill. Measured
across 22 paths on 2026-11-07 the last mark sat above the realised exit in 15
of them, and fitting on last marks produced a POSITIVE intercept: a long option
gaining value at zero underlying move, over a holding period of theta.

The other way to get a wrong answer is the clock. The ledger stamps UTC and the
candle archive stamps naive IST, so a missing conversion shifts every window by
five and a half hours and measures bars from a different part of the session.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "transfer_lab", ROOT / "tools" / "research" / "transfer_lab.py")
tl = importlib.util.module_from_spec(_spec)
sys.modules["transfer_lab"] = _spec and tl
_spec.loader.exec_module(tl)

#: The real 16:15 gas trade of 2026-11-06.
GAS_CE = "NATURALGAS26NOV285CE"
GAS_PE = "NATURALGAS26NOV285PE"


def _recs(points):
    """(underlying ATR, premium percent) pairs as fit() takes them."""
    return [{"und_atr": x, "prem_pct": y, "day": "2026-11-06", "span": 4,
             "option": GAS_CE, "underlying": "NATURALGAS",
             "strategy": "strat-rangefade-mcx-v1", "pnl": 0.0}
            for x, y in points]


# ===================================================== the contract is parsed
def test_the_underlying_is_read_off_the_contract():
    assert tl.underlying_of(GAS_CE) == "NATURALGAS"
    assert tl.underlying_of("GOLDM26NOV138500PE") == "GOLDM"
    assert tl.underlying_of("SILVERM26OCT196000PE") == "SILVERM"


def test_a_contract_that_is_not_one_is_refused_not_guessed():
    assert tl.underlying_of("") is None
    assert tl.underlying_of("NOTANOPTION") is None


def test_a_call_is_long_the_underlying_and_a_put_is_short():
    """THE SIGN THAT DECIDES EVERY ROW. Crossing these inverts the slope and
    turns a working conversion into a negative one."""
    assert tl.side_of(GAS_CE) == 1
    assert tl.side_of(GAS_PE) == -1


# ============================================================ the clock is UTC
def test_a_ledger_stamp_is_converted_from_utc_to_ist():
    """positions.opened_at is UTC; the archive is keyed by naive IST. The real
    10:30 IST fill of 2026-11-06 is stored as 05:00:37."""
    assert tl._ist("2026-11-06T05:00:37.123456+00:00") == "2026-11-06 10:30:37"


def test_the_conversion_crosses_midnight_correctly():
    assert tl._ist("2026-11-06T19:00:00") == "2026-11-07 00:30:00"


def test_an_unparseable_stamp_does_not_crash_the_run():
    assert tl._ist("not-a-date") == "not-a-date"


def test_the_offset_is_five_and_a_half_hours():
    assert tl.IST_OFFSET.total_seconds() == 5.5 * 3600


# ================================================= a hold must span real bars
def test_a_hold_inside_one_bar_is_not_an_observation():
    """An underlying move measured inside a single 15-minute bar is exactly
    zero by construction. Six of the 22 paths on 2026-11-07 were like this and
    they only piled noise around the origin."""
    assert tl.MIN_SPAN_BARS >= 2


# ====================================================== the fit is arithmetic
def test_a_perfect_line_recovers_its_own_slope():
    f = tl.fit(_recs([(1.0, 3.0), (2.0, 6.0), (3.0, 9.0), (4.0, 12.0)]))
    assert f["slope"] == pytest.approx(3.0)
    assert f["intercept"] == pytest.approx(0.0, abs=1e-9)
    assert f["r"] == pytest.approx(1.0)


def test_an_inverted_relationship_reports_a_negative_slope():
    f = tl.fit(_recs([(1.0, -3.0), (2.0, -6.0), (3.0, -9.0)]))
    assert f["slope"] < 0 and f["r"] == pytest.approx(-1.0)


def test_two_points_are_too_few_to_fit():
    assert tl.fit(_recs([(1.0, 3.0), (2.0, 6.0)])) is None


def test_no_points_is_none_not_an_error():
    assert tl.fit([]) is None


def test_a_flat_underlying_column_cannot_be_divided_by():
    """All rows at the same ATR has no slope, and must not raise."""
    assert tl.fit(_recs([(1.0, 3.0), (1.0, 6.0), (1.0, 9.0)])) is None


def test_a_flat_premium_column_is_refused_too():
    assert tl.fit(_recs([(1.0, 2.0), (2.0, 2.0), (3.0, 2.0)])) is None


def test_sign_agreement_counts_rows_that_moved_together():
    f = tl.fit(_recs([(1.0, 3.0), (2.0, 6.0), (-1.0, +1.0), (-2.0, -5.0)]))
    assert f["sign_agreement"] == 3


def test_the_intercept_is_reported_not_forced_through_zero():
    """A forced zero intercept would hide the thing worth seeing: what a long
    option does when the underlying does nothing."""
    f = tl.fit(_recs([(1.0, 5.0), (2.0, 8.0), (3.0, 11.0)]))
    assert f["intercept"] == pytest.approx(2.0)


# ============================================ the report says what it cannot say
def test_an_empty_corpus_says_it_cannot_be_backfilled(capsys):
    tl.report([], [0.3])
    out = capsys.readouterr().out
    assert "Nothing to fit" in out
    assert "cannot be backfilled" in out


def test_a_positive_intercept_is_flagged_as_unexplained(capsys):
    tl.report(_recs([(1.0, 5.0), (2.0, 8.0), (3.0, 11.0)]), [0.3])
    out = capsys.readouterr().out
    assert "unexplained" in out


def test_the_report_converts_a_measured_edge_into_premium(capsys):
    tl.report(_recs([(1.0, 3.0), (2.0, 6.0), (3.0, 9.0)]), [0.318])
    out = capsys.readouterr().out
    assert "+0.318" in out and "WHAT A MEASURED EDGE IS WORTH" in out


def test_the_report_carries_its_own_n_and_caveat(capsys):
    tl.report(_recs([(1.0, 3.0), (2.0, 6.0), (3.0, 9.0)]), [0.3])
    out = capsys.readouterr().out
    assert "n = 3" in out
    assert "no premium path" in out


# ====================================================== fidelity to the ledger
def test_the_slope_is_fitted_on_the_realised_exit_not_the_last_mark():
    """THE DEFECT. The last mark is the last poll BEFORE the exit, and it sat
    above the realised fill in 15 of 22 paths."""
    src = (ROOT / "tools" / "research" / "transfer_lab.py").read_text(encoding="utf-8")
    assert "current_price" in src              # the ledger's exit price
    assert "ORDER BY observed_at DESC" not in src   # never "the last mark"


def test_only_closed_positions_with_an_archived_path_are_measured():
    """An open position has no exit, and a position with no path is a premium
    nobody polled - it would be an inferred number dressed as a measured one."""
    src = (ROOT / "tools" / "research" / "transfer_lab.py").read_text(encoding="utf-8")
    assert "status = 'CLOSED'" in src
    assert "position_marks" in src


def test_the_atr_is_the_same_formula_production_uses():
    src = (ROOT / "tools" / "research" / "transfer_lab.py").read_text(encoding="utf-8")
    assert 'max(c["high"] - c["low"]' in src
    assert 'abs(c["high"] - p["close"])' in src
