"""Seed lineup + capital constant for the MCX Commodity Arena.

Separate from bots/strategy/portfolio.py's index Dojo seeds so the two
leagues can never be confused: this module ONLY ever feeds a
StrategyPortfolioManager constructed with file_name="mcx_strategy_portfolio.json".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Commander-approved 2026-07-18. Real premium math (verified against MCX's
#: own contract specs, not guessed): one ATM commodity option costs roughly
#: 15,000-30,000 in premium. On a 50,000 chest (the index arena's size) that
#: is up to 60% of the chest in one trade with no room for even two open
#: positions; on 100,000 the same trade is 15-30% of the chest, one stopped
#: loss (-20% backstop) costs 3-6% of the chest — the same risk geometry the
#: index arena already runs, so the two leagues are comparable when picking
#: eventual champions.
MCX_STRATEGY_STARTING_CAPITAL = 100_000.0

#: Real MCX products only. GOLDM/SILVERM are MINI contracts (see
#: kite_market_data_provider._MCX_CONTRACT_MULTIPLIER) — the standard GOLD/
#: SILVER contracts cost 1.5-2.5 LAKH premium per lot, too large for this
#: chest size. CRUDEOIL/NATURALGAS trade their standard contracts (already
#: liquid, already fit the chest).
MCX_UNIVERSE = ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]

#: Correlation families for the commodity cluster gate (same discipline as
#: the index arena's 2026-07-17 fix: NIFTY/BANKNIFTY/SENSEX move ~90%
#: together and a same-direction cluster is one bet, not three). ENERGY and
#: PRECIOUS move on different drivers (crude/gas vs bullion), so they are
#: separate families, each independently capped.
MCX_FAMILY_ENERGY = {"CRUDEOIL", "NATURALGAS"}
MCX_FAMILY_PRECIOUS = {"GOLDM", "SILVERM"}


def generate_mcx_seed_portfolio() -> dict[str, Any]:
    """Baseline MCX Arena lineup — earned-only stats, zero inherited history.

    All four strategies start SHADOW_MODE: unlike the index Dojo (which had
    an already-measured champion from a comparable live system), none of
    these commodity modules have ANY prior live evidence. Promotion is earned
    entirely on this arena's own paper data.
    """
    now_str = datetime.now(timezone.utc).isoformat()

    def _seed(strategy_id: str, name: str, regimes: list[str], notes: str) -> dict[str, Any]:
        return {
            "strategy_id": strategy_id,
            "name": name,
            "version": "1.0.0",
            "created_at": now_str,
            "status": "SHADOW_MODE",
            "supported_assets": list(MCX_UNIVERSE),
            "supported_regimes": regimes,
            "domain_confidence": {"DEFAULT": 50.0},
            "expectancy": {"DEFAULT": 0.0},
            "win_rate": {"DEFAULT": 0.0},
            "trade_count": {"DEFAULT": 0},
            "capital": {"starting": MCX_STRATEGY_STARTING_CAPITAL, "realized_pnl": 0.0},
            "context_memory": {"regime_performance": {}, "volatility_performance": {}, "notes": notes},
            "history": [{"timestamp": now_str, "event": "MCX Arena launch: registered SHADOW_MODE with zeroed stats."}],
        }

    s1 = _seed(
        "strat-sessionshift-mcx-v1", "SessionShift", ["RISK-ON", "HIGH-VOLATILITY"],
        "Trades the 17:00-19:30 IST US-market hand-off, when crude/gold volume genuinely wakes up.",
    )
    s2 = _seed(
        "strat-eventrider-mcx-v1", "EventRider", ["HIGH-VOLATILITY"],
        "Rides sharp momentum thrusts in the 17:00-18:30 IST evening volatility window.",
    )
    s3 = _seed(
        "strat-rangefade-mcx-v1", "RangeFade", ["SIDEWAYS", "LOW-VOLATILITY"],
        "Fades VWAP overstretches during the quiet 09:30-16:30 IST pre-overlap hours.",
    )
    s4 = _seed(
        "strat-trendrider-mcx-v1", "TrendRider", ["RISK-ON", "BULL", "BEAR"],
        "Joins an already-confirmed evening trend (18:00-22:30 IST) with volume behind it.",
    )

    return {
        "strategies": {s["strategy_id"]: s for s in (s1, s2, s3, s4)},
        "updated_at": now_str,
    }
