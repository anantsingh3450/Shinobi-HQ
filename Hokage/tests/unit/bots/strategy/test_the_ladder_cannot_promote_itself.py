"""The last rung of the research pipeline promoted strategies to live status
by itself, inside the trading loop.

2026-11-09. Unparking NATURALGAS woke five strategies that the funding
decision had left ACTIVE only because every asset they were scoped to was
parked. That raised a question about the other direction: what else can change
a strategy's status with nobody watching?

`evaluate_promotions` in the improvement bot was moved behind the commander's
approval on 2026-10-12, with the reasoning written out: an ACTIVE strategy
takes real entries and competes for a war chest, a PROBATION one does not, so
promotion raises risk - and reducing risk may act alone while raising it
always asks. Retirement stayed autonomous because an archived strategy cannot
open anything.

`evaluate_pipeline_transition` was the other door and it was still open. It is
called from `AutonomousTradingBot._evaluate_learning` and from
`StrategyPortfolioManager`, and both callers took the PRODUCTION status it
returned and rewrote it to ACTIVE - the whole distance between "a candidate
advanced a rung" and "a strategy nobody approved is taking real entries".

TWO WAYS THROUGH IT, AND THE SECOND WAS THE WORSE ONE:

  1. The HAC comparison. Sound statistics, and still not a licence to act.

  2. "No existing production strategy in this domain, promote directly!" -
     promotion on NO evidence of any kind. The only condition was that no
     other strategy was active on the asset. A test asserted this behaviour
     and passed: FIVE winning trades on TCS reached ACTIVE.

     And the condition had quietly become ordinary. The funding decision
     archived two modules and parked four assets, so most assets have no
     active strategy BY DESIGN. Emptiness was being read as an opening.

WHAT IS DELIBERATELY STILL AUTONOMOUS. The rungs below PROBATION do not
trade, so advancing one costs nothing. Tightening those too would be a
different error: a pipeline that cannot move at all stops producing
candidates, and then there is nothing to approve.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bots.strategy.evolution import StrategyEvolutionEngine  # noqa: E402
from hokage.memory.resolver import PathResolver  # noqa: E402

EVOLUTION = ROOT / "src" / "bots" / "strategy" / "evolution.py"


def _status_writes(path: Path) -> set[str]:
    """Every literal assigned to a `[...]["status"]` subscript, via the AST.

    ASKS THE TREE, NOT THE TEXT. This module's own docstring explains the
    PROBATION -> PRODUCTION rung at length, and a grep for "PRODUCTION" would
    fire on the explanation of the trap it guards. Four source rails did
    exactly that on 2026-11-09.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "status"):
                found.add(node.value.value)
    return found


# ================================================= the source cannot go live
def test_the_pipeline_never_writes_a_trading_status():
    """PRODUCTION is rewritten to ACTIVE by both callers, so writing either
    one here is what starts real entries."""
    written = _status_writes(EVOLUTION)
    assert written, "the AST walk found nothing - the rail is broken, not passing"
    assert "PRODUCTION" not in written
    assert "ACTIVE" not in written


def test_the_pre_trading_rungs_still_advance_on_their_own():
    """The guard must not have frozen the whole pipeline. These four statuses
    take no entries, so advancing them raises no risk."""
    written = _status_writes(EVOLUTION)
    assert {"BACKTEST", "PAPER_VALIDATION", "SHADOW_MODE", "PROBATION"} <= written


@pytest.mark.parametrize("caller", [
    ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py",
    ROOT / "src" / "bots" / "strategy" / "portfolio.py",
])
def test_no_caller_turns_production_into_active(caller):
    """Both callers used to do exactly this, one of them inside the trading
    loop. A PRODUCTION status arriving from the pipeline is now a bug, and the
    callers must refuse it rather than quietly make it live.

    SCOPED TO THE CALLING FUNCTION, deliberately. A first version of this rail
    flagged any `if` mentioning both statuses and tripped on
    `if status in ("ACTIVE", "PRODUCTION") and expectancy < 0` - a RETIREMENT
    check, which is the autonomous direction and must stay. A rail that cannot
    tell promotion from retirement would eventually be silenced rather than
    obeyed.
    """
    tree = ast.parse(caller.read_text(encoding="utf-8"))

    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and "evaluate_pipeline_transition" in ast.unparse(n)]
    assert funcs, f"{caller.name} no longer calls the pipeline - rail is stale"

    for func in funcs:
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Constant)
                    and node.value.value == "ACTIVE"):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "status"):
                    raise AssertionError(
                        f"{caller.name}:{node.lineno} sets a status to ACTIVE "
                        f"inside {func.name}, which handles the pipeline's "
                        f"return - that is the autonomous promotion again")


# ================================================ the behaviour, not the text
@pytest.fixture
def engine(tmp_path):
    return StrategyEvolutionEngine(PathResolver(tmp_path))


def _probation(**over) -> dict:
    strat = {
        "strategy_id": "strat-candidate-1", "name": "Candidate",
        "status": "PROBATION",
        "trade_count": {"DEFAULT": 25}, "win_rate": {"DEFAULT": 70.0},
        "expectancy": {"DEFAULT": 2000.0}, "sharpe_ratio": {"DEFAULT": 2.5},
        "drawdown": {"DEFAULT": 2.0}, "domain_confidence": {"DEFAULT": 90.0},
        "history": [],
    }
    strat.update(over)
    return strat


