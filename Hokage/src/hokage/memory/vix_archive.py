"""Keep India VIX. It is the only input to the gate that switches Hokage off.

WHY THIS EXISTS. The IV premium guard refuses every options BUY when VIX sits
at or above the 80th percentile of its trailing 60 days. On 2026-10-14 that
refused all thirteen signals Hokage found; on 2026-10-15 it refused eleven
more. One number decides whether he is allowed to act at all, and until now
that number was archived NOWHERE.

The consequence was found on 2026-10-15. `variance_premium_lab` produced the
first result in this system to clear a corrected bar on both halves — sellers
paid +3.0% on NIFTY and +2.4% on SENSEX out of sample — and it could only be
produced while a Zerodha session happened to be alive, because VIX had to be
fetched fresh every run. A dead token made the measurement unrepeatable, and a
measurement that cannot be repeated is not evidence; it is an anecdote with a
t-statistic attached.

Candles were already kept forever for exactly this reason (see
tools/research/candle_archive.py, written the day a futures roll deleted three
months of training tape). VIX was the half of that corpus nobody noticed was
missing: the candle archive holds what the index DID, and this holds what the
market CHARGED for it. Neither half answers a volatility question alone.

TODAY IS NEVER WRITTEN. Kite serves a bar for the session in progress, and its
`close` is the last trade, not the close. Writing it would freeze an intraday
reading as a settled one forever, because this archive is INSERT OR IGNORE and
never corrects itself. So `remember` drops every day on or after today in IST,
and that cutoff is explicit rather than the host's clock — the planned move to
a VPS would otherwise shift it by five and a half hours in silence.

INSERT OR IGNORE, NEVER REPLACE. A close already written is the record of what
the market charged on that day. The same doctrine the candle archive runs on.

NOTHING HERE IS SYNTHETIC. Every row came from Kite. A day with no data is
absent, not zero — a zero VIX would read as a perfectly calm market and sit at
the 0th percentile, which is the one reading that unblocks every gate.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from hokage.memory.resolver import brain_root

#: The exchange's day, not the host's. See the module docstring.
IST = ZoneInfo("Asia/Kolkata")

SCHEMA = """
CREATE TABLE IF NOT EXISTS vix (
    day   TEXT PRIMARY KEY,
    open  REAL,
    high  REAL,
    low   REAL,
    close REAL NOT NULL
);
"""


def db_path() -> Path:
    """Beside the candles, and resolved on every call.

    Resolved late so that moving the brain moves this too — the split-brain
    failure of 2026-10-09, where nine tools each computed their own path and
    went on writing a database nobody read.
    """
    return brain_root() / "candles.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def remember(candles, today: dt.date | None = None) -> int:
    """Write settled daily VIX bars in, keeping whatever is already there.

    `candles` is anything iterable of per-day records: Kite dicts
    (``{"date": ..., "close": ...}``), objects with ``.date``/``.close``
    attributes, or ``(day, close)`` pairs. Production hands this the candle
    objects it already fetched for the guard, so archiving costs no extra
    call to the broker.

    Returns rows actually added. A day already present is left untouched.
    """
    today = today or today_ist()
    rows: list[tuple] = []
    for candle in candles or ():
        if isinstance(candle, dict):
            day = _as_date(candle.get("date"))
            close = candle.get("close")
            o, h, low = candle.get("open"), candle.get("high"), candle.get("low")
        elif isinstance(candle, (tuple, list)) and len(candle) >= 2:
            day, close = _as_date(candle[0]), candle[1]
            o = h = low = None
        else:
            day = _as_date(getattr(candle, "date", None)
                           or getattr(candle, "timestamp", None))
            close = getattr(candle, "close", None)
            o = getattr(candle, "open", None)
            h = getattr(candle, "high", None)
            low = getattr(candle, "low", None)

        if day is None or close is None:
            continue
        try:
            close = float(close)
        except (TypeError, ValueError):
            continue
        # A zero or negative VIX is not a calm market, it is a bad print, and
        # it would score at the 0th percentile and unblock every gate.
        if close <= 0:
            continue
        # THE SESSION IN PROGRESS IS NOT A CLOSE. See the module docstring.
        if day >= today:
            continue
        rows.append((day.isoformat(),
                     _opt(o), _opt(h), _opt(low), close))

    if not rows:
        return 0
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO vix (day, open, high, low, close) "
            "VALUES (?,?,?,?,?)", rows)
        return conn.total_changes - before


def _opt(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load(start: str | None = None, end: str | None = None) -> list[tuple[dt.date, float]]:
    """Archived daily closes, oldest first, as ``(date, close)`` pairs.

    The same shape `iv_lab.load_vix_closes` has always returned, so it is a
    drop-in wherever VIX was previously fetched live.
    """
    path = db_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM vix LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return []          # the table has never been created: empty, not an error
    try:
        sql = "SELECT day, close FROM vix"
        params: list = []
        if start:
            sql += " WHERE day >= ?"
            params.append(start[:10])
            if end:
                sql += " AND day <= ?"
                params.append(end[:10])
        elif end:
            sql += " WHERE day <= ?"
            params.append(end[:10])
        sql += " ORDER BY day"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [(dt.date.fromisoformat(d), c) for d, c in rows]


def coverage() -> dict:
    """What the archive holds. Empty is reported as empty, never as zero."""
    rows = load()
    if not rows:
        return {"days": 0, "first": None, "last": None, "stale_days": None}
    return {
        "days": len(rows),
        "first": rows[0][0],
        "last": rows[-1][0],
        "stale_days": (today_ist() - rows[-1][0]).days,
    }
