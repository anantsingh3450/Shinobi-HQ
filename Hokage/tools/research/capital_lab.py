"""What a given account size can actually trade, in lots, priced live.

    python tools/research/capital_lab.py
    python tools/research/capital_lab.py --capital 300000
    python tools/research/capital_lab.py --capital 100000 --assets GOLDM NIFTY

ONE LAKH IS THE WHOLE ACCOUNT, NOT A CHEST
Corrected 2026-11-09, same day, on the commander's word. The first version of
this lab carved the account into per-strategy chests and then applied the 33%
premium cap INSIDE each one, so a GOLDM lot at 27,515 appeared to need an
83,379 chest and running four assets appeared to need 3,33,515. That is the
books' model, not his: the cap exists to stop one position eating a chest, and
with chests cut from a single seed it compounds into cap = 33%/N of the
account - 8.25% at four assets, which no lot in the universe fits under.

Read correctly, 1,00,000 is one pool and every lot in the universe fits inside
a single 33% cap of it. The binding constraint is not the cap at all. It is
how much can be LOST at once, so the sizing question is answered from the
measured loss distribution rather than from a fraction.

WHAT THE LOSSES ACTUALLY ARE. 125 real closed trades, phantoms excluded:

    losses  74   median -7.76%   p90 -16.80%   worst -28.36% of premium
    wins    50   median +9.98%                 best  +29.71%

The go-live mandate allows an 8% drawdown. Against the WORST single loss ever
recorded, total premium open at any moment must stay under 8% / 28.36% of the
account; against the p90 loss, under 8% / 16.8%. Those two readings differ by
70% and both are defensible, so both are printed. A single number here would
be a choice of risk appetite disguised as arithmetic.

WHY THIS EXISTS
2026-11-09. The paper books allocate a full chest to every live strategy -
one on the index book and six on MCX after NATURALGAS was unparked - so they
carry 7,00,000 rupees against a real seed of 1,00,000. Every rupee figure in
the system is therefore denominated in money that does not exist, including
the ones the go-live gate is judged on: "every competing strategy can afford
to trade" passes against chests that are not there, and a drawdown limit of 8%
is measured against seven times the account.

The percentage measurements are unaffected - an edge of 1.64% of premium is
1.64% at any size - which is exactly why this went unnoticed. It is the rupee
figures, the affordability audits and the risk caps that are wrong.

THE ARENA BOUNDS THE EXPOSURE, AND THE BOUND IS THE NUMBER THAT MATTERS
Winner-take-asset means one position per asset, not one per strategy, so six
gas strategies cannot hold six gas positions. Concurrent exposure is therefore

    scannable assets  x  MAX_PREMIUM_CHEST_FRACTION  x  chest

and with four assets at 33% of a 1,00,000 chest that is 1,32,000 rupees of
premium at risk at once, on a 1,00,000 rupee account. Options can expire
worthless, so premium at risk is capital at risk.

WHAT MAKES THIS ARITHMETIC AWKWARD RATHER THAN SIMPLE
Dividing the account by the asset count gives a chest, but a chest only
functions if 33% of it buys one lot - and a lot is indivisible. One lot of
GOLDM costs about 27,000 rupees, which needs a chest of 82,000 to sit inside
the cap. So a 1,00,000 account cannot fund two GOLDM chests, and the binding
constraint is the DEAREST lot a strategy might take rather than the average.

FLAT BROKERAGE PUNISHES SMALL. 40 rupees a round trip is 0.22% of an 18,000
lot and 0.80% of a 5,000 one, so shrinking positions to fit more of them
raises the cost of every trade. That trade-off is priced below rather than
left as a remark.

PRICED LIVE, THROUGH THE PRODUCTION RESOLVER. Lot sizes come from
`resolve_option_contract`, the same path the entry router uses, because Kite's
raw instrument dump reports lot_size=1 for MCX and reading it straight once
priced a gas round trip at 320% of premium. A contract that cannot be quoted
is reported as unquotable and never defaulted.

THIS TOOL CHANGES NOTHING. Chest sizes and the premium cap are risk
constants; they move on the commander's word alone. This only says what the
arithmetic allows.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bots.execution import charges  # noqa: E402
from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION  # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "research"))
from live_readiness import MAX_DRAWDOWN_PCT  # noqa: E402
from hokage.research import funded_cells  # noqa: E402

#: The real seed, as stated by the commander on 2026-11-09. Not read from the
#: books: the books are what this tool exists to check.
DEFAULT_CAPITAL = 100_000.0


def scannable_assets() -> list[str]:
    """Assets the scan loop reaches - funded, plus traded for the record.

    This is the concurrency bound under winner-take-asset, so it is the right
    denominator. Parked assets are excluded because the loop never reaches
    them, and a chest reserved for an asset that is not scanned is capital
    held against nothing.
    """
    return sorted(funded_cells.funded_assets()
                  | set(funded_cells.TRADED_FOR_THE_RECORD))


def price_one_lot(symbols: list[str]) -> dict[str, dict]:
    """{symbol: {premium, lot, cost}} priced live, or a reason it is absent."""
    from integrations.brokers.kite_connection import KiteConnectionManager
    from integrations.brokers.kite_market_data_provider import (
        KiteMarketDataProvider)
    from integrations.brokers.secrets import SecretManager

    manager = KiteConnectionManager(SecretManager())
    status = manager.connect()
    if not getattr(status, "connected", bool(status)):
        return {}
    provider = KiteMarketDataProvider(manager)
    kite = manager.get_kite_client()

    out: dict[str, dict] = {}
    for symbol in symbols:
        try:
            spot = provider.get_price(symbol)
            dearest = None
            for kind in ("CE", "PE"):
                contract = provider.resolve_option_contract(symbol, kind, spot)
                if not contract:
                    continue
                lot = float(contract.get("lot_size") or 0)
                if lot <= 1:
                    # The MCX defect. A lot size of 1 on an options contract
                    # is not a cheap lot, it is a missing one.
                    out[symbol] = {"error": f"lot_size={lot:g} unusable"}
                    break
                key = f"{contract['exchange']}:{contract['tradingsymbol']}"
                quote = kite.quote([key]).get(key) or {}
                premium = float(quote.get("last_price") or 0.0)
                if premium <= 0:
                    continue
                cost = premium * lot
                # The dearest of the two legs is what a chest must survive:
                # the strategy picks the side, not the sizing.
                if dearest is None or cost > dearest["cost"]:
                    dearest = {"premium": premium, "lot": lot, "cost": cost,
                               "contract": contract["tradingsymbol"]}
            if dearest is not None and symbol not in out:
                out[symbol] = dearest
            elif symbol not in out:
                out[symbol] = {"error": "no quotable ATM contract"}
        except Exception as exc:
            out[symbol] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def measured_losses() -> list[float]:
    """Realised losses as a percentage of entry premium, from the ledger.

    PHANTOMS EXCLUDED. The 292 rows minted by the 2026-07-15 reduce-only
    runaway closed at entry and carry no real outcome; counting them would
    pull every percentile toward zero and make the account look safer than it
    is.
    """
    import sqlite3

    from hokage.memory.resolver import brain_root

    path = brain_root() / "hokage.db"
    if not path.exists():
        return []
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT entry_price, quantity, realized_pnl, failure_reason "
            "FROM positions WHERE upper(status) = 'CLOSED'").fetchall()
    finally:
        con.close()

    out = []
    for row in rows:
        if str(row["failure_reason"] or "").startswith("PHANTOM"):
            continue
        notional = float(row["entry_price"] or 0) * float(row["quantity"] or 0)
        if notional <= 0:
            continue
        pct = float(row["realized_pnl"] or 0) / notional * 100.0
        if pct < 0:
            out.append(pct)
    return sorted(out)


def loss_at(losses: list[float], quantile: float) -> float | None:
    """The loss at a quantile of SEVERITY, as a positive percentage.

    1.0 is the worst ever recorded, 0.5 the median.

    SORTS ITS OWN INPUT. The first version relied on the caller having sorted
    ascending, which `measured_losses` does - so it was correct in production
    and wrong the moment a test passed a list in any other order. A function
    whose answer depends on an unstated ordering is a trap for whoever calls
    it next, and the ordering is cheaper to enforce than to document.
    """
    if not losses:
        return None
    severe = sorted((abs(v) for v in losses), reverse=True)
    index = int(round((1.0 - quantile) * (len(severe) - 1)))
    return severe[max(0, min(index, len(severe) - 1))]


def premium_budget(capital: float, drawdown_pct: float, loss_pct: float
                   ) -> float:
    """Total premium that may be open at once, given a loss assumption.

    THE REAL CONSTRAINT ON A POOLED ACCOUNT. If everything open stops out
    together at `loss_pct` of premium, the account loses `drawdown_pct`. The
    premium cap does not bind here - every lot in the universe fits inside 33%
    of a 1,00,000 pool - so what limits size is the loss, not the fraction.
    """
    if loss_pct <= 0:
        return 0.0
    return capital * (drawdown_pct / 100.0) / (loss_pct / 100.0)


def fit_within(budget: float, lot_costs: dict[str, float]) -> list[str]:
    """Most assets fundable inside a total-premium budget, cheapest first."""
    chosen: list[str] = []
    running = 0.0
    for symbol in sorted(lot_costs, key=lambda s: lot_costs[s]):
        if running + lot_costs[symbol] > budget:
            break
        running += lot_costs[symbol]
        chosen.append(symbol)
    return chosen


def chest_needed_for(lot_cost: float) -> float:
    """The chest a single lot of this size requires, given the premium cap.

    Only meaningful under the BOOKS' model, where each strategy holds its own
    chest. On a single pooled account this is the wrong question - see the
    module docstring.
    """
    return lot_cost / MAX_PREMIUM_CHEST_FRACTION


def max_concurrent_per_asset(capital: float, lot_costs: dict[str, float]
                             ) -> list[str]:
    """Assets fundable when each chest is sized to its OWN lot, cheapest first.

    This beats an even split and by a wide margin: an even split must survive
    the dearest lot in the set, so it over-provisions every cheap asset. On a
    1,00,000 account the even split funds ONE asset and this funds two.
    """
    chosen: list[str] = []
    running = 0.0
    for symbol in sorted(lot_costs, key=lambda s: lot_costs[s]):
        need = chest_needed_for(lot_costs[symbol])
        if running + need > capital:
            break
        running += need
        chosen.append(symbol)
    return chosen


def max_concurrent(capital: float, lot_costs: list[float]) -> int:
    """How many assets this capital can fund, worst lot first.

    Worst-first because a chest must survive the dearest lot that strategy
    might take; sizing by the average quietly funds a position that cannot be
    opened, which is the failure where a strategy wins an auction and then
    stands aside, denying the asset to everyone else.
    """
    if not lot_costs:
        return 0
    for count in range(len(lot_costs), 0, -1):
        chest = capital / count
        dearest = max(sorted(lot_costs, reverse=True)[:count])
        if chest * MAX_PREMIUM_CHEST_FRACTION >= dearest:
            return count
    return 0


def report(capital: float, symbols: list[str]) -> int:
    print("=" * 78)
    print("  WHAT THIS ACCOUNT CAN ACTUALLY TRADE")
    print("=" * 78)
    print(f"  capital        Rs {capital:,.0f} TOTAL - one pool, not a chest "
          f"each")
    print(f"  premium cap    {MAX_PREMIUM_CHEST_FRACTION:.0%} of the pool = "
          f"Rs {capital * MAX_PREMIUM_CHEST_FRACTION:,.0f} a position")
    print(f"  assets         {', '.join(symbols)}")
    print("  concurrency    one position per ASSET (winner-take-asset), not "
          "per strategy")
    print(f"  binding        the {MAX_DRAWDOWN_PCT:.0f}% drawdown mandate "
          f"against measured losses, not the cap")
    print()

    priced = price_one_lot(symbols)
    if not priced:
        print("  Broker session is not live - log in first, then re-run.")
        print("  Nothing below can be computed from stored data: lot sizes and")
        print("  premiums both move, and a stale lot cost is a wrong answer")
        print("  rather than an old one.")
        return 1

    print("  ONE LOT, PRICED LIVE")
    print(f"      {'asset':<12}{'premium':>10}{'lot':>8}{'cost/lot':>12}"
          f"{'chest if split':>16}")
    usable: dict[str, float] = {}
    for symbol in symbols:
        row = priced.get(symbol) or {}
        if "error" in row:
            print(f"      {symbol:<12}   {row['error']}")
            continue
        need = chest_needed_for(row["cost"])
        usable[symbol] = row["cost"]
        print(f"      {symbol:<12}{row['premium']:>10,.2f}{row['lot']:>8,.0f}"
              f"{row['cost']:>12,.0f}{need:>15,.0f}")
    print()
    if not usable:
        print("  Nothing could be priced. No arithmetic follows from that.")
        return 1

    # ---------------------------------------------------- the pooled answer
    print("  EACH LOT AS A SHARE OF THE WHOLE ACCOUNT")
    print(f"      the {MAX_PREMIUM_CHEST_FRACTION:.0%} cap on a pooled "
          f"Rs {capital:,.0f} account is "
          f"Rs {capital * MAX_PREMIUM_CHEST_FRACTION:,.0f} a position")
    for symbol in sorted(usable, key=lambda s: usable[s]):
        cost = usable[symbol]
        verdict = ("fits" if cost <= capital * MAX_PREMIUM_CHEST_FRACTION
                   else "OVER THE CAP")
        print(f"      {symbol:<12}{cost:>10,.0f}{cost / capital:>9.1%}"
              f"   {verdict}")
    print("      So the cap is not what binds. What binds is how much can be")
    print("      lost at once, which is measured below rather than assumed.")
    print()

    losses = measured_losses()
    if not losses:
        print("  No real closed trades to size from. Nothing follows.")
    else:
        print(f"  MEASURED LOSSES  ({len(losses)} real losing trades, "
              f"phantoms excluded)")
        for q, label in ((0.5, "median"), (0.75, "p75"), (0.9, "p90"),
                         (1.0, "worst ever")):
            print(f"      {label:<12}{loss_at(losses, q):>7.2f}% of premium")
        print()
        print(f"  TOTAL PREMIUM THAT MAY BE OPEN AT ONCE  "
              f"(drawdown mandate {MAX_DRAWDOWN_PCT:.0f}%)")
        print(f"      {'if a stop-out costs':<22}{'budget':>12}"
              f"{'concurrent assets':>22}")
        for q, label in ((1.0, "the worst ever"), (0.9, "the p90 loss"),
                         (0.5, "the median loss")):
            loss = loss_at(losses, q)
            budget = premium_budget(capital, MAX_DRAWDOWN_PCT, loss)
            fits = fit_within(budget, usable)
            label_full = f"{label} ({loss:.1f}%)"
            print(f"      {label_full:<22}{budget:>12,.0f}"
                  f"   {', '.join(fits) if fits else 'NONE'}")
        print()
        print("      These differ because they are different questions about")
        print("      risk appetite, not different arithmetic. The harsh row")
        print("      assumes every open position stops at the worst loss ever")
        print("      recorded, simultaneously; the median row assumes a")
        print("      typical one. Pick the row, not the number.")
    print()

    print("  THE BOOKS' MODEL, FOR CONTRAST - A CHEST PER STRATEGY")
    print("      Only meaningful if each strategy holds its own capital. With")
    print("      chests cut from one seed the cap compounds to 33%/N of the")
    print("      account, which is why this reads as unaffordable.")
    print("  SPLITTING THE ACCOUNT EVENLY")
    print(f"      {'chests':>7}{'chest each':>13}{'cap/position':>14}"
          f"{'lots affordable':>18}")
    for count in range(1, len(symbols) + 1):
        chest = capital / count
        cap = chest * MAX_PREMIUM_CHEST_FRACTION
        affordable = sorted(s for s, c in usable.items() if c <= cap)
        label = ", ".join(affordable) if affordable else "NONE"
        print(f"      {count:>7}{chest:>13,.0f}{cap:>14,.0f}   {label}")
    print()

    best = max_concurrent(capital, list(usable.values()))
    dearest_sym = max(usable, key=lambda s: usable[s])
    print("  WHAT THAT MEANS")
    if best == 0:
        print(f"      This capital cannot fund ONE chest. The cheapest lot is")
        cheapest = min(usable, key=lambda s: usable[s])
        print(f"      {cheapest} at Rs {usable[cheapest]:,.0f}, which needs a "
              f"chest of")
        print(f"      Rs {chest_needed_for(usable[cheapest]):,.0f} to sit "
              f"inside the {MAX_PREMIUM_CHEST_FRACTION:.0%} cap.")
    else:
        chest = capital / best
        print(f"      Even split:     {best} concurrent asset(s) at Rs "
              f"{chest:,.0f} a chest.")
        print(f"                      Bound by {dearest_sym} at Rs "
              f"{usable[dearest_sym]:,.0f} a lot, needing Rs "
              f"{chest_needed_for(usable[dearest_sym]):,.0f}.")
        per = max_concurrent_per_asset(capital, usable)
        print(f"      Sized per asset: {len(per)} concurrent asset(s) - "
              f"{', '.join(per) if per else 'none'}.")
        print("                      Strictly better, and the same arena. An "
              "even split")
        print("                      over-provisions every cheap asset to "
              "survive the dearest.")
    print()

    # Chests sized PER ASSET rather than evenly. An even split must survive
    # the dearest lot in the set, so it over-provisions every cheap asset;
    # sizing each chest to its own asset's lot is the same arena at a far
    # lower capital requirement, and it is the number worth planning against.
    print("  CHEAPEST ROUTE TO N CONCURRENT ASSETS (chests sized per asset)")
    print(f"      {'add':<12}{'chest for it':>14}{'cumulative':>13}"
          f"{'affordable at':>16}")
    running = 0.0
    order = sorted(usable, key=lambda s: usable[s])
    for symbol in order:
        need = chest_needed_for(usable[symbol])
        running += need
        verdict = "affordable now" if running <= capital else "needs more"
        print(f"      {symbol:<12}{need:>14,.0f}{running:>13,.0f}"
              f"   {verdict}")
    print()
    monthly = 10_000.0
    short = max(0.0, running - capital)
    if short > 0:
        print(f"      All {len(order)} concurrently needs Rs {running:,.0f}: "
              f"Rs {short:,.0f} more than")
        print(f"      the account holds, or {short / monthly:.0f} months at "
              f"Rs {monthly:,.0f} a month.")
    else:
        print(f"      All {len(order)} concurrently fits inside "
              f"Rs {capital:,.0f}.")
    print("      An even split would instead need Rs "
          f"{len(order) * chest_needed_for(max(usable.values())):,.0f}, "
          "because every")
    print("      chest would have to survive the dearest lot in the set.")
    print()

    print("  WHAT THE BOOKS DO TODAY, FOR CONTRAST")
    live = 7
    book_chest = 100_000.0
    exposure = len(symbols) * MAX_PREMIUM_CHEST_FRACTION * book_chest
    print(f"      {live} live strategies x Rs {book_chest:,.0f} = Rs "
          f"{live * book_chest:,.0f} allocated")
    print(f"      concurrent premium at risk: {len(symbols)} assets x "
          f"{MAX_PREMIUM_CHEST_FRACTION:.0%} x Rs {book_chest:,.0f}")
    print(f"                                = Rs {exposure:,.0f}  "
          f"({exposure / capital:.0%} of the real account)")
    print()

    print("  WHAT SHRINKING COSTS, BECAUSE BROKERAGE IS FLAT")
    print(f"      {'position':>12}{'round trip':>13}{'as % premium':>15}")
    for size in (5_000.0, 10_000.0, 18_375.0, 27_000.0, 50_000.0):
        rt = charges.option_round_trip(size, "GOLDM")
        print(f"      {size:>12,.0f}{rt.total:>13,.0f}"
              f"{rt.pct_of_premium:>14.2f}%")
    print("      40 rupees of brokerage is fixed, so halving a position")
    print("      roughly doubles what the trade costs in percentage terms -")
    print("      and the measured edges are 1.06% to 1.64% of premium.")
    print()
    print("  Chest sizes and the premium cap are risk constants and move on")
    print("  the commander's word alone. This tool reports; it changes nothing.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="What an account size can trade.")
    ap.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    ap.add_argument("--assets", nargs="*", default=None)
    args = ap.parse_args()
    symbols = [a.upper() for a in (args.assets or scannable_assets())]
    return report(args.capital, symbols)


if __name__ == "__main__":
    raise SystemExit(main())