def _incumbent() -> dict:
    return {
        "strategy_id": "strat-incumbent-1", "name": "Incumbent",
        "status": "PRODUCTION",
        "trade_count": {"DEFAULT": 20}, "win_rate": {"DEFAULT": 52.0},
        "expectancy": {"DEFAULT": 10.0}, "sharpe_ratio": {"DEFAULT": 1.0},
        "drawdown": {"DEFAULT": 5.0}, "domain_confidence": {"DEFAULT": 55.0},
        "history": [],
    }


def test_an_uncontested_asset_is_not_an_opening(engine):
    """THE FREE PASS. No active strategy on the asset used to be sufficient on
    its own - no trade count, no win rate, nothing."""
    candidate = _probation()
    changed, msg = engine.evaluate_pipeline_transition(candidate, None)
    assert changed is False
    assert candidate["status"] == "PROBATION"
    assert "not evidence" in msg


def test_the_free_pass_is_refused_however_good_the_record_looks(engine):
    """Even a flawless record does not open the door, because the door is not
    a statistics question. 100% wins over 500 trades still only proposes."""
    candidate = _probation(trade_count={"DEFAULT": 500},
                           win_rate={"DEFAULT": 100.0},
                           domain_confidence={"DEFAULT": 99.0})
    changed, _ = engine.evaluate_pipeline_transition(candidate, None)
    assert changed is False
    assert candidate["status"] == "PROBATION"


def test_the_withholding_is_written_into_the_history(engine):
    """A decision not to act still has to be auditable, or the next reader
    cannot tell a refusal from a gate that never fired."""
    candidate = _probation()
    engine.evaluate_pipeline_transition(candidate, None)
    assert any("WITHHELD" in e["event"] for e in candidate["history"])


def test_a_cleared_comparison_proposes_and_does_not_apply(engine):
    candidate = _probation(
        pnl_history={"DEFAULT": [3.0, 3.2, 2.8, 3.1, 2.9, 3.3, 2.7, 3.1,
                                 3.0, 3.2, 2.9, 3.1, 3.0, 3.2, 2.8, 3.0] * 2})
    candidate["trade_count"]["DEFAULT"] = 32
    boss = _incumbent()
    boss["pnl_history"] = {"DEFAULT": [1.0, 1.2, 0.8, 1.1, 0.9, 1.3, 0.7,
                                       1.1, 1.0, 1.2, 0.9, 1.1, 1.0, 1.2,
                                       0.8]}
    boss["trade_count"]["DEFAULT"] = 15

    changed, msg = engine.evaluate_pipeline_transition(candidate, boss)
    assert changed is False
    assert "PROMOTION PROPOSED" in msg
    assert candidate["status"] == "PROBATION"


def test_the_incumbent_is_not_demoted_while_the_challenger_waits(engine):
    """The demotion travelled with the promotion and must still. Retiring the
    only strategy covering an asset while its replacement waits for approval
    leaves the asset uncovered - and an uncovered asset is how the arena gets
    a winner that cannot fill."""
    candidate = _probation(
        pnl_history={"DEFAULT": [3.0, 3.2, 2.8, 3.1, 2.9, 3.3, 2.7, 3.1,
                                 3.0, 3.2, 2.9, 3.1, 3.0, 3.2, 2.8, 3.0] * 2})
    candidate["trade_count"]["DEFAULT"] = 32
    boss = _incumbent()
    boss["pnl_history"] = {"DEFAULT": [1.0, 1.2, 0.8, 1.1, 0.9, 1.3, 0.7,
                                       1.1, 1.0, 1.2, 0.9, 1.1, 1.0, 1.2,
                                       0.8]}
    boss["trade_count"]["DEFAULT"] = 15

    engine.evaluate_pipeline_transition(candidate, boss)
    assert boss["status"] == "PRODUCTION"
    assert not any("DEMOTION" in e.get("event", "")
                   for e in boss.get("history", []))


def test_the_commander_is_told_it_was_proposed_not_done(engine):
    candidate = _probation(
        pnl_history={"DEFAULT": [3.0, 3.2, 2.8, 3.1, 2.9, 3.3, 2.7, 3.1,
                                 3.0, 3.2, 2.9, 3.1, 3.0, 3.2, 2.8, 3.0] * 2})
    candidate["trade_count"]["DEFAULT"] = 32
    boss = _incumbent()
    boss["pnl_history"] = {"DEFAULT": [1.0] * 15}
    boss["trade_count"]["DEFAULT"] = 15

    engine.evaluate_pipeline_transition(candidate, boss)
    kinds = [n["change_type"] for n in engine.load_notifications()]
    assert "PROMOTION_PROPOSED" in kinds
    assert "PROMOTION" not in kinds, (
        "a proposal announced as a promotion teaches him it already happened")


def test_a_rejected_comparison_still_reports_changed_false(engine):
    """The existing behaviour, unchanged: failing the bar was already a no.
    What changed is that CLEARING it is also a no, for a different reason."""
    candidate = _probation(trade_count={"DEFAULT": 4})
    changed, _ = engine.evaluate_pipeline_transition(candidate, _incumbent())
    assert changed is False
    assert candidate["status"] == "PROBATION"


def test_the_policy_line_is_stated_where_the_ladder_lives(engine):
    """The rule that decides this is one sentence, and it has to be readable
    at the point someone would next consider loosening it."""
    doc = ast.get_docstring(ast.parse(EVOLUTION.read_text(encoding="utf-8")))
    assert doc is not None
    flat = " ".join(doc.split())
    assert "reducing it may act alone, raising it always asks" in flat
    assert "Emptiness is not an opening" in flat
