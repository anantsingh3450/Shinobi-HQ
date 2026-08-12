"""A strategy with no money does not fail loudly. It wins, then stands aside.

2026-08-12: SessionShift was re-scoped to GOLDM/SILVERM on measured edge
(t=+3.30/+2.59) while its `capital.starting` sat at 0 from the 2026-07-31
consolidation, giving it a chest of -1,280. It won SIXTEEN auctions that
session and filled NONE — every one died at the router with "Risk budget -422
affords 0 lots". The dashboard, the health score and the log all looked normal,
because a strategy competing and winning IS normal. Nothing checked the money.

The damage is not only the trades it missed. Winning an auction removes the
asset from every other strategy, so a broke strategy actively denies ground it
cannot use.
"""
from __future__ import annotations

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Manager:
    def __init__(self, strategies: dict) -> None:
        self.portfolio = {"strategies": strategies}


def _strat(name, status, start, realized, assets=None):
    return {
        "name": name,
        "status": status,
        "supported_assets": assets or ["GOLDM", "SILVERM"],
        "capital": {"starting": start, "realized_pnl": realized},
    }


def _bot(index=None, mcx=None):
    bot = object.__new__(Bot)
    bot.strategy_portfolio = _Manager(index or {})
    bot.mcx_strategy_portfolio = _Manager(mcx or {})
    return bot


def test_it_catches_the_exact_2026_08_12_state():
    bot = _bot(mcx={"s1": _strat("SessionShift", "SHADOW_MODE", 0.0, -1280.0)})
    findings = bot.audit_strategy_chests()
    assert len(findings) == 1
    assert "SessionShift" in findings[0]
    assert "-1,280" in findings[0]
    assert "GOLDM, SILVERM" in findings[0]


def test_a_funded_strategy_is_silent():
    bot = _bot(mcx={"s1": _strat("SessionShift", "SHADOW_MODE", 200_000.0, -1280.0)})
    assert bot.audit_strategy_chests() == []


def test_an_ARCHIVED_strategy_with_an_idle_chest_is_not_a_finding():
    """Archived strategies cannot trade by design, so their capital is not a
    fault — TrendRider sat on 200,000 while archived and that was merely idle,
    not broken. Flagging it would train the commander to ignore this alarm."""
    bot = _bot(mcx={
        "s1": _strat("TrendRider", "ARCHIVED", 0.0, -17_502.5),
        "s2": _strat("EventRider", "ARCHIVED", 0.0, 0.0),
    })
    assert bot.audit_strategy_chests() == []


def test_exactly_zero_counts_as_broke():
    """A chest of 0 buys nothing. The boundary must not be `< 0` — SessionShift
    would have passed a `< 0` check on the day it was zeroed, and only started
    failing once it had lost money it never had."""
    bot = _bot(mcx={"s1": _strat("Zeroed", "SHADOW_MODE", 0.0, 0.0)})
    assert len(bot.audit_strategy_chests()) == 1


def test_both_leagues_are_audited():
    bot = _bot(
        index={"a": _strat("MacroBreakout", "ACTIVE", 0.0, 0.0, ["NIFTY"])},
        mcx={"b": _strat("RangeFade", "SHADOW_MODE", 0.0, 0.0, ["NATURALGAS"])},
    )
    findings = bot.audit_strategy_chests()
    assert len(findings) == 2
    assert any(f.startswith("Index Dojo") for f in findings)
    assert any(f.startswith("MCX Arena") for f in findings)


def test_a_corrupt_capital_record_is_treated_as_broke_not_skipped():
    """Unreadable numbers must fail LOUD. Silently skipping a malformed record
    reproduces the original bug in a new place."""
    bot = _bot(mcx={"s1": {
        "name": "Corrupt", "status": "SHADOW_MODE",
        "supported_assets": ["GOLDM"],
        "capital": {"starting": "not-a-number", "realized_pnl": None},
    }})
    assert len(bot.audit_strategy_chests()) == 1


def test_a_missing_scope_is_described_rather_than_crashing():
    bot = _bot(mcx={"s1": {
        "name": "Unscoped", "status": "SHADOW_MODE",
        "capital": {"starting": 0.0, "realized_pnl": 0.0},
    }})
    findings = bot.audit_strategy_chests()
    assert "all assets" in findings[0]


def test_the_audit_runs_once_per_boot_not_once_per_loop(monkeypatch):
    """It fires from the trading loop, which runs every ~60 seconds. A CRITICAL
    log and a Telegram alert on every iteration would bury the alarm it is
    trying to raise."""
    bot = _bot(mcx={"s1": _strat("Broke", "SHADOW_MODE", 0.0, 0.0)})
    bot.telegram_bot = None
    calls = {"n": 0}
    real = bot.audit_strategy_chests

    def _counting():
        calls["n"] += 1
        return real()

    bot.audit_strategy_chests = _counting
    for _ in range(20):
        bot._announce_broke_strategies()
    assert calls["n"] == 1


def test_an_audit_failure_never_stops_the_trading_loop():
    bot = object.__new__(Bot)  # no portfolios attached at all
    bot.telegram_bot = None
    bot._announce_broke_strategies()  # must not raise
