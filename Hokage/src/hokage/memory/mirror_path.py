"""The premium path of the side that LOST the auction, paired with the winner.

WHY THE MIRROR EXPERIMENT COULD NOT BE SETTLED
The commander's hypothesis of 2026-10-23 - "every time it takes a call, take
a put" - was built as FadeRange and RiderTrend and has fired in perfect
lockstep with its originals ever since. It has never traded, and that is the
design: a mirror carries its original's confidence exactly, so every scan ties
and the tie-break puts a mirror below a non-mirror. 0 wins in 54 firings since
the 2026-10-28 fix.

So it has to be scored from the archive, and the archive could not do it:

  * on the UNDERLYING a mirror's edge is exactly minus its original's - same
    bar, opposite direction - so the direction column answers both sides at
    once and the flip creates no information whatsoever;
  * the question actually asked is whether the original was wrong about
    DIRECTION or wrong about MOVEMENT. Both sides BUY options; a long call and
    a long put are both long premium, both pay theta and the spread, and both
    lose when the underlying sits still. That distinction exists in premium
    and nowhere else;
  * `signal_archive` has stored the loser's scan-time premium since
    2026-11-03, which is ONE number. 2026-11-06 is typical: the winning CALL
    accumulated 83 marks and 32 marks on its two trades, and the losing PUT
    had exactly one price in the entire brain - what it cost at the instant it
    was proposed. One number cannot be a round trip.

So the loser now gets a path too, polled on the same tick as the winner.

A SEPARATE TABLE, NOT position_marks
`trail_arm_lab` reads `SELECT DISTINCT symbol, day FROM position_marks` and
treats every symbol it finds as a position that was held. A path for a
contract nobody ever bought would enter that study as a trade, which is the
"two things it believed were one" failure `premium_path.remember` was careful
to avoid when it added `effective_floor` beside `floor` rather than redefining
it. These rows are not positions and do not live with them.

PAIRED IN ONE ROW, NOT TWO PATHS TO ALIGN
Each row carries the loser's premium AND the winner's premium at the same
instant, because the question is always a difference between the two. A lab
that had to align two tables on a timestamp would be one rounding rule away
from comparing 17:30:01 with 17:30:16 and calling it a spread.

WHAT THIS STILL CANNOT TELL YOU
The loser never fills, so it has no stop, no trail and no exit of its own. The
path answers "what would the opposite option have been worth while the real
trade was open", which is the question - but the comparison is only honest
over the window the real position was actually held, and both sides' exits
would have differed. It records. It does not conclude.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from hokage.memory.resolver import brain_root

IST = ZoneInfo("Asia/Kolkata")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mirror_marks (
    symbol        TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    day           TEXT NOT NULL,
    premium       REAL NOT NULL,
    entry         REAL NOT NULL,
    held_symbol   TEXT NOT NULL,
    held_premium  REAL,
    held_entry    REAL,
    module_id     TEXT,
    decision_id   TEXT,
    scanned_at    TEXT,
    -- KEYED BY THE PAIR, not by the losing contract alone. Two positions open
    -- at once on the same underlying can propose the SAME opposing strike, and
    -- a key of (symbol, observed_at) would silently drop the second one's
    -- whole path through INSERT OR IGNORE.
    PRIMARY KEY (held_symbol, symbol, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_mirror_marks_day
    ON mirror_marks(day, symbol, observed_at);
CREATE INDEX IF NOT EXISTS idx_mirror_marks_held
    ON mirror_marks(held_symbol, day, observed_at);
"""


def db_path() -> Path:
    """Beside the candles and the chain, NOT in hokage.db, which gets pruned -
    this archive exists to be read in three months."""
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
    """Absent is None, never 0.0. A premium of 0.00 is a number the venue
    might really have quoted; None says it was not recorded."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def remember(
    symbol: str,
    premium: float,
    entry: float,
    *,
    held_symbol: str,
    held_premium=None,
    held_entry=None,
    module_id: str | None = None,
    decision_id: str | None = None,
    scanned_at: str | None = None,
    when: dt.datetime | None = None,
) -> bool:
    """Record one mark on the losing side. True if a row was written.

    Refuses rather than guesses, on the same terms as the chain archive and
    `premium_path.remember`:
      * a premium at or below zero is a bad print or a dead quote, never a
        free option;
      * an entry at or below zero makes every percentage meaningless;
      * a mark with no winner to pair it with is not an observation of
        anything, so `held_symbol` is required;
      * nothing is overwritten - the row stored for an instant is the record
        of that instant.
    """
    try:
        premium = float(premium)
        entry = float(entry)
    except (TypeError, ValueError):
        return False
    if premium <= 0 or entry <= 0 or not symbol or not held_symbol:
        return False

    when = when or now_ist()
    try:
        with connect() as conn:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO mirror_marks "
                "(symbol, observed_at, day, premium, entry, held_symbol, "
                " held_premium, held_entry, module_id, decision_id, scanned_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(symbol).upper(), when.isoformat(),
                 when.date().isoformat(), premium, entry,
                 str(held_symbol).upper(), _opt(held_premium),
                 _opt(held_entry),
                 str(module_id) if module_id else None,
                 str(decision_id) if decision_id else None,
                 str(scanned_at) if scanned_at else None),
            )
            return conn.total_changes > before
    except sqlite3.Error:
        # An archive that cannot write must never take a position down with
        # it. The caller is inside the exit path.
        return False


def path_for(held_symbol: str, day: str | dt.date | None = None) -> list[dict]:
    """Every stored mark of the side that lost to `held_symbol`, oldest first.

    Keyed by the HELD contract because that is what a reader has: a round trip
    in the ledger, asking what the other side would have done.
    """
    db = db_path()
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM mirror_marks LIMIT 1")
    except sqlite3.Error:
        conn.close()
        return []
    try:
        sql = "SELECT * FROM mirror_marks WHERE held_symbol = ?"
        args: list = [str(held_symbol).upper()]
        if day is not None:
            sql += " AND day = ?"
            args.append(day if isinstance(day, str) else day.isoformat())
        sql += " ORDER BY observed_at"
        return [dict(r) for r in conn.execute(sql, args)]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def coverage() -> dict:
    """What a lab can expect to find, so a study can state its own n."""
    db = db_path()
    empty = {"rows": 0, "pairs": 0, "first_day": None, "last_day": None}
    if not db.exists():
        return empty
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return empty
    try:
        rows, pairs, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT held_symbol || day), "
            "MIN(day), MAX(day) FROM mirror_marks").fetchone()
        return {"rows": rows or 0, "pairs": pairs or 0,
                "first_day": first, "last_day": last}
    except sqlite3.Error:
        return empty
    finally:
        conn.close()
