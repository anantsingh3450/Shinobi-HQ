"""Is Hokage ready for real money? Answered by measurement, not by feeling ready.

    python tools/research/live_readiness.py
    python tools/research/live_readiness.py --since 2026-08-17

THE COMMANDER'S OWN BAR, agreed 2026-07-15 and never since measured against:

    Sharpe          >= 1.20
    profit factor   >= 1.30
    max drawdown    <= 8%
    and a real edge: at least one strategy/asset cell clearing t >= 2.0

The target is ~20% annualised from a 20,000 seed. Success is consistency and
survival, NOT a return number, so these four are the gate and nothing else is.

WHY THIS EXISTS. On 2026-10-14 the commander asked why Hokage cannot generate
wealth. The honest answer was in his own ledger and nobody had ever assembled
it:

    all 382 closed positions        +19,737   PF 1.22   win 62.4%
    excluding the 2026-07-15 cascade -7,033   PF 0.92   win 39.3%

208 of those 382 were the reduce_only runaway that opened and closed the same
CRUDEOIL strike inside two minutes at zero P&L. Strip that one day out and the
lifetime record is NEGATIVE. Every "Hokage is up 19,737" reading was an
artifact of a bug.

That is the number this tool exists to stop anyone believing again. A system
is not judged on its best day's accounting artifact.

NOTHING HERE DECIDES ANYTHING. It reports. Going live is the commander's call,
and this only makes sure the call is made against arithmetic.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sqlite3
import statistics as st
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from hokage.memory.resolver import brain_root as _brain_root  # noqa: E402
from net_record import cost_for, day_concentration  # noqa: E402
from shared.instrument import underlying_of  # noqa: E402

BRAIN = _brain_root()
DB = BRAIN / "hokage.db"
SNAPSHOTS = BRAIN / "research" / "snapshots"

#: The agreed bar. These are the commander's numbers, not this tool's.
MIN_SHARPE = 1.20
MIN_PROFIT_FACTOR = 1.30
MAX_DRAWDOWN_PCT = 8.0
MIN_CONFIRMED_CELLS = 1
SHIP_BAR_T = 2.0

#: Below this, a ratio is arithmetic on noise. 173 lifetime round trips is
#: already thin; 30 is the floor at which any of it means anything at all.
MIN_TRADES_FOR_A_VERDICT = 30

#: The day the reduce_only runaway opened 208 positions on one strike and
#: closed them at zero within two minutes. Reported separately, always,
#: because including it flatters every ratio.
CASCADE_DAY = "2026-07-15"

#: Paper capital per league, from bots.strategy.portfolio and mcx_portfolio.
#: A drawdown limit is a fraction of the money at risk, so the base has to be
#: the account, not the profit accumulated so far.
CAPITAL_BY_ACCOUNT = {"paper": 50_000.0, "paper_mcx": 200_000.0}


def capital_for(rows: list[dict]) -> float:
    """Capital behind this set of positions: the sum of the accounts used."""
    accounts = {r.get("account_id") for r in rows if r.get("account_id")}
    total = sum(CAPITAL_BY_ACCOUNT.get(a, 0.0) for a in accounts)
    return total or sum(CAPITAL_BY_ACCOUNT.values())


def _load(since: str | None) -> list[dict]:
    con = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        q = "SELECT * FROM positions"
        args: tuple = ()
        if since:
            q += " WHERE substr(opened_at,1,10) >= ?"
            args = (since,)
        return [dict(r) for r in con.execute(q + " ORDER BY opened_at;", args)]
    finally:
        con.close()


def _day_of(row: dict) -> str:
    """The session a round trip belongs to: the day it CLOSED.

    Not the day it opened. P&L is realised at the exit, and every position in
    this ledger is intraday anyway, so the two agree - but when they stop
    agreeing the profit belongs to the day it was booked.
    """
    return str(row.get("closed_at") or row.get("opened_at") or "")[:10]


def _by_day(rows: list[dict], pnl_key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows:
        day = _day_of(r)
        if day:
            out[day] = out.get(day, 0.0) + float(r.get(pnl_key) or 0.0)
    return out


def without_the_best_day(rows: list[dict],
                         pnl_key: str = "net_pnl") -> tuple[str | None, list[dict]]:
    """The same record with its single best session removed.

    A TIME HOLD-OUT, NOT A TRIM. The gate already refuses to be judged on the
    2026-07-15 cascade, on the stated ground that "a system is not judged on
    its best day's accounting artifact" - and then said nothing about a best
    day that was NOT an artifact. On 2026-11-10 the attributed record was
    +23,458 at PF 1.40 net, which clears the 1.30 bar, and 2026-08-19 alone
    was +22,416 of it: five long calls riding one gold trend inside three
    hours. Sixty-seven trades over the remaining twenty-three days were worth
    +1,042.

    Those five positions are one observation, not five. A bar that one session
    can carry is not a bar, so the gate is asked to hold without it. This
    removes the best day, never the worst: the question is whether the edge
    survives losing its luck, not whether the losses can be tidied away.
    """
    rows = with_net(rows) if rows and pnl_key not in rows[0] else rows
    traded = [r for r in rows if float(r.get("realized_pnl") or 0) != 0]
    best, _, _, _ = day_concentration(_by_day(traded, pnl_key))
    if best is None:
        return None, list(rows)
    return best, [r for r in rows if _day_of(r) != best]


def with_net(rows: list[dict]) -> list[dict]:
    """Every row given a `net_pnl`: its realised P&L minus what it cost.

    THE BAR WAS BEING JUDGED ON THE PRICE DIFFERENCE. Brokerage is flat at 40
    rupees a round trip, so across this ledger charges came to 3.2x the entire
    gross profit and moved the lifetime profit factor from 1.03 to 0.94. A gate
    that decides whether real money gets traded cannot be the last screen in
    the system still reading gross.

    The costing is `net_record.cost_for`, not a second copy of it: the gate and
    the record must not be able to disagree about the same ledger. A row the
    ledger has no charge for is PRICED FROM THE SCHEDULE rather than counted
    free - absent is not zero - and `charges_measured` says which it was, so
    a reconstruction is never presented as a record.
    """
    out = []
    for r in rows:
        row = dict(r)
        qty = abs(float(row.get("quantity") or 0.0))
        entry = abs(float(row.get("entry_price") or 0.0)) * qty
        exit_ = abs(float(row.get("current_price") or 0.0)) * qty
        gross = float(row.get("realized_pnl") or 0.0)
        recorded = row.get("charges")
        if entry <= 0:
            # Nothing to price a percentage charge against. Reporting it as
            # free would understate the cost of exactly the rows least worth
            # trusting, so it is carried at gross and counted.
            row["cost"], row["charges_measured"] = 0.0, False
            row["cost_unknown"] = True
        else:
            cost, measured = cost_for(
                entry, exit_, underlying_of(str(row.get("market") or "")),
                recorded)
            row["cost"], row["charges_measured"] = cost, measured
            row["cost_unknown"] = False
        row["net_pnl"] = gross - float(row["cost"])
        out.append(row)
    return out


def measure(rows: list[dict], capital: float | None = None,
            pnl_key: str = "net_pnl") -> dict:
    """Sharpe, profit factor and drawdown from realised P&L.

    Zero-P&L rows are excluded from the ratios: a position opened and closed at
    the same price is not a trade that won or lost, and counting 208 of them
    drags a win rate from 62% to nothing while moving no money. They are
    counted and reported separately rather than quietly dropped.

    FLAT IS DECIDED ON GROSS, MEASURED ON NET. A position that opened and
    closed at one price still paid brokerage, so its net is not zero - but it
    is still not a trade that won or lost, and letting charges promote 208 of
    them into "losers" would be the cascade flattering the ratios all over
    again, in the other direction.
    """
    closed = sorted(rows, key=lambda r: r["closed_at"] or r["opened_at"])
    if pnl_key != "realized_pnl" and closed and pnl_key not in closed[0]:
        closed = with_net(closed)
    gross_all = [float(r["realized_pnl"] or 0) for r in closed]
    pnl = [float(r.get(pnl_key) or 0) for r, g in zip(closed, gross_all) if g != 0]
    flats = len(gross_all) - len(pnl)

    traded = [r for r, g in zip(closed, gross_all) if g != 0]
    out: dict = {
        "n": len(pnl), "flats": flats, "total_pnl": sum(pnl),
        "gross_pnl": sum(g for g in gross_all if g != 0),
        "cost_total": sum(float(r.get("cost") or 0.0) for r in traded),
        "charges_measured": sum(1 for r in traded if r.get("charges_measured")),
        "cost_unknown": sum(1 for r in traded if r.get("cost_unknown")),
        "pnl_key": pnl_key,
        # The daily series, so a caller can ask whether one session is the
        # whole record without re-deriving which rows were counted.
        "by_day": _by_day(traded, pnl_key),
    }
    if not pnl:
        return out

    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    gross_loss = abs(sum(losses))
    out["win_rate"] = 100 * len(wins) / len(pnl)
    out["avg_win"] = st.mean(wins) if wins else 0.0
    out["avg_loss"] = st.mean(losses) if losses else 0.0
    out["expectancy"] = st.mean(pnl)
    out["profit_factor"] = (sum(wins) / gross_loss) if gross_loss else math.inf

    # Sharpe on the per-trade series. Not annualised: annualising 34 trades
    # over two months would invent a confidence the sample cannot carry.
    out["sharpe"] = (
        st.mean(pnl) / st.stdev(pnl) if len(pnl) > 1 and st.stdev(pnl) else None
    )

    equity = peak = dd = 0.0
    for p in pnl:
        equity += p
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    out["peak_equity"] = peak
    out["max_drawdown"] = dd
    # AGAINST CAPITAL, NOT AGAINST PEAK PROFIT.
    #
    # Measured off peak profit this printed "150798.9%" - arithmetically
    # correct, unreadable, and worse than no number, because the peak was a
    # few rupees of accumulated profit and the drawdown was 32,799. The 8%
    # bar has only ever meant 8% of the money at risk, which is what a
    # drawdown limit protects.
    out["capital"] = capital
    out["max_drawdown_pct"] = (100 * dd / capital) if capital else None
    # Kept for reference, clearly named, never used as the gate.
    out["max_drawdown_pct_of_peak"] = (100 * dd / peak) if peak > 0 else None
    return out


def confirmed_cells() -> tuple[int, list[str], str | None]:
    """Cells clearing t >= 2.0 in the newest weekly-audit snapshot."""
    import json

    snaps = sorted(SNAPSHOTS.glob("*.json"))
    if not snaps:
        return 0, [], None
    d = json.loads(snaps[-1].read_text(encoding="utf-8-sig"))
    bar = d.get("ship_bar") or SHIP_BAR_T
    names: list[str] = []
    total = 0
    for asset, cells in (d.get("measurements") or {}).items():
        if not isinstance(cells, dict):
            continue
        for module, v in cells.items():
            if not isinstance(v, dict):
                continue
            total += 1
            t = v.get("t")
            if isinstance(t, (int, float)) and t >= bar:
                names.append(f"{module} / {asset}  t={t:+.2f}  n={v.get('n')}")
    return total, names, snaps[-1].stem


def _verdict(ok: bool | None) -> str:
    return "PASS" if ok else ("UNKNOWN" if ok is None else "FAIL")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="only positions opened on or after this date")
    args = ap.parse_args()

    if not DB.exists():
        print(f"  no database at {DB}")
        return 1

    rows = _load(args.since)
    print("=" * 78)
    print("  LIVE READINESS — measured against the commander's own agreed bar")
    print("=" * 78)
    if not rows:
        print("  No closed positions. Nothing to judge.")
        return 0

    rows = with_net(rows)
    clean_rows = [r for r in rows if r["opened_at"][:10] != CASCADE_DAY]
    everything = measure(rows, capital_for(rows))
    clean = measure(clean_rows, capital_for(clean_rows))
    best_day, lonely_rows = without_the_best_day(clean_rows)
    lonely = measure(lonely_rows, capital_for(lonely_rows))

    print("\n  P&L IS NET OF CHARGES throughout. Brokerage is flat per round")
    print("  trip, so it falls hardest on the smallest positions and does not")
    print("  cancel out of a ratio.")

    for label, m in (("ALL POSITIONS", everything),
                     (f"EXCLUDING THE {CASCADE_DAY} CASCADE", clean),
                     (f"AND WITHOUT ITS BEST DAY ({best_day})"
                      if best_day else "AND WITHOUT ITS BEST DAY", lonely)):
        print(f"\n  {label}")
        if not m["n"]:
            print("    no trades that moved money")
            continue
        print(f"    round trips      {m['n']}  (+{m['flats']} zero-P&L rows excluded)")
        print(f"    gross P&L        {m['gross_pnl']:+,.0f}")
        print(f"    charges          {-m['cost_total']:+,.0f}"
              f"   ({m['charges_measured']} of {m['n']} from the ledger, "
              f"the rest priced from the schedule)")
        print(f"    net P&L          {m['total_pnl']:+,.0f}")
        print(f"    win rate         {m['win_rate']:.1f}%")
        print(f"    avg win / loss   {m['avg_win']:+,.0f} / {m['avg_loss']:+,.0f}")
        print(f"    expectancy       {m['expectancy']:+,.0f} per trade")
        pf = m["profit_factor"]
        print(f"    profit factor    {pf:.2f}")
        sh = m["sharpe"]
        print(f"    Sharpe (per trade) {sh:+.3f}" if sh is not None else
              "    Sharpe (per trade) unknown")
        ddp = m["max_drawdown_pct"]
        print(f"    capital at risk  {m['capital']:,.0f}")
        print(f"    max drawdown     {m['max_drawdown']:,.0f}"
              + (f" ({ddp:.1f}% of capital)" if ddp is not None else ""))

    cbest, cbest_pnl, cshare, crest = day_concentration(clean.get("by_day") or {})
    if cbest:
        print("\n  CONCENTRATION")
        days = clean.get("by_day") or {}
        won = sum(1 for v in days.values() if v > 0)
        print(f"    trading days     {len(days)}  ({won} up, {len(days) - won} down)")
        print(f"    best day         {cbest}  {cbest_pnl:+,.0f}"
              + (f"   {cshare:.1f}% of the net total" if cshare else ""))
        print(f"    without it       {crest:+,.0f} over {len(days) - 1} days")

    print("\n" + "-" * 78)
    print("  THE GATE — judged on the record EXCLUDING the cascade, because a")
    print("  bug's accounting artifact is not a trading result, AND again")
    print("  without its best single day, because one session is one")
    print("  observation however many trades it contains.")
    print("-" * 78)

    total_cells, names, snap = confirmed_cells()
    enough = clean["n"] >= MIN_TRADES_FOR_A_VERDICT

    checks: list[tuple[str, bool | None, str]] = [
        (f"sample >= {MIN_TRADES_FOR_A_VERDICT} round trips",
         enough, f"{clean['n']} round trips"),
        (f"profit factor >= {MIN_PROFIT_FACTOR}",
         (clean.get("profit_factor", 0) >= MIN_PROFIT_FACTOR) if clean["n"] else None,
         f"{clean.get('profit_factor', 0):.2f}" if clean["n"] else "no data"),
        (f"Sharpe >= {MIN_SHARPE} (per trade)",
         (clean.get("sharpe") is not None and clean["sharpe"] >= MIN_SHARPE)
         if clean["n"] else None,
         f"{clean.get('sharpe'):+.3f}" if clean.get("sharpe") is not None else "unknown"),
        (f"max drawdown <= {MAX_DRAWDOWN_PCT}%",
         (clean.get("max_drawdown_pct") is not None
          and clean["max_drawdown_pct"] <= MAX_DRAWDOWN_PCT) if clean["n"] else None,
         f"{clean['max_drawdown_pct']:.1f}% of {clean.get('capital', 0):,.0f}"
         if clean.get("max_drawdown_pct") is not None else "unknown"),
        (f"confirmed cells >= {MIN_CONFIRMED_CELLS} (t>={SHIP_BAR_T})",
         len(names) >= MIN_CONFIRMED_CELLS,
         f"{len(names)} of {total_cells} measured" + (f", audit {snap}" if snap else "")),
        # THE SAME BAR, WITHOUT THE LUCK. Not a second, softer criterion: it is
        # the agreed profit factor asked of a record that no single session can
        # carry. Added 2026-11-10, when the record cleared 1.30 at 1.40 and one
        # day was 95.6% of it.
        (f"profit factor >= {MIN_PROFIT_FACTOR} without its best day",
         (lonely.get("profit_factor", 0) >= MIN_PROFIT_FACTOR)
         if lonely["n"] else None,
         f"{lonely.get('profit_factor', 0):.2f} over {lonely['n']} trades"
         + (f", ex {best_day}" if best_day else "") if lonely["n"] else "no data"),
    ]

    for label, ok, detail in checks:
        print(f"    [{_verdict(ok):7}] {label:38} {detail}")

    if names:
        print("\n    the confirmed edge:")
        for n in names:
            print(f"      {n}")

    failed = [c for c in checks if c[1] is not True]
    print()
    if failed:
        print(f"  NOT READY FOR REAL MONEY — {len(failed)} of {len(checks)} criteria unmet.")
        print("  Trading the commander's seed on this would be gambling, not compounding.")
    else:
        print("  Every criterion met. The decision to go live is the commander's.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
