"""What can a REAL 20,000 account actually trade?

Hokage's paper chests are 1-2 lakh per strategy. The commander's real starting
capital is 20,000. Those are different games, and a strategy tuned on the first
can be structurally unable to place a single order in the second.

This prices every asset in the universe against a range of real account sizes,
using live chain data and the SAME premium cap production enforces
(MAX_PREMIUM_CHEST_FRACTION). It answers one question per row: at this account
size, can Hokage buy one lot of this without breaking its own risk rule?

USAGE
    python tools/research/seed_capital_check.py
    python tools/research/seed_capital_check.py 20000 50000
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

#: Account sizes to price, in rupees.
DEFAULT_SIZES = (20_000.0, 50_000.0, 100_000.0, 200_000.0, 500_000.0)

UNIVERSE = ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION
    from integrations.brokers.kite_connection import KiteConnectionManager
    from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
    from integrations.brokers.secrets import SecretManager

    sizes = [float(a) for a in sys.argv[1:]] or list(DEFAULT_SIZES)

    manager = KiteConnectionManager(SecretManager())
    status = manager.connect()
    if not getattr(status, "connected", bool(status)):
        print("Broker session is not live — log in first, then re-run.")
        return 1
    provider = KiteMarketDataProvider(manager)

    print(f"premium cap = {MAX_PREMIUM_CHEST_FRACTION:.0%} of the account\n")
    header = f"  {'asset':11s} {'1 lot premium':>14s}  " + "".join(f"{int(s):>9,d}" for s in sizes)
    print(header)
    print("  " + "-" * (len(header) - 2))

    costs: dict[str, float] = {}
    for symbol in UNIVERSE:
        try:
            spot = provider.get_price(symbol)
            contract = provider.resolve_option_contract(symbol, "CE", spot)
            if not contract:
                print(f"  {symbol:11s} {'no contract':>14s}")
                continue
            lot = float(contract["lot_size"])
            premium = float(provider.get_quote(contract["tradingsymbol"]).price)
        except Exception as exc:
            print(f"  {symbol:11s} {'unavailable':>14s}   ({exc})")
            continue
        per_lot = premium * lot
        costs[symbol] = per_lot
        cells = ""
        for size in sizes:
            cells += f"{('OK' if per_lot <= size * MAX_PREMIUM_CHEST_FRACTION else 'no'):>9s}"
        print(f"  {symbol:11s} {per_lot:>14,.0f}  {cells}")

    if costs:
        cheapest = min(costs.items(), key=lambda kv: kv[1])
        need = cheapest[1] / MAX_PREMIUM_CHEST_FRACTION
        print(f"\n  Cheapest tradable lot: {cheapest[0]} at Rs {cheapest[1]:,.0f}.")
        print(f"  Minimum account that clears the {MAX_PREMIUM_CHEST_FRACTION:.0%} cap on it: "
              f"Rs {need:,.0f}.")
        print(f"  Below that, Hokage cannot legally place ANY option order in this universe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
