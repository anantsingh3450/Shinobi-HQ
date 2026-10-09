"""Shrink `audit_trail` back to the forensic record it was meant to be.

On 2026-10-09 the table held 3,808,221 rows in 1.5 GB. 98.9% of it was UI
telemetry written by the dashboard's SSE loop every 5 seconds and by a logging
handler that turned every INFO line into a durable row. See event_bus.py for
how that happened; this tool cleans up what it already wrote.

    python tools/ops/prune_audit_trail.py --report     # measure, change nothing
    python tools/ops/prune_audit_trail.py --prune      # archive, delete, vacuum

ARCHIVE, NOT DELETE. Purged rows are written to a gzipped JSONL file under
hokage_brain_archive/ first. Nothing is removed from the database until that
file exists and its line count matches the number of rows selected.

RUN IT WITH HOKAGE STOPPED. VACUUM takes an exclusive lock, and a running
Hokage holds connections open.

VACUUM needs free disk space roughly equal to the database size, because SQLite
rebuilds the file beside the original before swapping it in.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

#: Event types removed by --prune. Kept deliberately in step with
#: event_bus.TRANSIENT_EVENTS, and asserted equal by the test suite, so the
#: tool can never purge a type the bus still considers worth recording.
PURGEABLE = (
    "HEARTBEAT",
    "SYSTEM_HEALTH",
    "SHINOBI_LOG",
)

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "hokage_brain" / "hokage.db"
ARCHIVE_DIR = ROOT / "hokage_brain_archive"


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} PB"


def report(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM audit_trail").fetchone()[0]
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    pages = conn.execute("PRAGMA page_count").fetchone()[0]

    print(f"Database      {_human(page * pages)}   ({DB})")
    print(f"audit_trail   {total:,} rows")
    print()
    print(f"{'rows':>12}  {'share':>7}  event_type")
    print("-" * 52)

    rows = conn.execute(
        "SELECT event_type, COUNT(*) c FROM audit_trail "
        "GROUP BY event_type ORDER BY c DESC"
    ).fetchall()

    purgeable = 0
    for event_type, count in rows:
        mark = "  <- purgeable" if event_type in PURGEABLE else ""
        if event_type in PURGEABLE:
            purgeable += count
        share = (count / total * 100) if total else 0.0
        print(f"{count:>12,}  {share:>6.2f}%  {event_type}{mark}")

    print("-" * 52)
    keep = total - purgeable
    print(f"{purgeable:>12,}  {(purgeable / total * 100) if total else 0:>6.2f}%  PURGEABLE (UI telemetry)")
    print(f"{keep:>12,}  {(keep / total * 100) if total else 0:>6.2f}%  KEEP (forensic record)")

    if total:
        print()
        print(f"Estimated size after prune + vacuum: ~{_human(page * pages * keep / total)}")


def prune(conn: sqlite3.Connection, *, batch: int = 50_000) -> int:
    marks = ",".join("?" for _ in PURGEABLE)

    selected = conn.execute(
        f"SELECT COUNT(*) FROM audit_trail WHERE event_type IN ({marks})", PURGEABLE
    ).fetchone()[0]
    if not selected:
        print("Nothing to prune.")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = ARCHIVE_DIR / f"audit_trail_telemetry_{stamp}.jsonl.gz"

    print(f"Archiving {selected:,} rows to {out.name} ...")
    written = 0
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        cur = conn.execute(
            f"SELECT id, event_type, timestamp, data FROM audit_trail "
            f"WHERE event_type IN ({marks})",
            PURGEABLE,
        )
        while True:
            chunk = cur.fetchmany(batch)
            if not chunk:
                break
            for row in chunk:
                fh.write(json.dumps({
                    "id": row[0],
                    "event_type": row[1],
                    "timestamp": row[2],
                    "data": row[3],
                }) + "\n")
                written += 1
            print(f"  {written:,} / {selected:,}", end="\r", flush=True)
    print(f"  {written:,} / {selected:,}   archived to {_human(out.stat().st_size)}")

    # The archive must be complete before anything is removed. A short write
    # here and an unconditional DELETE below would lose the rows for good.
    if written != selected:
        print(f"ABORT: archived {written:,} rows but selected {selected:,}. "
              f"Nothing deleted. Archive left at {out}")
        return 0

    print("Deleting archived rows ...")
    conn.execute(f"DELETE FROM audit_trail WHERE event_type IN ({marks})", PURGEABLE)
    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM audit_trail").fetchone()[0]
    print(f"audit_trail now {remaining:,} rows")
    return written


def _files_on_disk() -> int:
    """Actual bytes the database occupies, WAL and shared-memory included.

    `page_count * page_size` is NOT this number, and the difference is the whole
    point of the exercise. The first version of this tool reported page_count
    and announced "freed 1.4 GB" while hokage.db was still 1.5 GB on disk with
    a 557 MB WAL beside it — the commander had asked for disk space back, and
    the tool reported a number that made it look like he had got it.
    """
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = DB.with_name(DB.name + suffix)
        if path.exists():
            total += path.stat().st_size
    return total


def vacuum(conn: sqlite3.Connection) -> None:
    before = _files_on_disk()
    logical = (conn.execute("PRAGMA page_size").fetchone()[0]
               * conn.execute("PRAGMA page_count").fetchone()[0])

    free = shutil.disk_usage(DB.parent).free
    if free < before * 1.2:
        print(f"SKIPPING VACUUM: needs ~{_human(before)} free, only {_human(free)} available.")
        print("The space is already reclaimed inside the file and will be reused.")
        print("Run with more free disk to shrink the file on disk.")
        return

    print(f"On disk {_human(before)}, live data {_human(logical)}. Rebuilding ...")
    t0 = time.time()
    conn.isolation_level = None

    # Order matters, and VACUUM alone is not enough.
    #
    # In WAL mode a VACUUM does not shrink hokage.db. The rebuild lands in the
    # WAL, the main file keeps its old length, and the WAL grows by the size of
    # the delete — measured on 2026-10-09: a 1.4 GB database "vacuumed" to a
    # reported 30.5 MB while the file stayed 1,507,266,560 bytes with a 616 MB
    # WAL beside it. Net effect of the cleanup: more disk used, not less.
    # Checkpointing does not fix it either; SQLite never truncates the main
    # file on checkpoint.
    #
    # Dropping to DELETE journalling for the duration is what actually rebuilds
    # the file at its compact size. WAL is restored immediately afterwards —
    # and SqliteStorageEngine.get_connection sets WAL on every connect anyway,
    # so a crash in between cannot leave Hokage journalling the slow way.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("VACUUM")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.isolation_level = ""

    after = _files_on_disk()
    print(f"Done in {time.time() - t0:.0f}s: {_human(before)} -> {_human(after)} "
          f"(freed {_human(before - after)} on disk)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true", help="measure only, change nothing")
    ap.add_argument("--prune", action="store_true", help="archive, delete, then vacuum")
    ap.add_argument("--no-vacuum", action="store_true", help="prune without rebuilding the file")
    args = ap.parse_args()

    if not args.report and not args.prune:
        ap.print_help()
        return 1
    if not DB.exists():
        print(f"No database at {DB}")
        return 1

    conn = sqlite3.connect(str(DB))
    try:
        report(conn)
        if args.prune:
            print()
            if prune(conn) and not args.no_vacuum:
                print()
                vacuum(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
