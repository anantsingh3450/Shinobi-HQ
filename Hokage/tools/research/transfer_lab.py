"""How much of an underlying ATR edge survives into option premium.

THE UNSTATED ASSUMPTION UNDER EVERY NUMBER IN THIS REPO
signal_lab, entry_module_lab, veto_lab, sweep_lab and the retirement bar all
score `edge_atr`: the underlying's forward move divided by ATR. Hokage does not
trade the underlying. It BUYS OPTIONS, and every one of those labs carries the
same caveat in its own docstring - "edge_atr measures the UNDERLYING's forward
move, not option P&L" - without anybody ever measuring the conversion.

That caveat is load-bearing. A gate whose blocked set differs by 0.3 ATR sounds
decisive next to a ship bar of t=2. Whether 0.3 ATR is worth anything to an
option buyer is a different question, and it is the one that decides whether a
measured difference is a finding or a rounding error.

WHAT IT MEASURES
One row per real closed position that has an archived premium path:

    underlying move from entry to exit, in ATR at entry, signed by the side
    the option was                       ->   realised premium change, percent

and fits a slope through them. The slope is the exchange rate: how many percent
of premium one ATR of underlying has actually been worth to this account.

WHY IT USES THE REAL EXIT AND NOT THE LAST MARK
The obvious thing is to read the premium path's first and last mark, and it is
wrong. Marks stop when the position closes, so the last mark is the last POLL
before the exit, not the exit. Measured on 2026-11-07 across 22 paths the last
mark sat ABOVE the realised exit far more often than below it, which makes
sense - the ladder fires on an adverse move, so the poll that triggers an exit
is usually followed by a worse fill. Fitting on last marks produced a POSITIVE
intercept, an option gaining value at zero underlying move, which is not a
thing that happens to a long option over a holding period of theta. The exit
price in the ledger is the honest number.

WHAT IT CANNOT TELL YOU
  * n IS TINY. Hokage has a handful of closed option positions with archived
    paths. This is a calibration, not a confirmed result, and nothing should be
    retired or shipped on it.
  * EVERY ROW IS A TRADE THAT WAS TAKEN. Positions that a gate blocked have no
    premium path at all, because nothing ever priced them - the whole reason
    the veto cannot be scored on premium directly.
  * IT POOLS ASSETS. Gas, gold and silver options have different premiums,
    different ATRs and different liquidity. Per-asset slopes need an n this
    does not have.
  * IT IS A SLOPE THROUGH REALISED TRADES, so it carries whatever the exit
    ladder did. It is the conversion THIS SYSTEM ACHIEVED, not the one a
    perfect exit would.

USAGE
    python tools/research/transfer_lab.py
    python tools/research/transfer_lab.py 0.318 0.062   # convert these edges
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hokage.memory.resolver import brain_root  # noqa: E402

#: Hokage's ledger stamps UTC and the candle archive stamps naive IST. See
#: memory: "SQLite timestamps are UTC" - a confusion here shifts every window
#: by five and a half hours and silently measures the wrong bars.
IST_OFFSET = dt.timedelta(hours=5, minutes=30)

#: Fewest underlying bars a hold must span to carry a move. A window inside one
#: 15-minute bar has an underlying move of exactly zero by construction, which
#: is not an observation of anything - six of the 22 paths on 2026-11-07 were
#: like this and they only added noise around the origin.
MIN_SPAN_BARS = 2


def _conn(name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{brain_root() / name}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def underlying_of(option_symbol: str) -> str | None:
    """NATURALGAS26NOV285CE -> NATURALGAS."""
    m = re.match(r"([A-Z]+?)\d", option_symbol.upper())
    return m.group(1) if m else None


def side_of(option_symbol: str) -> int:
    """+1 for a CALL (long the underlying), -1 for a PUT."""
    return 1 if option_symbol.upper().endswith("CE") else -1


class Bars:
    """Underlying bars, indexed once per symbol."""

    def __init__(self) -> None:
        self._cache: dict[str, list[dict]] = {}

    def of(self, symbol: str) -> list[dict]:
        if symbol not in self._cache:
            with _conn("candles.db") as conn:
                self._cache[symbol] = [dict(r) for r in conn.execute(
                    "SELECT ts, high, low, close FROM candles WHERE symbol = ?"
                    " ORDER BY ts", (symbol,))]
        return self._cache[symbol]

    def index_at(self, symbol: str, stamp: str) -> int | None:
        """The last bar at or before `stamp` (naive IST, 'YYYY-MM-DD HH:MM:SS')."""
        found = None
        for i, bar in enumerate(self.of(symbol)):
            if bar["ts"] <= stamp:
                found = i
            else:
                break
        return found

    def atr(self, symbol: str, idx: int | None, period: int = 14) -> float | None:
        """ATR by the same formula `_compute_underlying_bias` uses."""
        bars = self.of(symbol)
        if idx is None or idx < period + 1:
            return None
        window = bars[idx - period:idx + 1]
        trs = [max(c["high"] - c["low"], abs(c["high"] - p["close"]),
                   abs(c["low"] - p["close"]))
               for p, c in zip(window[:-1], window[1:])]
        return (sum(trs) / len(trs)) if trs else None


def _ist(stamp: str) -> str:
    """A UTC ledger stamp as the naive IST string the archive is keyed by."""
    text = stamp.replace("T", " ")[:19]
    try:
        moment = dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text
    return (moment + IST_OFFSET).strftime("%Y-%m-%d %H:%M:%S")


def rows() -> list[dict]:
    """One record per closed option position that has an archived path."""
    bars = Bars()
    out: list[dict] = []
    with _conn("hokage.db") as hk:
        positions = hk.execute(
            "SELECT market, entry_price, current_price, realized_pnl, opened_at,"
            " closed_at, strategy_id FROM positions WHERE status = 'CLOSED'"
            " AND entry_price > 0 AND current_price > 0 AND closed_at IS NOT NULL"
            " ORDER BY opened_at").fetchall()

    with _conn("candles.db") as cd:
        try:
            marked = {(r["symbol"], r["day"]) for r in cd.execute(
                "SELECT DISTINCT symbol, day FROM position_marks")}
        except sqlite3.Error:
            marked = set()

    for pos in positions:
        option = pos["market"]
        under = underlying_of(option)
        if not under:
            continue
        opened, closed = _ist(pos["opened_at"]), _ist(pos["closed_at"])
        # A position with no archived path is not measurable here: the path is
        # what proves the premium was real and polled, not inferred.
        if (option, opened[:10]) not in marked:
            continue
        i0 = bars.index_at(under, opened)
        i1 = bars.index_at(under, closed)
        atr = bars.atr(under, i0)
        if i0 is None or i1 is None or not atr:
            continue
        span = i1 - i0
        if span < MIN_SPAN_BARS:
            continue
        series = bars.of(under)
        entry, exit_price = pos["entry_price"], pos["current_price"]
        out.append({
            "option": option,
            "underlying": under,
            "strategy": (pos["strategy_id"] or "?"),
            "day": opened[:10],
            "span": span,
            "und_atr": ((series[i1]["close"] - series[i0]["close"])
                        * side_of(option)) / atr,
            "prem_pct": 100.0 * (exit_price - entry) / entry,
            "pnl": pos["realized_pnl"],
        })
    return out


def fit(recs: list[dict]) -> dict | None:
    """Slope, intercept and r of premium percent against underlying ATR."""
    if len(recs) < 3:
        return None
    xs = [r["und_atr"] for r in recs]
    ys = [r["prem_pct"] for r in recs]
    mx, my = st.mean(xs), st.mean(ys)
    sx = st.stdev(xs)
    sy = st.stdev(ys)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)
    slope = cov / (sx ** 2)
    return {
        "n": len(recs),
        "slope": slope,
        "intercept": my - slope * mx,
        "r": cov / (sx * sy),
        "mean_und": mx,
        "mean_prem": my,
        "sign_agreement": sum(1 for x, y in zip(xs, ys) if (x > 0) == (y > 0)),
    }


def report(recs: list[dict], edges: list[float]) -> None:
    print("=" * 84)
    print("  TRANSFER LAB — what one ATR of underlying has been worth in premium")
    print("  Every edge_atr in this repo is in the left column's units. Hokage")
    print("  buys options, which are in the right column's.")
    print("=" * 84)
    if not recs:
        print("\n  No closed position has both a premium path and underlying bars.")
        print("  Nothing to fit. This cannot be backfilled: a premium path only")
        print("  exists for a contract that was actually bought and polled.")
        return

    print(f"\n  {'day':11} {'contract':24} {'strategy':16} {'bars':>5} "
          f"{'und ATR':>8} {'premium':>8}")
    for r in sorted(recs, key=lambda r: r["day"]):
        strat = r["strategy"].replace("strat-", "").replace("-mcx-v1", "")
        print(f"  {r['day']:11} {r['option']:24} {strat:16} {r['span']:>5} "
              f"{r['und_atr']:>+8.2f} {r['prem_pct']:>+7.1f}%")

    f = fit(recs)
    if not f:
        print(f"\n  n={len(recs)} — too few to fit.")
        return
    print(f"\n  n = {f['n']}  (holds spanning >= {MIN_SPAN_BARS} underlying bars)")
    print(f"  mean underlying move   {f['mean_und']:+.3f} ATR")
    print(f"  mean premium change    {f['mean_prem']:+.2f}%")
    print(f"  correlation            r = {f['r']:+.3f}   r2 = {f['r'] ** 2:.3f}")
    print(f"  sign agreement         {f['sign_agreement']}/{f['n']}")
    print(f"  SLOPE                  {f['slope']:+.2f}% of premium per 1.0 ATR")
    print(f"  intercept              {f['intercept']:+.2f}% at zero underlying move")
    if f["intercept"] > 0:
        print("    ^ POSITIVE, which a long option should not be over a holding")
        print("      period of theta. Treat it as unexplained, not as a finding.")

    print("\n  WHAT A MEASURED EDGE IS WORTH, at this slope:")
    print(f"    {'edge_atr':>9}  {'premium':>9}   {'on a 13.90 gas option':>24}")
    for edge in edges:
        pct = f["slope"] * edge
        print(f"    {edge:>+9.3f}  {pct:>+8.2f}%   {0.01 * pct * 13.90:>+24.3f}")
    print("\n  The smallest premium change ever archived on gas is 0.05, so a")
    print("  conversion below that is not observable on the tape at all.")
    print(f"\n  CAVEAT: n={f['n']}, pooled across assets, every row a trade that was")
    print("  TAKEN. A blocked trade has no premium path, which is exactly why a")
    print("  gate cannot be scored on premium directly.")


def main() -> int:
    edges = []
    for arg in sys.argv[1:]:
        try:
            edges.append(float(arg))
        except ValueError:
            pass
    report(rows(), edges or [0.062, 0.100, 0.311, 0.318, 1.000])
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
