"""Keep the premium path of a held position. Without it the exits are opinion.

2026-10-22 produced nine round trips, and the exits sorted themselves into
three clean groups:

    TARGET_HIT      3   +10,526    every winner
    TRAIL_LOCK      3       -62    every scratch
    Hard Backstop   2    -3,643    both big losses
    Thesis Stop     1    -1,125

Three trades armed the trail, had their protective floor ratcheted to exactly
the entry price, and ended at a rounding error after peaking +5.4%, +5.1% and
+8.2%. A fourth armed, kept ratcheting, and ran to target for +4,050. So one
armed trade in four paid, and the obvious question — is locking breakeven at
arm costing more than it saves — HAS NO ANSWER, because the data to answer it
does not exist.

WHAT WAS AVAILABLE WHEN THE QUESTION WAS ASKED. Every log on disk, searched:

    exit-ladder lines            33
    distinct positions covered    8
    oldest surviving     2026-09-22

Thirty-three lines, and logs rotate, so even those are evaporating. No table
in the brain's fifty-three stored a held position's premium over time.
`positions` keeps `current_price`, which is ONE mark — the last one — and a
single mark cannot describe a path. The ladder computed the whole thing on
every tick and threw all of it away except the three state changes worth a
log line.

This is the same wound as the candle archive (a futures roll deleted three
months of training tape) and the option chain archive (premium history dies
with the contract), learned a fourth time. The difference is that this one is
entirely self-inflicted: the numbers pass through memory on every tick. They
are simply not written down.

SO: EVERY MARK, NOT EVERY STATE CHANGE. The ladder logs transitions because a
log is for a human reading it later. An archive is for a lab, and a lab asking
"would a floor at entry minus 2% have exited here" needs the bars BETWEEN the
transitions — the ones where nothing happened to log. A path with only its
corners recorded answers nothing about what happened along the edges.

IT LIVES WITH THE CANDLES, NOT IN hokage.db. On 2026-10-09 hokage.db reached
1.5 GB on dashboard telemetry and had to be pruned. An archive that exists to
be read in three months must not sit in the store that gets pruned. candles.db
is the one that keeps everything forever.

WHAT THIS DOES NOT DO. It does not change an exit, a floor, or a target. It
records. The trail question stays open until there is enough tape to close it,
and the point of this module is that the clock on that started today instead
of starting again in January.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from hokage.memory.resolver import brain_root

IST = ZoneInfo("Asia/Kolkata")

#: Minimum gap between two stored marks for one position.
#:
#: The ladder is evaluated far more often than this. Storing every evaluation
#: would be the per-tick dump `_trace_ladder` deliberately refuses — 74% of
#: 2026-08-27's log was one sentence repeated, burying 135 real errors — and
#: the archive would inherit the same disease in row form.
#:
#: Fifteen seconds is sixty times finer than the 15-minute bars every other
#: study here runs on, so no trail question is limited by it. It is coarser
#: than the tick an exit can actually fire on, which is a real and accepted
#: loss of fidelity: a reconstruction can say which 15-second window a
#: hypothetical floor would have triggered in, not the exact second.
MIN_SECONDS_BETWEEN_MARKS = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS position_marks (
    symbol      TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    day         TEXT NOT NULL,
    premium     REAL NOT NULL,
    entry       REAL NOT NULL,
    peak        REAL,
    floor       REAL,
    target      REAL,
    decision_id TEXT,
    PRIMARY KEY (symbol, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_position_marks_day
    ON position_marks(day, symbol, observed_at);
"""


def db_path() -> Path:
    """Beside the candles, the VIX and the chain. One market-history store,
    and specifically NOT hokage.db, which gets pruned."""
    return brain_root() / "candles.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def _opt(value) -> float | None:
    """A value we do not have is None, never 0.0. A floor of 0.00 reads as
    'no protection' and a floor of None reads as 'not recorded', and a study
    that cannot tell them apart will conclude the wrong thing."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def remember(
    symbol: str,
    premium: float,
    entry: float,
    *,
    peak=None,
    floor=None,
    target=None,
    decision_id: str | None = None,
    when: dt.datetime | None = None,
) -> bool:
    """Record one mark on one open position. True if a row was written.

    Refuses rather than guesses:
      * a premium at or below zero is a bad print or a dead quote, never a
        free option — the same rule the chain archive applies
      * an entry at or below zero makes every percentage meaningless
      * nothing is ever overwritten; a mark already stored for this symbol at
        this instant is the record of that instant
    """
    try:
        premium = float(premium)
        entry = float(entry)
    except (TypeError, ValueError):
        return False
    if premium <= 0 or entry <= 0 or not symbol:
        return False

    when = when or now_ist()
    try:
        with connect() as conn:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO position_marks "
                "(symbol, observed_at, day, premium, entry, peak, floor, "
                " target, decision_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(symbol).upper(), when.isoformat(), when.date().isoformat(),
                 premium, entry, _opt(peak), _opt(floor), _opt(target),
                 str(decision_id) if decision_id else None),
            )
            return conn.total_changes > before
    except sqlite3.Error:
        # An archive that cannot write must never take a position down with
        # it. The caller is inside the exit path.
        return False


def path_for(symbol: str, day: str | dt.date | None = None) -> list[dict]:
    """Every stored mark for one position, oldest first.

    `day` narrows to one session, which matters because the same option
    symbol can be traded on several days and each is a separate path.
    """
    db = db_path()
    if not db.exists():
        return []
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM position_marks LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return []
    try:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM position_marks WHERE symbol = ?"
        params: list = [str(symbol).upper()]
        if day is not None:
            sql += " AND day = ?"
            params.append(day.isoformat() if hasattr(day, "isoformat") else str(day))
        sql += " ORDER BY observed_at"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def coverage() -> dict:
    """What the archive holds. Empty reads as empty, never as zero."""
    empty = {"marks": 0, "positions": 0, "days": 0, "first": None, "last": None}
    db = db_path()
    if not db.exists():
        return empty
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM position_marks LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return empty
    try:
        marks, positions, days, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol || day), COUNT(DISTINCT day), "
            "MIN(day), MAX(day) FROM position_marks").fetchone()
    finally:
        conn.close()
    return {"marks": marks, "positions": positions, "days": days,
            "first": first, "last": last}
