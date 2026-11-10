"""The lifetime record with the broker's charges taken out of it.

WHY THIS EXISTS
`PortfolioBot.apply_trade` does `self.cash += pos.realized_pnl` and nothing
else. No brokerage, no STT, no GST, no stamp duty. So every P&L number Hokage
has ever produced - the per-strategy expectancies, the sweep results, the
retirement decisions, and the profit factor 1.04 that the go-live gate is
judged against - is GROSS. `bots.execution.charges` quotes the real schedule
from zerodha.com/charges and says plainly that it does not touch the ledger.
Nothing had ever run it across the ledger either, so the size of the gap was
unknown. This reads it.

WHAT MAKES THIS WORTH A TOOL RATHER THAN A SPREADSHEET
Brokerage is FLAT - 40 rupees a round trip whatever the size - so the cost is
not a percentage that cancels out of a ratio. It falls hardest on the smallest
positions, which are exactly the ones this account can afford, and it is paid
on losers as well as winners. A profit factor is gross-profit over gross-loss;
charges push the numerator down and the denominator up at once, so PF moves
further than the raw rupee total suggests.

THIS CHANGES NOTHING. It reads `positions`, computes, and prints. Deducting
charges at the fill is a separate change that rewrites every number the
commander has been shown, and it is his to make knowingly.

WHAT IT CANNOT KNOW
The exit turnover is real here (`current_price` is the exit fill), so these
are not the flat-exit estimates `charges.option_round_trip` falls back to.
But partial fills, order modifications and any trade that was split into more
than one order each cost another 20 rupees, and the ledger records one row per
position - so this is a FLOOR on charges, never a ceiling.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bots.execution import charges  # noqa: E402
from shared.instrument import underlying_of  # noqa: E402

DEFAULT_DB = Path(r"C:\Hokage\hokage_brain\hokage.db")


@dataclass(frozen=True)
class Trade:
    """One closed position, gross and net."""

    symbol: str
    underlying: str
    strategy: str
    quantity: float
    entry_value: float
    exit_value: float
    gross: float
    cost: float
    closed_at: str
    #: True when `cost` is what the ledger says was actually taken, False
    #: when it is this tool's estimate for a position from the gross era.
    #: Averaging the two without saying so would present a reconstruction as
    #: a record.
    measured: bool = False

    @property
    def net(self) -> float:
        return self.gross - self.cost

    @property
    def cost_pct(self) -> float:
        return (self.cost / self.entry_value * 100.0) if self.entry_value else 0.0


def cost_for(entry_value: float, exit_value: float, underlying: str,
             recorded: float | None) -> tuple[float, bool]:
    """What one round trip cost, and whether that is a record or an estimate.

    THE ONE DEFINITION. `live_readiness` judges the go-live gate on net P&L
    and this file reports the net record; two copies of this rule is how the
    gate and the record come to disagree about the same ledger. WHAT WAS
    ACTUALLY TAKEN BEATS WHAT THIS TOOL WOULD CHARGE: since 2026-11-09 the
    ledger records the real figure per position, and before that the column is
    NULL and the estimate is all there is.
    """
    if recorded is not None:
        return float(recorded), True
    return (charges.option_round_trip(entry_value, underlying,
                                      exit_value=exit_value).total, False)


def day_concentration(
    pnl_by_day: dict[str, float],
) -> tuple[str | None, float, float, float]:
    """The best day, what it was worth, its share of the profit, and the rest.

    WHY A GATE NEEDS THIS. On 2026-11-10 the whole attributed-era record was
    +23,458 over 68 trades, PF 1.40 net - and 2026-08-19 alone was +22,416 of
    it, five long calls riding one gold trend inside three hours. Strip that
    one day and 67 trades are worth +1,042; strip two and the era is negative.

    A ratio that one day can carry is not a measurement of a system, and
    `live_readiness` already refuses to judge on the 2026-07-15 cascade for
    the same reason - with the difference that the cascade was a bug and this
    day was real. A real day is still n=1.

    Share is of the TOTAL, which may be negative or zero; it is returned as
    0.0 there rather than as an infinity, because "this day is 400% of a tiny
    total" is arithmetic, not information.
    """
    if not pnl_by_day:
        return None, 0.0, 0.0, 0.0
    best = max(pnl_by_day, key=lambda d: pnl_by_day[d])
    best_pnl = pnl_by_day[best]
    total = sum(pnl_by_day.values())
    rest = total - best_pnl
    share = (100.0 * best_pnl / total) if total > 0 else 0.0
    return best, best_pnl, share, rest


def closed_trades(db: Path) -> list[Trade]:
    """Every real closed position, with its charges priced on both legs.

    PHANTOMS ARE EXCLUDED. The 2026-07-15 reduce-only runaway left 292 rows
    that were never real orders; including them would price charges on trades
    that never happened and drown the real record 2:1.
    """
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    columns = {r[1] for r in con.execute("PRAGMA table_info(positions)")}
    # `charges` arrived with schema 10 on 2026-11-09. Before that there is
    # nothing to read and every figure here is this tool's estimate.
    charge_col = ", charges" if "charges" in columns else ""
    rows = con.execute(
        "SELECT market, quantity, entry_price, current_price, realized_pnl, "
        f"       strategy_id, closed_at, failure_reason{charge_col} "
        "FROM positions WHERE status = 'CLOSED' ORDER BY closed_at"
    ).fetchall()
    con.close()

    out: list[Trade] = []
    for row in rows:
        if str(row["failure_reason"] or "").startswith("PHANTOM"):
            continue
        qty = abs(float(row["quantity"] or 0.0))
        entry = abs(float(row["entry_price"] or 0.0)) * qty
        exit_ = abs(float(row["current_price"] or 0.0)) * qty
        if entry <= 0:
            continue
        symbol = str(row["market"])
        root = underlying_of(symbol)
        # WHAT WAS ACTUALLY TAKEN BEATS WHAT THIS TOOL WOULD CHARGE. Since
        # 2026-11-09 the ledger records the real figure per position; before
        # that the column is NULL and the estimate is all there is.
        recorded = row["charges"] if charge_col else None
        cost, measured = cost_for(entry, exit_, root, recorded)
        out.append(Trade(
            symbol=symbol,
            underlying=root,
            strategy=str(row["strategy_id"] or "unattributed"),
            quantity=qty,
            entry_value=entry,
            exit_value=exit_,
            gross=float(row["realized_pnl"] or 0.0),
            cost=cost,
            closed_at=str(row["closed_at"] or ""),
            measured=measured,
        ))
    return out


def profit_factor(values: list[float]) -> float | None:
    """Gross profit over gross loss. None when nothing was lost."""
    won = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    if lost <= 0:
        return None
    return won / lost


def _pf_text(values: list[float]) -> str:
    pf = profit_factor(values)
    return "no losses" if pf is None else f"{pf:.2f}"


@dataclass(frozen=True)
class Summary:
    """One population, gross against net."""

    label: str
    n: int
    gross_total: float
    net_total: float
    gross_pf: float | None
    net_pf: float | None
    gross_wins: int
    net_wins: int
    cost_total: float
    median_cost_pct: float


def summarise(label: str, trades: list[Trade]) -> Summary:
    gross = [t.gross for t in trades]
    net = [t.net for t in trades]
    return Summary(
        label=label,
        n=len(trades),
        gross_total=sum(gross),
        net_total=sum(net),
        gross_pf=profit_factor(gross),
        net_pf=profit_factor(net),
        gross_wins=sum(1 for v in gross if v > 0),
        net_wins=sum(1 for v in net if v > 0),
        cost_total=sum(t.cost for t in trades),
        median_cost_pct=statistics.median([t.cost_pct for t in trades]) if trades else 0.0,
    )


def _pf_cell(pf: float | None) -> str:
    return "  n/a " if pf is None else f"{pf:6.2f}"


def report(db: Path) -> int:
    trades = closed_trades(db)
    if not trades:
        print("No closed non-phantom positions in", db)
        return 1

    print()
    print("=" * 74)
    print("THE RECORD, NET OF CHARGES")
    print("=" * 74)
    print(f"ledger     {db}")
    print(f"rates      {charges.RATES_SOURCE}, read {charges.RATES_READ_ON}")
    print(f"trades     {len(trades)} real closed positions "
          f"({trades[0].closed_at[:10]} to {trades[-1].closed_at[:10]})")
    real = sum(1 for t in trades if t.measured)
    print(f"basis      {real} priced from the ledger's own charges column, "
          f"{len(trades) - real} estimated")
    print("           (charges have been deducted at the fill since "
          f"{charges.DEDUCTED_FROM}; before that there is")
    print("           nothing recorded to read, so those rows are this "
          "tool's reconstruction.)")
    print("           Estimates assume one order per leg.")
    print("           A split fill costs another 20 rupees, so this is a")
    print("           FLOOR on charges, never a ceiling.")

    whole = summarise("everything", trades)
    print()
    print("-" * 74)
    print("  OVERALL")
    print("-" * 74)
    print(f"  gross P&L        Rs {whole.gross_total:>12,.0f}")
    print(f"  charges          Rs {whole.cost_total:>12,.0f}"
          f"   (median {whole.median_cost_pct:.2f}% of premium)")
    print(f"  net P&L          Rs {whole.net_total:>12,.0f}")
    print()
    print(f"  profit factor    gross {_pf_text([t.gross for t in trades])}"
          f"      net {_pf_text([t.net for t in trades])}")
    print(f"  winners          gross {whole.gross_wins}/{whole.n}"
          f"          net {whole.net_wins}/{whole.n}")
    flipped = [t for t in trades if t.gross > 0 >= t.net]
    print(f"  wins that charges turned into losses: {len(flipped)}")

    # HOW MANY DAYS IS THIS RECORD, REALLY. A profit factor that one session
    # carries is arithmetic on n=1, and net_total alone cannot show that.
    by_day: dict[str, float] = {}
    for t in trades:
        if t.closed_at:
            by_day[t.closed_at[:10]] = by_day.get(t.closed_at[:10], 0.0) + t.net
    best, best_pnl, share, rest = day_concentration(by_day)
    if best:
        print()
        print("-" * 74)
        print("  CONCENTRATION — is this a system, or is it one day?")
        print("-" * 74)
        won = sum(1 for v in by_day.values() if v > 0)
        print(f"  trading days     {len(by_day)}  ({won} up, "
              f"{len(by_day) - won} down)")
        print(f"  best day         {best}  Rs {best_pnl:>+12,.0f}"
              + (f"   {share:.1f}% of the net total" if share else ""))
        print(f"  without it       Rs {rest:>+12,.0f} over "
              f"{len(by_day) - 1} days")
        if share >= 50.0:
            print(f"  ONE DAY IS {share:.0f}% OF THIS RECORD. Every ratio above "
                  f"is that day")
            print("  plus noise, whatever its sample size says.")

    print()
    print("-" * 74)
    print("  BY UNDERLYING")
    print("-" * 74)
    print(f"  {'asset':<12} {'n':>4} {'gross':>11} {'charges':>10} "
          f"{'net':>11}  {'PF gross':>8} {'PF net':>7}")
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(t.underlying, []).append(t)
    for asset, rows in sorted(groups.items(),
                              key=lambda kv: -sum(t.net for t in kv[1])):
        s = summarise(asset, rows)
        print(f"  {asset:<12} {s.n:>4} {s.gross_total:>11,.0f} "
              f"{-s.cost_total:>10,.0f} {s.net_total:>11,.0f}  "
              f"{_pf_cell(s.gross_pf):>8} {_pf_cell(s.net_pf):>7}")

    print()
    print("-" * 74)
    print("  BY STRATEGY")
    print("-" * 74)
    print(f"  {'strategy':<30} {'n':>4} {'gross':>10} {'net':>10}  "
          f"{'PF gross':>8} {'PF net':>7}")
    by_strat: dict[str, list[Trade]] = {}
    for t in trades:
        by_strat.setdefault(t.strategy, []).append(t)
    for name, rows in sorted(by_strat.items(),
                             key=lambda kv: -sum(t.net for t in kv[1])):
        s = summarise(name, rows)
        print(f"  {name:<30} {s.n:>4} {s.gross_total:>10,.0f} "
              f"{s.net_total:>10,.0f}  "
              f"{_pf_cell(s.gross_pf):>8} {_pf_cell(s.net_pf):>7}")

    print()
    print("-" * 74)
    print("  WHERE THE MONEY WENT")
    print("-" * 74)
    print("  Composition is modelled from the schedule in every case: the")
    print("  ledger records one total per position, not its lines. The")
    print("  shares are therefore exact only where the total was estimated.")
    totals: dict[str, float] = {}
    for t in trades:
        trip = charges.option_round_trip(t.entry_value, t.underlying,
                                         exit_value=t.exit_value)
        for line, rupees, _pct in trip.breakdown():
            totals[line] = totals.get(line, 0.0) + rupees
    for line, rupees in sorted(totals.items(), key=lambda kv: -kv[1]):
        share = rupees / whole.cost_total * 100.0 if whole.cost_total else 0.0
        print(f"  {line:<14} Rs {rupees:>9,.0f}   {share:5.1f}% of all charges")

    print()
    print("-" * 74)
    print("  WHAT THIS DOES NOT DO")
    print("-" * 74)
    print("  Nothing here was written anywhere. The ledger still holds gross")
    print("  P&L and the bot still moves cash by gross P&L. Deducting these")
    print("  at the fill rewrites every number on every dashboard and in")
    print("  every past sweep, so it is the commander's call to make.")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    if not args.db.exists():
        print(f"No ledger at {args.db}")
        return 1
    return report(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
