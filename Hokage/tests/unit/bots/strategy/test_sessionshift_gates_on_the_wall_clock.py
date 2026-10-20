"""SessionShift's window was minutes-since-open. MCX opened at 17:00.

2026-10-20, Dussehra. NSE and BSE were shut; MCX ran its EVENING SESSION
ONLY, opening at 17:00. SessionShift's window is 17:00-18:30 on GOLDM and
17:00-19:30 on SILVERM, and it was expressed as minutes since the session's
first bar against constants written for a 09:00 open:

    WINDOW_START_MIN = 480   # 17:00 for a 09:00 MCX open

So 480 minutes after a 17:00 open is 01:00, and the window never arrived.
Both metals were evaluated ten times across the evening and every single one
was refused:

    17:30  GOLDM    outside the 17:00-18:30 IST window (30min into session)
    18:30  GOLDM    outside the 17:00-18:30 IST window (90min into session)

The clock said 18:30 and the module said 90 minutes. The commander lost the
only window that has produced a trade this month, on a day it was open.

THE HYPOTHESIS WAS ALWAYS ABOUT AN EXTERNAL MARKET'S HOURS. The US overlap
begins at 17:00 IST regardless of when MCX opened; minutes-since-open only
coincided with that on a normal day. So the gate reads the wall clock now.

WHAT MUST NOT CHANGE, and these tests exist mainly to pin it: the constants
stay in minutes-since-09:00, so the TUNABLES contract holds and the
commander-approved GOLDM value of 570 still means 18:30. On any 09:00-open
day the behaviour is byte-identical to before, which is what makes this safe
to ship against measurements taken the old way.
"""
from __future__ import annotations

import datetime as dt

import pytest

from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES
from bots.strategy.components.models import MarketContext

SHIFT = MCX_ENTRY_MODULES["strat-sessionshift-mcx-v1"]


def _ctx(symbol: str, minute_of_day: int | None, minutes_into_session=0,
         ema9=100.0, ema21=99.0, price=100.0, vwap=99.5):
    """A context with a directional band, so only the clock gate can refuse."""
    return MarketContext(
        symbol=symbol, price=price, ema9=ema9, ema21=ema21, vwap=vwap,
        closes=(price,) * 50, highs=(price,) * 50, lows=(price,) * 50,
        atr=1.0, minutes_into_session=minutes_into_session,
        session_date=dt.date(2026, 10, 20), minute_of_day=minute_of_day,
    )


def _refusal(ctx) -> str:
    sig = SHIFT.evaluate(ctx)
    return "" if getattr(sig, "should_enter", False) else (sig.reason or "")


def _outside_window(ctx) -> bool:
    return "US-overlap window" in _refusal(ctx)


# ------------------------------------------------- the evening-only session
def test_the_window_opens_at_seventeen_hundred_whatever_time_mcx_opened():
    """THE BUG. 17:30 on a 17:00-open session: the clock is inside the
    window and minutes_into_session is 30."""
    ctx = _ctx("SILVERM", minute_of_day=17 * 60 + 30, minutes_into_session=30)
    assert not _outside_window(ctx), _refusal(ctx)


def test_gold_closes_at_eighteen_thirty_on_an_evening_only_session():
    inside = _ctx("GOLDM", minute_of_day=18 * 60 + 29, minutes_into_session=89)
    outside = _ctx("GOLDM", minute_of_day=18 * 60 + 31, minutes_into_session=91)
    assert not _outside_window(inside), _refusal(inside)
    assert _outside_window(outside)


def test_silver_runs_an_hour_longer_than_gold():
    at_1900 = 19 * 60
    assert not _outside_window(_ctx("SILVERM", at_1900))
    assert _outside_window(_ctx("GOLDM", at_1900))


# -------------------------------- a normal day behaves exactly as before
@pytest.mark.parametrize("hhmm,inside", [
    ((9, 15), False), ((12, 0), False), ((16, 59), False),
    ((17, 0), True), ((17, 30), True), ((18, 29), True),
    ((18, 30), False), ((19, 0), False), ((23, 0), False),
])
def test_gold_on_a_normal_day_is_unchanged(hhmm, inside):
    """A 09:00 open means minutes_into_session and the clock agree, so this
    is the old behaviour restated. If any of these flip, the fix has moved
    the window on days it was measured on."""
    h, m = hhmm
    minute = h * 60 + m
    ctx = _ctx("GOLDM", minute_of_day=minute,
               minutes_into_session=minute - 9 * 60)
    assert (not _outside_window(ctx)) is inside, f"{h:02d}:{m:02d}"


def test_the_boundaries_are_the_approved_ones():
    """GOLDM 570 was proposed by Hokage's own sweep on 2026-09-22 and
    approved. It must still mean 18:30."""
    assert SHIFT.SESSION_ANCHOR_MIN == 9 * 60
    assert SHIFT.SESSION_ANCHOR_MIN + SHIFT.WINDOW_START_MIN == 17 * 60
    assert SHIFT.WINDOW_END_MIN_BY_ASSET["GOLDM"] == 570
    assert SHIFT.SESSION_ANCHOR_MIN + 570 == 18 * 60 + 30
    assert SHIFT.SESSION_ANCHOR_MIN + SHIFT.WINDOW_END_MIN == 19 * 60 + 30


def test_silverm_is_still_not_given_golds_evidence():
    """A class-level change would have applied GOLDM's measurement to
    SILVERM for free. Edge does not travel between assets."""
    assert "SILVERM" not in SHIFT.WINDOW_END_MIN_BY_ASSET


# ------------------------------------------------------- missing is not noon
def test_an_unknown_clock_stands_aside():
    """Doctrine: gates skip on missing data, they never fabricate. A guessed
    hour here would trade the wrong part of the day."""
    ctx = _ctx("GOLDM", minute_of_day=None, minutes_into_session=510)
    assert "session clock unknown" in _refusal(ctx)


def test_it_no_longer_reads_minutes_into_session_for_the_gate():
    """The two now disagree on an evening-only session, and reading the old
    field would reinstate the bug."""
    import ast
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "strategy" / "components"
           / "mcx_entries.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "evaluate"
              and any(isinstance(d, ast.Attribute) and d.attr == "minute_of_day"
                      for d in ast.walk(n)))
    assert not any(isinstance(d, ast.Attribute)
                   and d.attr == "minutes_into_session"
                   for d in ast.walk(fn)), (
        "SessionShift is reading minutes_into_session again")


# --------------------------------------------------- the refusal still tallies
def test_the_refusal_still_classifies_as_session_time():
    """gate_analytics matches free text. A reworded refusal lands in
    UNCLASSIFIED, the one bucket that must never be hard to see."""
    from bots.autonomous.gate_analytics import GateId, classify_reason

    reason = _refusal(_ctx("GOLDM", minute_of_day=12 * 60))
    assert "outside the" in reason
    assert classify_reason(reason) is GateId.SESSION_TIME


def test_the_refusal_reports_the_clock_not_a_misleading_offset():
    """"90min into session" while the clock read 18:30 is what made this
    bug invisible for an evening."""
    reason = _refusal(_ctx("GOLDM", minute_of_day=12 * 60 + 5,
                           minutes_into_session=185))
    assert "clock 12:05" in reason
    assert "185" not in reason
