"""Not one of 417 closed positions ever recorded why it closed.

2026-11-09. A NATURALGAS put closed 11 minutes after it opened for a net loss
of 1,074, and the ledger row said `failure_reason = None`. Asked why, the
answer turned out to be that the field has NEVER held a real exit reason. Its
only non-null values in the whole ledger are the 292 PHANTOM annotations
written by hand for the 2026-07-15 reduce-only runaway.

THE REASON WAS COMPUTED CORRECTLY AND THROWN AWAY. One line above the write,
the log says:

    Kakashi Risk Analysis: Loss triggered on NATURALGAS26NOV285PE.
    Causes: Price violated stop-loss threshold; Execution slippage drag 0.47%

That answer existed. It just never reached the ledger, because:

  1. THE WRONG KEY. `UPDATE positions SET failure_reason = ? WHERE
     position_id = ?` was given `tracking.get("decision_id", "UNKNOWN")`.
     Positions are keyed by UUIDs; a decision id never matches one, and when
     the key was missing the literal string "UNKNOWN" matched nothing either.

  2. A DEAD TABLE. The companion `UPDATE trades` keyed correctly, on a table
     that has never held a single real row.

  3. SILENCE. A zero-row UPDATE is not an error in SQLite. The try/except
     around it could only see exceptions, so a write that did nothing was
     indistinguishable from a write that worked - for every exit Hokage has
     ever taken.

Fault 3 is the one that matters. Faults 1 and 2 are ordinary bugs; it was the
silence that let them live for months in a field three dashboards read.

WIDENED WHILE FIXING IT. The only writer ran `if not is_win`, so even a
working version would have left every winner blank. A winner that cannot say
whether it hit its target or was closed by the clock is as unanalysable as a
loser that cannot name its stop, and the thesis-stop measurement needs both.
"""
from __future__ import annotations

import ast
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

BOT = ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py"

from bots.portfolio.models import Account, Position  # noqa: E402
from bots.portfolio.models import TradeDirection, TradeStatus  # noqa: E402


