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

THE DATA RUNS OUT, AND THE EXPIRY IS THE DANGEROUS PART. Every function
here answers None for a year nobody has entered, and every caller handles
None correctly — so nothing breaks, nothing errors, and SIX behaviours
quietly revert at midnight on 31 December:

    the 08:45 checklist goes back to red-flagging every Saturday
    the blind-feed alarm goes back to nagging for a login on a holiday
    both EOD reports go back to reporting "no trades" about a shut market
    the watchdog's staleness window goes back to expecting a dead feed
    the option archive goes back to storing a chain nobody traded
    and a holiday with an MCX evening in it gets written off entirely

That is 2026-10-20 and 2026-11-07 arriving together, on a date known
years in advance, with nothing on fire. So THIS FILE SAYS HOW LONG IT HAS
LEFT (`coverage_warning`), from 75 days out, in the log at boot and in the
08:45 checklist he reads every morning. The warning names the fix, and it
escalates once the date has passed.

COVERAGE IS DERIVED FROM THE DATA, NEVER DECLARED BESIDE IT. A year is
covered because its holidays are entered, so there is no second fact to
forget: `_EQUITY_HOLIDAYS[2027] = {}` is NOT coverage, it is a year half
typed, and it answers None exactly like a year nobody touched. A declared
span that can disagree with the dates under it is how a correctly entered
year gets silently ignored, and the fail-safe direction is unknown.

ONLY THE EXCHANGE'S OWN LIST GOES IN. Checked 2026-11-10, NSE had not yet
published 2027 (they publish in December) and six third-party lists
disagreed with each other on Holi, Ambedkar Jayanti, Muharram, Id-ul-Fitr
and Balipratipada. A guessed holiday is worse than no holiday: it is the
nagging and the written-off evening at the same time, with the authority
of a typed date. Wait for the circular.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from hokage.memory.resolver import brain_root

FULL = "FULL"
EVENING = "EVENING"
MUHURAT = "MUHURAT"
CLOSED = "CLOSED"

#: MCX's evening-only session on an equity holiday starts here.
EVENING_SESSION_START = dt.time(17, 0)

#: NSE/BSE equity and F&O holidays, BY YEAR. Hand-entered from the exchange
#: list and cross-checked against the candle archive (see
#: confirmed_holidays_from_archive). The ten 2026 dates before 2026-10-20
#: are each confirmed by an absence of NIFTY candles on a weekday.
#:
#: A YEAR IS COVERED BECAUSE ITS DATES ARE HERE. Adding a year is one block
#: and nothing else; an empty block is a year half typed and is not coverage
#: (see `covers`). To add 2027: take the dates from the NSE circular at
#: nseindia.com - not from a holiday website, which on 2026-11-10 disagreed
#: with five other holiday websites - add the block, add any MCX evenings to
#: the set below, and the warning stops on its own.
_EQUITY_HOLIDAYS: dict[int, dict[dt.date, str]] = {}

