"""What a given account size can actually trade, in lots, priced live.

    python tools/research/capital_lab.py
    python tools/research/capital_lab.py --capital 300000
    python tools/research/capital_lab.py --capital 100000 --assets GOLDM NIFTY

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


def chest_needed_for(lot_cost: float) -> float:
    """The chest a single lot of this size requires, given the premium cap."""
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
    print(f"  capital        Rs {capital:,.0f}")
    print(f"  premium cap    {MAX_PREMIUM_CHEST_FRACTION:.0%} of a chest, "
          f"per position")
    print(f"  assets         {', '.join(symbols)}")
    print("  concurrency    one position per ASSET (winner-take-asset), not "
          "per strategy")
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
          f"{'chest needed':>15}")
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
