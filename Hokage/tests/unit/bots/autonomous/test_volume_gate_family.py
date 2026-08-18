"""The volume gate must ask the strategy that is trading, not a rival.

2026-08-18: the gate ran BEFORE the league and chose its threshold from
`strategy_portfolio.select_strategy(symbol)` — the strategy the PORTFOLIO would
pick. The league runs ~450 lines later and REASSIGNS selected_strat from its own
winner, so the strategy whose family set the bar was frequently not the strategy
that would have traded. On failure the gate did `continue`, dropping the whole
symbol before any module competed for it.

Measured across every volume rejection Hokage has ever made:

    by family      260 FAKE_BREAKOUT (1.10x bar)    18 THIN_TAPE (0.50x bar)
    blocked ratios n=278  min 0.29  median 0.68  max 1.10
    would pass the 0.50x trend bar                 242 of 278

87% of them were decided by the breakout threshold and would have passed the bar
a mean-reversion entry is supposed to face. VOLUME was 37.5% of all index
rejections, so this was the largest fixable blocker in the book.

THE SHAPE OF THE FIX
  pre-league   dead-tape floor only (TREND_MIN_RATIO). Nobody knows the winner
               yet, so no family-specific demand can honestly be made.
  post-league  the winner's own family. A breakout winner still must show the
               surge; a mean-reversion winner no longer inherits the demand
               from a rival it just beat.

This LOOSENS nothing about what a breakout must prove. It stops charging that
proof to modules that never claimed to be breakouts.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.autonomous.intelligence import VolumeEngine


def _bot():
    return object.__new__(Bot)


# ------------------------------------------------------------ the classifier
def test_a_breakout_name_is_a_breakout_family():
    assert _bot()._entry_family_of("MacroBreakout") == "breakout"
    assert _bot()._entry_family_of("macro breakout v2") == "breakout"


def test_everything_else_is_held_to_the_thin_tape_floor():
    for name in ("MeanReversion", "TrendPullback", "RangeFade", "SessionShift"):
        assert _bot()._entry_family_of(name) == "trend", name


def test_an_unknown_name_is_not_treated_as_a_breakout():
    """The old helper returned "breakout" on ANY exception, so a lookup failure
    silently imposed the strictest bar. Absence of evidence is not evidence of
    a breakout."""
    assert _bot()._entry_family_of(None) == "trend"
    assert _bot()._entry_family_of("") == "trend"


# ------------------------------------------------ what the thresholds now mean
def test_the_242_of_278_now_pass_the_pre_league_floor():
    """Every ratio Hokage ever blocked sat between 0.29 and 1.10. Those at or
    above 0.50 must now survive the pre-league gate and reach the auction."""
    engine = VolumeEngine()
    for ratio in (0.50, 0.68, 0.88, 0.94, 0.99, 1.09):
        ok, reason = engine.validate_breakout(ratio, 1.0, entry_family="trend")
        assert ok, f"{ratio}x should clear the dead-tape floor: {reason}"


def test_a_genuinely_dead_tape_is_still_refused_early():
    engine = VolumeEngine()
    ok, reason = engine.validate_breakout(0.29, 1.0, entry_family="trend")
    assert not ok
    assert "THIN_TAPE" in reason


def test_a_breakout_winner_still_has_to_show_the_surge():
    """The point is not that breakouts get easier. It is that non-breakouts
    stop paying for them."""
    engine = VolumeEngine()
    ok, reason = engine.validate_breakout(0.94, 1.0, entry_family="breakout")
    assert not ok
    assert "FAKE_BREAKOUT" in reason
    assert engine.validate_breakout(1.10, 1.0, entry_family="breakout")[0]


# ------------------------------------------------------- the production wiring
def _scan_source() -> str:
    return textwrap.dedent(inspect.getsource(Bot._scan_and_enter_opportunities))


def _family_call_args():
    """AST, not text: an earlier guard of this kind failed on a COMMENT that
    named the calls in the opposite order. Parse the code, not the prose."""
    tree = ast.parse(_scan_source())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == "validate_breakout":
                kw = {k.arg: k.value for k in node.keywords}
                out.append((node.lineno, kw.get("entry_family")))
    out.sort()
    return out


def test_the_gate_is_asked_twice_floor_first_then_family():
    calls = _family_call_args()
    assert len(calls) == 2, f"expected a pre-league floor and a post-league family check, got {len(calls)}"

    first, second = calls[0][1], calls[1][1]
    assert isinstance(first, ast.Constant) and first.value == "trend", (
        "the pre-league gate must apply the dead-tape floor only — it cannot "
        "know the winner's family yet"
    )
    assert isinstance(second, ast.Name), (
        "the post-league check must pass a family derived from the winner, "
        "not a hardcoded string"
    )


def test_the_family_comes_from_the_winner_not_the_symbol():
    """The bug in one line: the family was resolved from the SYMBOL, before the
    auction. It must be resolved from the strategy that won it."""
    tree = ast.parse(_scan_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == "_entry_family_of":
                arg = node.args[0]
                assert isinstance(arg, ast.Call), "expected selected_strat.get('name')"
                assert getattr(arg.func, "attr", None) == "get"
                assert getattr(arg.func.value, "id", None) == "selected_strat"
                return
    raise AssertionError("_entry_family_of is never called in the entry path")


def test_the_old_symbol_based_helper_is_gone():
    """Leaving it behind invites the next caller to reintroduce the bug."""
    assert not hasattr(Bot, "_entry_family_for"), (
        "_entry_family_for resolved the family from the symbol pre-league; "
        "it must not survive alongside its replacement"
    )
