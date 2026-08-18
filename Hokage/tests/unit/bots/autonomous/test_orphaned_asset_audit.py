"""An orphaned asset raises no error. It simply never trades.

2026-08-12: TrendRider was archived for measuring negative (NATURALGAS n=724,
edge -0.283, t=-1.64) and its 200,000 chest was released to SessionShift. Both
decisions were correct. But TrendRider was the ONLY strategy scoped to
CRUDEOIL, and SessionShift is scoped to GOLDM and SILVERM — so CRUDEOIL
silently stopped being tradable.

It stayed that way for SIX SESSIONS and was found on 2026-08-18 only because
the commander asked why there had been no trades. Every cycle Hokage logged
"not scoped to CRUDEOIL" twice and stood aside, which at a glance is
indistinguishable from a patient tape. A dead asset and a quiet one produce
exactly the same silence.

`evolution.py` Rail 2 already refuses to autonomously archive a strategy that
would orphan an asset — but it guards the NEXT archive and never inspected the
lineup it inherited. These tests cover the hole that predates the rule.
"""
from __future__ import annotations

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

INDEX = ["NIFTY", "BANKNIFTY", "SENSEX"]


class _Manager:
    def __init__(self, strategies: dict) -> None:
        self.portfolio = {"strategies": strategies}


def _strat(name, status, assets, start=200000.0, realized=0.0):
    return {
        "name": name,
        "status": status,
        "supported_assets": assets,
        "capital": {"starting": start, "realized_pnl": realized},
    }


def _bot(index=None, mcx=None):
    bot = object.__new__(Bot)
    bot.strategy_portfolio = _Manager(index or {})
    bot.mcx_strategy_portfolio = _Manager(mcx or {})
    return bot


def _covered_index():
    """An index league where all three assets are genuinely owned."""
    return {
        "a": _strat("MacroBreakout", "SHADOW_MODE", INDEX, 100000.0),
        "b": _strat("MeanReversion", "SHADOW_MODE", INDEX, 100000.0),
    }


def test_it_catches_the_exact_2026_08_18_state():
    """The real lineup on the day this was found: CRUDEOIL owned by nobody."""
    bot = _bot(
        index=_covered_index(),
        mcx={
            "r": _strat("RangeFade", "SHADOW_MODE", ["NATURALGAS"]),
            "s": _strat("SessionShift", "SHADOW_MODE", ["GOLDM", "SILVERM"]),
            "t": _strat("TrendRider", "ARCHIVED", ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]),
            "e": _strat("EventRider", "ARCHIVED", ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]),
        },
    )
    findings = bot.audit_asset_coverage()
    assert len(findings) == 1, findings
    assert "CRUDEOIL" in findings[0]
    assert "MCX Arena" in findings[0]


def test_an_archived_strategy_does_not_count_as_cover():
    """The whole failure: an archived owner looks like an owner in the file."""
    bot = _bot(
        index=_covered_index(),
        mcx={"t": _strat("TrendRider", "ARCHIVED", ["CRUDEOIL"])},
    )
    assert any("CRUDEOIL" in f for f in bot.audit_asset_coverage())


def test_a_broke_owner_is_not_an_owner():
    """A strategy with no chest wins the auction and fills nothing, so the
    asset is dark even though something is scoped to it."""
    bot = _bot(
        index=_covered_index(),
        mcx={"s": _strat("SessionShift", "SHADOW_MODE", ["CRUDEOIL"], start=0.0, realized=-1280.0)},
    )
    findings = [f for f in bot.audit_asset_coverage() if "CRUDEOIL" in f]
    assert len(findings) == 1
    assert "SessionShift" in findings[0]
    assert "no chest" in findings[0]
    assert "fill nothing" in findings[0]


def test_silence_when_every_asset_has_a_solvent_live_owner():
    bot = _bot(
        index=_covered_index(),
        mcx={
            "r": _strat("RangeFade", "SHADOW_MODE", ["CRUDEOIL", "NATURALGAS"]),
            "s": _strat("SessionShift", "SHADOW_MODE", ["GOLDM", "SILVERM"]),
        },
    )
    assert bot.audit_asset_coverage() == []


def test_an_empty_scope_fails_open_and_covers_everything():
    """`_strategy_supports` treats a missing scope as 'no restriction
    recorded'. The audit must honour that, or it would invent orphans for
    every strategy that never narrowed its universe."""
    bot = _bot(
        index=_covered_index(),
        mcx={"any": _strat("Generalist", "SHADOW_MODE", [])},
    )
    assert bot.audit_asset_coverage() == []


def test_an_unloaded_league_is_not_reported_as_four_orphans():
    """A league that failed to load is a different fault with its own alarm.
    Reporting every asset in it would bury a real single-asset orphan."""
    bot = _bot(index=_covered_index(), mcx={})
    assert bot.audit_asset_coverage() == []


def test_index_orphans_are_caught_too():
    bot = _bot(
        index={"a": _strat("MacroBreakout", "SHADOW_MODE", ["NIFTY", "BANKNIFTY"], 100000.0)},
        mcx={"r": _strat("RangeFade", "SHADOW_MODE", ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"])},
    )
    findings = bot.audit_asset_coverage()
    assert len(findings) == 1
    assert "SENSEX" in findings[0]
    assert "Index Dojo" in findings[0]


def test_chest_definition_is_shared_with_the_chest_audit():
    """Both audits must agree on what 'can afford to trade' means. If they
    drift, an asset gets reported as covered by a strategy that cannot fill."""
    broke = _strat("Broke", "SHADOW_MODE", ["CRUDEOIL"], start=0.0, realized=-1280.0)
    assert Bot._chest_of(broke) == -1280.0
    assert Bot._chest_of({"capital": {"starting": "junk"}}) == 0.0
    assert Bot._chest_of({}) == 0.0
