"""What does one round trip cost, before anything else? Measured, not modelled.

THE QUESTION THIS ANSWERS
2026-11-09. The ledger says profit factor 1.04 across 123 round trips - break
even. The audit says the best cell measures +0.496 ATR, and the transfer
measurement says 1.0 ATR of underlying is worth +3.31% of premium. So the best
edge in the system is worth about 1.6% of premium per trade.

That number only means something next to what a trade COSTS, and nothing in
Hokage knew what a trade costs:

  * `apply_trade` moves cash by price difference x quantity. No charges are
    deducted, anywhere. Every P&L figure in the system is GROSS.
  * The tax ledger stopped writing on 2026-08-17, recorded 0.0144% of traded
    value, and denominated Indian index options in USD.
  * The option chain archive stored `last_price` and no depth, so the spread
    was not recoverable from history either.

The spread is the dominant term and the only one that can be measured rather
than modelled. Crossing it once to get in and once to get out costs the full
bid-ask, so `(ask - bid) / mid` IS the round-trip cost in percent of premium,
before brokerage and statutory charges.

WHAT THIS IS
A live reading, now, of the ATM book for every underlying in the universe,
against the same expiry rule production trades (>= MIN_DTE days out). One
sample per contract. It is not a time series - the chain archive now records
depth so that a series can exist from today - and a spread measured at 09:15
is not the spread at 14:00.

AND THE REST OF THE COST
Brokerage and statutory charges are now included, from
`bots.execution.charges` - rates read off zerodha.com/charges rather than
recalled, because third-party calculators disagreed by a factor of 2.4 on the
largest line (options STT: 0.0625% on some pages, 0.15% on the broker's own).

Brokerage is FLAT at 20 rupees an order, so as a percentage it depends
entirely on position size. At this account's size it is the biggest single
line - bigger than the spread on every index. Trading smaller makes it dearer,
not cheaper.

STILL NOT THE WHOLE COST: theta over the holding period is not in these
figures. It is no longer unmeasurable, which is what this file used to say -
`tools/research/theta_lab.py` now measures it from day-over-day straddle
decay in the chain archive and puts it at 0.03-0.98% of premium over a
realised hold on the index. That is the same order as everything below, and it
is enough to move NIFTY and SENSEX from clearing their cost to UNDECIDED.

It is kept out of this lab's totals rather than folded in because the two
numbers have different standing: the spread and the charges below are read off
a live book and a published schedule, while the decay figure rests on six to
ten independent day-pairs and does not separate decay from implied volatility.
Adding an estimate to two measurements and printing one total would hide which
part is which. Read both labs.

MCX decay is NOT measured at all - the chain archive holds two
non-consecutive days for the commodities, so GOLDM, the widest funded margin
below, is the cell whose cost is least complete.

USAGE
    python tools/research/spread_lab.py
    python tools/research/spread_lab.py NIFTY GOLDM
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

#: The transfer measurement: 1.0 ATR of underlying move is worth this much of
#: the premium. Measured 2026-11-07, r=+0.871, n=15. An assumption carried
#: forward, labelled as one - not re-measured here.
PCT_PREMIUM_PER_ATR = 3.31

#: Minimum days to expiry, matching the production mandate: 0-DTE is roulette.
MIN_DTE = 2

UNIVERSE = ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOIL", "NATURALGAS",
            "GOLDM", "SILVERM"]

#: The best measured hold-out edge per cell, in ATR, from power_lab on
#: 2026-11-09. Carried here only to put the cost beside an edge; the audit
#: remains the source of truth.
BEST_EDGE_ATR = {
    "SENSEX": ("MacroBreakout", 0.364),
    "GOLDM": ("SessionShift", 0.496),
    "NIFTY": ("MacroBreakout", 0.321),
    "CRUDEOIL": ("TrendRider", 0.088),
    "NATURALGAS": ("RiderTrend", 0.066),
    "BANKNIFTY": ("MacroBreakout", 0.197),
    "SILVERM": ("SessionShift", 0.072),
}


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(str(ROOT / ".env"))
    from hokage.memory import option_archive as oa

    only = {a.upper() for a in sys.argv[1:]} or None

    print("=" * 94)
    print("  SPREAD LAB - the round-trip cost of one option, measured live")
    print("=" * 94)
    from bots.execution import charges as ch

    print("  spread% = (ask - bid)/mid, what crossing the book twice costs.")
    print(f"  fees%   = brokerage + STT + transaction + GST + stamp + SEBI,")
    print(f"            from {ch.RATES_SOURCE}, read {ch.RATES_READ_ON}.")
    print("  Theta over the hold is NOT included here: these totals are")
    print("  incomplete. It is measured by tools/research/theta_lab.py at")
    print("  0.03-0.98% of premium on the index, and not at all on MCX yet.")
    print()
    print(f"  Edge column: best measured hold-out edge for that underlying,")
    print(f"  converted at {PCT_PREMIUM_PER_ATR}% of premium per 1.0 ATR.")
    print()

    from integrations.brokers.kite_connection import KiteConnectionManager
    from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
    from integrations.brokers.secrets import SecretManager

    manager = KiteConnectionManager(SecretManager())
    status = manager.connect()
    if not getattr(status, "connected", bool(status)):
        print("  Broker session is not live - log in first, then re-run.")
        return 1
    provider = KiteMarketDataProvider(manager)
    kite = manager.get_kite_client()

    print(f"  {'asset':<11} {'contract':<24} {'mid':>9} {'spread%':>8} "
          f"{'fees%':>7} {'cost%':>7} {'edge%':>7}  verdict")
    print("  " + "-" * 92)

    rows = []
    for symbol in UNIVERSE:
        if only and symbol not in only:
            continue
        try:
            quoted = _quote_atm(provider, kite, symbol)
        except Exception as exc:
            print(f"  {symbol:<12} could not quote: {type(exc).__name__}: "
                  f"{str(exc)[:50]}")
            continue
        if not quoted:
            print(f"  {symbol:<12} no ATM contract with a two-sided book")
            continue

        for name, bid, ask, lot in quoted:
            if lot <= 1:
                # REFUSE, do not guess. A lot size of 1 on an option is the
                # known MCX dump defect, and dividing flat brokerage by a
                # turnover of one lot-unit invents a cost of several hundred
                # percent. A missing number must read as missing.
                print(f"  {symbol:<11} {name:<24} {'':>9} {'':>8} {'':>7} "
                      f"{'':>7} {'':>7}  LOT SIZE UNUSABLE ({lot:g})")
                continue
            if bid <= 0 or ask <= 0:
                print(f"  {symbol:<11} {name:<24} {'':>9} {'':>8} {'':>7} "
                      f"{'':>7} {'':>7}  NO TWO-SIDED BOOK")
                continue
            mid = (bid + ask) / 2.0
            spread_pct = (ask - bid) / mid * 100.0
            # Charges are a function of TURNOVER, not of the quoted premium:
            # brokerage is flat per order, so the same option costs a very
            # different percentage at a different lot size.
            fees_pct = ch.option_round_trip(mid * lot, symbol).pct_of_premium
            cost_pct = spread_pct + fees_pct
            module, edge_atr = BEST_EDGE_ATR.get(symbol, ("?", 0.0))
            edge_pct = edge_atr * PCT_PREMIUM_PER_ATR
            verdict = "EDGE > COST" if edge_pct > cost_pct else "COST EATS EDGE"
            print(f"  {symbol:<11} {name:<24} {mid:>9.2f} {spread_pct:>7.2f}% "
                  f"{fees_pct:>6.2f}% {cost_pct:>6.2f}% {edge_pct:>6.2f}%  {verdict}")
            rows.append({"symbol": symbol, "cost": cost_pct, "edge": edge_pct,
                         "spread": spread_pct, "fees": fees_pct,
                         "module": module})

    print()
    print("=" * 94)
    if not rows:
        print("  Nothing quoted with a two-sided book. Outside market hours the")
        print("  depth is empty, which is absence of data and not a zero spread.")
        return 0

    ok = [r for r in rows if r["edge"] > r["cost"]]
    print(f"  {len(ok)} of {len(rows)} quoted contracts carry an edge bigger than")
    print(f"  the FULL round trip - spread plus every published charge.")
    survivors = sorted({r["symbol"] for r in ok})
    if survivors:
        print(f"  Survive cost: {', '.join(survivors)}")
    dead = sorted({r["symbol"] for r in rows} - set(survivors))
    if dead:
        print(f"  Do not:       {', '.join(dead)}")
    print()
    worst = max(rows, key=lambda r: r["cost"])
    best = min(rows, key=lambda r: r["cost"])
    print(f"  cheapest round trip: {best['symbol']} at {best['cost']:.2f}% "
          f"(spread {best['spread']:.2f} + fees {best['fees']:.2f})")
    print(f"  dearest  round trip: {worst['symbol']} at {worst['cost']:.2f}% "
          f"(spread {worst['spread']:.2f} + fees {worst['fees']:.2f})")
    fees_bigger = [r for r in rows if r["fees"] > r["spread"]]
    print()
    print(f"  FEES EXCEED THE SPREAD on {len(fees_bigger)} of {len(rows)} "
          f"contracts. Brokerage is flat at 40 rupees")
    print(f"  a round trip, so the smaller the position the dearer it is in "
          f"percentage terms.")
    print()
    print("  WHAT TO DO WITH THIS")
    print("  A cell whose edge is below its spread cannot be fixed by more")
    print("  sessions - the sample would only prove the loss more precisely.")
    print("  The levers are a bigger edge per trade, a cheaper instrument, or")
    print("  a structure that is paid the spread instead of paying it.")
    return 0


def _quote_atm(provider, kite, symbol: str):
    """[(tradingsymbol, bid, ask, lot_size)] for the ATM call and put.

    THROUGH THE PRODUCTION RESOLVER, not the raw instrument dump. Kite's dump
    reports `lot_size=1` for MCX contracts - the defect that parked the
    commodity league - and the first version of this lab read it straight,
    which priced a NATURALGAS round trip at 320% of premium and a CRUDEOIL one
    at 15%. Both were fabricated: flat brokerage divided by a turnover of
    fifteen rupees instead of eighteen thousand.

    `resolve_option_contract` is what the entry path itself uses, so a lot
    size that is wrong here is wrong in production too, and that is a bug
    worth having in one place rather than two.
    """
    spot = provider.get_price(symbol)
    out = []
    for kind in ("CE", "PE"):
        contract = provider.resolve_option_contract(symbol, kind, spot)
        if not contract:
            continue
        lot = float(contract.get("lot_size") or 0)
        key = f"{contract['exchange']}:{contract['tradingsymbol']}"
        try:
            q = kite.quote([key]).get(key) or {}
        except Exception:
            continue
        depth = q.get("depth") or {}
        bid = ((depth.get("buy") or [{}])[0]).get("price") or 0.0
        ask = ((depth.get("sell") or [{}])[0]).get("price") or 0.0
        out.append((contract["tradingsymbol"], float(bid), float(ask), lot))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
