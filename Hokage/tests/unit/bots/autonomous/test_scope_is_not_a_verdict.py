"""A strategy's scope is configuration. It is not a verdict, and it is not news.

2026-10-13, measured from the day's own journal: 19 of 98 entries were

    EntrySignal: MeanReversion: not scoped to BANKNIFTY.

MeanReversion carries supported_assets = ["NIFTY", "SENSEX"] by deliberate
decision, because edge is measured per asset and does not travel. So that
answer could not change between cycles - 19% of the record restating a choice
taken weeks earlier, burying the entries that carried information: the
MacroBreakout range refusals, the VWAP-stretch checks, the IV guard.

Identical in kind to the parked-asset lines removed a day earlier
(test_parked_assets_are_not_scanned), one level down: there it was an ASSET
nobody trades, here it is an asset/strategy PAIRING that was never meant to
exist.

THE DANGER IN FIXING THIS is the same, and so is the rail. Dropping the lines
can leave the verdict list EMPTY, and a no-trade carrying no reason at all is
worse than a noisy one - it cannot be told apart from a scan that crashed
before it started. Worse still, if an asset ever loses all coverage, silence
is exactly how "ceasing to trade an asset silently" happens, which is the rule
that blocks the pending MacroBreakout retirements.

So this pins both halves: the noise is gone, and the gap it could hide is
loud, named, and classified.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from bots.autonomous.gate_analytics import (
    GATE_KINDS,
    GateId,
    GateKind,
    classify_reason,
)

SRC = pathlib.Path("src/bots/autonomous/autonomous_bot.py")


# ------------------------------------------------- the predicate is unchanged
def test_a_scoped_asset_is_still_supported():
    """Over-matching here would mute a strategy on ground it can trade, which
    is the dangerous direction: fewer trades, silently."""
    strat = {"supported_assets": ["NIFTY", "SENSEX"]}
    assert AutonomousTradingBot._strategy_supports(strat, "NIFTY") is True
    assert AutonomousTradingBot._strategy_supports(strat, "nifty") is True


def test_an_unscoped_asset_is_not_supported():
    strat = {"supported_assets": ["NIFTY", "SENSEX"]}
    assert AutonomousTradingBot._strategy_supports(strat, "BANKNIFTY") is False


def test_a_missing_scope_still_fails_open():
    """An absent field means "no restriction recorded", never "trade nothing".
    A strategy must not be silently muted by a field nobody set."""
    assert AutonomousTradingBot._strategy_supports({}, "BANKNIFTY") is True
    assert AutonomousTradingBot._strategy_supports(
        {"supported_assets": []}, "BANKNIFTY"
    ) is True


# ------------------------------------------------------- the noise is gone
def test_neither_scan_loop_journals_a_scope_line():
    """THE REGRESSION. These two appends were 19% of one day's journal."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(
            v.value for v in node.values if isinstance(v, ast.Constant)
        )
        if "not scoped to" in text:
            offenders.append(node.lineno)
    assert not offenders, (
        f"a per-cycle scope line is back at {offenders}; a scope cannot change "
        f"between cycles, so journaling it every pass is pure noise"
    )


def test_both_loops_still_consult_the_predicate():
    """Silencing the message must not silence the RULE. A strategy competing
    for an asset it was never scoped to is the defect the predicate exists to
    stop."""
    src = SRC.read_text(encoding="utf-8")
    assert src.count("self._strategy_supports(") >= 2, (
        "both the MCX and index loops must still gate on scope"
    )


def test_the_out_of_scope_strategies_are_still_collected():
    """Dropped from the journal, not from knowledge - the gap message names
    them, so a coverage hole is readable without the portfolio JSON."""
    src = SRC.read_text(encoding="utf-8")
    assert src.count("out_of_scope.append(") >= 2


