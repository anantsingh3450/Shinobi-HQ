"""What the model predicted, beside what the ledger actually recorded.

THE QUESTION THIS ANSWERS
On 2026-11-09 three cells were funded and four assets were parked, on one
comparison: a measured hold-out edge in ATR, converted to a percentage of
premium, against the measured cost of one round trip. `funded_cells` says of
that decision: "That the two methods agree is the strongest thing in the
file."

Both methods are model-side. power_lab scores a signal's forward move on the
underlying; the cost side prices a hypothetical contract on a live book.
NEITHER HAS EVER BEEN COMPARED WITH WHAT THE ACCOUNT ACTUALLY DID. Hokage has
a ledger of real closed option positions with real entry and exit fills, and
nothing had ever put the two side by side.

This does. It changes nothing: it reads `positions` and `candles`, computes,
and prints.

WHY IT ASKS THE QUESTION TWICE, IN TWO DIFFERENT UNITS
In PERCENT OF PREMIUM, so the answer is comparable to a cost - that is the
unit the funding decision was made in. And in ATR, which removes the transfer
constant and the cost schedule from the comparison entirely and asks only:
did the underlying move the way the signal said it would, over the holds this
system actually took? If the two units disagree the fault is in the
conversion; if they agree, it is in the signal.

THE POOLED TRANSFER CONSTANT, WHICH THIS REPLACES
Every edge-in-premium figure in `funded_cells` was produced by multiplying an
ATR edge by 3.31% of premium per ATR. `transfer_lab` fitted that constant and
says plainly in its own docstring that it "POOLS ASSETS ... per-asset slopes
need an n this does not have". It was applied to all seven underlyings
anyway. The fifteen rows it was fitted on contain exactly ONE SILVERM trade,
and SILVERM is one of the assets the constant parked.

This fits the slope per asset, by dropping transfer_lab's archived-path
filter. That filter requires a `position_marks` row to prove the premium was
polled; it is a real check, but the fitted quantity uses the ledger's entry
and exit fills, not the marks, so what the filter mostly does is shrink n
from 93 to 15. Both fits are printed, so the cost of dropping it is visible
rather than assumed.

WHAT IT CANNOT TELL YOU
  * n IS SMALL EVERYWHERE and tiny on the index. Nothing here clears a ship
    bar in either direction, and nothing should be funded, parked, retired or
    un-parked on this alone.
  * THE INDEX ROWS ARE OLD. NIFTY, SENSEX and BANKNIFTY have not traded since
    August, and those months contain defects since fixed - an inverted entry
    grade, a stop ladder priced off a frozen book, a bias engine reading
    yesterday's tape. Their realised figures are reported with their last
    trade date so they can be discounted on sight.
  * EVERY ROW IS A TRADE THAT WAS TAKEN. A blocked signal has no fill and no
    premium, so this scores the system's choices, not the signal's.
  * HOLDS INSIDE TWO UNDERLYING BARS ARE DROPPED, because a move measured
    inside one bar is zero by construction. The count dropped is printed.
  * FILLS PAY NO SPREAD. The active friction profile resolves to ZERO, so a
    realised figure here is gross of the bid/ask. The spread measured on
    2026-11-09 is added to the cost side, and labelled where it is added.

USAGE
    python tools/research/model_vs_ledger.py
    python tools/research/model_vs_ledger.py --db <path to hokage.db>
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import transfer_lab as TL  # noqa: E402

from bots.execution import charges  # noqa: E402
from shared.instrument import underlying_of  # noqa: E402

#: The best measured hold-out edge per underlying, in ATR, from power_lab on
#: 2026-11-09 - the same table `spread_lab` carries and the same numbers that
#: chose the funded family. Carried, not re-measured: the audit remains the
#: source of truth and this file only puts the number beside the ledger.
BEST_EDGE_ATR: dict[str, tuple[str, float]] = {
    "SENSEX": ("MacroBreakout", 0.364),
    "GOLDM": ("SessionShift", 0.496),
    "NIFTY": ("MacroBreakout", 0.321),
    "CRUDEOIL": ("TrendRider", 0.088),
    "NATURALGAS": ("RiderTrend", 0.066),
    "BANKNIFTY": ("MacroBreakout", 0.197),
    "SILVERM": ("SessionShift", 0.072),
}

#: The pooled constant `funded_cells` was built on, kept so the per-asset
#: slopes below can be read against it.
POOLED_SLOPE = 3.31

#: Round-trip bid/ask measured live on 2026-11-09 (`spread_lab`), as a
#: percentage of premium. Crossing the book to get in and out costs the full
#: spread, so this IS the round trip. Added to the fee side because paper
#: fills do not pay it.
SPREAD_PCT: dict[str, float] = {
    "SILVERM": 0.16,
    "NIFTY": 0.27,
    "SENSEX": 0.26,
    "GOLDM": 0.33,
    "BANKNIFTY": 0.34,
    "CRUDEOIL": 0.20,
    "NATURALGAS": 0.67,
}

#: Where those two tables came from, printed so a reader can date the basis.
BASIS = "power_lab + spread_lab, 2026-11-09"

DEFAULT_DB = Path(r"C:\Hokage\hokage_brain\hokage.db")


@dataclass(frozen=True)
class Row:
    """One closed position, as both units see it."""

    asset: str
    strategy: str
    closed_on: str
    premium: float
    gross_pct: float
    cost_pct: float
    #: Underlying move over the hold, in ATR at entry, signed by the option's
    #: side. None when the candle archive cannot span the hold.
    atr_move: float | None

    @property
    def net_pct(self) -> float:
        return self.gross_pct - self.cost_pct


def _t(values: list[float]) -> tuple[int, float, float]:
    """n, mean and Student's t against zero. t is 0.0 when it is undefined."""
    n = len(values)
    if n < 2:
        return n, (values[0] if values else 0.0), 0.0
    mean = st.mean(values)
    sd = st.stdev(values)
    return n, mean, (mean / (sd / n**0.5) if sd else 0.0)


