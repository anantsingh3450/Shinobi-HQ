"""Clear out the one repeated warning that is 99.7% of the incident table.

    python tools/ops/prune_watchdog_incidents.py --report   # measure only
    python tools/ops/prune_watchdog_incidents.py --prune    # archive, delete, vacuum

WHAT IS IN THERE. 47,675 incidents, of which 47,519 are byte-for-byte the
same row:

    severity    WARNING
    subsystem   heartbeat_freshness
    root_cause  Stale heartbeats detected for: market_data

The market_data heartbeat can only be published by a quote that actually came
back, so it goes stale whenever the feed is quiet - including every night and
every weekend, when the feed is quiet for the obvious reason. Until the feed
window shipped on 2026-10-12, the watchdog raised that warning around the
clock.

The effect of the fix, by day:

    2026-10-10   9,927
    2026-10-11  12,814
    2026-10-12   2,033   <- feed window scoped to 09:00-23:30 IST
    2026-10-13     214   <- and all 214 fall inside 14:00-15:18 IST,
                            which is exactly the DNS outage that day

So the writer is now honest: what it still records is a real outage. Rows from
before the fix describe a defect that no longer exists, and 99.7% of them are
one sentence repeated.

WHY AGE ALONE IS THE WRONG RULE. A rolling 7-day window keeps 26,269 of them,
because the two worst days are inside it. The noise is bounded by WHEN THE
WRITER WAS FIXED, not by how old it is, so that date is the default cut and it
is stated rather than computed.

NEVER TOUCHED, whatever the cut:
  * every HIGH or CRITICAL incident (127 of them - real, multi-subsystem)
  * every warning that is not this exact sentence (156 rows: strategy_engine,
    improvement_engine, orchestrator)
  * everything on or after the cut date

ARCHIVE, NOT DELETE. Rows go to a gzipped JSONL beside the brain first, with
the table's DDL in the header, and nothing is removed until that file exists
and holds exactly as many rows as were selected.

RUN IT WITH HOKAGE STOPPED. VACUUM takes an exclusive lock.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

# The WAL trap - a VACUUM in WAL mode does not shrink the file, it grows it -
# cost a day to find on 2026-10-09 and is solved once, there. Importing rather
# than copying keeps that lesson in one place.
from prune_audit_trail import (  # noqa: E402
    ARCHIVE_DIR,
    DB,
    _human,
    vacuum,
)

#: The exact sentence, matched in full rather than with LIKE. A pattern would
#: eventually swallow a different market_data incident that deserved reading.
NOISE_ROOT_CAUSE = "Stale heartbeats detected for: market_data"
NOISE_SUBSYSTEM = "heartbeat_freshness"

#: The day the feed window shipped and the writer stopped crying at night.
#: Rows before this describe a defect that no longer exists.
DEFAULT_CUT = "2026-10-12"

_WHERE = (
    "severity = 'WARNING' AND subsystem = ? AND root_cause = ? "
    "AND substr(timestamp, 1, 10) < ?"
)


def _params(cut: str) -> tuple[str, str, str]:
    return (NOISE_SUBSYSTEM, NOISE_ROOT_CAUSE, cut)


def report(conn: sqlite3.Connection, cut: str) -> int:
    total = conn.execute("SELECT COUNT(*) FROM watchdog_incidents;").fetchone()[0]
    selected = conn.execute(
        f"SELECT COUNT(*) FROM watchdog_incidents WHERE {_WHERE};", _params(cut)
    ).fetchone()[0]
    print(f"  database          {DB}")
    print(f"  incidents         {total}")
    print(f"  cut before        {cut}")
    print(f"  selected          {selected}  ({selected / total * 100:.1f}%)")
    print(f"  kept              {total - selected}")

    print("\n  kept, by severity:")
    for sev, n in conn.execute(
        f"SELECT severity, COUNT(*) FROM watchdog_incidents "
        f"WHERE NOT ({_WHERE}) GROUP BY severity ORDER BY severity;",
        _params(cut),
    ):
        print(f"    {sev:9} {n}")

    print("\n  kept, most recent days:")
    for day, n in conn.execute(
        f"SELECT substr(timestamp,1,10), COUNT(*) FROM watchdog_incidents "
        f"WHERE NOT ({_WHERE}) GROUP BY 1 ORDER BY 1 DESC LIMIT 6;",
        _params(cut),
    ):
        print(f"    {day}  {n}")
    return selected


def prune(conn: sqlite3.Connection, cut: str) -> int:
    conn.row_factory = sqlite3.Row
    rows = list(
        conn.execute(
            f"SELECT * FROM watchdog_incidents WHERE {_WHERE} ORDER BY timestamp;",
            _params(cut),
        )
    )
    if not rows:
        print("  nothing to prune.")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARCHIVE_DIR / f"watchdog_incidents_stale_market_data_{stamp}.jsonl.gz"

    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='watchdog_incidents';"
    ).fetchone()

    written = 0
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "_archive": "watchdog_incidents: repeated market_data staleness warnings",
            "_reason": (
                "written around the clock until the feed window shipped "
                "2026-10-12; see tools/ops/prune_watchdog_incidents.py"
            ),
            "_table": "watchdog_incidents",
            "_cut_before": cut,
            "_schema": ddl[0] if ddl else None,
            "_archived_at": datetime.now(timezone.utc).isoformat(),
        }) + "\n")
        for r in rows:
            fh.write(json.dumps({k: r[k] for k in r.keys()}, default=str) + "\n")
            written += 1

    with gzip.open(out, "rt", encoding="utf-8") as fh:
        lines = sum(1 for _ in fh) - 1  # the header is not a row

    if written != len(rows) or lines != len(rows):
        print(
            f"  ABORTED: archive holds {lines} rows, {len(rows)} were selected "
            f"({written} written). Nothing deleted."
        )
        return 1

    print(f"  archived {written} rows -> {out.name} ({_human(out.stat().st_size)})")

    with conn:
        conn.execute(f"DELETE FROM watchdog_incidents WHERE {_WHERE};", _params(cut))

    left = conn.execute("SELECT COUNT(*) FROM watchdog_incidents;").fetchone()[0]
    still = conn.execute(
        f"SELECT COUNT(*) FROM watchdog_incidents WHERE {_WHERE};", _params(cut)
    ).fetchone()[0]
    print(f"  deleted {written} rows. {left} incidents remain ({still} still selectable).")
    return 0 if still == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true", help="measure, change nothing")
    ap.add_argument("--prune", action="store_true", help="archive, delete, vacuum")
    ap.add_argument(
        "--before", default=DEFAULT_CUT, metavar="YYYY-MM-DD",
        help=f"archive this message only before this date (default {DEFAULT_CUT})",
    )
    args = ap.parse_args()

    if not DB.exists():
        print(f"  no database at {DB}")
        return 1
    if not (args.report or args.prune):
        ap.print_help()
        return 1
    try:
        datetime.strptime(args.before, "%Y-%m-%d")
    except ValueError:
        print(f"  --before must be YYYY-MM-DD, got {args.before!r}")
        return 1

    if args.report and not args.prune:
        conn = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
        try:
            report(conn, args.before)
        finally:
            conn.close()
        return 0

    conn = sqlite3.connect(DB)
    try:
        selected = report(conn, args.before)
        print()
        if selected == 0:
            return 0
        rc = prune(conn, args.before)
        if rc == 0:
            print()
            vacuum(conn)
        return rc
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
