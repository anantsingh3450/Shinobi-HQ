"""Write India VIX down, once, forever.

    python tools/ops/archive_vix.py            # top up and report
    python tools/ops/archive_vix.py --status   # report only, no broker call

WHY THIS EXISTS. VIX is the only input to the IV premium guard, the gate that
refused all thirteen of Hokage's signals on 2026-10-14 and eleven more on
2026-10-15. It was archived nowhere, so every question about volatility --
including the variance premium result, the first thing in this system to clear
a corrected bar on both halves -- could only be asked while a Zerodha token
happened to be alive. Evidence that expires with a token is not evidence.

THE BOT IS THE PRIMARY ARCHIVER. `_india_vix_percentile` already pulls 70
daily bars every time the guard runs and now writes them through, so on any
day Hokage runs this has nothing to do. This exists for the days he does not:
a weekend sync, a host move, a session he spent down. The archive is INSERT OR
IGNORE, so running it twice writes nothing twice.

It needs a live broker session. With no session and an empty archive it exits
non-zero rather than reporting success over nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from hokage.memory import vix_archive  # noqa: E402


def report() -> dict:
    cover = vix_archive.coverage()
    print(f"  archive   {vix_archive.db_path()}")
    if not cover["days"]:
        print("  EMPTY — no India VIX has ever been archived.")
        return cover
    print(f"  days      {cover['days']}")
    print(f"  span      {cover['first']} .. {cover['last']}")
    print(f"  newest is {cover['stale_days']} day(s) behind today")
    return cover


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true",
                    help="report what is held; never touch the broker")
    args = ap.parse_args()

    print("=" * 72)
    print("  INDIA VIX ARCHIVE")
    print("=" * 72)
    before = report()

    if args.status:
        return 0 if before["days"] else 1

    from iv_lab import fetch_vix_from_kite

    try:
        fetched = fetch_vix_from_kite()
    except Exception as exc:
        print(f"\n  live fetch FAILED: {str(exc)[:120]}")
        if before["days"]:
            print("  The archive still holds what it held. Nothing was lost.")
            return 1
        print("  Nothing archived and nothing fetched. This needs a live")
        print("  Zerodha session — the commander logs in, the tool does not.")
        return 1

    added = vix_archive.remember(fetched)
    print(f"\n  fetched   {len(fetched)} daily closes from Kite")
    print(f"  added     {added} new")
    print("  (a day already held is never overwritten, and the session in")
    print("   progress is never written at all — its close is not a close)")
    print("")
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
