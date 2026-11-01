"""The sizing grade could not work, because nobody wrote down the size.

`_grade_sizing_quality` read `allocation_pct` out of the entry record. Of
Hokage's three entry paths only ONE has ever written that key:

    autonomous_bot.py  index options path   sets allocation_pct
    autonomous_bot.py  MCX Arena path       does not
    autonomous_bot.py  manual entry path    does not

So the review fell to its `1.0` default, and 1.0/conviction*100 is inside the
CORRECT band for every conviction Hokage scores. 487 of 488 reviews read
CORRECT. Every commodity trade and every commander entry was graded on a
number that had never been measured.

Worse, `allocation_pct` and the premium cap are written in DIFFERENT
denominators — allocation_pct is a percentage of total capital, while
MAX_PREMIUM_CHEST_FRACTION caps a position at 33% of its strategy's own war
chest. Grading one against the other would have been wrong even with the key
present everywhere.

`chest_fraction_pct` is the one denominator, stamped by all three paths at
entry. It has to be frozen at entry: the chest moves with every realized exit,
so asking the question afterwards answers a different question — the same
mistake the R:R grade made by reading a ratcheting stop (9f0d6f4).

Companion to test_review_grades_measure_something.py, which covers the grades
themselves.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


def _bot():
    return object.__new__(Bot)


class _Mgr:
    def __init__(self, rows):
        self._rows = rows

    def get_capital_report(self, deployed=None):
        return self._rows


def _bot_with_chest(rows):
    bot = _bot()
    bot.strategy_deployed_capital = lambda: {}
    bot._portfolio_manager_for_strategy = lambda sid: _Mgr(rows)
    return bot


_ROWS = [
    {"strategy_id": "strat-a", "starting_capital": 100_000.0, "realized_pnl": 20_000.0},
    {"strategy_id": "strat-b", "starting_capital": 100_000.0, "realized_pnl": -40_000.0},
]


# ----------------------------------------------------- the chest, not what is left
def test_the_chest_is_starting_plus_realized():
    """Not `available`. Available subtracts whatever is open right now, so the
    same trade would grade differently depending on what else happened to be
    held at the time."""
    assert _bot_with_chest(_ROWS)._strategy_chest_size("strat-a") == 120_000.0


def test_a_losing_chest_has_shrunk_and_the_grade_must_see_that():
    assert _bot_with_chest(_ROWS)._strategy_chest_size("strat-b") == 60_000.0


def test_an_unknown_strategy_gets_no_chest_rather_than_a_fresh_one():
    """`_strategy_available_capital` falls through to STRATEGY_STARTING_CAPITAL
    for an id it does not recognise — the fallback that hands an unresolvable
    strategy a full fresh chest. A post-trade grade must not inherit it."""
    assert _bot_with_chest(_ROWS)._strategy_chest_size("strat-ghost") is None


def test_a_missing_strategy_id_gets_no_chest():
    assert _bot_with_chest(_ROWS)._strategy_chest_size("") is None
    assert _bot_with_chest(_ROWS)._strategy_chest_size(None) is None


def test_an_exhausted_chest_is_unknown_not_a_division_by_zero():
    rows = [{"strategy_id": "s", "starting_capital": 50_000.0, "realized_pnl": -50_000.0}]
    assert _bot_with_chest(rows)._strategy_chest_size("s") is None


def test_a_broken_portfolio_read_is_unknown_not_a_crash():
    """This runs on the entry path. It must never be the reason an order is
    not tracked."""
    bot = _bot()
    bot.strategy_deployed_capital = lambda: {}

    def _boom(sid):
        raise RuntimeError("portfolio file is locked")

    bot._portfolio_manager_for_strategy = _boom
    assert bot._strategy_chest_size("strat-a") is None


# ------------------------------------------------------------- the fraction itself
def test_the_fraction_is_premium_paid_over_the_chest():
    """One CRUDEOIL lot at 7,920 premium against a 120,000 chest = 6.6%."""
    bot = _bot_with_chest(_ROWS)
    assert bot._chest_fraction_pct("strat-a", 7_920.0, 1.0) == pytest.approx(6.6)


def test_quantity_counts_so_two_lots_read_as_twice_the_chest():
    bot = _bot_with_chest(_ROWS)
    one = bot._chest_fraction_pct("strat-a", 7_920.0, 1.0)
    two = bot._chest_fraction_pct("strat-a", 7_920.0, 2.0)
    assert two == pytest.approx(one * 2)


def test_a_position_at_the_cap_reads_as_the_cap():
    """The cap is expressed in exactly this unit, which is the whole reason to
    grade in it."""
    from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION

    bot = _bot_with_chest(_ROWS)
    at_cap = 120_000.0 * MAX_PREMIUM_CHEST_FRACTION
    assert bot._chest_fraction_pct("strat-a", at_cap, 1.0) == pytest.approx(
        MAX_PREMIUM_CHEST_FRACTION * 100.0
    )


def test_an_unresolvable_strategy_yields_none_not_a_number():
    assert _bot_with_chest(_ROWS)._chest_fraction_pct("strat-ghost", 7_920.0, 1.0) is None


@pytest.mark.parametrize("price,qty", [(0.0, 1.0), (7_920.0, 0.0), (-10.0, 1.0)])
def test_a_costless_entry_yields_none(price, qty):
    """A premium of zero is not a free position, it is a price nobody read."""
    assert _bot_with_chest(_ROWS)._chest_fraction_pct("strat-a", price, qty) is None


def test_a_non_numeric_price_yields_none_not_a_crash():
    assert _bot_with_chest(_ROWS)._chest_fraction_pct("strat-a", None, 1.0) is None


# ------------------------------------------- all three entry paths record it
def _src() -> str:
    return Path(
        __import__("bots.autonomous.autonomous_bot", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")


def test_every_entry_path_stamps_the_chest_fraction():
    """Three stamps: manual, MCX Arena, index options. If a fourth entry path
    is ever added without one, its trades grade UNKNOWN forever and silently —
    which is better than a fabricated CORRECT, but is still a gap."""
    src = _src()
    stamps = src.count('"initial_stop_price":')
    assert stamps == 3, "a new entry path appeared; it needs a chest fraction too"
    assert src.count('"chest_fraction_pct": self._chest_fraction_pct(') == stamps


def test_the_exit_path_reads_it_without_a_default():
    """The `1.0` default is the defect. It must not come back."""
    src = _src()
    assert 'entry_meta.get("chest_fraction_pct")' in src
    assert 'entry_meta.get("chest_fraction_pct", 1.0)' not in src


def test_the_review_is_handed_the_chest_fraction_and_the_heat():
    src = _src()
    assert "position_size_pct=_chest_pct," in src
    assert "mae_pct=_mae_pct," in src
    # allocation_pct must no longer reach the sizing grade: it is a percentage
    # of TOTAL capital and shares no denominator with the premium cap.
    assert "position_size_pct=_alloc_pct," not in src
