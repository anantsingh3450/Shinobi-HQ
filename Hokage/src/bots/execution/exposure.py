"""How much premium may be open across the WHOLE account at one moment.

APPROVED BY THE COMMANDER 2026-11-09: "go with the p90 row".

WHY A PORTFOLIO-LEVEL RAIL AT ALL
Every risk check in Hokage was per-strategy. `MAX_PREMIUM_CHEST_FRACTION` caps
one position at a third of one chest, and that is a good rail - but with seven
live strategies each holding a 1,00,000 chest, nothing stopped the account as
a whole from carrying far more premium than it owns. Four concurrent assets at
33% of a chest each is 1,32,000 of premium on a 1,00,000 account.

`max_portfolio_exposure_pct` already existed and looked like this rail. It is
computed in `capital_preservation` and `personality_engine`, written to a
cache file, shown in the briefing - and READ BY NOTHING THAT CAN BLOCK A
TRADE. Its sibling `max_allocation_pct` is enforced; this one never was. A
number that is displayed but not obeyed is the same shape as a health score of
100 on a dead process, so this module exists rather than a fix to that one:
the rail belongs at the sizing seam, not in an advisory cache.

HOW THE NUMBER WAS CHOSEN
Not as a fraction of capital. From what is actually lost when a trade goes
wrong, measured over 74 real losing trades (phantoms excluded) on 2026-11-09:

    median 7.76%    p75 12.62%    p90 16.80%    worst ever 28.36%

The go-live mandate allows an 8% drawdown. If everything open stops out
together, total premium times the loss rate is the drawdown, so

    budget = capital x drawdown_allowed / loss_per_stop_out

The three readings differ by a factor of 3.7 and all are defensible, which is
why the commander chose between them rather than being handed one. He chose
the p90: survive a bad-but-not-unprecedented day, rather than price in the
worst single loss ever recorded happening on every open position at once.

IT DOES NOT RECOMPUTE ITSELF, AND THAT IS DELIBERATE
Deriving this from the live loss distribution every run would be more
"adaptive" and would be wrong. If measured losses improved, the budget would
GROW - the system would raise its own risk ceiling on a quiet month, with no
one deciding anything. That is exactly the self-evolution that was closed on
2026-08-26 and again in the promotion pipeline today. The inputs below are
frozen with the date they were measured; `capital_lab` reports when the live
distribution has drifted away from them, as something to approve rather than
something to apply.

WHAT IT DOES NOT COVER
Realised losses are not in the denominator: this bounds what is at risk NOW,
not cumulative drawdown over a losing run. It also assumes a simultaneous
stop-out, which is the conservative direction for correlated positions and the
honest one for an index book where NIFTY and SENSEX move together.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The real account, as stated by the commander on 2026-11-09. One pool, not a
#: chest each - the per-strategy chests in the portfolio books are views of
#: this same money, which is why they must not be added together.
ACCOUNT_CAPITAL = 100_000.0

#: The drawdown the go-live gate allows (`tools/research/live_readiness.py`).
#: Duplicated as a number here rather than imported because `src` must not
#: depend on `tools`; a test asserts the two agree.
DRAWDOWN_BUDGET_PCT = 8.0

#: What one stop-out costs, as a percentage of premium. The p90 of 74 measured
#: losing trades. NOT a guess, and NOT re-derived at runtime.
STOP_OUT_LOSS_PCT = 16.80
STOP_OUT_LOSS_BASIS = "p90 of 74 real losing trades, measured 2026-11-09"

#: Total premium that may be open across the account at any instant.
#: Written as the arithmetic rather than as a literal, so the three inputs
#: above stay the only place a risk decision lives.
MAX_TOTAL_PREMIUM = round(
    ACCOUNT_CAPITAL * (DRAWDOWN_BUDGET_PCT / 100.0)
    / (STOP_OUT_LOSS_PCT / 100.0), 2)


@dataclass(frozen=True)
class ExposureVerdict:
    """Whether a new position fits, and the room that remains."""

    allowed: bool
    remaining: float
    open_premium: float
    reason: str


def remaining_budget(open_premium: float) -> float:
    """Premium still available, never negative."""
    return max(0.0, MAX_TOTAL_PREMIUM - max(0.0, float(open_premium)))


def check(open_premium: float, new_premium: float) -> ExposureVerdict:
    """Can `new_premium` of premium be added on top of what is already open?

    A position exactly filling the budget is allowed; one exceeding it is not.
    """
    open_premium = max(0.0, float(open_premium))
    new_premium = max(0.0, float(new_premium))
    room = remaining_budget(open_premium)
    if new_premium <= room:
        return ExposureVerdict(
            True, room, open_premium,
            f"fits: Rs {new_premium:,.0f} of Rs {room:,.0f} remaining "
            f"(Rs {open_premium:,.0f} already open of a Rs "
            f"{MAX_TOTAL_PREMIUM:,.0f} budget)")
    return ExposureVerdict(
        False, room, open_premium,
        f"account exposure: Rs {open_premium:,.0f} already open leaves "
        f"Rs {room:,.0f} of the Rs {MAX_TOTAL_PREMIUM:,.0f} total-premium "
        f"budget, and this needs Rs {new_premium:,.0f}. Budget is "
        f"{DRAWDOWN_BUDGET_PCT:.0f}% of Rs {ACCOUNT_CAPITAL:,.0f} divided by "
        f"a {STOP_OUT_LOSS_PCT:.2f}% stop-out ({STOP_OUT_LOSS_BASIS})")


def describe() -> str:
    """One block for a boot log or an audit header."""
    return (
        f"account exposure rail: Rs {MAX_TOTAL_PREMIUM:,.0f} of premium may be "
        f"open at once\n"
        f"    = {DRAWDOWN_BUDGET_PCT:.0f}% drawdown of Rs "
        f"{ACCOUNT_CAPITAL:,.0f} / a {STOP_OUT_LOSS_PCT:.2f}% stop-out\n"
        f"    basis: {STOP_OUT_LOSS_BASIS}; approved by the commander "
        f"2026-11-09 (the p90 row)")
