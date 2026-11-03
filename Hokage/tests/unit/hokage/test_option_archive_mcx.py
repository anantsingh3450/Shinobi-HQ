"""MCX trades eight hours past the index close, and one SESSION_END judged both.

2026-11-03. The mirror experiment — "every time it takes a call, take a put" —
had run for eleven days on natural gas and could not be settled. A mirror only
wins where its original was wrong about DIRECTION rather than about MOVEMENT,
and since both sides BUY options and both pay theta, that distinction exists
only in premium terms. The losing side never fills, so it has no premium path,
and `option_chain` held NIFTY and SENSEX only. There was nothing to price it
from, so the experiment could not answer its own question.

Adding MCX to the archive brought a trap with it. `is_after_close` compared
against a single 15:30, so a chain captured at 16:00 would be stamped a CLOSE
for NIFTY — correctly — and also for NATURALGAS, which has another seven and a
half hours to trade. Mid-session premium would have entered the corpus wearing
a settle's clothes, and every later study would have inherited it silently.

The scheduled capture runs at 23:40, after both markets, so this only bites a
manual run — which is precisely when someone is looking at the numbers and
most likely to trust them.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import option_archive as oa

ROOT = Path(__file__).resolve().parents[3]

IST = ZoneInfo("Asia/Kolkata")
#: 16:00 — NIFTY has closed, MCX has not. The whole point.
BETWEEN = dt.datetime(2026, 11, 3, 16, 0, tzinfo=IST)
#: 23:40, when the scheduled capture runs: both markets shut.
AFTER_BOTH = dt.datetime(2026, 11, 3, 23, 40, tzinfo=IST)
MIDDAY = dt.datetime(2026, 11, 3, 11, 0, tzinfo=IST)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return oa


def _row(symbol="NATURALGAS", strike=275.0, option_type="CE", price=18.4):
    return {"symbol": symbol, "expiry": dt.date(2026, 11, 20), "strike": strike,
            "option_type": option_type, "last_price": price,
            "oi": 1200.0, "volume": 90.0, "spot": 276.3}


# ----------------------------------------- when does a session end
def test_mcx_closes_at_2330_not_1530():
    assert oa.session_end_for("NATURALGAS") == dt.time(23, 30)
    assert oa.session_end_for("GOLDM") == dt.time(23, 30)
    assert oa.session_end_for("SILVERM") == dt.time(23, 30)
    assert oa.session_end_for("CRUDEOIL") == dt.time(23, 30)


def test_the_index_keeps_1530():
    assert oa.session_end_for("NIFTY") == dt.time(15, 30)
    assert oa.session_end_for("SENSEX") == dt.time(15, 30)


def test_an_unknown_symbol_gets_the_earlier_close():
    """The permissive answer. A symbol nobody has mapped is never silently
    excluded from the corpus; at worst it is stamped too generously, and the
    calendar still guards whether the day traded at all."""
    assert oa.session_end_for("SOMETHINGNEW") == dt.time(15, 30)
    assert oa.session_end_for(None) == dt.time(15, 30)


# ----------------------------------------- the 16:00 trap
def test_at_1600_the_index_has_closed_and_mcx_has_not():
    assert oa.is_after_close(BETWEEN, "NIFTY") is True
    assert oa.is_after_close(BETWEEN, "NATURALGAS") is False


def test_at_2340_both_are_shut():
    assert oa.is_after_close(AFTER_BOTH, "NIFTY") is True
    assert oa.is_after_close(AFTER_BOTH, "NATURALGAS") is True


def test_no_symbol_still_answers_for_the_index():
    """Every caller that predates MCX meant the index session."""
    assert oa.is_after_close(BETWEEN) is True
    assert oa.is_after_close(MIDDAY) is False


# ----------------------------------------- what reaches a measurement
def test_a_1600_mcx_capture_is_not_a_close(archive):
    archive.remember([_row()], BETWEEN)
    assert archive.closing_snapshots() == [], \
        "mid-session MCX premium entered the corpus as a day's settle"


def test_a_1600_index_capture_is_a_close(archive):
    archive.remember([_row(symbol="NIFTY", strike=23700.0, price=120.0)], BETWEEN)
    assert len(archive.closing_snapshots()) == 1


def test_a_2340_mcx_capture_is_a_close(archive):
    archive.remember([_row()], AFTER_BOTH)
    rows = archive.closing_snapshots()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NATURALGAS"


def test_one_capture_can_hold_a_close_and_a_mark_at_once(archive):
    """The 16:00 run is not wrong for NIFTY and right for gas, or the other
    way around — it is both at the same time, and the filter must split them."""
    archive.remember([_row(), _row(symbol="NIFTY", strike=23700.0, price=120.0)],
                     BETWEEN)
    kept = [r["symbol"] for r in archive.closing_snapshots()]
    assert kept == ["NIFTY"]


# ----------------------------------------- resolving the MCX anchor
def _load_archiver():
    spec = importlib.util.spec_from_file_location(
        "archive_options", ROOT / "tools" / "ops" / "archive_options.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["archive_options"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fut(symbol, tradingsymbol, expiry):
    return {"name": symbol, "instrument_type": "FUT", "exchange": "MCX",
            "tradingsymbol": tradingsymbol, "expiry": expiry}


def test_the_front_future_is_the_nearest_expiry_not_the_first_alphabetically():
    """NATURALGAS26NOVFUT sorts before NATURALGAS26OCTFUT, and October is the
    live contract until it expires. Sorting by name prices the chain off a
    contract that has stopped trading."""
    mod = _load_archiver()
    dump = [
        _fut("NATURALGAS", "NATURALGAS26NOVFUT", dt.date(2026, 11, 24)),
        _fut("NATURALGAS", "NATURALGAS26OCTFUT", dt.date(2026, 10, 27)),
        _fut("NATURALGAS", "NATURALGAS26DECFUT", dt.date(2026, 12, 24)),
    ]
    assert mod._front_future(dump, "NATURALGAS", dt.date(2026, 10, 20)) \
        == "MCX:NATURALGAS26OCTFUT"


def test_an_expired_future_is_never_the_anchor():
    mod = _load_archiver()
    dump = [
        _fut("NATURALGAS", "NATURALGAS26OCTFUT", dt.date(2026, 10, 27)),
        _fut("NATURALGAS", "NATURALGAS26NOVFUT", dt.date(2026, 11, 24)),
    ]
    assert mod._front_future(dump, "NATURALGAS", dt.date(2026, 11, 3)) \
        == "MCX:NATURALGAS26NOVFUT"


def test_no_live_future_returns_none_rather_than_guessing():
    mod = _load_archiver()
    dump = [_fut("NATURALGAS", "NATURALGAS26OCTFUT", dt.date(2026, 10, 27))]
    assert mod._front_future(dump, "NATURALGAS", dt.date(2026, 11, 3)) is None


def test_another_underlyings_futures_are_not_borrowed():
    mod = _load_archiver()
    dump = [_fut("GOLDM", "GOLDM26NOVFUT", dt.date(2026, 11, 27))]
    assert mod._front_future(dump, "NATURALGAS", dt.date(2026, 11, 3)) is None


def test_options_are_not_mistaken_for_futures():
    mod = _load_archiver()
    dump = [
        {"name": "NATURALGAS", "instrument_type": "CE", "exchange": "MCX",
         "tradingsymbol": "NATURALGAS26NOV275CE", "expiry": dt.date(2026, 11, 20)},
        _fut("NATURALGAS", "NATURALGAS26NOVFUT", dt.date(2026, 11, 24)),
    ]
    assert mod._front_future(dump, "NATURALGAS", dt.date(2026, 11, 3)) \
        == "MCX:NATURALGAS26NOVFUT"


def test_the_mcx_underlyings_are_registered_with_no_hardcoded_anchor():
    """A hardcoded spot key would be a contract name, and contracts roll."""
    mod = _load_archiver()
    for symbol in ("NATURALGAS", "GOLDM", "SILVERM", "CRUDEOIL"):
        segment, anchor = mod.UNDERLYINGS[symbol]
        assert segment == "MCX"
        assert anchor is None, f"{symbol} anchor is pinned to {anchor}"


def test_the_instrument_dump_is_fetched_once_per_segment():
    """Four MCX underlyings, one large download."""
    mod = _load_archiver()
    calls = []

    class _Kite:
        def instruments(self, segment):
            calls.append(segment)
            return []

    kite = _Kite()
    for _ in range(4):
        mod._instruments(kite, "MCX")
    assert calls == ["MCX"]
