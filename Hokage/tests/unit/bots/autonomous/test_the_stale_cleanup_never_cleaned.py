"""The startup cleanup reported a clean database and had never closed a row.

2026-11-12. Approved to extend `_cleanup_stale_paper_positions` to the MCX
book; reading it found it had never worked on EITHER book. Four faults, each
of which alone would have been enough:

  1. `pos._replace(status=CLOSED)`. `Position` is a `@dataclass(slots=True)`.
     `_replace` is a NamedTuple method, so this raised AttributeError on
     every position it tried to clean - proven:

         >>> hasattr(Position(...), "_replace")
         False

  2. `_dt.fromisoformat(pos.opened_at)` assumed a string while the model
     declares `opened_at: datetime`.

  3. A bare `except Exception: pass` inside the loop swallowed both.

  4. So `cleaned` stayed 0 for ever and the function logged

         Startup cleanup: No stale paper positions found. DB is clean.

     A fabricated all-clear. Same shape as the zero-row UPDATE that hid 417
     missing exit reasons, and as the default review grades that invented
     verdicts for trades nobody had assessed.

AND IT ONLY LOOKED AT THE INDEX BOOK, which is the bug it was opened for.

A stale OPEN row blocks MaxPositionsRiskRule, so the consequence of all this
is the quietest possible failure: no entries, no error, and a log line saying
everything is fine.
"""
from __future__ import annotations

import datetime as dt
import inspect
import logging
import textwrap
from types import SimpleNamespace

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.execution.models import TradeDirection, TradeStatus
from bots.portfolio.models import Position

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 11, 12, 9, 0, tzinfo=IST)


def _pos(market, opened, status=TradeStatus.OPEN, reason=None):
    return Position(
        position_id=f"id-{market}-{opened}", market=market,
        direction=TradeDirection.LONG, quantity=10.0, entry_price=100.0,
        current_price=100.0, status=status, opened_at=opened,
        failure_reason=reason)


def _bot(books, *, load_raises=()):
    bot = object.__new__(Bot)
    bot._now_ist = lambda: NOW
    bot.orchestrator = SimpleNamespace(
        paper_venue=SimpleNamespace(_account_id="paper"),
        mcx_venue=SimpleNamespace(_account_id="paper_mcx"),
        paper_venues={},
    )
    saved = []

    def load(account_id):
        if account_id in load_raises:
            raise RuntimeError("ledger unreadable")
        return books[account_id]

    bot.orchestrator.portfolio_store = SimpleNamespace(
        load_account=load, save_account=lambda a: saved.append(a.account_id))
    bot._saved = saved
    return bot


def _book(account_id, positions):
    return SimpleNamespace(
        account_id=account_id,
        positions={p.position_id: p for p in positions})


# ======================================================= fault 1: the API
def test_a_position_cannot_be_replaced_the_namedtuple_way():
    """THE FAULT, pinned at the model. If Position ever becomes a NamedTuple
    this test should be deleted, not the production code changed back."""
    p = _pos("GOLDM26NOV1PE", dt.datetime(2026, 11, 10, 17, 0))
    assert not hasattr(p, "_replace")


def test_the_cleanup_no_longer_calls_replace():
    """ASK THE AST. Stripping `#` comments is not enough: the docstring above
    this function quotes `pos._replace(status=CLOSED)` as the thing that was
    wrong, so a text scan fires on the prose explaining the trap it guards.
    That is the third time that has happened in four days."""
    import ast

    src = textwrap.dedent(inspect.getsource(Bot._cleanup_stale_paper_positions))
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_replace"]
    assert not calls, "Position is a dataclass; _replace raises AttributeError"


# ================================================ it actually closes a row
def test_a_stale_index_position_is_closed():
    stale = _pos("NIFTY26NOV25500CE", dt.datetime(2026, 11, 10, 10, 0))
    books = {"paper": _book("paper", [stale]),
             "paper_mcx": _book("paper_mcx", [])}
    _bot(books)._cleanup_stale_paper_positions()
    assert stale.status == TradeStatus.CLOSED


def test_a_stale_mcx_position_is_closed():
    """THE BUG THIS WAS OPENED FOR. `mcx_venue` is its own attribute, so the
    commodity book was never even loaded."""
    stale = _pos("GOLDM26NOV141000PE", dt.datetime(2026, 11, 10, 17, 30))
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [stale])}
    bot = _bot(books)
    bot._cleanup_stale_paper_positions()
    assert stale.status == TradeStatus.CLOSED
    assert bot._saved == ["paper_mcx"], "only the book that changed is written"


def test_the_close_records_why():
    """A position closed with no stated reason is the defect this project
    keeps paying for."""
    stale = _pos("GOLDM26NOV141000PE", dt.datetime(2026, 11, 9, 17, 30))
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [stale])}
    _bot(books)._cleanup_stale_paper_positions()
    assert "Startup cleanup" in stale.failure_reason
    assert "2026-11-09" in stale.failure_reason
    assert "Not a market exit" in stale.failure_reason


