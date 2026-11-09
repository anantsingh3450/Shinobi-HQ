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

WHAT IT IS NOT
Not the whole cost. Brokerage and statutory charges are real and are NOT
included here, deliberately: the only charges model in this repo is a mock
emitting USD at rates an order of magnitude below Indian option rates, and
quoting a wrong number next to a measured one is how a measurement gets
discredited. Those rates have to come from the broker's published schedule,
verified, not recalled.

So read this as a FLOOR on cost, and compare it against edge honestly.

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
    print("  (ask - bid) / mid is what crossing the book twice costs, as a")
    print("  percent of premium. Brokerage and statutory charges are NOT")
    print("  included - see the header. This is a FLOOR on cost.")
    print()
    print(f"  Edge column: best measured hold-out edge for that underlying,")
    print(f"  converted at {PCT_PREMIUM_PER_ATR}% of premium per 1.0 ATR.")
    print()

    try:
        kite = oa._kite() if hasattr(oa, "_kite") else None
    except Exception:
        kite = None
    if kite is None:
        from integrations.brokers.secrets import SecretManager
        from kiteconnect import KiteConnect

        secrets = SecretManager()
        kite = KiteConnect(api_key=secrets.get_secret("api_key", broker="zerodha"))
        kite.set_access_token(secrets.get_secret("access_token", broker="zerodha"))

    print(f"  {'asset':<12} {'contract':<26} {'bid':>9} {'ask':>9} "
          f"{'mid':>9} {'cost%':>7} {'edge%':>7}  verdict")
    print("  " + "-" * 90)

    rows = []
    for symbol in UNIVERSE:
        if only and symbol not in only:
            continue
        try:
            quoted = _quote_atm(kite, oa, symbol)
        except Exception as exc:
            print(f"  {symbol:<12} could not quote: {type(exc).__name__}: "
                  f"{str(exc)[:50]}")
            continue
        if not quoted:
            print(f"  {symbol:<12} no ATM contract with a two-sided book")
            continue

        for name, bid, ask in quoted:
            if bid <= 0 or ask <= 0:
                print(f"  {symbol:<12} {name:<26} {bid:>9.2f} {ask:>9.2f} "
                      f"{'':>9} {'':>7} {'':>7}  NO TWO-SIDED BOOK")
                continue
            mid = (bid + ask) / 2.0
            cost_pct = (ask - bid) / mid * 100.0
            module, edge_atr = BEST_EDGE_ATR.get(symbol, ("?", 0.0))
            edge_pct = edge_atr * PCT_PREMIUM_PER_ATR
            verdict = "EDGE > COST" if edge_pct > cost_pct else "COST EATS EDGE"
            print(f"  {symbol:<12} {name:<26} {bid:>9.2f} {ask:>9.2f} "
                  f"{mid:>9.2f} {cost_pct:>6.2f}% {edge_pct:>6.2f}%  {verdict}")
            rows.append({"symbol": symbol, "cost": cost_pct, "edge": edge_pct,
                         "module": module})

    print()
    print("=" * 94)
    if not rows:
        print("  Nothing quoted with a two-sided book. Outside market hours the")
        print("  depth is empty, which is absence of data and not a zero spread.")
        return 0

    ok = [r for r in rows if r["edge"] > r["cost"]]
    print(f"  {len(ok)} of {len(rows)} quoted contracts have an edge bigger than")
    print(f"  the spread alone, before brokerage and statutory charges.")
    print()
    worst = max(rows, key=lambda r: r["cost"])
    best = min(rows, key=lambda r: r["cost"])
    print(f"  cheapest book: {best['symbol']} at {best['cost']:.2f}%")
    print(f"  dearest  book: {worst['symbol']} at {worst['cost']:.2f}%")
    print()
    print("  WHAT TO DO WITH THIS")
    print("  A cell whose edge is below its spread cannot be fixed by more")
    print("  sessions - the sample would only prove the loss more precisely.")
    print("  The levers are a bigger edge per trade, a cheaper instrument, or")
    print("  a structure that is paid the spread instead of paying it.")
    return 0


def _quote_atm(kite, oa, symbol: str):
    """[(tradingsymbol, bid, ask)] for the ATM call and put."""
    spot_key = oa.SPOT_KEYS[symbol] if hasattr(oa, "SPOT_KEYS") else None
    contracts = oa.atm_contracts(kite, symbol, MIN_DTE) \
        if hasattr(oa, "atm_contracts") else None
    if contracts is None:
        return _quote_atm_fallback(kite, symbol)
    keys = [c["key"] for c in contracts]
    quotes = kite.quote(keys)
    out = []
    for c in contracts:
        q = quotes.get(c["key"]) or {}
        depth = q.get("depth") or {}
        bid = ((depth.get("buy") or [{}])[0]).get("price") or 0.0
        ask = ((depth.get("sell") or [{}])[0]).get("price") or 0.0
        out.append((c["key"].split(":")[-1], float(bid), float(ask)))
    return out


def _quote_atm_fallback(kite, symbol: str):
    """Resolve the ATM pair straight from the instrument dump.

    Deliberately separate from option_archive's own resolver: this tool must
    work even if that module's helpers change shape, and a cost measurement
    that silently stops running is worse than one that is obviously absent.
    """
    import datetime as dt

    from hokage.memory import option_archive as oa

    exchange = "MCX" if symbol in ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM") \
        else ("BFO" if symbol == "SENSEX" else "NFO")
    spot_key = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
                "SENSEX": "BSE:SENSEX"}.get(symbol)
    if spot_key:
        spot = kite.ltp(spot_key)[spot_key]["last_price"]
    else:
        fut = [i for i in kite.instruments("MCX")
               if i["name"] == symbol and i["instrument_type"] == "FUT"]
        if not fut:
            return []
        fut.sort(key=lambda i: i["expiry"])
        key = f"MCX:{fut[0]['tradingsymbol']}"
        spot = kite.ltp(key)[key]["last_price"]

    today = dt.date.today()
    dump = [i for i in kite.instruments(exchange)
            if i["name"] == symbol and i["instrument_type"] in ("CE", "PE")
            and i["expiry"] and (i["expiry"] - today).days >= MIN_DTE]
    if not dump:
        return []
    nearest_expiry = min(i["expiry"] for i in dump)
    chain = [i for i in dump if i["expiry"] == nearest_expiry]
    strike = min({i["strike"] for i in chain}, key=lambda s: abs(s - spot))

    out = []
    for kind in ("CE", "PE"):
        match = [i for i in chain
                 if i["strike"] == strike and i["instrument_type"] == kind]
        if not match:
            continue
        key = f"{exchange}:{match[0]['tradingsymbol']}"
        q = kite.quote([key]).get(key) or {}
        depth = q.get("depth") or {}
        bid = ((depth.get("buy") or [{}])[0]).get("price") or 0.0
        ask = ((depth.get("sell") or [{}])[0]).get("price") or 0.0
        out.append((match[0]["tradingsymbol"], float(bid), float(ask)))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
