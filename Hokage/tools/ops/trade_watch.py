"""Say when Hokage trades, watched from OUTSIDE Hokage.

One stdout line per entry and per exit, for a Monitor to turn into a
notification. Nothing else is printed, so silence means nothing happened.

WHY THIS FILE IS PARANOID. The previous day-watch reported "no trade" for
four consecutive days and was wrong every one of them: it opened the ledger
by a RELATIVE path, the resulting error was swallowed by a handler that
logged "no change", and a real +1,505 win went unreported. The failure mode
of a watcher is not a crash, it is confident silence. So:

  * THE BRAIN ROOT IS ABSOLUTE, from the environment or a hardcoded default.
    Nothing here depends on the working directory.
  * EVERY FAILURE PRINTS. A watch that cannot read the ledger must say so;
    silence is reserved for "nothing happened" and must mean only that.
  * IT PRINTS ONE BASELINE LINE ON START, so an armed watch is
    distinguishable from a dead one without waiting for a trade.
  * THE DATABASE IS OPENED READ-ONLY. A watcher that can lock the ledger can
    stop the thing it is watching.

`positions` is the ledger. `trades` is the exit writer's dead table and has
never held a real entry - that confusion has produced three wrong answers
already, one of them from an earlier version of this watch.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

#: Absolute, and absolute on purpose. See the module docstring.
BRAIN_ROOT = Path(os.environ.get("HOKAGE_BRAIN_ROOT", r"C:\Hokage\hokage_brain"))

POLL_SECONDS = 20

_COLUMNS = ("position_id", "market", "direction", "quantity", "entry_price",
            "realized_pnl", "unrealized_pnl", "status", "opened_at",
            "closed_at", "strategy_id")


def _say(line: str) -> None:
    """One event, flushed. An unflushed line is an unsent notification."""
    print(line, flush=True)


def _snapshot(db: Path) -> dict[str, dict]:
    """Every position, keyed by id. Read-only; never locks the ledger."""
    uri = f"{db.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM positions").fetchall()
    finally:
        conn.close()
    return {r["position_id"]: dict(r) for r in rows}


def _money(value) -> str:
    try:
        return f"{float(value):+,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _entry_line(row: dict) -> str:
    return (f"ENTRY  {row.get('market')}  {row.get('direction')} "
            f"qty {row.get('quantity')} @ {row.get('entry_price')}  "
            f"[{row.get('strategy_id')}]  opened {row.get('opened_at')}")


def _exit_line(row: dict) -> str:
    return (f"EXIT   {row.get('market')}  {row.get('status')}  "
            f"realised {_money(row.get('realized_pnl'))}  "
            f"[{row.get('strategy_id')}]  closed {row.get('closed_at')}")


def main() -> int:
    db = BRAIN_ROOT / "hokage.db"

    # THE FIRST READ IS ALLOWED TO BE FATAL, and only the first. A watch that
    # cannot open the ledger at all has nothing to watch, and starting anyway
    # would be the exact silence this file exists to prevent.
    try:
        seen = _snapshot(db)
    except Exception as exc:
        _say(f"WATCH-ERROR could not open the ledger at {db}: "
             f"{type(exc).__name__}: {exc}")
        return 1

    open_now = [r for r in seen.values() if r.get("status") != "CLOSED"]
    _say(f"BASELINE watching {db} - {len(seen)} positions on record, "
         f"{len(open_now)} open. Entries and exits from here will be reported.")
    for row in open_now:
        _say("ALREADY OPEN  " + _entry_line(row))

    consecutive_faults = 0
    while True:
        time.sleep(POLL_SECONDS)
        try:
            current = _snapshot(db)
            consecutive_faults = 0
        except Exception as exc:
            # EVERY fault prints. The ledger being briefly locked is normal,
            # but a fault that repeats is the watch going blind and must not
            # look like a quiet market.
            consecutive_faults += 1
            _say(f"WATCH-ERROR read {consecutive_faults} failed: "
                 f"{type(exc).__name__}: {exc}")
            continue

        for pid, row in current.items():
            was = seen.get(pid)
            if was is None:
                _say(_entry_line(row))
            elif was.get("status") != row.get("status"):
                _say(_exit_line(row))
        seen = current


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
