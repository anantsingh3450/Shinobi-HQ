"""Half the account was missing from the account-wide rail.

2026-11-11, found on a live exit. GOLDM26NOV141000PE closed and logged:

    [ERROR] Exit reason for GOLDM26NOV141000PE could not be recorded: no
    ledger position matched that symbol in accounts ['paper']. The reason
    exists only in this log.

The position was in `paper_mcx`. The shout was the 2026-11-10 fix working as
designed; what it exposed was the account list.

`mcx_venue` is its own attribute on the orchestrator with its own
`account_id="paper_mcx"`, deliberately separate so the commodity league's
ledger can never mix with the index Dojo's. It is NOT in `paper_venues`,
which holds only the broker-driven venues. So this, written by hand at two
call sites,

    venues = [paper_venue] + list(paper_venues.values())

silently excluded the entire MCX Arena.

THE SECOND SITE IS THE SERIOUS ONE. `_account_open_premium` is the
denominator of the only risk rail in Hokage that is not per-strategy, and
`exposure.ACCOUNT_CAPITAL` says why it has to be account-wide: "The real
account, as stated by the commander on 2026-11-09. One pool, not a chest
each." That evening's GOLDM put was 25,125 of the 47,619 ceiling and the rail
counted ZERO, because it could not see the account the trade was in.

The constant is untouched. A rail that cannot measure half of what it bounds
is not a loosened rail, it is a broken one.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap
from types import SimpleNamespace

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


def _bot(*, paper="paper", mcx="paper_mcx", brokers=("paper_zerodha",)):
    """A bot whose orchestrator looks like the real pipeline's."""
    bot = object.__new__(Bot)
    bot.orchestrator = SimpleNamespace(
        paper_venue=SimpleNamespace(_account_id=paper) if paper else None,
        mcx_venue=SimpleNamespace(_account_id=mcx) if mcx else None,
        paper_venues={b: SimpleNamespace(_account_id=b) for b in brokers},
    )
    return bot


# ====================================================== the account list
def test_the_mcx_account_is_in_the_list():
    """THE DEFECT, in one assertion."""
    assert "paper_mcx" in _bot()._paper_account_ids()


def test_every_account_appears_once_and_the_index_comes_first():
    ids = _bot(brokers=("paper_zerodha", "paper_coindcx"))._paper_account_ids()
    assert ids[0] == "paper", "callers log this; a shuffling list reads as a change"
    assert set(ids) == {"paper", "paper_mcx", "paper_zerodha", "paper_coindcx"}
    assert len(ids) == len(set(ids))


def test_a_venue_sharing_an_account_id_is_not_counted_twice():
    """The broker paper venues are constructed without an explicit
    account_id, so more than one can resolve to the same account."""
    ids = _bot(brokers=("paper", "paper_mcx"))._paper_account_ids()
    assert ids == ["paper", "paper_mcx"]


@pytest.mark.parametrize("missing", ["paper", "mcx"])
def test_a_missing_venue_is_survived(missing):
    """An orchestrator built without one of them must not raise - the
    exposure rail turns any exception into infinity and blocks every
    entry, so a crash here is a silent trading halt."""
    bot = _bot(paper=None if missing == "paper" else "paper",
               mcx=None if missing == "mcx" else "paper_mcx")
    ids = bot._paper_account_ids()
    assert ids, "the surviving account must still be found"
    assert None not in ids


def test_no_accounts_at_all_is_an_empty_list_not_a_crash():
    bot = _bot(paper=None, mcx=None, brokers=())
    assert bot._paper_account_ids() == []


# ======================================= the rail actually counts MCX now
def _priced_bot(index_positions, mcx_positions):
    """A bot whose ledger holds real-shaped positions in both accounts."""
    from bots.execution.models import TradeStatus

    def _pos(price, qty, status=TradeStatus.OPEN, failure_reason=None):
        return SimpleNamespace(status=status, entry_price=price, quantity=qty,
                               failure_reason=failure_reason)

    books = {
        "paper": SimpleNamespace(positions={
            f"i{n}": _pos(*args) for n, args in enumerate(index_positions)}),
        "paper_mcx": SimpleNamespace(positions={
            f"m{n}": _pos(*args) for n, args in enumerate(mcx_positions)}),
    }
    bot = _bot(brokers=())
    bot.orchestrator.portfolio_store = SimpleNamespace(
        load_account=lambda aid: books[aid])
    return bot


def test_the_goldm_put_now_consumes_the_budget():
    """THE EVENING THAT FOUND THIS. One lot of GOLDM26NOV141000PE at 2512.50
    on a lot of 10 is 25,125 - 53% of the 47,619 ceiling - and the rail
    measured 0."""
    from bots.execution import exposure

    bot = _priced_bot(index_positions=[], mcx_positions=[(2512.5, 10)])
    measured = bot._account_open_premium()
    assert measured == pytest.approx(25_125.0)
    assert 0 < measured < exposure.MAX_TOTAL_PREMIUM
    assert measured / exposure.MAX_TOTAL_PREMIUM > 0.5, (
        "half the ceiling, and it used to count as nothing")


def test_both_leagues_are_added_together():
    """One pool, not a chest each - the commander's own framing, and the
    reason this rail exists at all."""
    bot = _priced_bot(index_positions=[(100.0, 75)],      # 7,500
                      mcx_positions=[(2512.5, 10)])       # 25,125
    assert bot._account_open_premium() == pytest.approx(32_625.0)