def test_a_phantom_annotation_is_never_overwritten():
    """Those rows are the 2026-07-15 runaway's audit record."""
    stale = _pos("GOLDM26NOV1PE", dt.datetime(2026, 11, 9, 17, 30),
                 reason="PHANTOM: 2026-07-15 runaway")
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [stale])}
    _bot(books)._cleanup_stale_paper_positions()
    assert stale.status == TradeStatus.CLOSED       # it still stops blocking
    assert stale.failure_reason == "PHANTOM: 2026-07-15 runaway"


# =============================================== what it must NOT close
def test_todays_position_is_left_alone():
    fresh = _pos("GOLDM26NOV1PE", dt.datetime(2026, 11, 12, 8, 0))
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [fresh])}
    bot = _bot(books)
    bot._cleanup_stale_paper_positions()
    assert fresh.status == TradeStatus.OPEN
    assert bot._saved == []


def test_a_position_opened_after_midnight_ist_is_not_stale():
    """THE UTC TRAP. `opened_at` is stored UTC, so 00:30 IST on the 12th is
    2026-11-11T19:00Z - yesterday's DATE in UTC. Comparing UTC dates would
    force-close a position thirty minutes after it opened, as a 'prior
    session' leftover."""
    just_opened = _pos("GOLDM26NOV1PE",
                       dt.datetime(2026, 11, 11, 19, 0, tzinfo=dt.timezone.utc))
    assert just_opened.opened_at.astimezone(IST).date() == dt.date(2026, 11, 12)
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [just_opened])}
    _bot(books)._cleanup_stale_paper_positions()
    assert just_opened.status == TradeStatus.OPEN, (
        "a position opened half an hour ago is not a prior session")


def test_an_already_closed_position_is_not_touched():
    closed = _pos("GOLDM26NOV1PE", dt.datetime(2026, 11, 9, 17, 0),
                  status=TradeStatus.CLOSED)
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [closed])}
    bot = _bot(books)
    bot._cleanup_stale_paper_positions()
    assert bot._saved == []
    assert closed.failure_reason is None


@pytest.mark.parametrize("opened", [
    "2026-11-10T10:00:00",                      # naive string, as SQLite stores
    "2026-11-10T10:00:00+00:00",                # aware string
    dt.datetime(2026, 11, 10, 10, 0),           # naive datetime, as the model declares
])
def test_both_shapes_of_opened_at_are_understood(opened):
    """Fault 2: it assumed a string. The model declares a datetime, and the
    stores disagree, so both have to work."""
    stale = _pos("GOLDM26NOV1PE", opened)
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [stale])}
    _bot(books)._cleanup_stale_paper_positions()
    assert stale.status == TradeStatus.CLOSED


# =================================== silence is the fault that cost the most
def test_a_fault_is_never_reported_as_a_clean_database(caplog):
    """FAULT 4, and the reason the other three survived. The old code could
    only ever reach its own all-clear line."""
    books = {"paper_mcx": _book("paper_mcx", [])}
    bot = _bot(books, load_raises=("paper",))
    with caplog.at_level(logging.DEBUG):
        bot._cleanup_stale_paper_positions()
    assert "NOT a clean bill of health" in caplog.text
    assert "no stale paper positions in" not in caplog.text


def test_a_broken_position_is_logged_not_swallowed(caplog):
    """A position whose date cannot be read must say so. `except: pass` here
    is what made a no-op look like a clean database."""
    bad = _pos("GOLDM26NOV1PE", "not-a-timestamp")
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [bad])}
    with caplog.at_level(logging.DEBUG):
        _bot(books)._cleanup_stale_paper_positions()
    assert "could not clean" in caplog.text
    assert "GOLDM26NOV1PE" in caplog.text
    assert "NOT a clean bill of health" in caplog.text


def test_the_loop_has_no_bare_pass_handler():
    src = textwrap.dedent(inspect.getsource(Bot._cleanup_stale_paper_positions))
    import ast
    for handler in (n for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.ExceptHandler)):
        body = [s for s in handler.body if not isinstance(s, ast.Pass)]
        assert body, "an exception handler here must report, never pass"


def test_the_all_clear_names_the_accounts_it_checked(caplog):
    """"DB is clean" said nothing about WHICH database. Both books now."""
    books = {"paper": _book("paper", []),
             "paper_mcx": _book("paper_mcx", [])}
    with caplog.at_level(logging.DEBUG):
        _bot(books)._cleanup_stale_paper_positions()
    assert "no stale paper positions in paper, paper_mcx" in caplog.text


def test_it_asks_for_the_account_list_rather_than_building_one():
    src = textwrap.dedent(inspect.getsource(Bot._cleanup_stale_paper_positions))
    assert "_paper_account_ids()" in src
    assert "paper_venue._account_id" not in src
