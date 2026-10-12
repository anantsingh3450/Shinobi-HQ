"""Promotion raises risk, so it asks. And the evidence behind it was wrong.

`evaluate_promotions` used to flip a PROBATION strategy to ACTIVE by itself,
save the portfolio, and Telegram "Automatically promoted to ACTIVE/LIVE mode".
It is reached from `process_autopsy`, which runs it every five trades.

An ACTIVE strategy takes real entries and competes for a chest; a PROBATION
one does not. The evolution policy has exactly one rule about that --
reducing risk may act alone, raising risk always asks -- and this was on the
wrong side of it. Retirement stays autonomous because an archived strategy
cannot open anything. Promotion is the mirror case.

THE BAR IT USED WAS ALSO MEANINGLESS. `win_rate["DEFAULT"]` is pooled across
every asset, and win rate does not track profitability. Measured in the live
portfolio on 2026-10-12:

    strat-trendrider-mcx-v1   win_rate 60.0%   realized -17,502
    strat-macrobreakout-...   win_rate 100.0%  trade_count 1

TrendRider clears a 55% bar having lost seventeen thousand rupees. Ten pooled
trades is also far under the weekly audit's MIN_N, with no hold-out split, no
production stop and no t-statistic.

Same measurement, same bar, same alert. It just cannot pull the trigger.
"""
from __future__ import annotations

import ast
import inspect
import json
import textwrap

import pytest

from bots.improvement.improvement_bot import ImprovementBot


class _Portfolio:
    """Minimal stand-in for the portfolio manager."""

    def __init__(self, strategies):
        self.portfolio = {"strategies": strategies}
        self.saved = 0

    def save(self):
        self.saved += 1


def _bot(tmp_path, strategies, monkeypatch):
    from hokage.memory.resolver import PathResolver

    monkeypatch.setenv("HOKAGE_DISABLE_TELEGRAM", "true")
    pm = _Portfolio(strategies)
    bot = ImprovementBot(
        portfolio_manager=pm,
        resolver=PathResolver(brain_root=tmp_path),
        prediction_ledger=None,
        trade_store=None,
    )
    return bot, pm


def _ready():
    return {
        "strat-x": {
            "name": "Strategy X",
            "status": "PROBATION",
            "win_rate": {"DEFAULT": 60.0},
            "trade_count": {"DEFAULT": 12},
            "history": [],
        }
    }


# ------------------------------------------------- it must not pull the trigger
def test_a_qualifying_strategy_is_NOT_promoted(tmp_path, monkeypatch):
    """THE regression. This used to set status = ACTIVE and save."""
    bot, pm = _bot(tmp_path, _ready(), monkeypatch)
    bot.evaluate_promotions()
    assert pm.portfolio["strategies"]["strat-x"]["status"] == "PROBATION"


def test_it_does_not_write_the_portfolio_at_all(tmp_path, monkeypatch):
    """A running Hokage rewrites portfolio JSON from memory; a save here is
    how a status change becomes permanent behind the commander's back."""
    bot, pm = _bot(tmp_path, _ready(), monkeypatch)
    bot.evaluate_promotions()
    assert pm.saved == 0


def test_it_leaves_no_promotion_in_the_history(tmp_path, monkeypatch):
    bot, pm = _bot(tmp_path, _ready(), monkeypatch)
    bot.evaluate_promotions()
    assert pm.portfolio["strategies"]["strat-x"]["history"] == []


# ------------------------------------------------------ but it must still ask
def test_a_qualifying_strategy_becomes_a_PENDING_proposal(tmp_path, monkeypatch):
    bot, _ = _bot(tmp_path, _ready(), monkeypatch)
    bot.evaluate_promotions()

    props = bot.load_proposals()
    assert len(props) == 1
    p = props[0]
    assert p["action"] == "promote_to_active"
    assert p["status"] == "PENDING_APPROVAL"
    assert p["strategy_id"] == "strat-x"
    assert p["new_values"] == {"status": "ACTIVE"}
    assert p["approving_commander"] is None


def test_the_rationale_warns_that_win_rate_is_not_edge(tmp_path, monkeypatch):
    """The commander acts on this sentence. It must not read as an
    endorsement of a pooled win rate."""
    bot, _ = _bot(tmp_path, _ready(), monkeypatch)
    bot.evaluate_promotions()
    rationale = bot.load_proposals()[0]["rationale"]
    assert "pooled" in rationale
    assert "17,502" in rationale, "name the counterexample, do not hand-wave"
    assert "hold-out" in rationale


def test_running_twice_does_not_duplicate_the_proposal(tmp_path, monkeypatch):
    """process_autopsy calls this every five trades."""
    bot, _ = _bot(tmp_path, _ready(), monkeypatch)
    bot.evaluate_promotions()
    bot.evaluate_promotions()
    assert len(bot.load_proposals()) == 1


# ------------------------------------------------------------- the bar holds
@pytest.mark.parametrize("wr,tc", [(60.0, 9), (54.9, 12), (0.0, 0)])
def test_a_strategy_below_the_bar_proposes_nothing(tmp_path, monkeypatch, wr, tc):
    strategies = _ready()
    strategies["strat-x"]["win_rate"]["DEFAULT"] = wr
    strategies["strat-x"]["trade_count"]["DEFAULT"] = tc
    bot, _ = _bot(tmp_path, strategies, monkeypatch)
    bot.evaluate_promotions()
    assert bot.load_proposals() == []


@pytest.mark.parametrize("status", ["ACTIVE", "ARCHIVED", "SHADOW_MODE"])
def test_only_PROBATION_is_considered(tmp_path, monkeypatch, status):
    strategies = _ready()
    strategies["strat-x"]["status"] = status
    bot, _ = _bot(tmp_path, strategies, monkeypatch)
    bot.evaluate_promotions()
    assert bot.load_proposals() == []
    assert strategies["strat-x"]["status"] == status


def test_the_bar_is_unchanged_from_when_it_was_automatic():
    """The bar was never the problem; acting on it alone was. Moving it here
    would quietly change behaviour under cover of a safety fix."""
    assert ImprovementBot.PROMOTION_MIN_TRADES == 10
    assert ImprovementBot.PROMOTION_MIN_WIN_RATE == 55.0


# --------------------------------------- the code may not contain the trigger
def test_evaluate_promotions_never_assigns_ACTIVE():
    """AST, not text: the docstring explains what it used to do, and a raw
    scan would trip over its own explanation."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(ImprovementBot.evaluate_promotions)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "status"):
                    pytest.fail("evaluate_promotions assigns a status directly")
        if isinstance(node, ast.Call):
            attr = getattr(node.func, "attr", None)
            assert attr != "save", "evaluate_promotions must not save the portfolio"
