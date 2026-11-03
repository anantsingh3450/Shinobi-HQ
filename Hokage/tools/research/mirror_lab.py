"""Score the mirror experiment: does the opposite option have an edge?

WHY THIS EXISTS
The commander's hypothesis of 2026-10-23 — "every time it takes a call, take
a put" — was built as `FadeRangeEntry` and `RiderTrendEntry`, scoped to
natural gas. They have fired in perfect lockstep with their originals ever
since and NOTHING HAS EVER READ THE RESULT. `signal_archive` only writes;
until this file, no tool in the repo opened `auction_signals` to ask what the
experiment showed. Eleven days of faithful recording and no verdict.

WHY A MIRROR NEVER TRADES, AND WHY THAT IS CORRECT
A mirror carries its original's confidence exactly, so the pair ties on every
scan, and `_auction_key` makes a mirror lose a tie to a non-mirror. Wins: 0
since the 2026-10-28 tie-break fix. That is the design — the experiment must
not displace the measured strategy — and it is why the mirror has to be
scored from the archive rather than from a ledger it never reaches.

WHAT THIS LAB CAN ANSWER, AND WHAT IT CANNOT
It scores DIRECTION on the underlying, at the same horizons as signal_lab.
On the underlying a mirror's edge is EXACTLY minus its original's, because it
fires on the same bar with the opposite direction, so one column answers both
and no new information is created by the flip.

The question the mirror was actually built to answer is a different one, and
this lab CANNOT answer it. Both sides BUY options: a long call and a long put
are both long premium, both pay theta and the spread, both lose when the
underlying sits still. A mirror therefore only wins where the original was
wrong about DIRECTION, not where it was wrong about MOVEMENT — and separating
those two is the entire point of running it. That separation lives in premium
terms, and the premium does not exist in the archive:

  * the mirror never fills, so it has no premium path of its own;
  * `option_chain` covers NIFTY and SENSEX only — no MCX at all — at one
    snapshot a day, which cannot price an intraday pair.

So treat a direction result here as necessary, not sufficient: a direction
edge smaller than theta plus spread is not tradable by EITHER side.

USAGE
    python tools/research/mirror_lab.py
    python tools/research/mirror_lab.py --mirror faderange
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

ARCHIVE = Path(r"C:\Hokage\hokage_brain\candles.db")

#: Each mirror and the module it mirrors.
PAIRS = {
    "ridertrend": "trendrider",
    "faderange": "rangefade",
}

#: Same horizons and ATR period as signal_lab, so the numbers are comparable.
HORIZONS = (2, 4, 8)
ATR_PERIOD = 14

#: A scan's `underlying` must match a candle's close this closely for that
#: contract to be the one that was live. Futures roll, and pricing a scan off
#: the wrong contract is the error that once deleted three months of tape.
CONTRACT_TOLERANCE = 0.03


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{ARCHIVE}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def ledger(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT module_id, COUNT(*) scans, SUM(fired) fired, SUM(won) won,"
        " SUM(COALESCE(filled, 0)) filled, MIN(day) first_day, MAX(day) last_day"
        " FROM auction_signals GROUP BY module_id ORDER BY SUM(fired) DESC"
    ).fetchall()


def candles(con: sqlite3.Connection, symbol: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in con.execute(
        "SELECT contract, ts, high, low, close FROM candles WHERE symbol = ?"
        " ORDER BY ts", (symbol,)
    ):
        out.setdefault(r["contract"], []).append(dict(r))
    return out


def atr(bars: list[dict], i: int, period: int = ATR_PERIOD) -> float:
    window = bars[max(0, i - period):i]
    if len(window) < 2:
        return 0.0
    trs = [
        max(cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]))
        for prev, cur in zip(window[:-1], window[1:])
    ]
    return sum(trs) / len(trs) if trs else 0.0


def locate(bars_by_contract: dict[str, list[dict]], stamp: str,
           underlying: float) -> tuple[list[dict], int] | None:
    """The live contract's bar list and the index of the bar at `stamp`.

    The contract is identified by PRICE, not by date: the scan's own recorded
    underlying must match that contract's close at the time. A date rule would
    have to encode every roll, and getting a roll wrong prices a signal off a
    contract that was not trading.
    """
    best = None
    for bars, in ((b,) for b in bars_by_contract.values()):
        lo, hi = 0, len(bars)
        while lo < hi:                       # last bar at or before the scan
            mid = (lo + hi) // 2
            if str(bars[mid]["ts"])[:19] <= stamp:
                lo = mid + 1
            else:
                hi = mid
        i = lo - 1
        if i < 0 or not underlying:
            continue
        if abs(bars[i]["close"] - underlying) / abs(underlying) > CONTRACT_TOLERANCE:
            continue
        if best is None or str(bars[i]["ts"]) > str(best[0][best[1]]["ts"]):
            best = (bars, i)
    return best


def score(con, mirror: str, original: str) -> dict:
    """Forward move in ATR units, signed by the MIRROR's direction."""
    rows = con.execute(
        "SELECT scanned_at, symbol, direction, underlying FROM auction_signals"
        " WHERE module_id LIKE ? AND fired = 1 ORDER BY scanned_at",
        (f"%{mirror}%",),
    ).fetchall()
    if not rows:
        return {"fired": 0, "by_horizon": {}, "unscoreable": 0}

    bars_by_symbol = {s: candles(con, s) for s in {r["symbol"] for r in rows}}
    by_horizon: dict[int, list[float]] = {h: [] for h in HORIZONS}
    unscoreable = 0

    for r in rows:
        stamp = r["scanned_at"][:19].replace("T", " ")
        found = locate(bars_by_symbol[r["symbol"]], stamp, r["underlying"])
        if found is None:
            unscoreable += 1
            continue
        bars, i = found
        a = atr(bars, i)
        if a <= 0:
            unscoreable += 1
            continue
        sign = -1.0 if (r["direction"] or "").lower() == "short" else 1.0
        for h in HORIZONS:
            if i + h < len(bars):
                by_horizon[h].append(sign * (bars[i + h]["close"] - r["underlying"]) / a)

    return {"fired": len(rows), "by_horizon": by_horizon, "unscoreable": unscoreable}