# ------------------------------------- quiet, but the gap is never invisible
def test_no_coverage_at_all_says_so_by_name():
    reason = AutonomousTradingBot._no_verdict_reason(
        "BANKNIFTY", 0, ["MeanReversion", "MacroBreakout"]
    )
    assert "BANKNIFTY" in reason
    assert "no live strategy is scoped" in reason
    assert "cannot be traded" in reason
    assert "MeanReversion" in reason and "MacroBreakout" in reason


def test_no_coverage_with_nothing_live_is_still_a_sentence():
    """An empty list must not produce "out of scope: ." - a malformed reason
    is how a real gap gets skimmed past."""
    reason = AutonomousTradingBot._no_verdict_reason("GOLDM", 0, [])
    assert "none live" in reason
    assert "GOLDM" in reason


def test_scoped_but_unwired_is_a_different_message():
    """A coverage gap and a wiring fault are different problems. One message
    for both would send the commander to the wrong file."""
    gap = AutonomousTradingBot._no_verdict_reason("NIFTY", 0, ["X"])
    wiring = AutonomousTradingBot._no_verdict_reason("NIFTY", 2, [])
    assert gap != wiring
    assert "entry module" in wiring
    assert "cannot be traded" not in wiring


@pytest.mark.parametrize("scoped,out", [(0, ["A"]), (0, []), (3, []), (1, ["B"])])
def test_the_reason_is_never_empty(scoped, out):
    """The whole point of the rail: a no-trade always carries a reason."""
    assert AutonomousTradingBot._no_verdict_reason("NIFTY", scoped, out).strip()


def test_both_loops_use_the_rail():
    src = SRC.read_text(encoding="utf-8")
    assert src.count("_no_verdict_reason(") >= 3, (
        "both stand-aside branches must fall back to a stated reason, and the "
        "helper must be defined once"
    )


def test_the_rail_fires_only_when_nothing_else_spoke():
    """It must not append to a list that already holds real verdicts, or every
    stand-aside grows a confusing second explanation."""
    src = SRC.read_text(encoding="utf-8")
    assert src.count("if not module_verdicts:") == 1
    assert src.count("if not _module_verdicts:") == 1


# -------------------------------------------------- and it is still tallied
def test_the_gap_message_tallies_as_coverage_not_unclassified():
    """UNCLASSIFIED is where blockers go to be ignored, and a total loss of
    coverage is the one that must never be hard to see."""
    for reason in (
        AutonomousTradingBot._no_verdict_reason("BANKNIFTY", 0, ["MeanReversion"]),
        AutonomousTradingBot._no_verdict_reason("BANKNIFTY", 2, []),
    ):
        assert classify_reason(reason) is GateId.STRATEGY_SCOPE


def test_a_coverage_gap_is_not_presented_as_tunable():
    """STRATEGY_SCOPE is COVERAGE, not QUALITY. A threshold sweep cannot fix
    "nothing is scoped to this asset", and offering it as tunable would send
    the improvement loop after the wrong thing."""
    assert GATE_KINDS[GateId.STRATEGY_SCOPE] is GateKind.COVERAGE


def test_the_real_refusals_still_classify_as_themselves():
    """The rules added for the gap message must not swallow the entries that
    carry information."""
    assert classify_reason(
        "EntrySignal: MacroBreakout: price 55340.20 still inside 55260.00-55697.00 range."
    ) is GateId.ENTRY_SIGNAL
    assert classify_reason(
        "EntrySignal: SessionShift: outside the 17:00-18:30 IST US-overlap window."
    ) is GateId.SESSION_TIME
    assert classify_reason(
        "IV premium guard: India VIX at 98% percentile of 60d range."
    ) is GateId.IV_PREMIUM


# ------------------------------------------- the boot statement still exists
def test_the_boot_coverage_audit_is_what_makes_the_quiet_loop_safe():
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "audit_asset_coverage"
    )
    assert "_strategy_supports" in ast.dump(fn), (
        "audit_asset_coverage must still decide coverage with the same "
        "predicate the scan loop uses, or the boot statement and the loop can "
        "disagree"
    )
