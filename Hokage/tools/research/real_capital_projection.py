"""What would the commander's REAL money have done, on his actual plan?

    python tools/research/real_capital_projection.py
    python tools/research/real_capital_projection.py --seed 30000 --monthly 10000

WHY THIS EXISTS. Hokage learns on paper chests of 50,000 (Index Dojo) and
200,000 (MCX Arena) - 250,000 of simulated capital against a real seed of
30,000. Every position size he has ever chosen, every drawdown percentage he
has ever reported, and every affordability decision he has ever made was taken
at a scale the commander will not have for years.

THE OBVIOUS FIX IS A TRAP. Setting the paper chests to the real 30,000 makes
him honest and useless in the same stroke: the cheapest option lot in his
universe costs 10,748 and the production premium cap allows 33% of the
account, so a 30,000 account cannot place a SINGLE order. He would take zero
paper trades, learn nothing, and generate no record at all.

So he keeps learning at a scale that produces trades, and this reports -
separately and honestly - what the real plan would have done over the same
tape: which trades it could have afforded, which it had to skip, and where the
equity curve actually goes.

THE P&L TRANSFERS DIRECTLY. Paper positions are one lot: median outlays of
19,833 on BANKNIFTY against a live one-lot premium of 21,322, 21,865 on GOLDM
against 23,270. So the real account either affords the same one lot or it does
not, and when it does the rupee outcome is the same. Nothing is scaled or
modelled.

WHAT THIS IS NOT. It is not a forecast. It replays the record Hokage actually
produced against the contribution schedule, and that record is 89 round trips
at a profit factor of 0.92. A projection cannot be better than the system it
replays.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hokage.memory.resolver import brain_root as _brain_root  # noqa: E402

BRAIN = _brain_root()
DB = BRAIN / "hokage.db"

#: The commander's plan, stated 2026-10-14. The seed is not the lever; the
#: contribution is - year-one contributions are 20x the year-one return on the
#: seed at the agreed 20% annualised.
DEFAULT_SEED = 30_000.0
DEFAULT_MONTHLY = 10_000.0

#: Production's cap on premium as a fraction of the account
#: (MAX_PREMIUM_CHEST_FRACTION). Read here rather than assumed, because the
#: whole point is to apply the REAL constraint.
def _premium_cap() -> float:
    try:
        from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

        for name in ("MAX_PREMIUM_CHEST_FRACTION", "_MAX_PREMIUM_CHEST_FRACTION"):
            value = getattr(Bot, name, None)
            if isinstance(value, (int, float)) and 0 < value <= 1:
                return float(value)
    except Exception:
        pass
    return 0.33


#: The reduce_only runaway. 208 positions on one CRUDEOIL strike inside two
#: minutes at zero P&L. Excluded here for the same reason live_readiness
#: excludes it: a bug's accounting is not a trading result.
CASCADE_DAY = "2026-07-15"


def _months_between(start: date, when: date) -> int:
    """Whole monthly contributions credited by `when`, the first on day one."""
    months = (when.year - start.year) * 12 + (when.month - start.month)
    if when.day < start.day:
        months -= 1
    return max(0, months)


def project(rows: list[dict], seed: float, monthly: float, cap: float) -> dict:
    """Replay the record against the contribution schedule, in order."""
    rows = sorted(rows, key=lambda r: r["opened_at"])
    if not rows:
        return {"trades": 0}

    start = datetime.fromisoformat(rows[0]["opened_at"]).date()
    equity = seed
    contributed = 0.0
    taken = skipped = 0
    skipped_outlay: list[float] = []
    peak = equity
    drawdown = 0.0
    first_affordable: str | None = None
    curve: list[tuple[str, float]] = []

    for r in rows:
        when = datetime.fromisoformat(r["opened_at"]).date()
        want = _months_between(start, when) * monthly
        if want > contributed:
            equity += want - contributed
            contributed = want

        outlay = float(r["quantity"] or 0) * float(r["entry_price"] or 0)
        if outlay <= 0:
            continue

        if outlay <= equity * cap:
            equity += float(r["realized_pnl"] or 0)
            taken += 1
            if first_affordable is None:
                first_affordable = r["opened_at"][:10]
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            curve.append((r["opened_at"][:10], equity))
        else:
            skipped += 1
            skipped_outlay.append(outlay)

    return {
        "trades": taken + skipped,
        "taken": taken,
        "skipped": skipped,
        "skipped_median_outlay": (
            sorted(skipped_outlay)[len(skipped_outlay) // 2] if skipped_outlay else None
        ),
        "seed": seed,
        "contributed": contributed,
        "equity": equity,
        "invested": seed + contributed,
        "pnl": equity - seed - contributed,
        "max_drawdown": drawdown,
        "first_affordable": first_affordable,
        "start": start.isoformat(),
        "end": rows[-1]["opened_at"][:10],
        "curve": curve,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=float, default=DEFAULT_SEED)
    ap.add_argument("--monthly", type=float, default=DEFAULT_MONTHLY)
    args = ap.parse_args()

    if not DB.exists():
        print(f"  no database at {DB}")
        return 1

    con = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM positions WHERE realized_pnl IS NOT NULL "
            "AND substr(opened_at,1,10) != ? ORDER BY opened_at;", (CASCADE_DAY,))]
    finally:
        con.close()

    cap = _premium_cap()
    print("=" * 78)
    print("  REAL CAPITAL PROJECTION — the commander's plan over Hokage's own record")
    print(f"  seed {args.seed:,.0f} + {args.monthly:,.0f} a month, "
          f"premium capped at {cap:.0%} of the account")
    print(f"  the {CASCADE_DAY} cascade is excluded: a bug's accounting is not a result")
    print("=" * 78)

    out = project(rows, args.seed, args.monthly, cap)
    if not out.get("trades"):
        print("\n  No closed positions to replay.")
        return 0

    print(f"\n  record replayed   {out['start']} .. {out['end']}")
    print(f"  trades in record  {out['trades']}")
    print(f"    affordable      {out['taken']}")
    print(f"    SKIPPED         {out['skipped']}  (could not afford one lot)")
    if out["skipped_median_outlay"]:
        print(f"      median outlay it could not reach: "
              f"{out['skipped_median_outlay']:,.0f}")
    print(f"\n  paid in           {out['invested']:,.0f}  "
          f"(seed {out['seed']:,.0f} + {out['contributed']:,.0f} contributed)")
    print(f"  ended with        {out['equity']:,.0f}")
    print(f"  trading P&L       {out['pnl']:+,.0f}")
    print(f"  max drawdown      {out['max_drawdown']:,.0f}")
    print(f"  first affordable  {out['first_affordable'] or 'NEVER'}")

    print("\n  " + "-" * 74)
    if out["taken"] == 0:
        print("  THE REAL ACCOUNT COULD NOT HAVE TAKEN A SINGLE TRADE.")
        print("  Every signal Hokage acted on was out of reach at this account size.")
        print("  That is the honest state of the plan today, and it is an")
        print("  affordability problem, not a strategy problem.")
    elif out["pnl"] < 0:
        print(f"  The real account would have LOST {abs(out['pnl']):,.0f} trading,")
        print("  against a record whose profit factor is 0.92. A projection cannot")
        print("  be better than the system it replays.")
    else:
        print(f"  The real account would have made {out['pnl']:+,.0f} trading.")
        print("  Judge that against the contributions, not against the seed.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
