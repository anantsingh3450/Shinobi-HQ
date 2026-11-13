"""Keep the option chain. Without it a spread can never be measured.

2026-10-19. The commander changed the mandate to allow defined-risk
short-premium spreads — the one effect this system has ever confirmed on both
halves (sellers paid +2.9% out of sample on NIFTY, +2.4% on SENSEX) and the
one with the strongest independent literature behind it.

IT CANNOT BE MEASURED, AND THE REASON IS NOT CAUTION. Checked the same day
against the live venue:

    NIFTY26NOV22900CE    37 daily bars, listed 2026-08-26
    NIFTY26DEC22900CE    13 daily bars, listed 2026-09-30

An option contract carries history only from the day it listed, and an
expired contract is DELISTED — its token vanishes and its tape becomes
unfetchable forever. This is the futures-roll wound (candle_archive, written
the day a roll deleted three months of training tape) in its worst form:
options expire every week.

So the premium history for the past does not exist and never will. The only
corpus that can ever exist is the one that starts being written down now.
That is the same lesson as the candles and as India VIX, learned for the
third time, and the cost of not learning it is another three months spent in
exactly this position.

A SNAPSHOT, NOT A BACKFILL. Nothing here fetches history, because there is
none to fetch. It records what the chain cost TODAY, once a day, and the
corpus grows one session at a time. In three months a close-to-close spread
study becomes possible; today it does not, and no amount of modelling can
substitute. Deriving a premium from a pricing model would be a synthetic
price, which this codebase forbids and which
test_no_premium_is_modelled_anywhere already pins.

NOTHING IS EVER OVERWRITTEN. INSERT OR IGNORE, like the candles and the VIX:
what a contract cost on a day is the record of that day.

THE CAPTURE TIME IS STORED WITH EVERY ROW, because a snapshot taken at 11:00
is not a close and must never be read as one. The archive does not decide
what a row means; it records when the row was taken and lets the reader
judge. `closing_snapshots` returns only rows captured after the session ended.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from hokage.memory import trading_calendar
from hokage.memory.resolver import brain_root

IST = ZoneInfo("Asia/Kolkata")

#: NSE and BSE index options stop trading at 15:30 IST. A snapshot taken at or
#: after this is a settled close; one taken before it is an intraday mark.
SESSION_END = dt.time(15, 30)

#: MCX runs eight hours past the index close, so one SESSION_END cannot judge
#: both. A chain captured at 16:00 is a genuine close for NIFTY and a LIVE
#: intraday mark for NATURALGAS, and reading the second as the first would put
#: mid-session premium into the corpus labelled as a day's settle. The
#: scheduled run is at 23:40, after both, so this only bites a manual run --
#: which is exactly when someone is looking at the numbers.
SESSION_END_BY_SEGMENT = {
    "NSE": dt.time(15, 30),
    "MCX": dt.time(23, 30),
}


#: When each segment's session BEGINS. The mirror of SESSION_END_BY_SEGMENT,
#: and it was missing - this module knew when a session ends and had no
#: opinion about when it starts.
#:
#: THAT GAP MATTERS NOW THE CHAIN IS CAPTURED INTRADAY. `market_was_open`
#: answers about the DAY, not the moment, so at 08:00 on an ordinary Friday
#: it says True and the broker answers with YESTERDAY's closing prints. Those
#: rows would enter the corpus stamped as today's intraday marks, which is
#: the same error `archive_options.main` already refuses to make on a shut
#: day - "the broker would still answer with the previous session's prints,
#: and those rows would be indistinguishable from today's closes".
#:
#: Found 2026-11-13 at 07:51, before the restart that would have recorded
#: them, which is the only reason it was cheap.
SESSION_START_BY_SEGMENT = {
    "NSE": dt.time(9, 15),
    "MCX": dt.time(9, 0),
}


def session_start_for(symbol: str | None) -> dt.time:
    """When this underlying's session begins.

    Unknown symbols get the index open, which is the LATER of the two and
    therefore the conservative answer here: a new symbol is held back a
    quarter of an hour rather than having stale prints recorded against it.
    Note that this is the opposite direction from `session_end_for`, where
    permissive means the earlier time - in both cases the choice is the one
    that cannot put a stale price in the corpus.
    """
    segment = CALENDAR_SEGMENT.get(str(symbol or "").upper(), "NSE")
    return SESSION_START_BY_SEGMENT.get(segment, SESSION_START_BY_SEGMENT["NSE"])


def is_before_open(when: dt.datetime | None = None,
                   symbol: str | None = None) -> bool:
    """Is this snapshot earlier than the session it would be stamped with?

    A SPECIAL SESSION IS CONSULTED FIRST, because Muhurat opens at 14:20 and
    the ordinary 09:15 would call the whole morning "open" on a day the
    exchange is shut until the afternoon. Same ordering as
    `trading_calendar.session_kind`, for the same reason.

    An unreadable calendar answers False - not before the open - because the
    fallback must not silently stop the archive from recording anything at
    all. A stale row is a smaller harm than an empty corpus, and the
    `captured_at` stamp makes it identifiable either way.
    """
    when = when or now_ist()
    try:
        from hokage.memory import trading_calendar

        segment = CALENDAR_SEGMENT.get(str(symbol or "").upper(), "NSE")
        window = trading_calendar.session_window(when.date(), segment)
        if window:
            return when.time() < window[0]
    except Exception:
        pass
    return when.time() < session_start_for(symbol)


def session_end_for(symbol: str | None) -> dt.time:
    """When this underlying's session ends. Unknown symbols get the index
    close, which is the EARLIER of the two and therefore the permissive
    answer -- so a new symbol is never silently excluded, only possibly
    stamped too generously, and the calendar still guards the day itself."""
    segment = CALENDAR_SEGMENT.get(str(symbol or "").upper(), "NSE")
    return SESSION_END_BY_SEGMENT.get(segment, SESSION_END)

#: How many strikes either side of at-the-money to keep. A vertical spread
#: lives within a few strikes of the money, and the wings are where the
#: quotes go stale and the spreads go wide. Twenty-one strikes per expiry per
#: type is enough to build any defined-risk structure worth testing.
STRIKES_EACH_SIDE = 10

#: Which holiday calendar each underlying follows. NIFTY and SENSEX are both
#: equity-segment instruments and share the NSE/BSE list; a commodity option
#: would follow MCX, which trades an evening session on most equity holidays.
#: Anything unlisted is treated as equity, which is the archive's universe.
CALENDAR_SEGMENT = {
    "NIFTY": "NSE", "BANKNIFTY": "NSE", "FINNIFTY": "NSE", "MIDCPNIFTY": "NSE",
    "SENSEX": "NSE", "BANKEX": "NSE",
    "CRUDEOIL": "MCX", "NATURALGAS": "MCX", "GOLD": "MCX", "GOLDM": "MCX",
    "SILVER": "MCX", "SILVERM": "MCX",
}


def market_was_open(symbol: str, day: dt.date) -> bool | None:
    """Did this underlying's market trade on this day? None = cannot say.

    None is NOT "yes". The caller decides what to do with a day the calendar
    does not cover, and `remember` deliberately writes it rather than
    refusing, so the archive does not silently stop at the end of the
    calendar's span. The CLI reports it.
    """
    segment = CALENDAR_SEGMENT.get(str(symbol).upper(), "NSE")
    kind = trading_calendar.session_kind(day, segment)
    if kind is None:
        return None
    return kind != trading_calendar.CLOSED

SCHEMA = """
CREATE TABLE IF NOT EXISTS option_chain (
    symbol      TEXT NOT NULL,
    day         TEXT NOT NULL,
    expiry      TEXT NOT NULL,
    strike      REAL NOT NULL,
    option_type TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    last_price  REAL NOT NULL,
    oi          REAL,
    volume      REAL,
    spot        REAL,
    -- THE BID-ASK SPREAD IS THE COST OF THE WHOLE STRATEGY, and until
    -- 2026-11-09 this table did not record it. `last_price` is where the
    -- option last traded, which says nothing about what it would cost to
    -- get in and out right now.
    --
    -- The ledger cannot answer it either: paper fills are priced through
    -- the friction MODEL, so measuring cost from them measures the model.
    -- And an option's depth is gone the moment it is not quoted - the
    -- contract delists and the number never existed anywhere. Same lesson
    -- as the candles and the VIX, for a fourth time: the only corpus that
    -- can exist is the one that starts being written down.
    --
    -- NULL means not captured. 0 means genuinely no bid, which is real
    -- information and must never be read as a price of zero.
    bid         REAL,
    ask         REAL,
    PRIMARY KEY (symbol, day, expiry, strike, option_type)
);
CREATE INDEX IF NOT EXISTS idx_option_chain_lookup
    ON option_chain(symbol, expiry, strike, option_type, day);
