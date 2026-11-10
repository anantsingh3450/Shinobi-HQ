"""An approved decision about a commodity module could never land.

`ImprovementBot` was constructed with ONE portfolio book - the index Dojo's.
The MCX Arena is a separate `StrategyPortfolioManager` with a separate file,
and that separation is deliberate: it is the entire mechanism keeping two
leagues' capital from being read as one. But the improvement bot was never
handed the second book, so `apply_improvement_proposal` looked up any
`strat-*-mcx-v1` strategy, found nothing, and returned False.

`hokage improve <id>` reports that as:

    "Failed to apply proposal 'X'. Verify it is pending approval."

which blames the commander's input for a wiring fault. And the MCX Arena is
exactly where the modules the retirement policy keeps clearing live - on
2026-11-10 the policy cleared EventRider/NATURALGAS with a module-wide pooled
reading of -1.69 at n=512 and 39.1% accuracy, and that decision had no route
to the book at all.

THE SECOND FAULT IS BOOKKEEPING, AND IT MUTED A MEASUREMENT. Two of the three
PENDING retirements named modules `fund_cells.py` had already archived the day
before. Nothing marks a row APPLIED when the outcome arrives by another route,
so they sat PENDING for ever - and a PENDING row SUPPRESSES re-proposal of the
same change, so the table was simultaneously wrong about the state and
silencing the measurement that would have corrected it.

Neither fix invents a status word. `hokage.research.proposals` exists because
two spellings of PENDING made every measured proposal invisible for weeks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src").is_dir() and (parent / "tests").is_dir():
            return parent
    raise AssertionError("could not find the repository root")


ROOT = _repo_root()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bots.improvement.improvement_bot import ImprovementBot  # noqa: E402
from hokage.memory.resolver import PathResolver              # noqa: E402
from hokage.research import proposals as _proposals           # noqa: E402


class _Book:
    """The smallest thing that behaves like one league's portfolio book."""

    def __init__(self, strategies: dict) -> None:
        self.portfolio = {"strategies": strategies}
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


def _bot(tmp_path, index: _Book, mcx: _Book | None = None) -> ImprovementBot:
    return ImprovementBot(
        portfolio_manager=index,
        resolver=PathResolver(tmp_path),
        extra_portfolio_managers=[mcx] if mcx is not None else None,
    )


def _index_book() -> _Book:
    return _Book({"strat-macrobreakout-commodities-v1":
                  {"status": "ACTIVE", "supported_assets": ["NIFTY"],
                   "history": []}})


def _mcx_book(status: str = "ACTIVE") -> _Book:
    return _Book({"strat-eventrider-mcx-v1":
                  {"status": status, "supported_assets": ["NATURALGAS"],
                   "history": []}})


def _proposal(strategy_id: str, new_values: dict) -> dict:
    return {
        "proposal_id": "prop-1",
        "strategy_id": strategy_id,
        "strategy_name": "EventRider",
        "asset": "NATURALGAS",
        "timestamp": "2026-11-10T00:00:00+00:00",
        "action": "ARCHIVE_STRATEGY",
        "previous_values": {"status": "ACTIVE"},
        "new_values": new_values,
        "rationale": "pooled -1.69 at n=512, 39.1% accuracy",
        "expected_improvement": None,
        "status": _proposals.PENDING,
        "approving_commander": None,
        "applied_at": None,
        "actual_post_change_performance": None,
        "measured_geometry": _proposals.stamp(3.22),
    }


# ----------------------------------------------------- finding the strategy
def test_a_strategy_in_the_second_book_is_found(tmp_path):
    bot = _bot(tmp_path, _index_book(), _mcx_book())
    manager, strat = bot._find_strategy("strat-eventrider-mcx-v1")
    assert strat is not None
    assert manager is bot.portfolio_managers[1], (
        "the MCX book must come back, not the primary one")


def test_the_book_that_holds_the_record_is_the_one_returned(tmp_path):
    """Saving the primary manager after editing a record found in the MCX one
    writes the wrong file and leaves the change nowhere - a success message
    over no change."""
    index, mcx = _index_book(), _mcx_book()
    bot = _bot(tmp_path, index, mcx)
    manager, _ = bot._find_strategy("strat-macrobreakout-commodities-v1")
    assert manager is index
    manager, _ = bot._find_strategy("strat-eventrider-mcx-v1")
    assert manager is mcx


