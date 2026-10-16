"""How many sessions was Hokage actually awake for?

    python tools/ops/session_coverage.py
    python tools/ops/session_coverage.py --weeks 12

WHY THIS EXISTS. On 2026-10-16 the question was why no trade had been taken
since 2026-09-22. The gate tally said entry modules were standing aside, the
signal-rate lab said the modules fire as often as they ever have, and both
were answering a question nobody had checked the premise of.

The premise was false. Hokage's last process before the gap died at
2026-09-23 06:27, and the next one started 2026-10-09 18:26 — sixteen
calendar days, twelve trading sessions, with no process, no decisions and no
log file. There was a second gap from 09-05 to 09-20.

AND THE WATCH DID NOT CATCH IT. `logs/liveness.log` has no entries for those
days either. The external liveness probe was built after a 3h39m death that
Hokage reported as "Health Score 100/100", on the principle that his own
watchdog dies with him — but it runs as a Windows scheduled task on the same
laptop under the same interactive logon. It is independent of the PROCESS and
not of the MACHINE, and the machine is what went away. A probe that shares a
failure domain with the thing it watches cannot report that domain failing.

So the single largest determinant of how fast Hokage learns is not his
strategy. It is how many sessions he is awake for, and nothing measured it.

WHAT COUNTS AS A SESSION. The candle archive, not a hardcoded calendar. A day
with archived index candles is a day the market traded; this needs no holiday
list and stays correct as the archive grows. A day the archive does not know
about is reported as unknown, never as a day Hokage missed.

THIS MEASURES, IT DOES NOT ALARM. The fix for an unwatched machine is a watch
that does not live on it, and that is the commander's call to make.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hokage.memory.resolver import brain_root  # noqa: E402

#: The index whose archived days define "the market was open". An index is a
#: calculation published on every trading day, so its presence is the cleanest
#: available proxy for a session and it carries no holiday table to rot.
SESSION_SYMBOL = "NIFTY"

#: A session with fewer decisions than this is counted as PARTIAL rather than
#: covered. A process that booted at 15:00 and recorded four rows was not
#: awake for that session in any sense that produces learning.
MIN_DECISIONS_FOR_A_FULL_SESSION = 20


def trading_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """Days the market traded, from the candle archive."""
    db = brain_root() / "candles.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts,1,10) FROM candles "
            "WHERE symbol=? AND ts>=? AND ts<=? ORDER BY 1",
            (SESSION_SYMBOL, start.isoformat(), end.isoformat() + " 23:59:59"),
        ).fetchall()
    finally:
        conn.close()
    return [dt.date.fromisoformat(r[0]) for r in rows]


def decisions_by_day(start: dt.date, end: dt.date) -> dict[dt.date, int]:
    db = brain_root() / "hokage.db"
    if not db.exists():
        return {}
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT substr(timestamp,1,10) d, COUNT(*) FROM no_trade_decisions "
            "WHERE timestamp>=? AND timestamp<=? GROUP BY d",
            (start.isoformat(), end.isoformat() + "T23:59:59Z"),
        ).fetchall()
    finally:
        conn.close()
    return {dt.date.fromisoformat(d): n for d, n in rows}


def coverage(start: dt.date, end: dt.date) -> dict:
    """Sessions the market was open against sessions Hokage recorded."""
    sessions = trading_days(start, end)
    seen = decisions_by_day(start, end)
    if not sessions:
        return {"sessions": 0}

    covered, partial, missed = [], [], []
    for day in sessions:
        n = seen.get(day, 0)
        if n == 0:
            missed.append(day)
        elif n < MIN_DECISIONS_FOR_A_FULL_SESSION:
            partial.append(day)
        else:
            covered.append(day)

    # The longest unbroken run of missed sessions. One missed day is a bad
    # morning; twelve in a row is a system nobody is watching, and the two
    # should never average into the same percentage.
    longest, run, worst = 0, 0, []
    current: list[dt.date] = []
    for day in sessions:
        if seen.get(day, 0) == 0:
            run += 1
            current.append(day)
            if run > longest:
                longest, worst = run, list(current)
        else:
            run, current = 0, []

    return {
        "sessions": len(sessions),
        "covered": len(covered),
        "partial": len(partial),
        "missed": len(missed),
        "missed_days": missed,
        "longest_blackout": longest,
        "blackout_days": worst,
        "first": sessions[0],
        "last": sessions[-1],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--weeks", type=int, default=8)
    args = ap.parse_args()

    end = dt.date.today()
    start = end - dt.timedelta(weeks=args.weeks)

    print("=" * 76)
    print("  SESSION COVERAGE — how many sessions Hokage was awake for")
    print(f"  sessions come from the {SESSION_SYMBOL} candle archive, so no")
    print("  holiday calendar can go stale. A day the archive does not know")
    print("  about is not counted against him.")
    print("=" * 76)

    out = coverage(start, end)
    if not out.get("sessions"):
        print(f"\n  The candle archive holds no {SESSION_SYMBOL} days in this "
              f"window, so coverage cannot be measured.")
        print("  That is missing data, not a perfect record.")
        return 1

    pct = out["covered"] / out["sessions"] * 100.0
    print(f"\n  window            {out['first']} .. {out['last']}")
    print(f"  market sessions   {out['sessions']}")
    print(f"    recorded        {out['covered']}   ({pct:.0f}%)")
    print(f"    partial         {out['partial']}   "
          f"(fewer than {MIN_DECISIONS_FOR_A_FULL_SESSION} decisions)")
    print(f"    MISSED          {out['missed']}")
    if out["longest_blackout"]:
        days = out["blackout_days"]
        print(f"\n  longest blackout  {out['longest_blackout']} sessions   "
              f"{days[0]} .. {days[-1]}")
    if out["missed_days"]:
        print("\n  missed sessions:")
        line = "   "
        for day in out["missed_days"]:
            if len(line) > 66:
                print(line)
                line = "   "
            line += f" {day.isoformat()}"
        if line.strip():
            print(line)

    print("\n  " + "-" * 72)
    if pct >= 95:
        print("  He is awake for the market. Uptime is not the bottleneck.")
    else:
        print(f"  He recorded {out['covered']} of {out['sessions']} sessions. "
              f"Every missed one is")
        print("  evidence not gathered — and the target for going live is a")
        print("  hundred paper round trips, which is a count of sessions as")
        print("  much as it is a count of setups.")
        print("  The liveness probe cannot catch this: it is a scheduled task")
        print("  on the same machine under the same interactive logon, so it")
        print("  goes down with what it is watching.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
