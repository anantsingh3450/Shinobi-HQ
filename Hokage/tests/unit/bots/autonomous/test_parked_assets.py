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
    """The real lineup as of 2026-10-21: CRUDEOIL still parked, NATURALGAS
    un-parked and covered again, SessionShift on the metals. No asset may
    raise a coverage alarm.

    This was the 09-22 state — both energies parked, SessionShift alone.
    Gas came back by commander directive on 10-21; crude did not, because
    its seven sweeps all failed out of sample.
    """
    bot = _bot({
        "s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"]),
        "r": _strat("RangeFade", "ACTIVE", ["NATURALGAS"], start=100000.0),
    })
    assert bot.audit_asset_coverage() == []


def test_an_unparked_orphan_still_screams(monkeypatch):
    """An asset dropped BY ACCIDENT must still be reported — the alarm has to
    survive the exemption, or parking becomes a way to silence real faults.

    Written with NATURALGAS as the example, which was itself parked on
    2026-09-22 when the gas fade went negative out of sample. The test documents
    the RULE, not that asset, so parking is lifted for gas here and CRUDEOIL —
    parked for a different reason on a different date — carries the
    still-exempt half of the assertion.
    """
    monkeypatch.setitem(Bot.PARKED_ASSETS, "NATURALGAS", None)
    monkeypatch.delitem(Bot.PARKED_ASSETS, "NATURALGAS")
    bot = _bot({"s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"])})
    findings = bot.audit_asset_coverage()
    assert any("NATURALGAS" in f for f in findings)
    assert not any("CRUDEOIL" in f for f in findings), "crude is parked, not orphaned"


def test_parking_does_not_silence_the_index_league():
    bot = _bot({"s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"])})
    bot.strategy_portfolio = _Manager({
        "a": _strat("MacroBreakout", "SHADOW_MODE", ["NIFTY", "BANKNIFTY"], 100000.0),
    })
    findings = bot.audit_asset_coverage()
    assert any("SENSEX" in f for f in findings)


def test_a_broke_owner_is_still_reported_even_for_a_parked_asset_name(monkeypatch):
    """Parking suppresses the NO-STRATEGY finding only. A strategy that is
    scoped but cannot fill is a different fault and must still surface."""
    # raising=False: gas was un-parked for real on 2026-10-21, so there may
    # be nothing left to remove here. The RULE under test is unchanged.
    monkeypatch.delitem(Bot.PARKED_ASSETS, "NATURALGAS", raising=False)
    bot = _bot({
        "r": _strat("RangeFade", "SHADOW_MODE", ["NATURALGAS"], start=0.0, realized=-500.0),
        "s": _strat("SessionShift", "ACTIVE", ["GOLDM", "SILVERM"]),
    })
    findings = bot.audit_asset_coverage()
    assert any("NATURALGAS" in f and "no chest" in f for f in findings)


def test_rangefade_keeps_its_narrow_scope_in_the_real_brain():
    """RangeFade was archived on 09-22 and REVIVED on 2026-10-21 by commander
    directive, to accumulate a gas record on an archive that now survives the
    futures roll. Nothing it measured improved - still +3.11 in sample against
    -1.91 out of it.

    The SCOPE half of this test is what still bites, and it matters more now
    that the module is live: an empty `supported_assets` FAILS OPEN in
    `_strategy_supports`, so a revived RangeFade with a blank scope would be
    armed against the entire universe rather than gas alone.
    """
    import json
    import os
    from pathlib import Path

    # The live brain, wherever it is. Published by conftest.py — it left the
    # repo on 2026-10-09 and walking up for a `hokage_brain` directory now
    # finds nothing.
    brain = Path(os.environ["HOKAGE_PRODUCTION_BRAIN"])
    book = json.loads(
        (brain / "portfolio" / "mcx_strategy_portfolio.json")
        .read_text(encoding="utf-8-sig")
    )
    rf = book["strategies"]["strat-rangefade-mcx-v1"]
    assert rf["supported_assets"] == ["NATURALGAS"], rf["supported_assets"]