def _slope(pairs: list[tuple[float, float]]) -> tuple[int, float, float] | None:
    """n, slope and r for premium percent against underlying ATR."""
    if len(pairs) < 3:
        return None
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return len(pairs), sxy / sxx, (sxy / ((sxx * syy) ** 0.5) if syy > 0 else 0.0)


def read_rows(db: Path) -> tuple[list[Row], int, int]:
    """Every real closed position, with its ATR move where one is measurable.

    Returns the rows, how many were dropped as phantoms, and how many could
    not be given an ATR move. Both counts are reported rather than silently
    absorbed: a filter that quietly removes half the evidence is how a small
    sample starts looking like a large one.
    """
    bars = TL.Bars()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    columns = {r[1] for r in con.execute("PRAGMA table_info(positions)")}
    charge_col = ", charges" if "charges" in columns else ""
    raw = con.execute(
        "SELECT market, quantity, entry_price, current_price, realized_pnl, "
        f"       strategy_id, opened_at, closed_at, failure_reason{charge_col} "
        "FROM positions WHERE status = 'CLOSED' ORDER BY closed_at"
    ).fetchall()
    con.close()

    rows: list[Row] = []
    phantoms = no_atr = 0
    for r in raw:
        if str(r["failure_reason"] or "").startswith("PHANTOM"):
            phantoms += 1
            continue
        qty = abs(float(r["quantity"] or 0.0))
        entry = abs(float(r["entry_price"] or 0.0)) * qty
        exit_value = abs(float(r["current_price"] or 0.0)) * qty
        if entry <= 0:
            continue
        symbol = str(r["market"])
        asset = underlying_of(symbol)

        # What was actually taken beats what this tool would charge; before
        # schema 10 the column is NULL and the estimate is all there is.
        recorded = r["charges"] if charge_col else None
        if recorded is not None:
            cost = float(recorded)
        else:
            cost = charges.option_round_trip(
                entry, asset, exit_value=exit_value).total

        move = _atr_move(bars, symbol, asset,
                         str(r["opened_at"] or ""), str(r["closed_at"] or ""))
        if move is None:
            no_atr += 1

        rows.append(Row(
            asset=asset,
            strategy=str(r["strategy_id"] or "unattributed")
            .replace("strat-", "").replace("-v1", ""),
            closed_on=str(r["closed_at"] or "")[:10],
            premium=entry,
            gross_pct=float(r["realized_pnl"] or 0.0) / entry * 100.0,
            cost_pct=cost / entry * 100.0,
            atr_move=move,
        ))
    return rows, phantoms, no_atr


