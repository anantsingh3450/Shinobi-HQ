"""The bias engine is a VETO, and it had only ever been measured as a SIGNAL.

Those are different questions. A rule can predict direction well on its own and
still be a bad gate on someone else's entry, if its "yes" condition barely
overlaps that entry's firing condition. Then it is not filtering, it is an off
switch with a t-stat attached.

On 2026-08-12 that is exactly what happened. SessionShift — the highest-t entry
module in the system — won 16 auctions on GOLDM/SILVERM and the veto blocked 15
of them, every one reading "tape is MIXED". `tools/research/veto_lab.py` was
built to score the pair TOGETHER and found, at the 60-minute horizon Hokage
actually trades:

    GOLDM    SessionShift  alone n=411 t=+3.30  ->  gated n=58 t=+1.23
    SILVERM  SessionShift  alone n=556 t=+2.59  ->  gated n=40 t=+1.53

A module that clears the t>=2 bar alone falls below it once gated, and the
BLOCKED set is where the edge lives (GOLDM t=+3.06, SILVERM t=+2.22).

These tests pin the resulting decision and — more importantly — the SHAPE of
the fix: disabled per symbol on measured evidence, kept everywhere it measured
as a genuine filter, and never quietly widened.
"""
from __future__ import annotations

import pytest

from bots.autonomous import bias_rules


def test_the_two_symbols_the_lab_condemned_are_the_only_ones_disabled():
    assert bias_rules.VETO_DISABLED_SYMBOLS == frozenset({"GOLDM", "SILVERM"})


@pytest.mark.parametrize("symbol", ["NIFTY", "BANKNIFTY", "SENSEX"])
def test_the_veto_survives_on_the_indices_where_it_MEASURED_as_a_filter(symbol):
    """MacroBreakout is live on all three and the veto improves it: NIFTY
    t=+2.88 -> +3.52, SENSEX +2.32 -> +2.51, blocking only ~30-45%. Killing
    the veto globally would have thrown that away to fix a commodity problem."""
    assert symbol not in bias_rules.VETO_DISABLED_SYMBOLS


def test_crudeoil_is_not_quietly_relit_by_this_change():
    """CRUDEOIL is dark by commander decision. Standing the veto down there
    would be meaningless (nothing is scoped to it) but it would also be a
    silent edit to a deliberate decision. Keep it out."""
    assert "CRUDEOIL" not in bias_rules.VETO_DISABLED_SYMBOLS


def test_naturalgas_keeps_its_veto_because_its_module_is_exempt_anyway():
    """RangeFade is the only strategy scoped to NATURALGAS and it is
    COUNTER_TREND, so `_check_conduct_gates` already skips the veto for it.
    Disabling the symbol as well would change nothing today and would remove a
    guard from any future module scoped there."""
    assert "NATURALGAS" not in bias_rules.VETO_DISABLED_SYMBOLS


class _StubBot:
    """The narrowest possible stand-in: only what the early-out reads."""

    _compute_underlying_bias = None  # replaced below


def test_a_disabled_symbol_returns_None_not_MIXED(monkeypatch):
    """None and MIXED are NOT interchangeable at the call site.

        if bias == "MIXED":  -> blocks the trade
        if bias is None:     -> skips the check

    Returning "MIXED" to stand the veto down would block every trade on the
    symbol — the exact failure being fixed, inverted.
    """
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    bot = object.__new__(Bot)
    verdict = Bot._compute_underlying_bias(bot, "GOLDM")
    assert verdict is None


def test_standing_down_happens_BEFORE_any_market_data_is_fetched():
    """The early-out must not depend on the venue.

    Returning None is not enough evidence on its own: the fetch itself is
    wrapped in `try/except Exception -> return None`, so a symbol that reached
    the venue and failed looks identical from the outside. Count the venue
    accesses instead — a stood-down symbol must make ZERO, so its behaviour
    cannot change when the feed hiccups.
    """
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    class _CountingPriceSource:
        def __init__(self) -> None:
            self.calls = 0

        def resolve_instrument(self, symbol):
            self.calls += 1
            raise RuntimeError("venue deliberately unavailable")

    class _Orchestrator:
        def __init__(self) -> None:
            self.price_source = _CountingPriceSource()

    bot = object.__new__(Bot)
    bot.orchestrator = _Orchestrator()

    assert Bot._compute_underlying_bias(bot, "SILVERM") is None
    assert bot.orchestrator.price_source.calls == 0, "stood-down symbol touched the venue"

    # Control: a symbol that still runs the veto DOES reach the venue, which
    # proves the assertion above passed because of the early-out and not
    # because nothing calls the venue at all.
    assert Bot._compute_underlying_bias(bot, "NIFTY") is None
    assert bot.orchestrator.price_source.calls == 1


def test_case_is_normalised_so_a_lowercase_symbol_cannot_slip_past():
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    bot = object.__new__(Bot)
    assert Bot._compute_underlying_bias(bot, "goldm") is None
    assert Bot._compute_underlying_bias(bot, "SilverM") is None
