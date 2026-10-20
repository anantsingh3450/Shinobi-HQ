"""It was Dussehra, and nothing in the system knew.

2026-10-20: Hokage sat awake and blind all morning while I told the commander
five times to log in. NSE and BSE were shut for Dussehra. Nothing anywhere
knew what day it was.

THE SECOND HALF IS THE INTERESTING ONE. The day was not a write-off. MCX ran
an EVENING SESSION FROM 17:00 — exactly SessionShift's window, the only one
that has produced a trade this month. A calendar answering only "open or
closed" would have been wrong in the other direction and written off a
tradeable evening. So there are three states, and a fourth for not knowing.

THE HAND-ENTERED LIST IS CROSS-CHECKED AGAINST THE TAPE. A weekday the
exchange did not trade leaves a hole in the candle archive, and a hole
cannot be mistyped. All ten holidays the archive shows for 2026 appear in
the list below, which is the only reason to trust the part of it that was
typed by hand.
"""
from __future__ import annotations

import datetime as dt

import pytest

from hokage.memory import trading_calendar as cal


# ------------------------------------------------------------- the three states
def test_a_normal_weekday_is_a_full_session():
    monday = dt.date(2026, 10, 19)
    assert cal.session_kind(monday, "NSE") == cal.FULL
    assert cal.session_kind(monday, "MCX") == cal.FULL


def test_dussehra_closes_equities_but_not_the_mcx_evening():
    """THE DAY THIS FILE EXISTS FOR. Getting this wrong in either direction
    costs something: nagging for a login into a shut market, or writing off
    the one window that trades."""
    day = dt.date(2026, 10, 20)
    assert cal.session_kind(day, "NSE") == cal.CLOSED
    assert cal.session_kind(day, "MCX") == cal.EVENING
    assert cal.holiday_name(day) == "Dussehra"
    assert cal.anything_trades(day) is True


def test_a_holiday_with_no_evening_session_closes_everything():
    day = dt.date(2026, 4, 3)          # Good Friday
    assert cal.session_kind(day, "NSE") == cal.CLOSED
    assert cal.session_kind(day, "MCX") == cal.CLOSED
    assert cal.anything_trades(day) is False


def test_the_weekend_needs_no_list():
    for day in (dt.date(2026, 10, 17), dt.date(2026, 10, 18)):
        assert cal.session_kind(day, "NSE") == cal.CLOSED
        assert cal.session_kind(day, "MCX") == cal.CLOSED


def test_the_evening_session_starts_at_five():
    assert cal.EVENING_SESSION_START == dt.time(17, 0)


# ------------------------------------------------- unknown is not open
def test_a_date_outside_the_calendar_is_unknown_rather_than_open():
    """A 2027 date is not a normal session merely because 2027 is absent
    from a 2026 holiday list. Guessing open is how a holiday becomes five
    hours of nagging."""
    assert cal.session_kind(dt.date(2027, 3, 15), "NSE") is None
    assert cal.session_kind(dt.date(2025, 3, 15), "NSE") is None
    assert cal.anything_trades(dt.date(2027, 3, 15)) is None


def test_describe_says_unknown_out_loud():
    text = cal.describe(dt.date(2027, 3, 15))
    assert "unknown" in text
    assert "not the same as open" in text


def test_rubbish_input_is_unknown_not_a_crash():
    assert cal.session_kind("tuesday") is None          # type: ignore[arg-type]
    assert cal.session_kind(None) is None               # type: ignore[arg-type]


# -------------------------------------------------------------- descriptions
def test_describe_names_the_evening_session():
    text = cal.describe(dt.date(2026, 10, 20))
    assert "Dussehra" in text
    assert "MCX evening session from 17:00" in text
    assert "CLOSED" in text


def test_describe_a_normal_day_is_short():
    assert cal.describe(dt.date(2026, 10, 19)) == "2026-10-19: normal session"


# ------------------------------------------- the tape checks the typed list
def test_every_holiday_the_archive_shows_is_in_the_list():
    """THE CROSS-CHECK. A weekday the exchange did not trade leaves a hole in
    the candle archive, and a hole cannot be mistyped. If the archive shows a
    gap this list does not know about, the list is wrong — not the tape.

    Skipped where no archive exists, because an absent archive is missing
    data and proves nothing either way.
    """
    import os
    from pathlib import Path

    production = Path(os.environ["HOKAGE_PRODUCTION_BRAIN"]) / "candles.db"
    if not production.exists():
        pytest.skip("no candle archive on this machine")

    import sqlite3

    conn = sqlite3.connect(f"{production.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts,1,10) FROM candles WHERE symbol='NIFTY'"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        pytest.skip("no NIFTY candles archived yet")

    traded = {dt.date.fromisoformat(r[0]) for r in rows}
    first, last = min(traded), max(traded)
    gaps = []
    day = first
    while day <= last:
        if day.weekday() < 5 and day not in traded:
            gaps.append(day)
        day += dt.timedelta(days=1)

    unknown = [d for d in gaps if cal.session_kind(d, "NSE") != cal.CLOSED]
    assert not unknown, (
        f"the tape shows no trading on {unknown} but the calendar calls them "
        f"open — the typed list is wrong, not the archive"
    )


def test_the_archive_reader_returns_nothing_rather_than_lying(tmp_path,
                                                              monkeypatch):
    """An absent archive is missing data. Returning [] must never be read as
    "there were no holidays"."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "empty"))
    assert cal.confirmed_holidays_from_archive() == []
