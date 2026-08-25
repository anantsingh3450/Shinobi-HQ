"""A parked asset is a decision. An orphaned one is a bug. Say which.

CRUDEOIL was parked on 2026-08-26 after six sweeps, each train vs hold-out on
the cleaned corpus, each failing out of sample:

    stretch threshold, 6 bands       hold-out -0.33 .. -1.07, best +0.53
    trend guard, 6 settings + off    hold-out -0.11 .. -1.28, ALL negative
    evening window 17:00-22:30       hold-out -0.02 .. -1.27
    horizon 30m..240m (no stop)      +2.06 at 240m
    horizon x stop, 12 combinations  hold-out -1.63 .. +0.82, none clears
    signal inverted (follow)         train -7.72 / hold +1.49

The 240-minute +2.06 was measured WITHOUT a stop; under full geometry it fell
to +0.82 — the same lesson SILVERM taught on 2026-08-15. Crude fails as a fade
AND as a follow, so this is not a tuning problem: the signal carries no
information there. NATURALGAS on the identical signal measures +3.37 out of
sample.

WHY THIS NEEDED A REGISTRY. audit_asset_coverage fires CRITICAL + Telegram when
an asset has no live strategy, which is exactly right for an accident — CRUDEOIL
itself went dark unnoticed for six sessions in August. But a standing decision
firing that alarm every boot teaches the commander to ignore it, and then the
next real orphan goes unseen. So a parked asset is logged, not alarmed, and an
asset missing a strategy WITHOUT being parked still screams.
"""
from __future__ import annotations

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

INDEX = ["NIFTY", "BANKNIFTY", "SENSEX"]


class _Manager:
    def __init__(self, strategies: dict) -> None:
        self.portfolio = {"strategies": strategies}


def _strat(name, status, assets, start=200000.0, realized=0.0):
    return {"name": name, "status": status, "supported_assets": assets,
            "capital": {"starting": start, "realized_pnl": realized}}


def _bot(mcx):
    bot = object.__new__(Bot)
    bot.strategy_portfolio = _Manager({
        "a": _strat("MacroBreakout", "SHADOW_MODE", INDEX, 100000.0),
        "b": _strat("MeanReversion", "SHADOW_MODE", INDEX, 100000.0),
    })
    bot.mcx_strategy_portfolio = _Manager(mcx)
    return bot


def test_crude_is_parked_with_a_stated_reason():
    assert "CRUDEOIL" in Bot.PARKED_ASSETS
    reason = Bot.PARKED_ASSETS["CRUDEOIL"]
    assert reason and len(reason) > 20, "a park without a reason is just a gap"


def test_the_live_lineup_no_longer_alarms_on_crude():
    """The real post-park state: RangeFade on gas only, SessionShift on the
    metals, crude parked."""
    bot = _bot({
        "r": _strat("RangeFade", "SHADOW_MODE", ["NATURALGAS"]),
        "s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"]),
    })
    assert bot.audit_asset_coverage() == []


def test_an_unparked_orphan_still_screams():
    """NATURALGAS dropped by accident must still be reported — the alarm has to
    survive the exemption, or parking becomes a way to silence real faults."""
    bot = _bot({"s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"])})
    findings = bot.audit_asset_coverage()
    assert any("NATURALGAS" in f for f in findings)
    assert not any("CRUDEOIL" in f for f in findings), "crude is parked, not orphaned"


def test_parking_does_not_silence_the_index_league():
    bot = _bot({"r": _strat("RangeFade", "SHADOW_MODE", ["NATURALGAS"]),
                "s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"])})
    bot.strategy_portfolio = _Manager({
        "a": _strat("MacroBreakout", "SHADOW_MODE", ["NIFTY", "BANKNIFTY"], 100000.0),
    })
    findings = bot.audit_asset_coverage()
    assert any("SENSEX" in f for f in findings)


def test_a_broke_owner_is_still_reported_even_for_a_parked_asset_name():
    """Parking suppresses the NO-STRATEGY finding only. A strategy that is
    scoped but cannot fill is a different fault and must still surface."""
    bot = _bot({
        "r": _strat("RangeFade", "SHADOW_MODE", ["NATURALGAS"], start=0.0, realized=-500.0),
        "s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"]),
    })
    findings = bot.audit_asset_coverage()
    assert any("NATURALGAS" in f and "no chest" in f for f in findings)


def test_rangefade_is_scoped_to_gas_only_in_the_real_brain():
    """The measurement is worthless if the lineup did not actually change."""
    import json
    from pathlib import Path

    here = Path(__file__).resolve()
    root = next(a for a in here.parents if (a / 'hokage_brain').is_dir())
    book = json.loads(
        (root / "hokage_brain" / "portfolio" / "mcx_strategy_portfolio.json")
        .read_text(encoding="utf-8-sig")
    )
    scope = book["strategies"]["strat-rangefade-mcx-v1"]["supported_assets"]
    assert scope == ["NATURALGAS"], scope