# ======================================================= the shape of the fix
def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(BOT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise AssertionError(f"{name} not found")


def test_no_raw_sql_keys_a_position_by_a_trade_id():
    """The original defect, pinned at the source. Any UPDATE of
    `positions.failure_reason` keyed by something called a trade or decision
    id is the same bug returning."""
    src = ast.unparse(_method("_log_post_mortem_failure"))
    assert "UPDATE positions" not in src
    assert "UPDATE trades" not in src
    assert "trade_id" not in _method_args("_log_post_mortem_failure"), (
        "a trade_id parameter here invites keying off it again")


def _method_args(name: str) -> list[str]:
    return [a.arg for a in _method(name).args.args]


def test_the_reason_is_recorded_for_every_exit_not_only_losses():
    """The call must sit OUTSIDE the `if not is_win` branch."""
    tree = ast.parse(BOT.read_text(encoding="utf-8"))
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "is_win" in ast.unparse(node.test):
            if "_record_exit_reason" in ast.unparse(node):
                guarded = True
    assert not guarded, (
        "_record_exit_reason is inside an is_win branch, so one outcome "
        "silently keeps no reason")
    assert "_record_exit_reason" in BOT.read_text(encoding="utf-8")


def test_a_write_that_lands_nowhere_is_logged_as_an_error():
    """THE LESSON. Faults 1 and 2 were ordinary bugs; this is what let them
    survive. A recorder that can miss must say when it misses."""
    src = ast.unparse(_method("_record_exit_reason"))
    assert "logger.error" in src
    assert "only in" in src or "could not be recorded" in src


# ============================================================= the behaviour
class _Store:
    """A portfolio store that round-trips, like the SQLite one."""

    def __init__(self, accounts: dict[str, Account]):
        self.accounts = accounts
        self.saves: list[str] = []

    def load_account(self, account_id: str) -> Account:
        return self.accounts[account_id]

    def save_account(self, account: Account) -> None:
        self.saves.append(account.account_id)


class _Venue:
    def __init__(self, account_id: str):
        self._account_id = account_id


class _Orchestrator:
    def __init__(self, store, account_ids):
        self.portfolio_store = store
        self.paper_venue = _Venue(account_ids[0])
        self.paper_venues = {f"b{i}": _Venue(a)
                             for i, a in enumerate(account_ids[1:], start=1)}


def _position(market: str, pid: str, opened: dt.datetime,
              reason: str | None = None) -> Position:
    return Position(
        position_id=pid, market=market, direction=TradeDirection.LONG,
        quantity=1250.0, entry_price=14.7, current_price=13.9,
        unrealized_pnl=0.0, realized_pnl=-1000.0, status=TradeStatus.CLOSED,
        opened_at=opened, closed_at=opened + dt.timedelta(minutes=11),
        failure_reason=reason)


@pytest.fixture
def bot():
    """The real method, bound to a stand-in with only what it touches.

    Constructing an AutonomousTradingBot boots half the system; the method
    under test reads `self.orchestrator` and nothing else.
    """
    from bots.autonomous.autonomous_bot import AutonomousTradingBot

    class Stub:
        _record_exit_reason = AutonomousTradingBot._record_exit_reason

    return Stub()


def test_the_reason_lands_on_the_position(bot):
    pos = _position("NATURALGAS26NOV285PE", "a4d06f96-uuid",
                    dt.datetime(2026, 11, 9, 17, 47))
    account = Account(account_id="paper_mcx", initial_balance=100000.0,
                      cash=100000.0, currency="INR",
                      positions={pos.position_id: pos})
    store = _Store({"paper_mcx": account})
    bot.orchestrator = _Orchestrator(store, ["paper_mcx"])

    assert bot._record_exit_reason("NATURALGAS26NOV285PE", "Stop-Loss hit")
    assert pos.failure_reason == "Stop-Loss hit"
    assert store.saves == ["paper_mcx"], "the change must be persisted"


def test_a_decision_id_would_have_matched_nothing(bot):
    """Why the original missed: the id it keyed on is not the position's."""
    pos = _position("NATURALGAS26NOV285PE", "a4d06f96-781e-422d-b26c",
                    dt.datetime(2026, 11, 9, 17, 47))
    account = Account(account_id="paper_mcx", initial_balance=100000.0,
                      cash=100000.0, currency="INR",
                      positions={pos.position_id: pos})
    bot.orchestrator = _Orchestrator(_Store({"paper_mcx": account}),
                                     ["paper_mcx"])
    assert pos.position_id != "decision-2026-11-09-001"
    # Found by symbol, so it lands regardless of any decision id.
    assert bot._record_exit_reason("NATURALGAS26NOV285PE", "Stop-Loss hit")


def test_the_newest_position_in_that_symbol_wins(bot):
    """The same contract can be traded more than once in a session. The one
    that just closed is the most recently opened."""
    old = _position("GOLDM26NOV138500PE", "old-uuid",
                    dt.datetime(2026, 11, 9, 10, 0), reason="Target hit")
    new = _position("GOLDM26NOV138500PE", "new-uuid",
                    dt.datetime(2026, 11, 9, 17, 47))
    account = Account(account_id="paper_mcx", initial_balance=100000.0,
                      cash=100000.0, currency="INR",
                      positions={old.position_id: old, new.position_id: new})
    bot.orchestrator = _Orchestrator(_Store({"paper_mcx": account}),
                                     ["paper_mcx"])

    bot._record_exit_reason("GOLDM26NOV138500PE", "Stop-Loss hit")
    assert new.failure_reason == "Stop-Loss hit"
    assert old.failure_reason == "Target hit", "an earlier trade is not rewritten"


def test_a_phantom_annotation_is_never_overwritten(bot):
    """Those 292 rows are the audit record of the reduce-only runaway. They
    are deliberately retained and must not be replaced by an exit note."""
    phantom = _position(
        "CRUDEOIL26JUL7750CE", "phantom-uuid",
        dt.datetime(2026, 7, 15, 11, 0),
        reason="PHANTOM: minted by the 2026-07-15 reduce-only exit runaway")
    account = Account(account_id="paper_mcx", initial_balance=100000.0,
                      cash=100000.0, currency="INR",
                      positions={phantom.position_id: phantom})
    bot.orchestrator = _Orchestrator(_Store({"paper_mcx": account}),
                                     ["paper_mcx"])

    assert bot._record_exit_reason("CRUDEOIL26JUL7750CE", "Stop-Loss hit") is False
    assert phantom.failure_reason.startswith("PHANTOM")


def test_it_searches_every_paper_account(bot):
    """Index and commodity books are separate accounts, and the exit path is
    reached from both. A fix that only looked at `paper_venue` would have
    silently skipped every MCX exit - the same single-venue blind spot as the
    2026-08-17 exit-loop bug."""
    pos = _position("NATURALGAS26NOV285PE", "mcx-uuid",
                    dt.datetime(2026, 11, 9, 17, 47))
    main = Account(account_id="paper_main", initial_balance=100000.0,
                   cash=100000.0, currency="INR", positions={})
    mcx = Account(account_id="paper_mcx", initial_balance=100000.0,
                  cash=100000.0, currency="INR",
                  positions={pos.position_id: pos})
    store = _Store({"paper_main": main, "paper_mcx": mcx})
    bot.orchestrator = _Orchestrator(store, ["paper_main", "paper_mcx"])

    assert bot._record_exit_reason("NATURALGAS26NOV285PE", "Stop-Loss hit")
    assert pos.failure_reason == "Stop-Loss hit"


def test_an_unmatched_symbol_returns_false_and_does_not_raise(bot):
    """It must not take the trading loop down, and it must not pretend."""
    account = Account(account_id="paper_mcx", initial_balance=100000.0,
                      cash=100000.0, currency="INR", positions={})
    bot.orchestrator = _Orchestrator(_Store({"paper_mcx": account}),
                                     ["paper_mcx"])
    assert bot._record_exit_reason("NOSUCH26NOV1CE", "Stop-Loss hit") is False


def test_an_empty_reason_writes_nothing(bot):
    """Absent is not a reason. Writing "" would turn "we never recorded one"
    into "it closed for no reason", which reads as an answer."""
    pos = _position("GOLDM26NOV138500PE", "uuid",
                    dt.datetime(2026, 11, 9, 17, 47))
    account = Account(account_id="paper_mcx", initial_balance=100000.0,
                      cash=100000.0, currency="INR",
                      positions={pos.position_id: pos})
    bot.orchestrator = _Orchestrator(_Store({"paper_mcx": account}),
                                     ["paper_mcx"])
    assert bot._record_exit_reason("GOLDM26NOV138500PE", None) is False
    assert bot._record_exit_reason("GOLDM26NOV138500PE", "") is False
    assert pos.failure_reason is None


def test_a_broken_orchestrator_does_not_break_the_exit(bot):
    """An exit that completes with no reason recorded is far better than an
    exit that does not complete."""
    bot.orchestrator = object()
    assert bot._record_exit_reason("GOLDM26NOV138500PE", "Stop-Loss hit") is False
