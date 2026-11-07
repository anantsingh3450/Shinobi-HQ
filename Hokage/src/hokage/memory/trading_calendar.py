"""Which days the market trades, and which part of the day.

2026-10-20. Hokage sat awake and blind all morning and I told the commander
five times to log in. It was Dussehra. Nothing in this system knew.

Worse than the wasted attention: the day was NOT a write-off, and nothing
knew that either. NSE and BSE were shut, but MCX ran an EVENING SESSION
FROM 17:00 — which is exactly SessionShift's window, the only one that has
produced a trade this month. A calendar that only answered "open or closed"
would have been wrong in the other direction and written the day off.

So this answers three states, not two:

    FULL      the normal session
    EVENING   MCX only, from 17:00 — an exchange holiday for equities
    CLOSED    nothing trades

MISSING IS A FOURTH STATE AND IT IS NOT "OPEN". A date this calendar has
never heard of returns None, and a caller must treat that as "I do not
know" rather than assuming a normal session. Guessing open is how a holiday
becomes five hours of nagging; guessing closed is how a live evening gets
written off.

WHERE THE DATES COME FROM. The exchange publishes them; they are entered
here as data. The candle archive CONFIRMS them retroactively — a weekday
with no NIFTY candles was a holiday, and `confirmed_holidays_from_archive`
reads them straight out of the tape. That cross-check found ten for 2026
and all ten match the published list, which is the only reason to trust the
hand-entered part of this file.

NOTHING HERE IS INFERRED FROM A WEEKDAY RULE BEYOND THE WEEKEND. Saturday
and Sunday are closed by exchange rule and need no list. Everything else is
data or it is None.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from hokage.memory.resolver import brain_root

FULL = "FULL"
EVENING = "EVENING"
CLOSED = "CLOSED"

#: MCX's evening-only session on an equity holiday starts here.
EVENING_SESSION_START = dt.time(17, 0)

#: NSE/BSE equity and F&O holidays, 2026. Hand-entered from the exchange
#: list and cross-checked against the candle archive (see
#: confirmed_holidays_from_archive). The ten dates before 2026-10-20 are
#: each confirmed by an absence of NIFTY candles on a weekday.
_EQUITY_HOLIDAYS_2026: dict[dt.date, str] = {
    dt.date(2026, 3, 3): "Holi",
    dt.date(2026, 3, 26): "exchange holiday",
    dt.date(2026, 3, 31): "exchange holiday",
    dt.date(2026, 4, 3): "Good Friday",
    dt.date(2026, 4, 14): "Dr Ambedkar Jayanti",
    dt.date(2026, 5, 1): "Maharashtra Day",
    dt.date(2026, 5, 28): "exchange holiday",
    dt.date(2026, 6, 26): "exchange holiday",
    dt.date(2026, 9, 14): "Ganesh Chaturthi",
    dt.date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    dt.date(2026, 10, 20): "Dussehra",
    dt.date(2026, 11, 10): "Diwali Balipratipada",
    dt.date(2026, 11, 24): "Guru Nanak Jayanti",
    dt.date(2026, 12, 25): "Christmas",
}

#: Equity holidays on which MCX still runs its evening session. This is the
#: norm rather than the exception for commodity markets, but it is listed
#: explicitly rather than assumed: being wrong in this direction writes off
#: a tradeable evening, and being wrong the other way sends Hokage hunting
#: a market that is shut.
#:
#: 2026-10-20 is confirmed by the broker's own notice: "MCX and NCOM will
#: operate only during the evening session, starting at 5:00 PM".
_MCX_EVENING_ON_EQUITY_HOLIDAY: set[dt.date] = {
    dt.date(2026, 4, 14),
    dt.date(2026, 5, 1),
    dt.date(2026, 9, 14),
    dt.date(2026, 10, 2),
    dt.date(2026, 10, 20),
    dt.date(2026, 11, 24),
}

#: Dates the calendar covers. Outside this span every answer is None,
#: because a 2027 date is not "open" simply because 2027 is not in a 2026
#: holiday list.
_KNOWN_FROM = dt.date(2026, 1, 1)
_KNOWN_TO = dt.date(2026, 12, 31)


def session_kind(day: dt.date, segment: str = "NSE") -> str | None:
    """FULL, EVENING, CLOSED, or None when this calendar cannot say.

    `segment` is "NSE" (equities and index options) or "MCX".
    """
    if not isinstance(day, dt.date):
        return None
    if not (_KNOWN_FROM <= day <= _KNOWN_TO):
        return None            # outside the data, not "normal"
    if day.weekday() >= 5:
        return CLOSED          # exchange rule, no list needed
    if day not in _EQUITY_HOLIDAYS_2026:
        return FULL

    if segment.upper() == "MCX":
        return EVENING if day in _MCX_EVENING_ON_EQUITY_HOLIDAY else CLOSED
    return CLOSED


def holiday_name(day: dt.date) -> str | None:
    return _EQUITY_HOLIDAYS_2026.get(day)


def anything_trades(day: dt.date) -> bool | None:
    """True when ANY segment trades. None when unknown."""
    kinds = [session_kind(day, s) for s in ("NSE", "MCX")]
    if any(k is None for k in kinds):
        return None
    return any(k in (FULL, EVENING) for k in kinds)


def nothing_trades(day: dt.date) -> bool:
    """True ONLY when this calendar positively says every segment is shut.

    THE ONE PLACE THAT COMPARISON IS ALLOWED TO LIVE. `anything_trades`
    answers None for a date outside the data, and the difference between

        if anything_trades(day) is False:      # correct - unknown alarms
        if not anything_trades(day):           # silences on None

    is one word and a silent alarm. On 2026-11-07 four separate senders each
    needed this question - the feed probe, the watchdog's staleness window,
    the 08:45 morning checklist and the 09:00 login confirmation - and four
    copies of that comparison is four chances to write the second one.

    Callers that want to SUPPRESS something ask this. Nothing else should
    compare `anything_trades` to a boolean.
    """
    return anything_trades(day) is False


def segment_shut(day: dt.date, segment: str) -> bool:
    """True ONLY when this calendar positively says THIS segment is shut.

    THE SECOND PLACE THAT COMPARISON LIVES, and the only one allowed to ask
    about one league on its own. `nothing_trades` is the right question for a
    whole-system alarm; it is the WRONG question for a per-league report.

    2026-10-20, Dussehra: equities CLOSED all day, MCX trading from 17:00. So
    `nothing_trades` is False and the 15:35 equity report would still have
    said "no trades today" about a market that never opened, while the 23:35
    MCX report must fire, because MCX genuinely ran.

    Unknown is not shut, exactly as in `nothing_trades`: outside the data
    every report keeps sending. An unmaintained calendar must go back to
    being noisy, never to being quiet.
    """
    return session_kind(day, segment) == CLOSED


def describe(day: dt.date) -> str:
    """One line for a log or an alert."""
    nse = session_kind(day, "NSE")
    mcx = session_kind(day, "MCX")
    if nse is None or mcx is None:
        return (f"{day}: outside this calendar — unknown, which is not the "
                f"same as open")
    if nse == FULL:
        return f"{day}: normal session"
    name = holiday_name(day) or "weekend"
    if mcx == EVENING:
        return (f"{day}: {name} — equities CLOSED, MCX evening session from "
                f"{EVENING_SESSION_START.strftime('%H:%M')}")
    return f"{day}: {name} — everything closed"


def confirmed_holidays_from_archive(symbol: str = "NIFTY") -> list[dt.date]:
    """Weekdays inside the archive's span that produced no candles.

    THE CROSS-CHECK, and the only reason the hand-entered list above is
    trustworthy. A weekday the exchange did not trade leaves a hole in the
    tape, and the tape cannot be mistyped. Returns [] when the archive is
    absent — missing data, never an assertion that there were no holidays.
    """
    path = brain_root() / "candles.db"
    if not path.exists():
        return []
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts,1,10) FROM candles WHERE symbol=?",
            (symbol,)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    if not rows:
        return []

    traded = {dt.date.fromisoformat(r[0]) for r in rows}
    first, last = min(traded), max(traded)
    out = []
    day = first
    while day <= last:
        if day.weekday() < 5 and day not in traded:
            out.append(day)
        day += dt.timedelta(days=1)
    return out
