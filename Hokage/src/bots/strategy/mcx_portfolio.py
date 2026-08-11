"""Seed lineup + capital constant for the MCX Commodity Arena.

Separate from bots/strategy/portfolio.py's index Dojo seeds so the two
leagues can never be confused: this module ONLY ever feeds a
StrategyPortfolioManager constructed with file_name="mcx_strategy_portfolio.json".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Commander-approved 2026-07-31: TWO strategies of 200,000, replacing four of
#: 100,000. The original figure assumed "one ATM commodity option costs roughly
#: 15,000-30,000 in premium". That assumption did not survive contact with the
#: chain. MCX lists only MONTHLY option expiries, so the nearest contract above
#: the 2-DTE floor is always weeks out and carries a month of time value.
#: Measured 2026-07-31: CRUDEOIL 18 DTE = 49,430/lot, SILVERM 25 DTE = 38,400,
#: GOLDM 29 DTE = 35,060, NATURALGAS 25 DTE = 15,250. Against a 100,000 chest
#: and the 33% premium cap (MAX_PREMIUM_CHEST_FRACTION), three of the four
#: commodities were unaffordable and the arena was four strategies competing
#: over ONE asset.
#:
#: The cap is not the problem — a 49,430 option on a 100,000 chest genuinely is
#: half the capital in one trade. The mismatch was capital per strategy. Rather
#: than inflate synthetic cash to fit the instrument (paper exists to learn what
#: the REAL account can afford), the same 400,000 now backs half as many
#: strategies. At 200,000 every MCX commodity clears the cap with room to spare.
MCX_STRATEGY_STARTING_CAPITAL = 200_000.0

#: Real MCX products only. GOLDM/SILVERM are MINI contracts (see
#: kite_market_data_provider._MCX_CONTRACT_MULTIPLIER) — the standard GOLD/
#: SILVER contracts cost 1.5-2.5 LAKH premium per lot, too large for this
#: chest size. CRUDEOIL/NATURALGAS trade their standard contracts (already
#: liquid, already fit the chest).
MCX_UNIVERSE = ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]

#: CRUDEOIL IS DELIBERATELY DARK (commander decision, 2026-08-12).
#:
#: It stays in the universe — quotes, contract specs and routing all remain
#: correct — but NO strategy is scoped to it, so the league never bets on it.
#: This is a decision, not an oversight, and it must not be "fixed" by scoping
#: some existing module onto crude.
#:
#: TrendRider was its only competitor and measured NEGATIVE there (60m n=724,
#: edge -0.283, t=-1.64), so it was archived. Nothing else has measured edge on
#: crude: signal_lab found mean-reversion strong on it (60m t=+3.90, 120m
#: t=+5.13), but that is a SIGNAL with no EntryModule implementing it, and the
#: entry module is what actually chooses CALL vs PUT.
#:
#: To light crude back up, the order is: build a mean-reversion EntryModule,
#: measure it with tools/research/entry_module_lab.py, and only then scope it.
#: Trading an asset whose chooser has never been measured is precisely what
#: produced 25 trades at 33% direction accuracy for -17,520.

#: Correlation families for the commodity cluster gate (same discipline as
#: the index arena's 2026-07-17 fix: NIFTY/BANKNIFTY/SENSEX move ~90%
#: together and a same-direction cluster is one bet, not three). ENERGY and
#: PRECIOUS move on different drivers (crude/gas vs bullion), so they are
#: separate families, each independently capped.
MCX_FAMILY_ENERGY = {"CRUDEOIL", "NATURALGAS"}
MCX_FAMILY_PRECIOUS = {"GOLDM", "SILVERM"}


def generate_mcx_seed_portfolio() -> dict[str, Any]:
    """Baseline MCX Arena lineup — earned-only stats, zero inherited history.

    Both strategies start SHADOW_MODE: unlike the index Dojo (which had an
    already-measured champion from a comparable live system), neither commodity
    module has ANY prior live evidence. Promotion is earned entirely on this
    arena's own paper data.

    TWO strategies, not four (2026-07-31). The pair was chosen for session
    coverage and opposing philosophy, NOT on P&L — the only day either had run
    was the day the host slept from 10:28 to 18:03, so the trade counts were
    meaningless evidence:

      RangeFade   09:30-16:30 IST, fades a VWAP overstretch  (mean reversion)
      TrendRider  18:00-22:30 IST, joins a confirmed trend   (momentum)

    Between them they cover thirteen hours of the MCX session without overlap
    and test genuinely opposite ideas, which is what makes a tournament worth
    running. The retired pair — SessionShift (17:00-19:30) and EventRider
    (17:00-18:30) — both crowded the same evening slot as each other and as
    TrendRider, so dropping them costs coverage nothing. Their entry modules
    remain in components/mcx_entries.py and can be re-registered whenever the
    arena has the capital to field them.
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
        "strat-rangefade-mcx-v1", "RangeFade", ["SIDEWAYS", "LOW-VOLATILITY"],
        "Fades VWAP overstretches during the quiet 09:30-16:30 IST pre-overlap hours.",
    )
    s2 = _seed(
        "strat-trendrider-mcx-v1", "TrendRider", ["RISK-ON", "BULL", "BEAR"],
        "Joins an already-confirmed evening trend (18:00-22:30 IST) with volume behind it.",
    )

    return {
        "strategies": {s["strategy_id"]: s for s in (s1, s2)},
        "updated_at": now_str,
    }
