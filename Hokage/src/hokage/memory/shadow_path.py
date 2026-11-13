"""The premium path of a trade the bias gate refused to let happen.

WHY A GATE CANNOT BE SCORED WITHOUT THIS
veto_lab measures the bias engine over all history and answers in edge_atr -
the UNDERLYING's forward move. transfer_lab then measured what that currency is
worth to an option buyer: +3.31% of premium per 1.0 ATR, n=15. Put together,
the gate's largest confirmed effect (0.318 ATR on gas TrendRider at two hours)
is about 1.05% of premium, and its 60-minute effect is 0.03 on a 13.90 option -
below 0.05, the smallest premium change ever archived on gas.

Those are conversions, not measurements. The gate has never been scored on
premium directly and could not be, for a reason no amount of history fixes: a
blocked trade is never bought, so NOTHING HAS EVER PRICED ONE. The inventory on
2026-11-07 was total:

  * `option_chain` holds ONE SNAPSHOT PER DAY over 13 days - no intraday series
    exists at any horizon Hokage trades;
    [2026-11-13: `option_marks` now records the near-expiry chain every 15
    minutes. It does not change the sentence above - it starts the series
    that sentence says is missing, from today forward and never backwards,
    and it still holds nothing for a contract the gate BLOCKED.]
  * `auction_signals` stores the blocked contract's premium at the instant it
    was proposed, which is ONE number, and seven contract-days in the whole
    brain have a second;
  * `position_marks` has 22 real paths and every one is a trade that was TAKEN.
    Five of them belong to a decision the gate had to approve. Its blocked set
    has none.

So the blocked side gets a path of its own, polled on the same tick that marks
real positions.

WHY IT CANNOT RIDE THE POSITION LOOP
`mirror_path` pairs the auction loser with the winner and is polled BY the
winner's tracking loop - there is always a real position driving it. A blocked
trade has no position; that is the whole point. Nothing would ever poll it, so
this archive is its own registry: the first mark is written at the instant of
the block, and the tick rebuilds what is still live by reading it back. A
restart therefore resumes a path instead of abandoning it, and no new state
file exists to drift.

ONE LIVE SHADOW PER UNDERLYING, which is a bound and also the honest shape.
`_active_positions_tracking` is keyed by symbol alone, so Hokage cannot hold two
positions in one symbol - and the question being asked is what the trade it
WOULD have had open was worth. Without the bound, a 120-minute window and a
15-minute scan would stack eight shadows per asset and quote all of them on
every tick.

A SEPARATE TABLE, NOT position_marks
`trail_arm_lab` reads `SELECT DISTINCT symbol, day FROM position_marks` and
treats every symbol it finds as a position that was held. A path for a contract
nobody bought would enter that study as a trade. Same reasoning as
`mirror_marks`, and the same conclusion: these rows are not positions and do
not live with them.

WHAT THIS STILL CANNOT TELL YOU
The shadow has no stop, no trail and no exit of its own, so it answers "what
would that contract have been worth while the trade would have been open" and
not "what would the trade have made". transfer_lab's slope is the conversion
THIS SYSTEM ACHIEVED, ladder included; a shadow has no ladder. It records. It
does not conclude.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from hokage.memory.resolver import brain_root

IST = ZoneInfo("Asia/Kolkata")

#: How long a shadow is polled for, in minutes.
#:
#: The labs score forward horizons of 2, 4 and 8 fifteen-minute bars, so 120
#: minutes is the longest window any of them asks about and a path this long can
#: be sliced at 30 and 60 without being re-collected. It is also roughly what
#: Hokage's real trades live: the two gas positions of 2026-11-06 were held
#: 1h26m and 2h49m.
WINDOW_MINUTES = 120

#: The gate this archive exists to measure. The conduct gate returns one reason
#: string for several different refusals - the IV premium guard and the
#: late-session cutoff among them - and a shadow path for those would be
#: measuring something nobody asked about.
GATE_MARKER = "Bias engine:"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_marks (
    symbol        TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    day           TEXT NOT NULL,
    premium       REAL NOT NULL,
    entry         REAL NOT NULL,
    underlying    TEXT NOT NULL,
    direction     TEXT,
    blocked_by    TEXT,
    module_id     TEXT,
    decision_id   TEXT,
    scanned_at    TEXT NOT NULL,
    -- KEYED BY THE DECISION, not by the contract alone. The same strike can be
    -- blocked at two different scans in one session - gas was blocked eight
    -- times on 2026-11-06, twice on the same contract - and a key of
    -- (symbol, observed_at) would merge two separate refusals into one path.
    PRIMARY KEY (symbol, scanned_at, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_shadow_marks_day
    ON shadow_marks(day, underlying, observed_at);
CREATE INDEX IF NOT EXISTS idx_shadow_marks_decision
    ON shadow_marks(symbol, scanned_at, observed_at);
"""