def test_a_closed_position_holds_no_risk():
    from bots.execution.models import TradeStatus

    bot = _priced_bot(index_positions=[],
                      mcx_positions=[(2512.5, 10, TradeStatus.CLOSED)])
    assert bot._account_open_premium() == 0.0


def test_a_phantom_still_holds_no_risk():
    """The 292 phantom rows from the 2026-07-15 runaway are an audit record,
    not exposure. Counting them would block every entry for ever."""
    from bots.execution.models import TradeStatus

    bot = _priced_bot(
        index_positions=[],
        mcx_positions=[(2512.5, 10, TradeStatus.OPEN, "PHANTOM: runaway")])
    assert bot._account_open_premium() == 0.0


def test_an_unreadable_book_still_blocks_rather_than_waves_through():
    """Unknown must leave no room. A risk rail that cannot measure must not
    let the trade past."""
    bot = _bot(brokers=())

    def boom(_aid):
        raise RuntimeError("ledger unreadable")

    bot.orchestrator.portfolio_store = SimpleNamespace(load_account=boom)
    assert bot._account_open_premium() == float("inf")


# ===================================== the exit reason reaches the ledger
def test_an_mcx_exit_reason_lands_in_the_mcx_account():
    """What the live error reported: the reason existed only in the log."""
    from bots.execution.models import TradeStatus

    mcx_pos = SimpleNamespace(market="GOLDM26NOV141000PE", opened_at=2.0,
                              status=TradeStatus.CLOSED, failure_reason=None)
    books = {
        "paper": SimpleNamespace(positions={}),
        "paper_mcx": SimpleNamespace(positions={"p": mcx_pos}),
    }
    saved: list = []
    bot = _bot(brokers=())
    bot.orchestrator.portfolio_store = SimpleNamespace(
        load_account=lambda aid: books[aid],
        save_account=lambda acct: saved.append(acct))

    assert bot._record_exit_reason("GOLDM26NOV141000PE", "Loss triggered") is True
    assert mcx_pos.failure_reason == "Loss triggered"
    assert saved == [books["paper_mcx"]], "only the MCX book should be written"


def test_a_phantom_annotation_is_never_overwritten():
    from bots.execution.models import TradeStatus

    phantom = SimpleNamespace(market="GOLDM26NOV141000PE", opened_at=2.0,
                              status=TradeStatus.CLOSED,
                              failure_reason="PHANTOM: 2026-07-15 runaway")
    books = {"paper": SimpleNamespace(positions={}),
             "paper_mcx": SimpleNamespace(positions={"p": phantom})}
    bot = _bot(brokers=())
    bot.orchestrator.portfolio_store = SimpleNamespace(
        load_account=lambda aid: books[aid],
        save_account=lambda acct: None)

    assert bot._record_exit_reason("GOLDM26NOV141000PE", "Loss triggered") is False
    assert phantom.failure_reason.startswith("PHANTOM")


def test_a_symbol_in_no_account_still_shouts():
    """The 2026-11-10 behaviour that found this bug must survive it."""
    books = {"paper": SimpleNamespace(positions={}),
             "paper_mcx": SimpleNamespace(positions={})}
    bot = _bot(brokers=())
    bot.orchestrator.portfolio_store = SimpleNamespace(
        load_account=lambda aid: books[aid], save_account=lambda a: None)
    assert bot._record_exit_reason("NOTHING26NOV1CE", "Loss triggered") is False


# ================================ nobody hand-rolls this list a fourth time
def test_neither_caller_builds_its_own_account_list():
    """A list built by hand at each call site is a list that will be wrong
    again - it has been wrong three times. Both callers must ask."""
    for method in (Bot._account_open_premium, Bot._record_exit_reason):
        src = textwrap.dedent(inspect.getsource(method))
        assert "_paper_account_ids()" in src, (
            f"{method.__name__} must ask for the account list")
        assert "paper_venues" not in src, (
            f"{method.__name__} is building the list by hand again")


def test_the_only_place_that_knows_names_the_mcx_venue():
    src = textwrap.dedent(inspect.getsource(Bot._paper_account_ids))
    assert "mcx_venue" in src
    assert "paper_venue" in src
    assert "paper_venues" in src


def test_the_exposure_constant_was_not_touched():
    """This fix TIGHTENS a measurement. It must not have moved the ceiling,
    which is commander-approved (2026-11-09, "go with the p90 row").
    """
    from bots.execution import exposure

    assert exposure.ACCOUNT_CAPITAL == 100_000.0
    assert exposure.DRAWDOWN_BUDGET_PCT == 8.0
    assert exposure.STOP_OUT_LOSS_PCT == 16.80
    assert exposure.MAX_TOTAL_PREMIUM == pytest.approx(47_619.0, abs=1.0)


def test_no_other_caller_still_hand_rolls_the_pair():
    """A rail on the whole module, so a new call site cannot reintroduce it.

    Asks the AST rather than the text: the docstrings here explain the wrong
    pattern on purpose, and a text scan fires on the prose that documents the
    trap it guards.
    """
    src = (_repo_root() / "src" / "bots" / "autonomous"
           / "autonomous_bot.py").read_text(encoding="utf-8")
    offenders = []
    for fn in (n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef)):
        if fn.name == "_paper_account_ids":
            continue
        names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        consts = {n.value for n in ast.walk(fn)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if "paper_venues" in names or "paper_venues" in consts:
            offenders.append(fn.name)
    assert not offenders, (
        f"these build the account list by hand instead of calling "
        f"_paper_account_ids(): {offenders}")
