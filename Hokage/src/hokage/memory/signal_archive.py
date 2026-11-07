"""Every module's signal, not just the one that won the auction.

2026-10-26. The commander's mirror experiment put RiderTrend in the arena
beside TrendRider: identical logic, opposite option, same asset. Both fired
on both evening gas scans:

    19:00   TrendRider: LONG (conf 60)  |  RiderTrend: SHORT (conf 60)
    19:30   TrendRider: LONG (conf 60)  |  RiderTrend: SHORT (conf 60)

TrendRider took both. The MCX arena is WINNER-TAKE-ASSET - one strategy per
asset per scan, highest confidence wins - and a mirror carries its original's
confidence by deliberate design, so every scan is an exact tie and the
tie-break picks the same side forever. RiderTrend produced two correct
signals and will never place an order while its original is live on gas.

THE EXPERIMENT CANNOT BE RUN AS PAIRED LIVE FILLS. Filling both would mean
two opposite positions on one asset, which breaks the one-bet-per-asset rule
the correlation cap exists to enforce. So the losing side is SCORED instead
of traded, which is what this archive makes possible.

IT IS STRICTLY MORE EVIDENCE, NOT A CONSOLATION PRIZE. An auction winner is
a biased sample: it is the signal that happened to out-bid the others on that
scan. Scoring every signal measures each module on its OWN firing condition,
which is the thing entry_module_lab has always wanted and could only get by
re-deriving signals offline from a copy of the production rules - a copy that
drifts. These rows come from the live evaluate() call itself.

WHAT IS STORED AND WHY EACH FIELD EARNS ITS PLACE
    the underlying price AT SIGNAL TIME, because scoring walks forward from
      there and re-deriving it later from candles invites an off-by-one bar
    confidence, because the auction ranks on it and the ties are the story
    the verdict of EVERY module, winner and loser alike, each flagged, so a
      lab can ask "what would the loser have made" without guessing who lost
    the refusals too, so the denominator is real: a module that stands aside
      ninety-nine times out of a hundred has a different character from one
      that fires constantly, and a table of only the fires hides that

IT LIVES IN candles.db. hokage.db reached 1.5 GB on telemetry and was pruned
on 2026-10-09; an archive meant to answer a question in three months must not
sit in the store that gets pruned.

NOTHING HERE DECIDES ANYTHING. It records what the auction already computed
and threw away. No gate reads it, no entry depends on it, and every failure
path returns quietly - it runs inside the scan loop, and a scan that crashed
because a row could not be written would be a far worse bug than a lost row.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from hokage.memory.resolver import brain_root

IST = ZoneInfo("Asia/Kolkata")

SCHEMA = """
CREATE TABLE IF NOT EXISTS auction_signals (
    scanned_at  TEXT NOT NULL,
    day         TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    module_id   TEXT,
    fired       INTEGER NOT NULL,
    direction   TEXT,
    confidence  REAL,
    won         INTEGER NOT NULL,
    filled      INTEGER,
    underlying  REAL,
    reason      TEXT,
    option_symbol  TEXT,
    option_premium REAL,
    PRIMARY KEY (scanned_at, symbol, strategy_id)
);
CREATE INDEX IF NOT EXISTS idx_auction_signals_cell
    ON auction_signals(symbol, strategy_id, day);
