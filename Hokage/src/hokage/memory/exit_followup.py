"""What the option did AFTER Hokage sold it.

THE QUESTION, in the commander's words (2026-11-12): "what if after his exit
option again goes up and reached his target, or what if it goes further down".

Hokage has never known. `position_review` grades an exit from the REASON he
gave it - TRAIL_LOCK, TARGET_HIT, EOD - and never from what the price did
next. Two GOLDM puts on consecutive days make the cost of that blindness
concrete: both peaked above +6%, both armed the trail, both fell back to the
break-even floor, both lost (-255 and -697 net). Whether holding either one
would have reached its target or collapsed further is simply unanswerable.

THE DATA DOES NOT EXIST UNLESS WE WRITE IT. An option's price history dies
with the contract: there is no archive anywhere to look this up afterwards.
So this records forward only, and can never answer the question for the 126
positions already closed.

WHY ITS OWN TABLES AND NOT `option_chain`. That table is keyed by underlying
plus strike plus option type plus expiry date, and captures a band around the
money. A held contract drifts out of that band, and reconstructing its
tradingsymbol from the parts is a parsing problem with an expiry lookup
inside it. These tables key by the position and store the tradingsymbol that
the venue actually filled, so the follow-up quote is a direct lookup with
nothing inferred.

IT LIVES IN candles.db, beside the other measurement corpora, NOT in
hokage.db - that database reached 1.5 GB on telemetry once already.

WHAT THIS MODULE DOES NOT DO. It does not judge. `tools/research/
post_exit_lab.py` reads these rows and reports; nothing here decides whether
an exit was good, and nothing anywhere tunes an exit rule from them without
the same hold-out test that killed three hypotheses this week.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from hokage.memory.resolver import brain_root

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

#: How long after an exit the contract is still worth watching. Two hours
#: covers the horizon the weekly audit measures (60 minutes) with room either
#: side, and stops well short of turning every exit into an all-day quote
#: subscription.
FOLLOW_MINUTES = 120

SCHEMA = """
CREATE TABLE IF NOT EXISTS exit_followups (
    position_id   TEXT PRIMARY KEY,
    contract      TEXT NOT NULL,
    underlying    TEXT,
    exchange      TEXT,
    strategy_id   TEXT,
    quantity      REAL,
    entry_price   REAL,
    exit_price    REAL NOT NULL,
    exit_reason   TEXT,
    target_price  REAL,
    stop_price    REAL,
    peak_price    REAL,
    gross_pnl     REAL,
    charges       REAL,
    exited_at     TEXT NOT NULL,
    follow_until  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exit_observations (
    position_id   TEXT NOT NULL,
    captured_at   TEXT NOT NULL,
    last_price    REAL,
    bid           REAL,
    ask           REAL,
    PRIMARY KEY (position_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_followups_until
    ON exit_followups (follow_until);
"""


def db_path() -> Path:
    return brain_root() / "candles.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.executescript(SCHEMA)
    return conn


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).isoformat()


def remember_exit(
    *,
    position_id: str,
    contract: str,
    underlying: str | None,
    exchange: str | None,
    strategy_id: str | None,
    quantity: float | None,
    entry_price: float | None,
    exit_price: float,
    exit_reason: str | None,
    target_price: float | None,
    stop_price: float | None,
    peak_price: float | None,
    gross_pnl: float | None,
    charges: float | None,
    exited_at: dt.datetime | None = None,
    follow_minutes: int = FOLLOW_MINUTES,
) -> bool:
    """Write down an exit so its aftermath can be watched. True if stored.

    IDEMPOTENT ON position_id. The exit path can be reached twice for one
    position (a partial fill, then the remainder), and a second row would
    double-count that exit in every aggregate. `INSERT OR IGNORE` keeps the
    first, which is the one whose `follow_until` window is correct.

    NEVER RAISES. A measurement write must not be able to break an exit.
    """
    try:
        when = exited_at or now_utc()
        until = when + dt.timedelta(minutes=max(1, int(follow_minutes)))
        conn = connect()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO exit_followups ("
                " position_id, contract, underlying, exchange, strategy_id,"
                " quantity, entry_price, exit_price, exit_reason,"
                " target_price, stop_price, peak_price, gross_pnl, charges,"
                " exited_at, follow_until)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(position_id), str(contract),
                 (underlying or None), (exchange or None),
                 (strategy_id or None),
                 _f(quantity), _f(entry_price), float(exit_price),
                 (exit_reason or None),
                 _f(target_price), _f(stop_price), _f(peak_price),
                 _f(gross_pnl), _f(charges),
                 _iso(when), _iso(until)))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception:
        return False


def _f(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def watchlist(when: dt.datetime | None = None) -> list[dict]:
    """Exits whose follow-up window is still open.

    What the chain capture quotes in addition to its usual band. Returns the
    tradingsymbol and exchange exactly as the venue filled them, so the quote
    key needs nothing inferred.
    """
    try:
        now = when or now_utc()
        conn = connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT position_id, contract, exchange, underlying"
                " FROM exit_followups WHERE follow_until > ?",
                (_iso(now),)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


def observe(position_id: str, last_price: float | None,
            bid: float | None = None, ask: float | None = None,
            when: dt.datetime | None = None) -> bool:
    """Record one post-exit mark. True if a new row landed.

    A repeated capture at the same instant is ignored rather than updated:
    two prices for one timestamp is a contradiction, and the first one is the
    one the clock actually saw.
    """
    try:
        if last_price is None:
            return False
        conn = connect()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO exit_observations"
                " (position_id, captured_at, last_price, bid, ask)"
                " VALUES (?,?,?,?,?)",
                (str(position_id), _iso(when or now_utc()),
                 float(last_price), _f(bid), _f(ask)))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception:
        return False


def followups(limit: int | None = None) -> list[dict]:
    """Every recorded exit, newest first, with its observations attached."""
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM exit_followups ORDER BY exited_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        out = []
        for row in conn.execute(sql).fetchall():
            item = dict(row)
            marks = conn.execute(
                "SELECT captured_at, last_price, bid, ask FROM"
                " exit_observations WHERE position_id = ?"
                " ORDER BY captured_at", (item["position_id"],)).fetchall()
            item["observations"] = [dict(m) for m in marks]
            out.append(item)
        return out
    finally:
        conn.close()


def coverage() -> dict:
    """How much of the corpus actually has aftermath recorded.

    A follow-up with no observations is an exit nobody watched - the capture
    was off, the broker was unreachable, or the window fell outside market
    hours. Counting those separately is the difference between "the exit was
    fine" and "we did not look".
    """
    conn = connect()
    try:
        total = conn.execute("SELECT count(*) FROM exit_followups").fetchone()[0]
        watched = conn.execute(
            "SELECT count(DISTINCT position_id) FROM exit_observations"
        ).fetchone()[0]
        marks = conn.execute(
            "SELECT count(*) FROM exit_observations").fetchone()[0]
        return {"exits": total, "with_observations": watched,
                "without_observations": total - watched, "marks": marks}
    finally:
        conn.close()
