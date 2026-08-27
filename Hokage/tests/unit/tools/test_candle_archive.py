"""Hokage's measurable history was shrinking. Keep the candles.

2026-08-27, 08:15. The gas sweep reported TRAIN n=3 where the same sweep had
reported n=55 twelve hours earlier. Nothing about the market changed — the
front-month contract rolled overnight:

    NATURALGAS26SEPFUT   3500 bars   from 2026-05-20   <- today's front month
    NATURALGAS26OCTFUT   2825 bars   from 2026-05-27
    NATURALGAS26NOVFUT   1787 bars   from 2026-05-29

A futures contract has no history from before it listed, and an expired one is
DELISTED along with its token, so its tape becomes unfetchable forever.
RangeFade/NATURALGAS measured +2.35 train / +2.67 hold-out on 08-26; on 08-27
the same pair on the same code read +2.44 / +1.08, because three weeks of the
train window had ceased to exist.

That is fatal to a system whose whole method is measurement. Every week Hokage
should know MORE; instead his evidence evaporated on a schedule nobody watched.
It is worst exactly where it hurts most: the EIA storage event has 12 usable
Thursdays today, and would still have had 12 next year, because the retrievable
window slides forward as fast as it fills.

TWO THINGS THIS FILE PROTECTS.

  1. NOTHING IS EVER OVERWRITTEN. INSERT OR IGNORE, never REPLACE. A bar already
     written is the record of what the tape said; a re-fetch through a different
     contract carries different absolute prices for the same underlying and must
     not silently rewrite history.

  2. NO INDICATOR IS COMPUTED ACROSS A ROLL SEAM. Two contracts trade at
     different prices, so an EMA or ATR whose trailing window spans the join is
     measuring the roll rather than the market. The first sessions of each new
     contract are dropped. A gap in the series is honest; a spliced indicator is
     a fabricated number, and this codebase has already paid twice for those —
     the 1.5%-of-price ATR and the flat 1,000-rupee trail.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "candle_archive", ROOT / "tools" / "research" / "candle_archive.py"
)
ca = importlib.util.module_from_spec(_spec)
sys.modules["candle_archive"] = ca
_spec.loader.exec_module(ca)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "DB", tmp_path / "candles.db")
    return ca


def bar(day: str, hour: int, close: float):
    return {"date": dt.datetime.strptime(f"{day} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S"),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 100.0}


def session(day: str, close: float, hours=range(9, 15)):
    return [bar(day, h, close) for h in hours]


# ------------------------------------------------------------- write and read
def test_bars_written_can_be_read_back(archive):
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="SEP")
    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    assert len(got) == 6
    assert got[0]["close"] == 300.0


def test_a_rewrite_never_changes_a_stored_bar(archive):
    """The load-bearing guarantee. September's contract prices gas differently
    from August's; a re-fetch must not rewrite what August recorded."""
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="AUG")
    archive.remember("NATURALGAS", session("2026-08-20", 999.0), contract="SEP")

    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    assert {b["close"] for b in got} == {300.0}
    assert {b["contract"] for b in got} == {"AUG"}


def test_new_bars_merge_without_disturbing_old_ones(archive):
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="AUG")
    added = archive.remember("NATURALGAS", session("2026-08-21", 310.0), contract="AUG")
    assert added == 6
    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    assert len(got) == 12


def test_remembering_nothing_is_not_an_error(archive):
    assert archive.remember("NATURALGAS", []) == 0


def test_a_range_with_no_data_returns_empty(archive):
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="AUG")
    assert archive.load("NATURALGAS", "2026-01-01 00:00:00", "2026-01-31 00:00:00") == []


def test_symbols_do_not_bleed_into_each_other(archive):
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="AUG")
    archive.remember("CRUDEOIL", session("2026-08-20", 5800.0), contract="AUG")
    gas = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    assert {b["close"] for b in gas} == {300.0}


# --------------------------------------------------------------- roll seams
def test_the_first_sessions_of_a_new_contract_are_dropped(archive):
    """An EMA21 reads 42 bars — roughly a session and a half of MCX tape. If the
    window spans a roll it is measuring a price discontinuity, not a trend."""
    for day, close in (("2026-08-24", 300.0), ("2026-08-25", 301.0)):
        archive.remember("NATURALGAS", session(day, close), contract="AUG")
    for day, close in (("2026-08-26", 350.0), ("2026-08-27", 351.0),
                       ("2026-08-28", 352.0)):
        archive.remember("NATURALGAS", session(day, close), contract="SEP")

    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    days = sorted({b["date"].date() for b in got})
    assert dt.date(2026, 8, 26) not in days, "first session after the roll"
    assert dt.date(2026, 8, 27) not in days, "second session after the roll"
    assert dt.date(2026, 8, 28) in days, "settled, and must survive"
    assert dt.date(2026, 8, 25) in days, "the old contract is untouched"


def test_the_earliest_contract_is_not_treated_as_a_roll(archive):
    """Nothing precedes the first contract in the series, so there is no seam
    and dropping its opening sessions would just discard good tape."""
    for day in ("2026-08-24", "2026-08-25", "2026-08-26"):
        archive.remember("NATURALGAS", session(day, 300.0), contract="AUG")
    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    assert len({b["date"].date() for b in got}) == 3


def test_a_single_contract_series_is_returned_whole(archive):
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="SEP")
    assert len(archive.load("NATURALGAS", "2026-08-01 00:00:00",
                            "2026-08-31 23:59:00")) == 6


def test_dropping_seams_from_nothing_is_safe(archive):
    assert archive._drop_roll_seams([]) == []


def test_two_settle_sessions_covers_the_longest_indicator_window(archive):
    """42 bars is the longest trailing window any module uses (EMA21). An MCX
    session is ~58 fifteen-minute bars, so two sessions clears it."""
    assert archive.SETTLE_SESSIONS * 58 > 42


# ------------------------------------------------------- shape and contract
def test_loaded_bars_match_the_shape_kite_returns(archive):
    """The archive is a drop-in for load_bars; a missing key would break every
    lab at once, in the middle of a measurement."""
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="SEP")
    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")[0]
    for key in ("date", "open", "high", "low", "close", "volume"):
        assert key in got, key
    assert isinstance(got["date"], dt.datetime)


def test_every_bar_records_which_contract_it_came_from(archive):
    archive.remember("NATURALGAS", session("2026-08-20", 300.0), contract="SEP")
    got = archive.load("NATURALGAS", "2026-08-01 00:00:00", "2026-08-31 23:59:00")
    assert all(b["contract"] == "SEP" for b in got)


def test_sync_does_not_route_through_the_archive_reader():
    """load_bars reads the archive FIRST and falls back to Kite. If sync went
    through it, the archive would be asked to fill itself and would stay
    permanently empty — silently, since an empty archive looks like a quiet
    market rather than an error.

    Checked by walking the AST, not by grepping the text: the comment that
    EXPLAINS this rule names load_bars, and a text scan cannot tell a rule from
    a description of one. That is the same trap a guard test fell into on
    2026-08-22.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(ca.sync)))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_fetch_from_kite" in called
    assert "load_bars" not in called