"""


def db_path() -> Path:
    """Beside the candles, the VIX, the chain and the premium paths."""
    return brain_root() / "candles.db"


#: Columns added after the table was first created. CREATE TABLE IF NOT
#: EXISTS does nothing to a table that already exists, so a new column has to
#: be added by hand or every existing brain keeps writing the old shape and
#: the lab silently reads NULLs forever.
_ADDED_COLUMNS = (
    ("option_symbol", "TEXT"),
    ("option_premium", "REAL"),
)


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(auction_signals)")}
    for name, kind in _ADDED_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE auction_signals ADD COLUMN {name} {kind}")
    return conn


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def _num(value) -> float | None:
    """A value we do not have is None, never 0.0. A confidence of 0.0 means
    the module scored it zero; None means nobody asked."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def remember_scan(
    symbol: str,
    verdicts,
    *,
    winner_strategy_id: str | None = None,
    underlying: float | None = None,
    when: dt.datetime | None = None,
    premiums: dict | None = None,
) -> int:
    """Record one scan: every module that was asked, and what it answered.

    `verdicts` is an iterable of (strategy_id, module_id, signal) where signal
    exposes should_enter / direction / confidence / reason.

    `premiums` maps a lowercase direction ("long"/"short") to
    (option_symbol, premium): what the contract that side would have BOUGHT
    cost at this instant. It is the only part of a scan that cannot be
    recovered later — an option's history dies with its contract — and it is
    what separates "wrong about direction" from "wrong about movement" for a
    module that never fills, because both sides buy premium and both pay
    theta. Absent or unpriceable sides are written as NULL, never as 0.0.

    Returns rows written. Never raises: this runs inside the scan loop.
    """
    when = when or now_ist()
    stamp = when.isoformat()
    day = when.date().isoformat()

    rows = []
    for item in verdicts or ():
        try:
            strategy_id, module_id, sig = item
        except (TypeError, ValueError):
            continue
        if not strategy_id or sig is None:
            continue
        fired = bool(getattr(sig, "should_enter", False))
        direction = (getattr(sig, "direction", None) or None) if fired else None
        # Only a side that FIRED has a contract it would have bought. A
        # stand-aside has no direction, so pricing one would be inventing a
        # trade nobody proposed.
        option_symbol, option_premium = None, None
        if fired and premiums:
            quoted = premiums.get(str(direction or "").lower())
            if quoted:
                option_symbol, option_premium = quoted[0], _num(quoted[1])
        rows.append((
            stamp, day, str(symbol).upper(), str(strategy_id),
            str(module_id) if module_id else None,
            1 if fired else 0,
            direction,
            _num(getattr(sig, "confidence", None)) if fired else None,
            1 if (winner_strategy_id and strategy_id == winner_strategy_id) else 0,
            None,                       # filled: stamped later by mark_filled
            _num(underlying),
            (getattr(sig, "reason", None) or None),
            option_symbol, option_premium,
        ))
    if not rows:
        return 0
    try:
        with connect() as conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO auction_signals (scanned_at, day, symbol, "
                "strategy_id, module_id, fired, direction, confidence, won, "
                "filled, underlying, reason, option_symbol, option_premium) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows)
            return conn.total_changes - before
    except sqlite3.Error:
        return 0


def mark_filled(symbol: str, strategy_id: str, scanned_at: str,
                filled: bool) -> bool:
    """Record whether the winner's order actually became a position.

    WINNING IS NOT FILLING. A winner still faces the bias veto, the
    correlation cap, the IV guard and affordability — on 2026-10-26 the gas
    winner was blocked by "underlying tape is MIXED" after winning. A study
    that treats every winner as a trade is measuring a different system.
    """
    try:
        with connect() as conn:
            before = conn.total_changes
            conn.execute(
                "UPDATE auction_signals SET filled = ? WHERE scanned_at = ? "
                "AND symbol = ? AND strategy_id = ?",
                (1 if filled else 0, scanned_at, str(symbol).upper(),
                 str(strategy_id)))
            return conn.total_changes > before
    except sqlite3.Error:
        return False


def opposing_leg(symbol: str, scanned_at: str,
                 held_option: str | None = None) -> dict | None:
    """The priced contract a LOSING side of this scan would have bought.

    One leg at most, and deliberately: `remember_scan`'s premium map is keyed
    by DIRECTION, so however many modules fired, a scan holds at most one CE
    and one PE. The leg returned is the one whose contract is not the one that
    filled - which, for a mirror and its original, is exactly the opposite
    option the commander's 2026-10-23 hypothesis is about.

    Returns None rather than guessing when the losing side was unpriceable
    (a thin chain, a dead feed), because a leg with no entry premium cannot
    start a path. Absent is not zero.
    """
    db = db_path()
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM auction_signals LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return None
    try:
        rows = conn.execute(
            "SELECT module_id, strategy_id, direction, option_symbol,"
            " option_premium, reason FROM auction_signals"
            " WHERE scanned_at = ? AND symbol = ? AND fired = 1 AND won = 0"
            " AND option_symbol IS NOT NULL AND option_premium > 0",
            (str(scanned_at), str(symbol).upper()),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    held = str(held_option).upper() if held_option else None
    for row in rows:
        if held and str(row["option_symbol"]).upper() == held:
            continue            # the loser proposed the same contract
        return dict(row)
    return None


def winning_leg(symbol: str, scanned_at: str) -> dict | None:
    """The priced contract the WINNER of this scan would have bought.

    The other half of `opposing_leg`, and it exists for the trade that never
    happened: when a gate refuses an auction winner, this is the contract it
    was about to buy and what that cost at the instant of the refusal. Without
    it a blocked decision has no entry price, and a path with no entry cannot
    be scored - see `hokage.memory.shadow_path`.

    Returns None rather than guessing when the winning side was unpriceable
    (a thin chain, a dead feed). Absent is not zero.
    """
    db = db_path()
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM auction_signals LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return None
    try:
        row = conn.execute(
            "SELECT module_id, strategy_id, direction, option_symbol,"
            " option_premium, reason FROM auction_signals"
            " WHERE scanned_at = ? AND symbol = ? AND fired = 1 AND won = 1"
            " AND option_symbol IS NOT NULL AND option_premium > 0 LIMIT 1",
            (str(scanned_at), str(symbol).upper()),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return dict(row) if row else None


def signals_for(strategy_id: str, symbol: str | None = None,
                fired_only: bool = True) -> list[dict]:
    """Every recorded signal for one cell, oldest first."""
    db = db_path()
    if not db.exists():
        return []
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM auction_signals LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return []
    try:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM auction_signals WHERE strategy_id = ?"
        params: list = [str(strategy_id)]
        if symbol:
            sql += " AND symbol = ?"
            params.append(str(symbol).upper())
        if fired_only:
            sql += " AND fired = 1"
        sql += " ORDER BY scanned_at"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def coverage() -> dict:
    """What the archive holds. Empty reads as empty, never as zero."""
    empty = {"rows": 0, "scans": 0, "fired": 0, "cells": 0,
             "first": None, "last": None}
    db = db_path()
    if not db.exists():
        return empty
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM auction_signals LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return empty
    try:
        rows, scans, fired, cells, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT scanned_at || symbol), "
            "SUM(fired), COUNT(DISTINCT strategy_id || symbol), "
            "MIN(day), MAX(day) FROM auction_signals").fetchone()
    finally:
        conn.close()
    return {"rows": rows or 0, "scans": scans or 0, "fired": fired or 0,
            "cells": cells or 0, "first": first, "last": last}
