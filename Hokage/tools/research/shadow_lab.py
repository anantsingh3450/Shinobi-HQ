"""The bias gate, scored in the units Hokage actually trades.

WHAT THIS ANSWERS THAT veto_lab CANNOT
veto_lab measures the gate over all history and answers in edge_atr - the
underlying's forward move. That is not what Hokage buys. transfer_lab measured
the conversion at +3.31% of premium per 1.0 ATR (n=15), which puts the gate's
largest confirmed effect at about 1.05% of premium and its 60-minute effect
below the smallest premium change ever archived on gas. Useful, and still a
conversion rather than a measurement.

This reads `shadow_marks`: the real premium path of contracts the gate refused
to buy, polled on the same tick that marks real positions. A blocked trade has
exactly one number in premium anywhere else in the brain - what it cost at the
instant it was proposed - and one number cannot be a round trip.

THE QUESTION, stated before there is any data so the answer cannot be
rewritten afterwards: a long option refused by the gate, priced over the window
the trade would have been held, either LOST value (the gate saved the account)
or GAINED it (the gate spent the account). Both sides of every Hokage trade are
long premium, so theta and the spread are paid either way and are already
inside these numbers.

WHAT IT STILL CANNOT TELL YOU
A shadow has no stop, no trail and no exit. It answers "what was that contract
worth while the trade would have been open", not "what would the trade have
made" - transfer_lab's slope is the conversion this system achieves WITH its
ladder, and a shadow has none. A negative shadow path does not prove the trade
would have lost, because the ladder might have cut it; a positive one does not
prove it would have won, because the ladder might have taken it early.

It records. It does not conclude. And it cannot be backfilled: nothing priced
the trades the gate refused before 2026-11-07.

USAGE
    python tools/research/shadow_lab.py
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hokage.memory.resolver import brain_root  # noqa: E402

#: Where the path is sliced, in minutes. The same horizons veto_lab scores on
#: the underlying (2, 4 and 8 fifteen-minute bars), so the two measurements of
#: the same gate can be read side by side.
SLICES = (30, 60, 120)

#: Minimum sample before a t-statistic is worth printing, and the bar a verdict
#: has to clear. Both deliberately the same as veto_lab's.
MIN_N = 30
SHIP_T = 2.0


def connect() -> sqlite3.Connection | None:
    db = brain_root() / "candles.db"
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _parse(stamp: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def shadows(con: sqlite3.Connection) -> list[dict]:
    """One record per refused decision, with its path sliced at each horizon.

    A slice takes the FIRST mark at or after the offset. Taking the nearest
    mark either side would let a 29-minute mark answer for 30 minutes and a
    61-minute one answer for 60, which quietly shortens or lengthens the window
    the number claims to describe.
    """
    try:
        rows = con.execute(
            "SELECT symbol, scanned_at, underlying, direction, entry,"
            " blocked_by, module_id, day, COUNT(*) AS marks,"
            " MIN(observed_at) AS started"
            " FROM shadow_marks GROUP BY symbol, scanned_at"
            " ORDER BY started").fetchall()
    except sqlite3.Error:
        return []

    out: list[dict] = []
    for row in rows:
        entry = row["entry"]
        started = _parse(row["started"])
        if not entry or entry <= 0 or started is None:
            continue
        marks = con.execute(
            "SELECT observed_at, premium FROM shadow_marks"
            " WHERE symbol = ? AND scanned_at = ? ORDER BY observed_at",
            (row["symbol"], row["scanned_at"])).fetchall()
        rec = {
            "symbol": row["symbol"], "underlying": row["underlying"],
            "direction": row["direction"], "day": row["day"],
            "entry": entry, "marks": row["marks"],
            "module_id": row["module_id"], "blocked_by": row["blocked_by"],
            "scanned_at": row["scanned_at"],
        }
        peak = max((m["premium"] for m in marks), default=None)
        rec["peak_pct"] = (100.0 * (peak - entry) / entry) if peak else None
        for minutes in SLICES:
            target = started + dt.timedelta(minutes=minutes)
            hit = next((m for m in marks if (_parse(m["observed_at"]) or started)
                        >= target), None)
            rec[f"pct_{minutes}"] = (
                100.0 * (hit["premium"] - entry) / entry if hit else None)
        out.append(rec)
    return out


def _stats(values: list[float]) -> tuple[int, float, float]:
    n = len(values)
    if n == 0:
        return 0, 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return n, mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return n, mean, mean / (math.sqrt(var / n) or 1e-9)


def verdict(values: list[float], minutes: int) -> str:
    """What the refused trades support, in premium, at the ship bar."""
    n, mean, t = _stats(values)
    if n == 0:
        return f"{minutes:>4}m  no path reaches this horizon yet"
    if n < MIN_N:
        return (f"{minutes:>4}m  n={n} mean {mean:+.2f}%  t={t:+.2f}  "
                f"— under n={MIN_N}, not a result")
    if mean < 0 and t <= -SHIP_T:
        return (f"{minutes:>4}m  n={n} mean {mean:+.2f}%  t={t:+.2f}  "
                f"— THE GATE SAVED MONEY: refused trades lost premium")
    if mean > 0 and t >= SHIP_T:
        return (f"{minutes:>4}m  n={n} mean {mean:+.2f}%  t={t:+.2f}  "
                f"— THE GATE SPENT MONEY: refused trades gained premium")
    return (f"{minutes:>4}m  n={n} mean {mean:+.2f}%  t={t:+.2f}  "
            f"— below the bar, the refusals are noise in premium")


def report(con: sqlite3.Connection | None) -> str:
    lines: list[str] = []

    def say(text: str = "") -> None:
        lines.append(text)
        print(text)

    say("=" * 84)
    say("  SHADOW LAB — the bias gate priced in premium, not in ATR")
    say("  Each row is a trade the gate refused, and what the contract it")
    say("  refused did over the window the trade would have been held.")
    say("=" * 84)

    recs = shadows(con) if con is not None else []
    if not recs:
        say("")
        say("  No refused trade has a priced path yet. The archive is written")
        say("  by the gate itself, one contract per asset per refusal, so the")
        say("  first rows arrive with the next session the gate says no in.")
        say("  THIS CANNOT BE BACKFILLED: nothing priced the trades the gate")
        say("  refused before 2026-11-07, which is why it has never been")
        say("  scored in premium.")
        return "\n".join(lines)

    say("")
    say(f"  {'day':11} {'refused contract':24} {'dir':6} {'entry':>7} "
        f"{'30m':>7} {'60m':>7} {'120m':>7} {'peak':>7} {'marks':>6}")
    for r in recs:
        def pct(key: str) -> str:
            v = r.get(key)
            return f"{v:>+6.1f}%" if v is not None else "      -"
        say(f"  {r['day']:11} {r['symbol']:24} {(r['direction'] or '?'):6} "
            f"{r['entry']:>7.2f} {pct('pct_30')} {pct('pct_60')} "
            f"{pct('pct_120')} {pct('peak_pct')} {r['marks']:>6}")

    say("")
    say("  WHAT THE REFUSALS DID. Negative means the gate saved the account;")
    say("  positive means it spent it. Both sides are LONG premium, so theta")
    say("  and the spread are already inside these numbers.")
    for minutes in SLICES:
        values = [r[f"pct_{minutes}"] for r in recs
                  if r.get(f"pct_{minutes}") is not None]
        say("    " + verdict(values, minutes))

    by_asset: dict[str, list[float]] = {}
    for r in recs:
        if r.get("pct_60") is not None:
            by_asset.setdefault(r["underlying"], []).append(r["pct_60"])
    if len(by_asset) > 1:
        say("")
        say("  PER ASSET at 60m, because direction here is per-asset and one")
        say("  pooled number has hidden that before:")
        for asset, values in sorted(by_asset.items()):
            n, mean, t = _stats(values)
            say(f"    {asset:12} n={n:>3}  mean {mean:+.2f}%  t={t:+.2f}")

    say("")
    say("  CAVEAT: a shadow has no stop, no trail and no exit. It says what")
    say("  the contract was worth, not what the trade would have made.")
    return "\n".join(lines)


def main() -> int:
    con = connect()
    try:
        report(con)
    finally:
        if con is not None:
            con.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
