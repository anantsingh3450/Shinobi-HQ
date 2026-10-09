"""Can each strategy actually AFFORD the assets it is scoped to?

THE FAILURE CLASS THIS COVERS
A strategy that cannot fill does not fail loudly — it competes, wins the
auction, and converts the win into a stand-aside, denying the asset to whatever
would have traded it. 2026-08-12 produced one instance through MISSING capital
(SessionShift, chest -1,280, 16 auction wins and zero fills). The other route to
the same place is chest SIZE: a chest large enough to exist but too small to
clear MAX_PREMIUM_CHEST_FRACTION against a real ATM premium.

`audit_strategy_chests` on the bot catches the first at boot. This catches the
second, against live chain data, because it needs a broker session and belongs
in a tool rather than the trading loop.

Prints one line per (strategy, asset) with the real ATM premium, the cap, and
whether one lot fits. Never prints a credential.

USAGE
    python tools/research/affordability_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hokage.memory.resolver import brain_root

#: The active brain root. NOT `BRAIN` — that ignored
#: HOKAGE_BRAIN_ROOT, so moving the brain gave Hokage one brain and this tool
#: another, silently. See hokage.memory.resolver.brain_root.
BRAIN = brain_root()


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION
    from integrations.brokers.kite_connection import KiteConnectionManager
    from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
    from integrations.brokers.secrets import SecretManager

    manager = KiteConnectionManager(SecretManager())
    status = manager.connect()
    if not getattr(status, "connected", bool(status)):
        print("Broker session is not live — log in first, then re-run.")
        return 1
    provider = KiteMarketDataProvider(manager)

    base = BRAIN / "portfolio"
    books = [
        ("Index Dojo", base / "strategy_portfolio.json"),
        ("MCX Arena", base / "mcx_strategy_portfolio.json"),
    ]

    print(f"premium cap = {MAX_PREMIUM_CHEST_FRACTION:.0%} of chest\n")
    problems = 0
    for league, path in books:
        if not path.exists():
            continue
        book = json.loads(path.read_text(encoding="utf-8-sig"))
        print(f"--- {league} ---")
        for strat in (book.get("strategies") or {}).values():
            if strat.get("status") == "ARCHIVED":
                continue
            cap = strat.get("capital") or {}
            chest = float(cap.get("starting", 0) or 0) + float(cap.get("realized_pnl", 0) or 0)
            ceiling = chest * MAX_PREMIUM_CHEST_FRACTION
            name = strat.get("name", "?")
            for symbol in strat.get("supported_assets") or []:
                try:
                    spot = provider.get_price(symbol)
                    contract = provider.resolve_option_contract(symbol, "CE", spot)
                    if not contract:
                        print(f"  {name:14s} {symbol:11s} no CE contract resolved")
                        continue
                    lot = float(contract["lot_size"])
                    premium = float(provider.get_quote(contract["tradingsymbol"]).price)
                except Exception as exc:
                    print(f"  {name:14s} {symbol:11s} quote unavailable ({exc})")
                    continue
                per_lot = premium * lot
                pct = (per_lot / chest * 100.0) if chest else float("inf")
                fits = per_lot <= ceiling
                if not fits:
                    problems += 1
                print(f"  {name:14s} {symbol:11s} 1 lot = {per_lot:>10,.0f} "
                      f"({pct:5.1f}% of {chest:>9,.0f} chest)  "
                      f"{'OK' if fits else 'CANNOT TRADE — over the cap'}")
        print()

    if problems:
        print(f"{problems} (strategy, asset) pair(s) cannot fill a single lot. Either the")
        print("chest is too small for that instrument or the asset should be de-scoped;")
        print("leaving it scoped means the strategy wins auctions there and never fills.")
    else:
        print("Every scoped (strategy, asset) pair can fill at least one lot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