def test_an_unknown_strategy_is_still_unknown(tmp_path):
    bot = _bot(tmp_path, _index_book(), _mcx_book())
    assert bot._find_strategy("strat-nothing-v9") == (None, None)


def test_one_book_still_works(tmp_path):
    """The second book is optional: nothing may break for a caller that has
    only one league."""
    bot = _bot(tmp_path, _index_book())
    assert len(bot.portfolio_managers) == 1
    assert bot._find_strategy("strat-eventrider-mcx-v1") == (None, None)


def test_the_same_manager_passed_twice_is_not_searched_twice(tmp_path):
    index = _index_book()
    bot = ImprovementBot(portfolio_manager=index,
                         resolver=PathResolver(tmp_path),
                         extra_portfolio_managers=[index, None])
    assert bot.portfolio_managers == [index]


def test_the_drift_error_names_what_it_searched(tmp_path):
    """"not found in portfolio" sent a reader to the wrong book for weeks."""
    bot = _bot(tmp_path, _index_book(), _mcx_book())
    with pytest.raises(ValueError) as err:
        bot.analyze_performance_drift("strat-nothing-v9", "NIFTY")
    assert "any portfolio book" in str(err.value)
    assert "strat-eventrider-mcx-v1" in str(err.value), (
        "the message should list what it did find")


def test_drift_analysis_reaches_an_mcx_strategy(tmp_path):
    """`hokage analyze-drift` on a commodity module raised ValueError before
    it could measure anything."""
    mcx = _mcx_book()
    mcx.portfolio["strategies"]["strat-eventrider-mcx-v1"].update(
        {"win_rate": {"NATURALGAS": 39.1}, "trade_count": {"NATURALGAS": 12}})
    bot = _bot(tmp_path, _index_book(), mcx)
    stats = bot.analyze_performance_drift("strat-eventrider-mcx-v1",
                                          "NATURALGAS")
    assert stats["asset"] == "NATURALGAS"


# ------------------------------------------------------------ applying it
def test_an_mcx_retirement_now_applies_and_saves_the_mcx_book(tmp_path,
                                                              monkeypatch):
    index, mcx = _index_book(), _mcx_book()
    bot = _bot(tmp_path, index, mcx)
    prop = _proposal("strat-eventrider-mcx-v1", {"status": "ARCHIVED",
                                                 "asset": "NATURALGAS"})
    saved: list = []
    monkeypatch.setattr(bot, "load_proposals", lambda: [prop])
    monkeypatch.setattr(bot, "_save_proposals_atomic", lambda ps: saved.append(ps))
    monkeypatch.setattr(bot, "_log_applied_improvement_immutable", lambda p: None)

    assert bot.apply_improvement_proposal("prop-1", "Commander Anant Singh") is True
    assert mcx.portfolio["strategies"]["strat-eventrider-mcx-v1"]["status"] == "ARCHIVED"
    assert mcx.saves == 1, "the MCX book must be the one written"
    assert index.saves == 0, "the index book must not be rewritten"
    assert prop["status"] == _proposals.APPLIED
    assert prop["approving_commander"] == "Commander Anant Singh"
    assert saved, "the proposal ledger was not persisted"


def test_without_the_second_book_it_refuses_rather_than_writing_the_wrong_one(
        tmp_path, monkeypatch):
    """The pre-2026-11-10 behaviour, pinned: one book means the MCX proposal
    cannot be applied. It must return False, never edit the index book."""
    index = _index_book()
    bot = _bot(tmp_path, index)
    prop = _proposal("strat-eventrider-mcx-v1", {"status": "ARCHIVED"})
    monkeypatch.setattr(bot, "load_proposals", lambda: [prop])
    assert bot.apply_improvement_proposal("prop-1", "Commander") is False
    assert index.saves == 0
    assert prop["status"] == _proposals.PENDING


