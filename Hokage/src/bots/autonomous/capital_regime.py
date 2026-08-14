"""What can this account size ACTUALLY trade?

WHY THIS EXISTS
Hokage's paper chests are 1-2 lakh per strategy. The commander's real starting
capital is 20,000. Those are different games, and nothing in the system knew
the difference — a strategy tuned on the first is structurally unable to place
a single order in the second, and would have discovered that only at the router,
one rejected trade at a time.

Measured 2026-08-15 on live chain data, with the 33% premium cap production
already enforces:

    NATURALGAS   7,688/lot   cheapest in the entire universe
    NIFTY        8,141       SENSEX   9,401     CRUDEOIL  10,950
    BANKNIFTY   16,050       GOLDM   22,755     SILVERM   23,615

To hold the CHEAPEST of those at 33% of account you need 23,295. At 20,000
Hokage cannot legally place ANY option order in his universe. That is
arithmetic, not strategy, and no amount of tuning changes it.

This module is the part that says so out loud, at boot, before a single scan.

WHAT IS AND IS NOT ENFORCED HERE
Phase 0 is REPORTING ONLY. `regime_for` and `affordable_assets` are read by the
boot announcement and nothing else — no gate consults them, no order is refused
because of them. The `max_open_positions` and `min_t_stat` fields on a profile
describe INTENT for Phase 3 and are deliberately not wired to anything yet;
shipping the vocabulary before the enforcement is the same pattern that let
per-symbol scoping and the per-strategy stop table land safely.

Nothing here does I/O, logs, or touches the clock.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Account equity below this is a SEED account: too small for most of the
#: universe, and the regime where a single bad trade is unrecoverable.
SEED_CEILING = 75_000.0
#: Above this the whole current universe is comfortably affordable and several
#: concurrent positions become reasonable.
GROWTH_CEILING = 300_000.0

SEED = "SEED"
GROWTH = "GROWTH"
SCALE = "SCALE"


@dataclass(frozen=True)
class RegimeProfile:
    """What a regime means. Only `name` and `summary` are used in Phase 0."""

    name: str
    #: PHASE 3 INTENT, NOT ENFORCED. How many positions may be open at once.
    max_open_positions: int
    #: PHASE 3 INTENT, NOT ENFORCED. Minimum measured t-stat a module needs to
    #: compete in this regime. A small account cannot afford a marginal edge:
    #: it has fewer trades to average over and no cushion to survive a run of
    #: losses, so it should take only the very best signals.
    min_t_stat: float
    summary: str


_PROFILES: dict[str, RegimeProfile] = {
    SEED: RegimeProfile(
        name=SEED,
        max_open_positions=1,
        min_t_stat=2.5,
        summary=(
            "Capital preservation. One position at a time, only the single "
            "strongest signal available, and only on assets whose lot genuinely "
            "fits. A loss here is not a data point, it is a setback."
        ),
    ),
    GROWTH: RegimeProfile(
        name=GROWTH,
        max_open_positions=2,
        min_t_stat=2.0,
        summary=(
            "The whole index universe is affordable and the metals are coming "
            "into range. Two concurrent positions, standard measured bar."
        ),
    ),
    SCALE: RegimeProfile(
        name=SCALE,
        max_open_positions=4,
        min_t_stat=2.0,
        summary=(
            "Every asset affordable with room to spare. Multiple concurrent "
            "positions across uncorrelated families; position size, not signal "
            "count, becomes the limiting factor."
        ),
    ),
}


def regime_for(equity: float) -> str:
    """Which capital regime this account size sits in."""
    if equity < SEED_CEILING:
        return SEED
    if equity < GROWTH_CEILING:
        return GROWTH
    return SCALE


def profile_for(equity: float) -> RegimeProfile:
    return _PROFILES[regime_for(equity)]


def minimum_account_for(lot_cost: float, cap_fraction: float) -> float:
    """Smallest account that can hold one lot without breaching the cap.

    Returns infinity for a non-positive cap rather than dividing by zero — a
    cap of 0 means nothing is ever affordable, which is a real answer.
    """
    if cap_fraction <= 0:
        return float("inf")
    return lot_cost / cap_fraction


def affordable_assets(
    chest: float,
    lot_costs: dict[str, float],
    cap_fraction: float,
) -> tuple[list[str], list[str]]:
    """Split a universe into what this chest can and cannot hold.

    `lot_costs` maps symbol -> rupee cost of one lot. Only symbols actually
    present are judged: an asset we could not PRICE is not the same as an
    asset we cannot AFFORD, and must never be reported as unaffordable.
    Callers pass in only what they successfully quoted.
    """
    ceiling = chest * cap_fraction
    affordable = sorted(s for s, cost in lot_costs.items() if cost <= ceiling)
    unaffordable = sorted(s for s, cost in lot_costs.items() if cost > ceiling)
    return affordable, unaffordable
