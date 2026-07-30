"""No single option position may swallow its strategy's war chest.

Before this cap the chest ceiling WAS the chest, so one position could consume
100% of a strategy's capital and only MAX_LOTS_PER_ORDER stood in the way.
Measured from live fills on 2026-07-30, one lot cost:

    CRUDEOIL   50.2% of its chest      SENSEX      18.9%
    BANKNIFTY  50.0%                   NATURALGAS  16.7%
    SILVERM    41.8%                   NIFTY       11.9%
    GOLDM      34.8%

Both leagues were running the same concentration — this was never an MCX quirk.
The cap is on PREMIUM, so an instrument that grows too rich for its chest simply
stops being affordable and returns when it cheapens; no banned list needed.
"""
from __future__ import annotations

import pytest

from bots.execution.options_router import (
    MAX_PREMIUM_CHEST_FRACTION,
    MAX_PREMIUM_CASH_FRACTION,
)


def _lots(premium_per_lot: float, chest: float, account_cash: float) -> int:
    """The production ceiling calculation, isolated."""
    budget = min(account_cash * MAX_PREMIUM_CASH_FRACTION, chest * MAX_PREMIUM_CHEST_FRACTION)
    return int(budget // premium_per_lot)


def test_cap_is_a_third_of_the_chest():
    assert MAX_PREMIUM_CHEST_FRACTION == 0.33


@pytest.mark.parametrize(
    "name,premium_per_lot,chest",
    [
        ("CRUDEOIL", 50230.0, 100000.0),   # 50.2%
        ("BANKNIFTY", 24978.0, 50000.0),   # 50.0%
        ("SILVERM", 41750.0, 100000.0),    # 41.8%
        ("GOLDM", 34850.0, 100000.0),      # 34.8%
    ],
)
def test_positions_over_a_third_of_the_chest_are_refused(name, premium_per_lot, chest):
    assert _lots(premium_per_lot, chest, account_cash=400000.0) == 0


@pytest.mark.parametrize(
    "name,premium_per_lot,chest",
    [
        ("NIFTY", 5960.0, 50000.0),        # 11.9%
        ("SENSEX", 9456.0, 50000.0),       # 18.9%
        ("NATURALGAS", 16688.0, 100000.0), # 16.7%
    ],
)
def test_affordable_positions_still_trade(name, premium_per_lot, chest):
    assert _lots(premium_per_lot, chest, account_cash=400000.0) >= 1


def test_the_cap_binds_before_the_account_cash_ceiling():
    """MCX account cash is 4L, so account*0.5 = 2L would have allowed CRUDEOIL.
    The chest is what must constrain a strategy, not the shared account."""
    account_only = 400000.0 * MAX_PREMIUM_CASH_FRACTION
    assert account_only // 50230.0 >= 1          # account ceiling alone permits it
    assert _lots(50230.0, 100000.0, 400000.0) == 0  # chest cap refuses it


def test_a_cheaper_contract_on_the_same_underlying_becomes_affordable_again():
    """Self-adjusting: no permanent ban, it returns when the premium falls."""
    assert _lots(50230.0, 100000.0, 400000.0) == 0
    assert _lots(30000.0, 100000.0, 400000.0) == 1


def test_chest_of_zero_never_divides_by_zero():
    assert _lots(5960.0, 0.0, 400000.0) == 0
