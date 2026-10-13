"""Empty `trades` of the 101 exit legs that have been posing as open positions.

    python tools/ops/reconcile_phantom_trades.py --report      # change nothing
    python tools/ops/reconcile_phantom_trades.py --reconcile   # archive, delete

WHAT IS ACTUALLY IN THERE. The `trades` table holds 101 rows. Every one of
them has `strategy_name = "AutonomousExit"` and `status = "OPEN"`, and the
newest is 2026-08-17. Not one genuine entry was ever written to this table:
`AutonomousExit` is the EXIT writer, so these are closing legs recorded as if
they were fresh positions. 85 of them landed on 2026-07-15 inside seconds of
each other on one CRUDEOIL strike, alternating LONG and SHORT - the
reduce_only runaway, where exits could open positions.

The real ledger is `positions`: 382 rows, all CLOSED, carrying entry and exit
prices, realised P&L and, since 2026-08-17, `strategy_id`. Nothing is
unaccounted for. The reconciliation needed here is to stop a dead table
claiming 101 live positions.

WHY NOT MARK THEM CLOSED, which is the obvious reading of "reconcile".
Because `calibration_engine` selects `WHERE t.status = 'CLOSED'` and bins what
it finds by the confidence the strategy predicted, comparing forecast win rate
against realised. Today all 101 are OPEN, so that query matches nothing and
the engine honestly returns empty. Flipping them to CLOSED would hand it 101
fabricated round trips with no outcome rows, and it would publish a
calibration curve computed from them. A measurement built from invented trades
cannot be told apart from a real one - which is the same reason the health
panel reports None for the latencies nothing measures.

An empty table says "nothing was recorded here", and that is the truth.

ARCHIVE, NOT DELETE. Every row is written to a gzipped JSONL file beside the
brain first, with the schema alongside it, and nothing is removed until that
file exists and holds exactly as many lines as were selected.

RUN IT WITH HOKAGE STOPPED. Nothing has written to this table since
2026-08-17, so contention is unlikely rather than impossible, and a ledger is
not the place to find out.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# Run by hand, so nothing has loaded `.env`; the resolver reads
# HOKAGE_BRAIN_ROOT from the environment and then from `.env`.
#
# NO FALLBACK, DELIBERATELY. prune_audit_trail keeps a repo-relative default
# for when this import fails, which is right for a tool that only trims
# telemetry. This one DELETES FROM A LEDGER, and a guessed path means either
# emptying a database nobody reads while the live one keeps its phantoms, or
# modifying one the operator did not mean. On 2026-10-09 exactly that split
# brain happened: the liveness probe fell back to the repo-relative default
# minutes after the brain moved to C:/Hokage and read a stale marker from
# OneDrive. Refusing is the only safe answer here.
from hokage.memory.resolver import brain_root as _brain_root

BRAIN = _brain_root()
DB = BRAIN / "hokage.db"

#: Beside the brain, not inside it, so a brain move takes the archive along.
ARCHIVE_DIR = BRAIN.parent / "hokage_brain_archive"

#: The exit writer's own label. Rows carrying it are closing legs, never
#: entries. Scoped on purpose: if a genuine entry ever lands in this table,
#: this tool must leave it alone rather than empty the ledger.
EXIT_WRITER = "AutonomousExit"


def _rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            "SELECT * FROM trades WHERE strategy_name = ? AND status = 'OPEN'"
            " ORDER BY executed_at ASC;",
            (EXIT_WRITER,),
        )
    )


def report(conn: sqlite3.Connection) -> int:
    total = conn.execute("SELECT COUNT(*) FROM trades;").fetchone()[0]
    selected = _rows(conn)
    print(f"  database            {DB}")
    print(f"  trades rows         {total}")
    print(f"  phantom exit legs   {len(selected)}  (strategy_name={EXIT_WRITER!r}, status=OPEN)")

    others = total - len(selected)
    print(f"  everything else     {others}" + ("  <- LEFT UNTOUCHED" if others else ""))

    if selected:
        by_day: dict[str, int] = {}
        for r in selected:
            by_day[str(r["executed_at"])[:10]] = by_day.get(str(r["executed_at"])[:10], 0) + 1
        print("\n  by day:")
        for day in sorted(by_day):
            print(f"    {day}  {by_day[day]:>3}")

    pos = conn.execute("SELECT COUNT(*) FROM positions;").fetchone()[0]
    closed = conn.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED';").fetchone()[0]
    print(f"\n  the real ledger: positions holds {pos} rows, {closed} of them CLOSED")
    return len(selected)


def reconcile(conn: sqlite3.Connection) -> int:
    selected = _rows(conn)
    if not selected:
        print("  nothing to reconcile.")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARCHIVE_DIR / f"trades_phantom_exit_legs_{stamp}.jsonl.gz"

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades';"
    ).fetchone()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(trades);")]

    written = 0
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        # The schema first, so the archive can be read back without this repo.
        fh.write(json.dumps({
            "_archive": "trades rows written by the AutonomousExit writer and left as OPEN",
            "_reason": "exit legs recorded as entries; see tools/ops/reconcile_phantom_trades.py",
            "_table": "trades",
            "_schema": schema[0] if schema else None,
            "_columns": columns,
            "_archived_at": datetime.now(timezone.utc).isoformat(),
        }) + "\n")
        for r in selected:
            fh.write(json.dumps({k: r[k] for k in r.keys()}, default=str) + "\n")
            written += 1

    # The header line is not a row, so count rows only.
    with gzip.open(out, "rt", encoding="utf-8") as fh:
        lines = sum(1 for _ in fh) - 1

    if written != len(selected) or lines != len(selected):
        print(
            f"  ABORTED: archive holds {lines} rows, {len(selected)} were selected "
            f"({written} written). Nothing deleted."
        )
        return 1

    print(f"  archived {written} rows -> {out}")

    ids = [r["trade_id"] for r in selected]
    with conn:
        conn.executemany("DELETE FROM trades WHERE trade_id = ?;", [(i,) for i in ids])

    left = conn.execute("SELECT COUNT(*) FROM trades;").fetchone()[0]
    still_phantom = len(_rows(conn))
    print(f"  deleted {len(ids)} rows. trades now holds {left} rows ({still_phantom} phantom).")
    if still_phantom:
        print("  WARNING: phantom rows remain; re-run --report.")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true", help="measure, change nothing")
    ap.add_argument("--reconcile", action="store_true", help="archive, then delete")
    args = ap.parse_args()

    if not DB.exists():
        print(f"  no database at {DB}")
        return 1
    if not (args.report or args.reconcile):
        ap.print_help()
        return 1

    # Read-only for --report: a measuring run must not be able to change
    # anything, including by taking a write lock.
    if args.report and not args.reconcile:
        conn = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
        try:
            report(conn)
        finally:
            conn.close()
        return 0

    conn = sqlite3.connect(DB)
    try:
        report(conn)
        print()
        return reconcile(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
