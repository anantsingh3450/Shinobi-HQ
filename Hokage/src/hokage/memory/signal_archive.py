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
    PRIMARY KEY (scanned_at, symbol, strategy_id)
);
CREATE INDEX IF NOT EXISTS idx_auction_signals_cell
    ON auction_signals(symbol, strategy_id, day);
"""


def db_path() -> Path:
    """Beside the candles, the VIX, the chain and the premium paths."""
    return brain_root() / "candles.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
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
) -> int:
    """Record one scan: every module that was asked, and what it answered.

    `verdicts` is an iterable of (strategy_id, module_id, signal) where signal
    exposes should_enter / direction / confidence / reason.

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
        rows.append((
            stamp, day, str(symbol).upper(), str(strategy_id),
            str(module_id) if module_id else None,
            1 if fired else 0,
            (getattr(sig, "direction", None) or None) if fired else None,
            _num(getattr(sig, "confidence", None)) if fired else None,
            1 if (winner_strategy_id and strategy_id == winner_strategy_id) else 0,
            None,                       # filled: stamped later by mark_filled
            _num(underlying),
            (getattr(sig, "reason", None) or None),
        ))
    if not rows:
        return 0
    try:
        with connect() as conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO auction_signals (scanned_at, day, symbol, "
                "strategy_id, module_id, fired, direction, confidence, won, "
                "filled, underlying, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