def _atr_move(bars: TL.Bars, symbol: str, asset: str,
              opened: str, closed: str) -> float | None:
    """The underlying's move over the hold, in ATR at entry, signed by side."""
    if not opened or not closed:
        return None
    start, end = TL._ist(opened), TL._ist(closed)
    i0 = bars.index_at(asset, start)
    i1 = bars.index_at(asset, end)
    atr = bars.atr(asset, i0)
    if i0 is None or i1 is None or not atr:
        return None
    if i1 - i0 < TL.MIN_SPAN_BARS:
        return None
    series = bars.of(asset)
    return ((series[i1]["close"] - series[i0]["close"])
            * TL.side_of(symbol)) / atr


def slopes_by_asset(rows: list[Row]) -> dict[str, tuple[int, float, float]]:
    """The transfer slope fitted per asset, instead of pooled across them."""
    out: dict[str, tuple[int, float, float]] = {}
    for asset in sorted({r.asset for r in rows}):
        pairs = [(r.atr_move, r.gross_pct) for r in rows
                 if r.asset == asset and r.atr_move is not None]
        fitted = _slope(pairs)
        if fitted:
            out[asset] = fitted
    return out


def report(db: Path) -> int:
    rows, phantoms, no_atr = read_rows(db)
    if not rows:
        print("No closed non-phantom positions in", db)
        return 1

    print()
    print("=" * 96)
    print("  THE MODEL AGAINST THE LEDGER")
    print("=" * 96)
    print(f"  ledger     {db}")
    print(f"  model      {BASIS}")
    print(f"  trades     {len(rows)} real closed positions "
          f"({rows[0].closed_on} to {rows[-1].closed_on}); "
          f"{phantoms} phantoms excluded")
    print(f"             {no_atr} of them carry no ATR move - no bars, or a "
          f"hold inside {TL.MIN_SPAN_BARS} bars")
    print("  fills pay NO spread (friction profile resolves to ZERO), so a")
    print("  realised figure below is gross of the bid/ask. The spread")
    print("  measured on 2026-11-09 is added to the cost side only.")

    fitted = slopes_by_asset(rows)
    print()
    print("-" * 96)
    print("  THE TRANSFER SLOPE, POOLED AND PER ASSET")
    print("-" * 96)
    print(f"  Every edge-in-premium figure in funded_cells was made by "
          f"multiplying an ATR edge")
    print(f"  by the pooled {POOLED_SLOPE}% of premium per ATR. Fitted per "
          f"asset instead:")
    print()
    print(f"  {'asset':<12} {'n':>4} {'slope %/ATR':>12} {'r':>8}   "
          f"{'vs pooled':>10}")
    for asset, (n, slope, r) in sorted(fitted.items(), key=lambda kv: -kv[1][1]):
        print(f"  {asset:<12} {n:>4} {slope:>11.2f}% {r:>+8.3f}   "
              f"{slope / POOLED_SLOPE:>9.2f}x")

    print()
    print("-" * 96)
    print("  PREDICTED AGAINST REALISED, IN PERCENT OF PREMIUM")
    print("-" * 96)
    print(f"  {'asset':<12} {'n':>3} {'last':>11} | {'edge%':>7} {'cost%':>6} "
          f"{'margin':>7} | {'gross%':>8} {'fees%':>6} {'net%':>8} {'t':>6}")
    by_asset: dict[str, list[Row]] = {}
    for row in rows:
        by_asset.setdefault(row.asset, []).append(row)
    for asset, group in sorted(by_asset.items(), key=lambda kv: -len(kv[1])):
        n, mean_net, t_net = _t([g.net_pct for g in group])
        gross = st.mean([g.gross_pct for g in group])
        fees = st.median([g.cost_pct for g in group])
        cost = fees + SPREAD_PCT.get(asset, 0.0)
        cell = BEST_EDGE_ATR.get(asset)
        slope = fitted.get(asset)
        if cell and slope:
            edge = cell[1] * slope[1]
            print(f"  {asset:<12} {n:>3} {group[-1].closed_on:>11} | "
                  f"{edge:>6.2f}% {cost:>5.2f}% {edge - cost:>+6.2f}% | "
                  f"{gross:>+7.2f}% {fees:>5.2f}% {mean_net:>+7.2f}% "
                  f"{t_net:>+6.2f}")
        else:
            print(f"  {asset:<12} {n:>3} {group[-1].closed_on:>11} | "
                  f"{'-':>7} {'-':>6} {'-':>7} | "
                  f"{gross:>+7.2f}% {fees:>5.2f}% {mean_net:>+7.2f}% "
                  f"{t_net:>+6.2f}")
    print()
    print("  edge%   = that asset's best hold-out edge_atr x its OWN fitted "
          "slope above")
    print("  cost%   = realised median fees + the 2026-11-09 spread")
    print("  margin  = what the model says one trade is worth before theta")
    print("  net%    = what one trade actually returned, charges deducted, "
          "spread not")

    print()
    print("-" * 96)
    print("  THE SAME QUESTION IN ATR, WHICH NEEDS NO CONVERSION AND NO COST")
    print("-" * 96)
    print("  Did the underlying move the way the signal said, over the holds")
    print("  this system took? Measured against the cell the model named.")
    print()
    print(f"  {'asset':<12} {'n':>3} {'realised ATR':>13} {'t':>7}   "
          f"{'model cell':<16} {'edge_atr':>9} {'captured':>9}")
    for asset, group in sorted(by_asset.items(), key=lambda kv: -len(kv[1])):
        moves = [g.atr_move for g in group if g.atr_move is not None]
        if not moves:
            continue
        n, mean_move, t_move = _t(moves)
        cell = BEST_EDGE_ATR.get(asset)
        if not cell:
            continue
        name, edge = cell
        share = f"{mean_move / edge:>8.2f}x" if edge else "       -"
        print(f"  {asset:<12} {n:>3} {mean_move:>+12.3f} {t_move:>+7.2f}   "
              f"{name:<16} {edge:>+9.3f} {share:>9}")

    print()
    print("-" * 96)
    print("  PER CELL, WHERE THE LEDGER HAS AT LEAST FIVE")
    print("-" * 96)
    # The two halves of this table are measured on different rows: a hold
    # the candle archive cannot span has a net percent but no ATR move. One
    # `n` over both would overstate the weaker half, so each carries its own.
    print(f"  {'asset':<12} {'strategy':<18} {'n':>3} {'net%':>8} {'t':>7}   "
          f"{'n':>3} {'realised ATR':>13} {'t':>7}")
    cells: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        cells.setdefault((row.asset, row.strategy), []).append(row)
    for (asset, strategy), group in sorted(cells.items(),
                                           key=lambda kv: -len(kv[1])):
        if len(group) < 5:
            continue
        n, mean_net, t_net = _t([g.net_pct for g in group])
        moves = [g.atr_move for g in group if g.atr_move is not None]
        if moves:
            m_n, m_mean, m_t = _t(moves)
            atr_text = f"{m_n:>3} {m_mean:>+12.3f} {m_t:>+7.2f}"
        else:
            atr_text = f"{0:>3} {'-':>12} {'-':>7}"
        print(f"  {asset:<12} {strategy:<18} {n:>3} {mean_net:>+7.2f}% "
              f"{t_net:>+7.2f}   {atr_text}")

    print()
    print("-" * 96)
    print("  WHAT THIS DOES NOT DO")
    print("-" * 96)
    print("  Nothing here was written anywhere, and nothing here clears a")
    print("  ship bar in either direction. A disagreement between the model")
    print("  and the ledger is a reason to measure again, not a reason to")
    print("  fund, park, un-park or retire a cell. Both sides are small")
    print("  samples; the index rows are from July and August and carry")
    print("  defects since fixed.")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"No ledger at {args.db}")
        return 1
    return report(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