_EQUITY_HOLIDAYS[2026] = {
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

#: SPECIAL SESSIONS: days the exchange TRADES that every ordinary rule in
#: this file would call shut. They exist, they are announced weeks ahead, and
#: they are the one case where a weekend is not a weekend.
#:
#: 2026-11-07 is why this table is here. The five senders had just been taught
#: to go quiet when the calendar says everything is closed, and the calendar
#: answered CLOSED for Sunday 2026-11-08 on the weekend rule alone, without
#: consulting any list. That is Diwali Muhurat trading. The gate shipped that
#: afternoon would have silenced the feed alarm, the login prompt, the morning
#: checklist and both reports THROUGH A LIVE SESSION - a silence far worse
#: than the nagging it replaced, because nagging is visible and silence is not.
#:
#: THE WINDOW IS PER SEGMENT AND IT IS NOT THE USUAL ONE. Muhurat is an
#: afternoon session, so MCX does NOT run its 17:00 evening here.
#:
#: NSE's window is the EQUITY F&O window, 14:20-15:40, because index options
#: are the entire tradable universe. Cash equities close at 15:30 (15:15 for
#: closing-auction stocks) and that difference is not Hokage's to care about.
_SPECIAL_SESSIONS: dict[dt.date, dict] = {
    dt.date(2026, 11, 8): {
        "name": "Diwali Muhurat trading (Samvat 2083)",
        "windows": {
            "NSE": (dt.time(14, 20), dt.time(15, 40)),   # equity F&O
            "MCX": (dt.time(14, 20), dt.time(15, 30)),
        },
        # The broker's own bulletin, which is the standard the 2026-10-20
        # MCX evening entry was held to. Press reports disagreed on the
        # close (15:30 vs 15:40) and on whether MCX ran at all; the bulletin
        # for HIS account is the one that decides.
        "source": "Zerodha bulletin 461711, 27 Oct 2026",
        # Worth knowing before reading a fill: F&O credits and 06 Nov
        # intraday equity profits are NOT in available funds during this
        # session, because settlement is shut.
        "settlement_holiday": True,
    },
}

#: How long before the cliff this file starts saying so. NSE publishes the
#: next year's holidays in December, so 75 days before 31 December is the
#: earliest the warning could be acted on - it starts nagging in the middle
#: of October and the circular arrives inside the window.
COVERAGE_WARNING_DAYS = 75

#: Where the dates come from, named in the warning so the fix needs no
#: memory. No underscores, brackets or asterisks in any warning text: these
#: go out over legacy Telegram Markdown, where one unpaired control
#: character used to eat the whole message.
COVERAGE_SOURCE = "the NSE circular at nseindia.com"


def covered_years() -> tuple[int, ...]:
    """The years whose holidays are actually entered, in order.

    A year with an EMPTY table is not in here. That is the fail-safe
    direction: a year half typed answers None like a year nobody touched,
    rather than calling Republic Day a normal session.
    """
    return tuple(sorted(y for y, table in _EQUITY_HOLIDAYS.items() if table))


def covers(day: dt.date) -> bool:
    """Whether this calendar has data for the year `day` falls in."""
    if not isinstance(day, dt.date):
        return False
    return bool(_EQUITY_HOLIDAYS.get(day.year))


def covered_until(today: dt.date | None = None) -> dt.date | None:
    """The last day covered by an unbroken run of years from `today`.

    UNBROKEN IS THE POINT. With 2026 and 2028 entered and 2027 missing, the
    answer is 2026-12-31 - a gap in the middle is a cliff like any other,
    and reporting the furthest year entered would hide it.

    None when this calendar does not cover `today` at all.
    """
    today = _today() if today is None else today
    if not covers(today):
        return None
    year = today.year
    while _EQUITY_HOLIDAYS.get(year + 1):
        year += 1
    return dt.date(year, 12, 31)


def days_of_coverage(today: dt.date | None = None) -> int | None:
    """Days until the data runs out. 0 on the last covered day.

    None when `today` itself is uncovered - already past the cliff, where
    "how many days left" has no answer and `coverage_warning` speaks
    instead.
    """
    today = _today() if today is None else today
    until = covered_until(today)
    return None if until is None else (until - today).days


def coverage_warning(today: dt.date | None = None) -> str | None:
    """The loud line, or None while there is nothing to say.

    THIS IS THE WHOLE POINT OF THE EXPIRY BEING KNOWN IN ADVANCE. It goes
    in the boot log and the 08:45 checklist, and it names the fix.
    """
    today = _today() if today is None else today
    years = covered_years()
    if not years:
        return ("The trading calendar has NO DATA AT ALL, so every holiday "
                "check answers unknown. Enter a year from "
                f"{COVERAGE_SOURCE} in the calendar file under "
                "src/hokage/memory/.")

    left = days_of_coverage(today)
    if left is None:
        # The last year covered BEFORE today, not the furthest year in the
        # table: with 2027 missing and 2028 entered, 2027 is still a cliff.
        earlier = [y for y in years if y < today.year]
        if not earlier:
            return ("The trading calendar does not cover today at all - it "
                    f"starts in {years[0]}, so every holiday check answers "
                    "unknown.")
        last = dt.date(earlier[-1], 12, 31)
        gone = (today - last).days
        return (f"The trading calendar EXPIRED {gone} day"
                f"{'' if gone == 1 else 's'} ago, on {last}. Hokage no "
                "longer knows what day it is: the 08:45 checklist will "
                "red-flag every Saturday, the blind-feed alarm will nag for "
                "a login on a holiday, both EOD reports will talk about a "
                f"market that never opened, and a holiday with an MCX "
                f"evening in it gets written off. Enter {today.year} from "
                f"{COVERAGE_SOURCE} in the calendar file under "
                "src/hokage/memory/.")

    if left > COVERAGE_WARNING_DAYS:
        return None
    when = (f"TODAY, {covered_until(today)}" if left == 0 else
            f"in {left} day{'' if left == 1 else 's'}, on "
            f"{covered_until(today)}")
    return (f"The trading calendar runs out {when}. After "
            f"that every holiday check answers unknown and six "
            "calendar-gated behaviours revert, starting with the 08:45 "
            f"checklist red-flagging every Saturday. Enter "
            f"{covered_until(today).year + 1} "
            f"from {COVERAGE_SOURCE} in the calendar file under "
            "src/hokage/memory/.")


def coverage_problems() -> list[str]:
    """Ways the tables above contradict each other. [] when they agree.

    A HALF-TYPED YEAR IS SAFE BUT SILENT, and silent is what this file
    exists to stop. Read at boot and asserted in the suite.
    """
    out = []
    for year, table in sorted(_EQUITY_HOLIDAYS.items()):
        if not table:
            out.append(f"{year} is listed with no holidays in it, so it is "
                       f"NOT covered - every {year} date answers unknown")
            continue
        wrong = sorted(d for d in table if d.year != year)
        if wrong:
            # isoformat, not repr: this line goes to Telegram, where
            # "datetime.date(2028, 1, 26)" says nothing to a reader.
            out.append(f"{year}'s table contains "
                       f"{', '.join(d.isoformat() for d in wrong)}, which "
                       f"are not {year} dates and will never be found")
    for day in sorted(_MCX_EVENING_ON_EQUITY_HOLIDAY):
        if day not in _EQUITY_HOLIDAYS.get(day.year, {}):
            out.append(f"{day} is listed as an MCX evening but is not an "
                       f"equity holiday, so the evening is unreachable")
    for day in sorted(_SPECIAL_SESSIONS):
        if not covers(day):
            out.append(f"{day} is a special session in a year this calendar "
                       f"does not cover, so it answers unknown and every "
                       f"calendar-gated sender goes silent through it")
    return out


def _today() -> dt.date:
    """Today in IST, which is the only timezone the exchange has.

    Deliberately not `session_manager.KolkataTime` - that module imports
    this one.
    """
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()


def session_kind(day: dt.date, segment: str = "NSE") -> str | None:
    """FULL, EVENING, CLOSED, or None when this calendar cannot say.

    `segment` is "NSE" (equities and index options) or "MCX".
    """
    if not isinstance(day, dt.date):
        return None
    if not covers(day):
        return None            # outside the data, not "normal"

    # BEFORE the weekend rule, which is the whole point: a Muhurat session on
    # a Sunday is a trading day, and asking "is it Saturday or Sunday" first
    # is how a live session reads as closed.
    special = _SPECIAL_SESSIONS.get(day)
    if special is not None:
        window = special["windows"].get(segment.upper())
        return MUHURAT if window else CLOSED

    if day.weekday() >= 5:
        return CLOSED          # exchange rule, no list needed
    if day not in _EQUITY_HOLIDAYS[day.year]:
        return FULL

    if segment.upper() == "MCX":
        return EVENING if day in _MCX_EVENING_ON_EQUITY_HOLIDAY else CLOSED
    return CLOSED


def holiday_name(day: dt.date) -> str | None:
    if not isinstance(day, dt.date):
        return None
    return _EQUITY_HOLIDAYS.get(day.year, {}).get(day)


def holidays(year: int | None = None) -> dict[dt.date, str]:
    """Every entered holiday, or one year's. A copy, not the table.

    THE PUBLIC WAY IN. Three tests used to read the module's private dict
    and broke the day it was keyed by year; a reader that wants the dates
    should not have to know the shape of the storage.
    """
    if year is not None:
        return dict(_EQUITY_HOLIDAYS.get(year, {}))
    merged: dict[dt.date, str] = {}
    for table in _EQUITY_HOLIDAYS.values():
        merged.update(table)
    return merged


def anything_trades(day: dt.date) -> bool | None:
    """True when ANY segment trades. None when unknown."""
    kinds = [session_kind(day, s) for s in ("NSE", "MCX")]
    if any(k is None for k in kinds):
        return None
    return any(k in (FULL, EVENING, MUHURAT) for k in kinds)


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


def special_session(day: dt.date) -> dict | None:
    """The special-session record for this day, or None.

    Callers that need the WINDOW rather than the verdict ask this - the
    watchdog's staleness window and the engine's own session status both do.
    """
    if not isinstance(day, dt.date):
        return None
    return _SPECIAL_SESSIONS.get(day)


def session_window(day: dt.date, segment: str) -> tuple[dt.time, dt.time] | None:
    """When this segment actually trades, for a day whose hours are not the
    usual ones. None means "the ordinary hours, or nothing" - it is NOT a
    statement that the segment is shut, so ask `segment_shut` for that.

    Only special sessions answer today. The ordinary 09:15-15:30 and the MCX
    evening live in the engine's own session manager, and duplicating them
    here would create a third calendar to disagree with the other two.
    """
    special = _SPECIAL_SESSIONS.get(day) if isinstance(day, dt.date) else None
    if special is None:
        return None
    return special["windows"].get(segment.upper())


def session_span(day: dt.date) -> tuple[dt.time, dt.time] | None:
    """The widest window any segment trades on a special-session day.

    For an alarm that only needs to know "should a quote be arriving right
    now" rather than which league it belongs to. None means this day has no
    special hours, which is NOT a statement that it is shut.
    """
    special = _SPECIAL_SESSIONS.get(day) if isinstance(day, dt.date) else None
    if not special:
        return None
    windows = [w for w in special["windows"].values() if w]
    if not windows:
        return None
    return min(w[0] for w in windows), max(w[1] for w in windows)


def describe(day: dt.date) -> str:
    """One line for a log or an alert."""
    nse = session_kind(day, "NSE")
    mcx = session_kind(day, "MCX")
    if nse is None or mcx is None:
        years = covered_years()
        covered = ", ".join(str(y) for y in years) if years else "no year"
        return (f"{day}: outside this calendar — unknown, which is not the "
                f"same as open. Entered: {covered}; the rest comes from "
                f"{COVERAGE_SOURCE}.")
    if nse == FULL:
        return f"{day}: normal session"

    special = _SPECIAL_SESSIONS.get(day)
    if special is not None:
        parts = []
        for segment in ("NSE", "MCX"):
            window = special["windows"].get(segment)
            if window:
                parts.append(f"{segment} {window[0].strftime('%H:%M')}-"
                             f"{window[1].strftime('%H:%M')}")
        hours = ", ".join(parts) if parts else "no segment trading"
        return f"{day}: {special['name']} — SPECIAL SESSION, {hours}"

    name = holiday_name(day) or "weekend"
    if mcx == EVENING:
        return (f"{day}: {name} — equities CLOSED, MCX evening session from "
                f"{EVENING_SESSION_START.strftime('%H:%M')}")
    return f"{day}: {name} — everything closed"


def unlisted_sessions_from_archive(symbol: str = "NIFTY") -> list[dt.date]:
    """Weekend days the archive has candles for that this file calls closed.

    THE OTHER HALF OF THE CROSS-CHECK, and the only part of this file that can
    notice its own gap. `confirmed_holidays_from_archive` catches a day listed
    as open that did not trade; this catches the dangerous inverse - a day that
    TRADED while every rule here called it shut, which is exactly what Diwali
    Muhurat trading is and exactly the state in which five senders go silent
    through a live session.

    It cannot be fooled and it cannot be mistyped: a weekend with candles in
    it is a session that happened. It also cannot anticipate - it speaks only
    after the tape exists - so it is a backstop for an unmaintained table, not
    a substitute for entering the dates.

    Returns [] when the archive is absent: missing data, never an assertion.
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

    out = []
    for (stamp,) in rows:
        try:
            day = dt.date.fromisoformat(stamp)
        except ValueError:
            continue
        if day.weekday() >= 5 and day not in _SPECIAL_SESSIONS:
            out.append(day)
    return sorted(out)


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