def db_path() -> Path:
    """Beside the candles, the chain and the other paths, NOT in hokage.db,
    which gets pruned - this archive exists to be read in three months."""
    return brain_root() / "candles.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def is_gate_block(reason: str | None) -> bool:
    """Whether this refusal came from the bias engine rather than some other
    gate. See GATE_MARKER."""
    return bool(reason) and GATE_MARKER in str(reason)


def remember(
    symbol: str,
    premium: float,
    entry: float,
    *,
    underlying: str,
    scanned_at: str,
    direction: str | None = None,
    blocked_by: str | None = None,
    module_id: str | None = None,
    decision_id: str | None = None,
    when: dt.datetime | None = None,
) -> bool:
    """Record one mark on the refused contract. True if a row was written.

    Refuses rather than guesses, on the same terms as every other archive here:
      * a premium at or below zero is a bad print or a dead quote, never a
        free option;
      * an entry at or below zero makes every percentage meaningless;
      * a mark with no scan to attach it to cannot be told apart from the next
        refusal of the same strike, so `scanned_at` is required;
      * nothing is overwritten - the row stored for an instant is the record of
        that instant.
    """
    try:
        premium = float(premium)
        entry = float(entry)
    except (TypeError, ValueError):
        return False
    if premium <= 0 or entry <= 0:
        return False
    if not symbol or not underlying or not scanned_at:
        return False

    when = when or now_ist()
    try:
        with connect() as conn:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO shadow_marks "
                "(symbol, observed_at, day, premium, entry, underlying, "
                " direction, blocked_by, module_id, decision_id, scanned_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(symbol).upper(), when.isoformat(),
                 when.date().isoformat(), premium, entry,
                 str(underlying).upper(),
                 str(direction) if direction else None,
                 str(blocked_by) if blocked_by else None,
                 str(module_id) if module_id else None,
                 str(decision_id) if decision_id else None,
                 str(scanned_at)),
            )
            return conn.total_changes > before
    except sqlite3.Error:
        # An archive that cannot write must never take the trading loop down
        # with it. The caller is inside the entry path.
        return False


def _read(sql: str, args: tuple) -> list[dict]:
    """Read-only query that answers [] rather than raising, for every caller
    here sits inside a live trading tick."""
    db = db_path()
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, args)]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def live(when: dt.datetime | None = None,
         window_minutes: int = WINDOW_MINUTES) -> list[dict]:
    """The shadows still inside their polling window, newest first.

    THE ARCHIVE IS THE REGISTRY. There is no state file and no in-memory set,
    so a restart resumes a path rather than abandoning it: what is live is
    whatever was written recently enough to still be live.

    At most one per underlying - see the module docstring. Where a session has
    blocked the same asset repeatedly, the most recent refusal is the one being
    tracked, because that is the trade Hokage would have had open now.
    """
    when = when or now_ist()
    cutoff = (when - dt.timedelta(minutes=window_minutes)).isoformat()
    rows = _read(
        "SELECT symbol, underlying, entry, direction, blocked_by, module_id,"
        " decision_id, scanned_at, MIN(observed_at) AS started,"
        " MAX(observed_at) AS latest, COUNT(*) AS marks"
        " FROM shadow_marks WHERE day = ? GROUP BY symbol, scanned_at"
        " HAVING started >= ? ORDER BY started DESC",
        (when.date().isoformat(), cutoff),
    )
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if row["underlying"] in seen:
            continue
        seen.add(row["underlying"])
        out.append(row)
    return out


def path_for(symbol: str, scanned_at: str | None = None) -> list[dict]:
    """Every stored mark of one refused contract, oldest first.

    Keyed by the contract AND the scan, because the same strike refused at two
    scans is two separate questions.
    """
    sql = "SELECT * FROM shadow_marks WHERE symbol = ?"
    args: list = [str(symbol).upper()]
    if scanned_at is not None:
        sql += " AND scanned_at = ?"
        args.append(str(scanned_at))
    sql += " ORDER BY observed_at"
    return _read(sql, tuple(args))


def coverage() -> dict:
    """What a lab can expect to find, so a study can state its own n.

    `armed` SEPARATES "NOT WIRED YET" FROM "NOTHING TO SHOW", the same way
    mirror_path.coverage does and for the same reason: the table is born on the
    first write, so before any block it does not exist - and rows=0 then is
    indistinguishable from a write path that is broken.
    """
    empty = {"rows": 0, "shadows": 0, "first_day": None, "last_day": None,
             "armed": False}
    rows = _read(
        "SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol || scanned_at) AS shadows,"
        " MIN(day) AS first_day, MAX(day) AS last_day FROM shadow_marks", ())
    if not rows:
        return empty
    row = rows[0]
    return {"rows": row["rows"] or 0, "shadows": row["shadows"] or 0,
            "first_day": row["first_day"], "last_day": row["last_day"],
            "armed": True}
