"""Measure what the premium chest cap does, by replaying the real MCX ledger.

WHY THIS EXISTS
Both GOLDM losses of 2026-11-02 and 2026-11-03 were graded `sizing=OVERSIZED`:
Rs 35,545 of premium against a ~Rs 108,000 strategy chest, sitting right on
`MAX_PREMIUM_CHEST_FRACTION = 0.33`. A designed -12% backstop on a position
that large is ~4% of the chest, against a mandate that caps drawdown at 8%.

WHAT THE CAP CAN AND CANNOT DO
`MAX_LOTS_PER_ORDER = 1`, and every MCX trade in the ledger is exactly one lot
(GOLDM 10, NATURALGAS 1250, SILVERM 5, CRUDEOIL 100). The router computes
`lots = floor(budget / premium_per_lot)` and skips when that is 0. So the cap
has exactly two outcomes per trade: ONE LOT, or NO TRADE.

That makes "reduce the size" impossible on this venue. Lowering the cap does
not buy a smaller gold position — it REFUSES gold. Raising it buys nothing,
because one lot is already the ceiling. This lab therefore measures the only
thing the cap actually controls: WHICH TRADES ARE ALLOWED TO HAPPEN.

METHOD
Walk the playbook-tagged closed MCX positions in time order, each strategy's
chest starting at its share of the opening ledger and compounding its own
realised P&L. At each candidate cap, a trade is taken when
`premium_per_lot <= cap * chest` and skipped otherwise; a skipped trade earns
nothing and leaves the chest untouched, which changes what the NEXT trade can
afford. Sequential by construction, because the cap is a function of a chest
the earlier trades moved.

FOUR LIMITS, STATED UP FRONT
  * Only the 58 positions carrying a playbook_id can be simulated. 42 closed
    MCX rows have none, so no chest owns them, and they are excluded -- they
    are worth -6,960 and that figure is simply absent from every column below.
  * A skipped trade is modelled as nothing happening. That is correct here
    rather than convenient: a strategy that cannot fill still WINS its auction
    and stands aside, denying the asset to the runner-up, so freeing the chest
    does not hand the slot to anyone else.
  * Realised P&L is replayed as-is for a taken trade. Entry and exit prices
    are whatever actually happened, so this is a selection experiment, not a
    re-simulation of the strategies.
  * The cash ceiling (`MAX_PREMIUM_CASH_FRACTION = 0.5`) is not modelled: on
    these chests it never binds before the chest ceiling. If chests ever shrink
    far enough for cash to bind first, this lab stops being accurate.

USAGE
    python tools/research/chest_cap_lab.py
"""
from __future__ import annotations

import re
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bots.execution.options_router import (  # noqa: E402
    MAX_LOTS_PER_ORDER,
    MAX_PREMIUM_CHEST_FRACTION as LIVE_CAP,
)

LEDGER = Path(r"C:\Hokage\hokage_brain\hokage.db")

#: paper_mcx opens at 4 lakh across its four strategies.
CHEST_AT_START = 100_000.0

CANDIDATES = (0.15, 0.20, 0.25, 0.28, 0.30, LIVE_CAP, 0.40, 0.50)


def load_trades() -> tuple[list[dict], float, int]:
    """(trades, pnl excluded for want of a playbook, how many were excluded)."""
    con = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT market, playbook_id, quantity, entry_price, realized_pnl, opened_at"
        " FROM positions WHERE account_id = 'paper_mcx' AND status != 'OPEN'"
        " ORDER BY opened_at"
    ).fetchall()

    trades, orphan_pnl, orphans = [], 0.0, 0
    for r in rows:
        if not r["playbook_id"]:
            orphan_pnl += float(r["realized_pnl"] or 0.0)
            orphans += 1
            continue
        qty, entry = float(r["quantity"] or 0), float(r["entry_price"] or 0)
        if qty <= 0 or entry <= 0:
            continue
        trades.append({
            "market": r["market"],
            "asset": re.match(r"[A-Z]+", r["market"]).group(0),
            "playbook": r["playbook_id"],
            # Every historical MCX fill is one lot, so quantity IS the lot size
            # and this is the premium a single lot costs.
            "premium_per_lot": entry * qty,
            "pnl": float(r["realized_pnl"] or 0.0),
            "opened_at": r["opened_at"],
        })
    return trades, orphan_pnl, orphans


