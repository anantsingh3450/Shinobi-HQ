"""Two definitions of the war chest, in the function that promised one.

2026-11-12, looking for why the lifetime record is negative. `_chest_of`
computed `starting + capital.realized_pnl` and its docstring said:

    One definition, shared by the chest audit and the coverage audit. They
    disagreeing about what "can afford to trade" means is how an asset ends
    up reported as covered by a strategy that cannot fill.

The stored key is GROSS on purpose. `StrategyPortfolio.book_fill` says so in
as many words - "`realized_pnl` STAYS GROSS ... The broker's cut goes in its
own key" - and `get_capital_report` subtracts `charges_paid` to report a net
figure, after a 2026-11-10 fix whose own docstring records that while
`available` was gross "every chest believed it held more than the account did
and sized the next order on the difference".

So there were two definitions, disagreeing by exactly the charges paid, in the
function that promised there was one.

THE GAP IS 85 RUPEES TODAY, and that is the argument for fixing it now.
Fill-time charge accounting began 2026-11-09, so one booked trade carries a
charge. Run the same arithmetic over the 126 closed positions on record and it
is 10,471 - 3.39x the whole gross profit. The leak did not stay small; it
started small.
"""
from __future__ import annotations

import inspect
import textwrap

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


def _strat(starting=100_000.0, gross=0.0, charges=None, uncharged=None):
    capital = {"starting": starting, "realized_pnl": gross}
    if charges is not None:
        capital["charges_paid"] = charges
    if uncharged is not None:
        capital["trades_without_charges"] = uncharged
    return {"strategy_id": "s1", "capital": capital}


# =================================================== the arithmetic
def test_the_brokers_cut_comes_out_of_the_chest():
    """THE DEFECT. sessionshift-mcx on 2026-11-12: 100,000 seed, +14,690
    gross, 85 charged. The chest is 114,605, not 114,690."""
    chest = Bot._chest_of(_strat(100_000.0, 14_690.0, 85.0))
    assert chest == pytest.approx(114_605.0)


def test_a_book_with_no_charges_yet_is_unchanged():
    """Every pre-2026-11-09 book has no `charges_paid` key at all. Those
    chests must read exactly as they did, or this fix silently rewrites
    history it has no information about."""
    assert Bot._chest_of(_strat(100_000.0, 25_900.0)) == pytest.approx(125_900.0)
    assert Bot._chest_of(_strat(200_000.0, -17_502.0)) == pytest.approx(182_498.0)


def test_losses_and_charges_both_shrink_the_chest():
    chest = Bot._chest_of(_strat(100_000.0, -18_790.0, 1_200.0))
    assert chest == pytest.approx(80_010.0)


def test_charges_can_push_a_thin_chest_below_its_seed():
    """A strategy that broke even gross has still paid the broker. Reporting
    it at seed is how a chest that cannot fill looks solvent."""
    assert Bot._chest_of(_strat(100_000.0, 0.0, 2_791.0)) == pytest.approx(97_209.0)


def test_the_gap_compounds_to_the_measured_lifetime_figure():
    """Not a round number pulled from nowhere: 10,471 is what the schedule
    comes to across the 126 closed positions, and 3.39x the gross profit of
    3,092. A chest blind to that is blind to the dominant term."""
    gross_only = Bot._chest_of(_strat(100_000.0, 3_092.0))
    net = Bot._chest_of(_strat(100_000.0, 3_092.0, 10_471.0))
    assert gross_only - net == pytest.approx(10_471.0)
    assert net < 100_000.0, "the real book is below its seed, and must say so"


# ============================================= it must not crash a scan
@pytest.mark.parametrize("capital", [
    {}, None,
    {"starting": "oops", "realized_pnl": 0.0},
    {"starting": 1.0, "realized_pnl": 0.0, "charges_paid": "x"},
])
def test_a_malformed_book_returns_zero_rather_than_raising(capital):
    """This is called from the coverage audit on every boot. A raise here
    takes out the audit that reports parked and orphaned assets."""
    assert Bot._chest_of({"capital": capital}) == 0.0


def test_a_null_value_degrades_to_the_rest_of_the_book():
    """A None in one key is not a reason to throw the whole chest away.
    `or 0.0` reads it as "nothing booked there yet", which is what a fresh
    book looks like, so the seed still counts."""
    assert Bot._chest_of(
        {"capital": {"starting": 1.0, "realized_pnl": None,
                     "charges_paid": None}}) == pytest.approx(1.0)


def test_a_missing_capital_block_is_zero_not_a_free_chest():
    """Falling through to a full seed is the `_strategy_available_capital`
    trap: an unresolvable strategy handed a fresh chest."""
    assert Bot._chest_of({}) == 0.0


# ======================================== the two definitions now agree
def test_it_matches_what_the_capital_report_calls_realized():
    """`get_capital_report` computes `gross - charges_paid` and calls that
    `realized_pnl`. The chest must be the same arithmetic, or the promise of
    one definition is false again."""
    from bots.strategy.portfolio import StrategyPortfolioManager

    src = textwrap.dedent(
        inspect.getsource(StrategyPortfolioManager.get_capital_report))
    assert 'realized = round(gross - charges, 2)' in src, (
        "the report's net definition moved; re-aim this rail")

    chest_src = textwrap.dedent(inspect.getsource(Bot._chest_of))
    assert "charges_paid" in chest_src
    assert "- charges" in chest_src


def test_uncharged_fills_are_not_treated_as_free():
    """`trades_without_charges` counts fills with NO charge accounting. Their
    cost is unknown, not zero - the chest uses the best figure it has and the
    capital report carries the count so the gap stays visible."""
    chest_src = textwrap.dedent(inspect.getsource(Bot._chest_of))
    assert "trades_without_charges" in chest_src
    # and a book carrying that counter still returns the charged arithmetic
    chest = Bot._chest_of(_strat(100_000.0, 1_000.0, 85.0, uncharged=12))
    assert chest == pytest.approx(100_915.0)
