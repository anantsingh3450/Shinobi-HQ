"""Edge is measured per asset, and it does not travel.

Measured 2026-08-11 with tools/research/entry_module_lab.py, the same module is
a winner on one commodity and a loser on another:

    SessionShift  GOLDM t=+3.17 / SILVERM t=+2.71   but NATURALGAS t=-2.14
    RangeFade     NATURALGAS t=+2.33                but GOLDM/SILVERM negative

They are near mirror images. A league where every strategy judges every asset
must therefore run each of them on ground where it measurably loses money.

`supported_assets` already existed on every strategy record, but the entry scan
never read it — it appeared exactly once, in an unrelated similarity check. This
is the gate that makes the field mean something.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

_SUPPORTS = Bot._strategy_supports


def test_a_scoped_strategy_competes_only_where_it_measured():
    strat = {"name": "SessionShift", "supported_assets": ["GOLDM", "SILVERM"]}
    assert _SUPPORTS(strat, "GOLDM")
    assert _SUPPORTS(strat, "SILVERM")
    assert not _SUPPORTS(strat, "NATURALGAS")
    assert not _SUPPORTS(strat, "CRUDEOIL")


def test_the_mirror_image_module_is_scoped_the_other_way():
    strat = {"name": "RangeFade", "supported_assets": ["NATURALGAS"]}
    assert _SUPPORTS(strat, "NATURALGAS")
    assert not _SUPPORTS(strat, "GOLDM")


@pytest.mark.parametrize("assets", [None, [], {}])
def test_missing_scope_fails_OPEN_and_never_silently_mutes(assets):
    """A strategy must never stop trading because a field is absent. Only a
    list that EXISTS and excludes the symbol keeps it out."""
    strat = {"name": "Legacy"}
    if assets is not None:
        strat["supported_assets"] = assets
    assert _SUPPORTS(strat, "NIFTY")
    assert _SUPPORTS(strat, "ANYTHING")


def test_matching_is_case_insensitive():
    strat = {"supported_assets": ["goldm"]}
    assert _SUPPORTS(strat, "GOLDM")
    assert _SUPPORTS(strat, "GoldM")


def test_todays_live_portfolios_are_unaffected_by_enforcement():
    """Every strategy currently lists its full universe, so switching the gate
    on changes nothing until a scope is deliberately narrowed. This is what
    makes the change safe to ship before it is used."""
    index_universe = ["NIFTY", "BANKNIFTY", "SENSEX"]
    mcx_universe = ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]
    for universe in (index_universe, mcx_universe):
        strat = {"supported_assets": list(universe)}
        for symbol in universe:
            assert _SUPPORTS(strat, symbol)
