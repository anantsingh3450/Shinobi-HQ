"""Nothing may widen a stop or raise size on its own. It nearly could.

2026-08-26, while answering "why is Hokage not improving on his own", the dead
evolution path in ImprovementBot turned out not to be dead — it was loaded.

`apply_autonomous_evolution` would, with no commander in the loop:

    widen the stop      stop_loss_atr_multiplier += 0.2, capped at 2.0
    raise the size      risk_multiplier          += 0.1, capped at 1.5

It had never fired for one reason only: `process_autopsy` called
`detect_patterns("strat-autotrend-equities-v1")`, an id in neither portfolio, so
the result was always empty. A one-line "fix" of that id — the obvious thing for
anyone to do while tidying — would have armed it.

And on what evidence? `detect_patterns` ignores its strategy_id argument, pools
every autopsy across every strategy and every symbol, and the trigger fires
every five trades. A win rate blended from four modules across six assets, over
five trades, could have raised risk on one of them.

That is Tier 3 in evolution.py — "anything that widens a stop, raises a cap, or
increases size" — the one tier that is never autonomous at any confidence, and
the line the commander's own standing rule draws around his capital.

The knobs it wrote were never read by production anyway (production reads
_THESIS_ATR_MULT_BY_STRATEGY_ASSET), so three independent faults sat on top of
each other and the only thing that stopped the loss was a typo.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

from bots.improvement.improvement_bot import ImprovementBot


def _source(func) -> str:
    return textwrap.dedent(inspect.getsource(func))


def test_the_autonomous_evolution_body_no_longer_writes_anything():
    """The method survives as a named refusal so callers do not crash, but it
    must contain no assignment into a strategy and no portfolio save."""
    src = _source(ImprovementBot.apply_autonomous_evolution)
    tree = ast.parse(src)

    saves = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "save_portfolio"]
    assert not saves, "the retired path must not persist a portfolio"

    subscript_writes = [n for n in ast.walk(tree)
                        if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Subscript) for t in n.targets)]
    assert not subscript_writes, "the retired path must not write a strategy knob"


def test_neither_risk_knob_is_assigned_anywhere_in_the_module():
    """Grep-level guard on the two names it used to move. Reading them is fine;
    writing them is what nearly cost money."""
    import bots.improvement.improvement_bot as mod

    tree = ast.parse(inspect.getsource(mod))
    written = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                key = getattr(target.slice, "value", None)
                if isinstance(key, str):
                    written.add(key)

    assert "stop_loss_atr_multiplier" not in written, (
        "autonomously widening a stop is Tier 3 and never automatic"
    )


def test_process_autopsy_no_longer_calls_the_evolution_path():
    """The call site is the arming mechanism. Removing the method but leaving
    the call would leave the next person to re-add one."""
    tree = ast.parse(_source(ImprovementBot.process_autopsy))
    calls = [getattr(n.func, "attr", None) for n in ast.walk(tree)
             if isinstance(n, ast.Call)]
    assert "apply_autonomous_evolution" not in calls


def test_the_module_still_records_autopsies():
    """The fix removes an unsafe action, not the observation. Autopsies are the
    corpus every measurement in the system is built on."""
    src = inspect.getsource(ImprovementBot.process_autopsy)
    assert "_autopsies_file" in src and "write" in src


def test_the_bot_still_defaults_to_advisory():
    sig = inspect.signature(ImprovementBot.__init__)
    assert sig.parameters["autonomous_mode"].default is False