def test_a_proposal_whose_outcome_already_exists_is_closed_not_failed(
        tmp_path, monkeypatch):
    """fund_cells archived EventRider on 2026-11-09. The 11-06 retirement
    proposal for the same module must stop being PENDING, because a PENDING
    row suppresses the re-proposal of the same question."""
    mcx = _mcx_book(status="ARCHIVED")
    bot = _bot(tmp_path, _index_book(), mcx)
    prop = _proposal("strat-eventrider-mcx-v1", {"status": "ARCHIVED",
                                                 "asset": "NATURALGAS"})
    logged: list = []
    monkeypatch.setattr(bot, "load_proposals", lambda: [prop])
    monkeypatch.setattr(bot, "_save_proposals_atomic", lambda ps: None)
    monkeypatch.setattr(bot, "_log_applied_improvement_immutable",
                        lambda p: logged.append(p))

    assert bot.apply_improvement_proposal("prop-1", "Commander Anant") is True
    assert prop["status"] == _proposals.APPLIED
    assert prop["already_in_target_state"] is True
    assert logged, "an immutable record must still be written"


def test_closing_an_already_done_proposal_does_not_claim_it_changed_anything(
        tmp_path, monkeypatch):
    mcx = _mcx_book(status="ARCHIVED")
    bot = _bot(tmp_path, _index_book(), mcx)
    prop = _proposal("strat-eventrider-mcx-v1", {"status": "ARCHIVED"})
    monkeypatch.setattr(bot, "load_proposals", lambda: [prop])
    monkeypatch.setattr(bot, "_save_proposals_atomic", lambda ps: None)
    monkeypatch.setattr(bot, "_log_applied_improvement_immutable", lambda p: None)
    bot.apply_improvement_proposal("prop-1", "Commander Anant")

    history = mcx.portfolio["strategies"]["strat-eventrider-mcx-v1"]["history"]
    assert history, "the book should record that the row was closed"
    event = history[-1]["event"]
    assert "already read" in event
    assert "nothing" in event


def test_a_partly_matching_proposal_is_applied_not_closed(tmp_path,
                                                          monkeypatch):
    """Status already right but a risk multiplier still to set is NOT done.
    Closing it on the strength of the half that matched would drop the rest."""
    mcx = _mcx_book(status="ARCHIVED")
    bot = _bot(tmp_path, _index_book(), mcx)
    prop = _proposal("strat-eventrider-mcx-v1",
                     {"status": "ARCHIVED", "risk_multiplier": 0.5})
    monkeypatch.setattr(bot, "load_proposals", lambda: [prop])
    monkeypatch.setattr(bot, "_save_proposals_atomic", lambda ps: None)
    monkeypatch.setattr(bot, "_log_applied_improvement_immutable", lambda p: None)
    bot.apply_improvement_proposal("prop-1", "Commander Anant")

    strat = mcx.portfolio["strategies"]["strat-eventrider-mcx-v1"]
    assert prop.get("already_in_target_state") is None
    assert strat["risk_multipliers"]["NATURALGAS"] == 0.5


def test_a_missing_history_list_does_not_crash_an_approved_decision(
        tmp_path, monkeypatch):
    """Absent is not empty: a strategy record written before `history` existed
    would have raised KeyError in the middle of applying his ruling."""
    mcx = _Book({"strat-eventrider-mcx-v1":
                 {"status": "ACTIVE", "supported_assets": ["NATURALGAS"]}})
    bot = _bot(tmp_path, _index_book(), mcx)
    prop = _proposal("strat-eventrider-mcx-v1", {"status": "ARCHIVED"})
    monkeypatch.setattr(bot, "load_proposals", lambda: [prop])
    monkeypatch.setattr(bot, "_save_proposals_atomic", lambda ps: None)
    monkeypatch.setattr(bot, "_log_applied_improvement_immutable", lambda p: None)
    assert bot.apply_improvement_proposal("prop-1", "Commander") is True
    assert mcx.portfolio["strategies"]["strat-eventrider-mcx-v1"]["status"] == "ARCHIVED"


# ----------------------------------------------------- what the report says
def test_the_policy_no_longer_claims_there_is_no_applier():
    """A report describing a state that has moved is the exact fault the
    surrounding comment warns about."""
    src = (ROOT / "src" / "bots" / "autonomous" / "evolution.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "no applier exists" not in code
    assert "hokage improve" in code, "it must name the command that applies it"


def test_the_pipeline_hands_the_bot_both_books():
    src = (ROOT / "src" / "hokage" / "orchestrator" / "pipeline.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "extra_portfolio_managers=[self.autonomous_bot.mcx_strategy_portfolio]" in code