"""


def db_path() -> Path:
    """Beside the candles and the VIX. One market-history store."""
    return brain_root() / "candles.db"


#: Columns added after the table already existed. CREATE TABLE IF NOT EXISTS
#: does nothing to a table that is already there, so a new column has to be
#: added explicitly or it silently never appears - and the rows that should
#: have carried it are gone for good.
_LATER_COLUMNS = (("bid", "REAL"), ("ask", "REAL"))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(option_chain)")}
    for name, kind in _LATER_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE option_chain ADD COLUMN {name} {kind}")
    return conn


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def is_after_close(when: dt.datetime | None = None,
                   symbol: str | None = None) -> bool:
    """Has this underlying's session ended for the day this snapshot belongs to?

    With no symbol this answers for the index session, which is what every
    caller meant before MCX was archived.
    """
    when = when or now_ist()
    return when.time() >= session_end_for(symbol)


def atm_strikes(strikes: list[float], spot: float,
                each_side: int = STRIKES_EACH_SIDE) -> list[float]:
    """The strikes within `each_side` of the money, nearest first.

    Returns fewer than asked for rather than inventing strikes that the
    exchange does not list, which is the whole reason this reads the dump
    instead of computing a ladder.
    """
    if not strikes or spot <= 0:
        return []
    ordered = sorted(set(strikes))
    nearest = min(range(len(ordered)), key=lambda i: abs(ordered[i] - spot))
    lo = max(0, nearest - each_side)
    hi = min(len(ordered), nearest + each_side + 1)
    return ordered[lo:hi]


def remember(rows, when: dt.datetime | None = None) -> int:
    """Write one day's chain snapshot in. Returns rows actually added.

    Each row is a mapping with symbol, expiry, strike, option_type and
    last_price; oi, volume and spot are optional. A row with no price is
    MISSING, not zero — a zero premium would read as a free option and make
    every spread look like free money.

    A row for a day this underlying's market was SHUT is refused. On
    2026-10-20, an equity holiday, the broker answered every quote with
    Monday's last print and 168 rows went in looking like Tuesday closes.
    A quote coming back is not evidence the market was open.
    """
    when = when or now_ist()
    day = when.date().isoformat()
    stamp = when.isoformat()

    out = []
    for r in rows or ():
        try:
            price = float(r["last_price"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0:
            # A zero or negative premium is a bad print or an untraded
            # contract, never a free option.
            continue
        expiry = r.get("expiry")
        if isinstance(expiry, (dt.date, dt.datetime)):
            expiry = expiry.date().isoformat() if isinstance(expiry, dt.datetime) \
                else expiry.isoformat()
        option_type = str(r.get("option_type") or "").upper()
        if option_type not in ("CE", "PE") or not expiry:
            continue
        try:
            strike = float(r["strike"])
        except (KeyError, TypeError, ValueError):
            continue
        symbol = str(r["symbol"]).upper()
        # False means the calendar is SURE the market was shut. None means it
        # cannot say, and that row is written — see market_was_open.
        if market_was_open(symbol, when.date()) is False:
            continue
        out.append((
            symbol, day, str(expiry), strike, option_type,
            stamp, price, _opt(r.get("oi")), _opt(r.get("volume")),
            _opt(r.get("spot")), _opt(r.get("bid")), _opt(r.get("ask")),
        ))

    if not out:
        return 0
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO option_chain (symbol, day, expiry, strike, "
            "option_type, captured_at, last_price, oi, volume, spot, bid, ask) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", out)
        return conn.total_changes - before


def _opt(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def closing_snapshots(symbol: str | None = None) -> list[dict]:
    """Rows captured AFTER the session ended, which are the only ones that
    may be read as a day's closing premium.

    Rows from a day the market was SHUT are also excluded, however they got
    in. The 2026-10-20 snapshot predates the guard in `remember` and its 168
    rows are Monday's prints wearing Tuesday's date; they stay in the table
    as the record of what happened, and no measurement reads them.
    """
    path = db_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM option_chain LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return []
    try:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM option_chain"
        params: list = []
        if symbol:
            sql += " WHERE symbol = ?"
            params.append(symbol.upper())
        sql += " ORDER BY day, expiry, strike"
        rows = [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
    # FILTERED IN PYTHON, NOT IN SQL. `time(captured_at)` looks like the
    # obvious filter and is wrong: captured_at carries a +05:30 offset, and
    # SQLite's time() converts to UTC, so a genuine 15:58 IST close reads as
    # 10:28 and is discarded as an intraday mark. The archive's own tests
    # caught it on the first run. Parsing the stamp means the answer does not
    # depend on how SQLite chooses to interpret an offset.
    return [r for r in rows
            if _captured_after_close(r.get("captured_at"), r.get("symbol"))
            and _market_traded_that_day(r.get("symbol"), r.get("day"))]


def _market_traded_that_day(symbol, day) -> bool:
    """False only when the calendar is SURE the market was shut. A day it
    cannot speak to is kept — dropping it would silently shrink the corpus
    the moment the calendar runs out of year."""
    try:
        parsed = dt.date.fromisoformat(str(day))
    except (TypeError, ValueError):
        return True
    return market_was_open(str(symbol or ""), parsed) is not False


def _captured_after_close(stamp: str | None, symbol: str | None = None) -> bool:
    if not stamp:
        return False
    try:
        when = dt.datetime.fromisoformat(str(stamp))
    except ValueError:
        return False
    if when.tzinfo is not None:
        when = when.astimezone(IST)
    return when.time() >= session_end_for(symbol)


def coverage() -> dict:
    """What the archive holds. Empty is reported as empty, never as zero."""
    path = db_path()
    if not path.exists():
        return {"rows": 0, "days": 0, "first": None, "last": None, "symbols": []}
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM option_chain LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return {"rows": 0, "days": 0, "first": None, "last": None, "symbols": []}
    try:
        rows, days, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT day), MIN(day), MAX(day) "
            "FROM option_chain").fetchone()
        symbols = [r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM option_chain ORDER BY symbol")]
    finally:
        conn.close()
    # `days` counts what is STORED. `usable_days` counts what a measurement
    # would actually read: after-close snapshots from days the market traded.
    # They differed from the moment the 2026-10-20 holiday went in, and a
    # status line that reports only the first one overstates the corpus.
    usable = {r["day"] for r in closing_snapshots()}
    return {"rows": rows, "days": days, "first": first, "last": last,
            "symbols": symbols, "usable_days": len(usable)}