def simulate(trades: list[dict], cap: float) -> dict:
    """Replay the ledger under one cap. Chests compound their own P&L."""
    chests: dict[str, float] = {}
    equity_path: list[float] = []
    equity = 0.0
    taken = skipped = 0
    wins: list[float] = []
    losses: list[float] = []
    skipped_pnl = 0.0
    by_asset: dict[str, int] = {}

    for t in trades:
        chest = chests.setdefault(t["playbook"], CHEST_AT_START)
        lots = min(int((cap * chest) // t["premium_per_lot"]), MAX_LOTS_PER_ORDER)
        if lots < 1:
            skipped += 1
            skipped_pnl += t["pnl"]
            by_asset[t["asset"]] = by_asset.get(t["asset"], 0) + 1
            continue
        pnl = t["pnl"] * lots
        taken += 1
        chests[t["playbook"]] = chest + pnl
        equity += pnl
        equity_path.append(equity)
        (wins if pnl > 0 else losses).append(pnl)

    peak = 0.0
    max_dd = 0.0
    for e in equity_path:
        peak = max(peak, e)
        max_dd = max(max_dd, peak - e)

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "cap": cap, "taken": taken, "skipped": skipped, "total": equity,
        "skipped_pnl": skipped_pnl,
        "max_dd": max_dd,
        # Drawdown against the whole MCX ledger, which is what the 8% mandate
        # is written about.
        "max_dd_pct": max_dd / (CHEST_AT_START * 4) * 100,
        "pf": (gross_win / gross_loss) if gross_loss else None,
        "wins": len(wins), "losses": len(losses),
        "mean": statistics.mean(wins + losses) if (wins or losses) else 0.0,
        "by_asset": by_asset,
    }


def main() -> int:
    trades, orphan_pnl, orphans = load_trades()
    if not trades:
        print("no playbook-tagged MCX positions to simulate.")
        return 1

    print(f"CHEST CAP SWEEP  --  {len(trades)} playbook-tagged MCX positions, "
          f"{trades[0]['opened_at'][:10]} to {trades[-1]['opened_at'][:10]}")
    print(f"production cap = {LIVE_CAP:.0%}, MAX_LOTS_PER_ORDER = {MAX_LOTS_PER_ORDER}, "
          f"chests start at Rs {CHEST_AT_START:,.0f} each")
    print(f"excluded: {orphans} closed rows with no playbook_id, worth "
          f"Rs {orphan_pnl:+,.0f} -- no chest owns them\n")

    print(f"{'cap':>6} {'taken':>6} {'skip':>5} {'total Rs':>10} {'vs live':>9} "
          f"{'maxDD Rs':>9} {'maxDD%':>7} {'PF':>5} {'W/L':>8}")
    print("-" * 80)

    live = simulate(trades, LIVE_CAP)
    results = []
    for cap in CANDIDATES:
        r = simulate(trades, cap)
        results.append(r)
        pf = f"{r['pf']:.2f}" if r["pf"] else "  --"
        tag = "  <-- production" if cap == LIVE_CAP else ""
        print(f"{cap:>5.0%} {r['taken']:>6} {r['skipped']:>5} {r['total']:>10,.0f} "
              f"{r['total'] - live['total']:>+9,.0f} {r['max_dd']:>9,.0f} "
              f"{r['max_dd_pct']:>6.2f}% {pf:>5} "
              f"{r['wins']}/{r['losses']:<4}{tag}")

    print("-" * 80)
    print("\nWHAT A LOWER CAP REFUSES (skips by asset):")
    for r in results:
        if r["cap"] > LIVE_CAP or not r["by_asset"]:
            continue
        detail = ", ".join(f"{k} x{v}" for k, v in sorted(r["by_asset"].items()))
        print(f"  {r['cap']:>4.0%}  skips {r['skipped']:>2}  "
              f"({detail})  forgoing Rs {r['skipped_pnl']:+,.0f}")

    print(f"\nRaising the cap changes nothing: MAX_LOTS_PER_ORDER is "
          f"{MAX_LOTS_PER_ORDER}, so one lot is already the ceiling and every\n"
          f"historical fill was one lot. Only a LOWER cap has any effect, and "
          f"its only effect is to refuse trades.")

    mandate = [r for r in results if r["max_dd_pct"] <= 8.0]
    print(f"\nMandate check (drawdown <= 8% of the 4-lakh ledger):")
    for r in results:
        verdict = "within" if r["max_dd_pct"] <= 8.0 else "BREACHES"
        print(f"  cap {r['cap']:>4.0%}  maxDD {r['max_dd_pct']:>5.2f}%  {verdict}")
    if mandate:
        best = max(mandate, key=lambda r: r["total"])
        print(f"\nbest total among caps that hold drawdown under 8%: "
              f"{best['cap']:.0%} (Rs {best['total']:,.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