def t_stat(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.stdev(values)
    return (statistics.mean(values) / (sd / len(values) ** 0.5)) if sd else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mirror", choices=sorted(PAIRS), help="score one mirror only")
    args = ap.parse_args()

    if not ARCHIVE.is_file():
        print(f"ERROR: archive not found at {ARCHIVE}")
        return 2
    con = connect()

    print("AUCTION LEDGER  (every module, not just the mirrors)")
    print(f"  {'module':26} {'scans':>6} {'fired':>6} {'won':>5} {'filled':>7}  window")
    for r in ledger(con):
        print(f"  {str(r['module_id'])[:24]:26} {r['scans']:>6} {r['fired'] or 0:>6} "
              f"{r['won'] or 0:>5} {r['filled'] or 0:>7}  {r['first_day']}..{r['last_day']}")

    pairs = {args.mirror: PAIRS[args.mirror]} if args.mirror else PAIRS
    for mirror, original in pairs.items():
        print(f"\n{'=' * 74}\nMIRROR {mirror.upper()}  (mirrors {original})")
        result = score(con, mirror, original)
        if not result["fired"]:
            print("  never fired — nothing to score.")
            continue
        print(f"  fired {result['fired']}, unscoreable {result['unscoreable']} "
              f"(no candle for the live contract at that moment)")
        print(f"\n  {'horizon':>12} {'n':>5} {'acc':>7} {'edge_atr':>10} {'t':>7}  verdict")
        for h in HORIZONS:
            moves = result["by_horizon"].get(h, [])
            if len(moves) < 2:
                print(f"  {h:>3} bars     {len(moves):>5}   too few to score")
                continue
            t = t_stat(moves)
            acc = sum(1 for m in moves if m > 0) / len(moves) * 100
            edge = statistics.mean(moves)
            verdict = ("CLEARS t>=2" if t is not None and abs(t) >= 2
                       else "no edge either way")
            t_txt = f"{t:>+7.2f}" if t is not None else f"{'--':>7}"
            print(f"  {h:>3} bars ({h * 15:>3}m) {len(moves):>5} {acc:>6.1f}% "
                  f"{edge:>+10.3f} {t_txt}  {verdict}")
        print("\n  The ORIGINAL's column is the exact negative of this one: same bar,"
              "\n  opposite direction. The flip creates no new information on the"
              "\n  underlying, which is why a direction result cannot settle this"
              "\n  experiment on its own.")

    print(f"\n{'=' * 74}\nPREMIUM COVERAGE  (what could settle this properly)")
    chain = con.execute(
        "SELECT symbol, COUNT(*) n, COUNT(DISTINCT captured_at) snaps,"
        " MIN(day) first_day, MAX(day) last_day"
        " FROM option_chain GROUP BY symbol").fetchall()
    have = {r["symbol"] for r in chain}
    for r in chain:
        print(f"  {r['symbol']:11} rows {r['n']:>5}  snapshots {r['snaps']:>4}  "
              f"{r['first_day']}..{r['last_day']}")
    missing = [r["symbol"] for r in con.execute(
        "SELECT DISTINCT symbol FROM auction_signals") if r["symbol"] not in have]
    for symbol in missing:
        print(f"  {symbol:11} NONE — premium cannot be reconstructed at all.")

    print("\n  One snapshot a day is a CLOSE, and these pairs fire intraday, so")
    print("  the chain cannot price the entry and the exit of a signal taken at")
    print("  19:30 and closed at 21:00. What it DOES unlock is the close-to-close")
    print("  version of the same question — hold both sides overnight and compare")
    print("  — which is a different experiment from the one the arena runs, and")
    print("  needs enough sessions behind it to mean anything.")
    print("\n  To settle the INTRADAY question the premium has to be captured at")
    print("  the moment each side fires, because an option's history dies with")
    print("  its contract and no amount of later archiving can go back for it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
