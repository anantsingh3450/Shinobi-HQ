"""Every risk ceiling in Hokage was per-strategy, so the account had none.

2026-11-09, approved by the commander: "go with the p90 row".

`MAX_PREMIUM_CHEST_FRACTION` caps one position at a third of one chest, and
that is a good rail. But with seven live strategies each holding a 1,00,000
chest, four of them correctly sized against their own chest could still carry
1,32,000 of premium on a 1,00,000 account. Nothing in the entry path knew what
the OTHER strategies were holding.

`max_portfolio_exposure_pct` already existed and looked like this rail. It is
computed in `capital_preservation` and `personality_engine`, written to
capital_preservation.json, read back by the briefing and the explainability
aggregator - and READ BY NOTHING THAT CAN BLOCK A TRADE. Its sibling
`max_allocation_pct` IS enforced, which is what made the gap hard to see. A
number that is displayed but not obeyed is the same shape as a health score of
100 on a process that has been dead for 3h39m.

THE NUMBER CAME FROM MEASURED LOSSES, NOT FROM A FRACTION OF CAPITAL. 74 real
losing trades, phantoms excluded: median 7.76%, p90 16.80%, worst 28.36% of
premium. Against the 8% drawdown the go-live gate allows, the budget is
capital x 8% / loss-per-stop-out - which gives 28,204 at the worst loss,
47,619 at the p90 and 1,03,150 at the median. Three defensible answers, so the
commander picked the row rather than being handed a number.

IT MUST NOT RECOMPUTE ITSELF. Re-deriving the budget from the live loss
distribution would make it GROW on a quiet month: the system raising its own
risk ceiling with nobody deciding anything, which is the self-evolution that
was closed on 2026-08-26 and again in the promotion ladder earlier today.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from bots.execution import exposure  # noqa: E402
from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION  # noqa: E402

#: Lot costs priced live on 2026-11-09, for the arithmetic the commander chose.
SENSEX, NIFTY, GAS, GOLDM = 12_039.0, 17_024.0, 19_375.0, 27_440.0


# ================================================== the number and its basis
def test_the_budget_is_the_p90_row():
    """8% of 1,00,000 divided by a 16.80% stop-out."""
    assert exposure.ACCOUNT_CAPITAL == 100_000.0
    assert exposure.DRAWDOWN_BUDGET_PCT == 8.0
    assert exposure.STOP_OUT_LOSS_PCT == pytest.approx(16.80)
    assert exposure.MAX_TOTAL_PREMIUM == pytest.approx(47_619.05, abs=0.5)


def test_the_budget_is_derived_not_typed():
    """The three inputs must be the only place a risk decision lives. A
    literal would let the stated reasoning and the enforced number drift."""
    src = (ROOT / "src" / "bots" / "execution" / "exposure.py").read_text(
        encoding="utf-8")
    assert "MAX_TOTAL_PREMIUM = round(" in src
    assert "ACCOUNT_CAPITAL * (DRAWDOWN_BUDGET_PCT" in src


def test_the_drawdown_matches_the_go_live_gate():
    """Two copies of one limit is how they come to disagree. `src` must not
    import `tools`, so the duplicate is asserted equal instead."""
    from live_readiness import MAX_DRAWDOWN_PCT

    assert exposure.DRAWDOWN_BUDGET_PCT == MAX_DRAWDOWN_PCT


def test_the_loss_basis_is_recorded_with_its_date():
    """A rate without a date is a rate nobody can re-check."""
    assert "2026-11-09" in exposure.STOP_OUT_LOSS_BASIS
    assert "74" in exposure.STOP_OUT_LOSS_BASIS


def test_it_does_not_read_the_live_loss_distribution():
    """THE SELF-LOOSENING TRAP. If the budget tracked measured losses, a quiet
    month would raise the risk ceiling on its own."""
    src = (ROOT / "src" / "bots" / "execution" / "exposure.py").read_text(
        encoding="utf-8")
    assert "sqlite3" not in src
    assert "positions" not in src.split('"""')[2] if '"""' in src else True
    flat = " ".join(src.split())
    assert "DOES NOT RECOMPUTE ITSELF" in flat


# ====================================================== what it actually does
def test_two_cheapest_assets_fit_and_a_third_does_not():
    """The p90 row, as behaviour: SENSEX + NIFTY = 29,063 of a 47,619 budget."""
    assert exposure.check(0.0, SENSEX).allowed
    assert exposure.check(SENSEX, NIFTY).allowed
    assert not exposure.check(SENSEX + NIFTY, GAS).allowed
    assert not exposure.check(SENSEX + NIFTY, GOLDM).allowed


def test_any_single_lot_still_fits():
    """The rail bounds CONCURRENCY, not which assets may be traded. GOLDM is
    the widest measured margin and must remain tradable on its own."""
    for lot in (SENSEX, NIFTY, GAS, GOLDM):
        assert exposure.check(0.0, lot).allowed


def test_gas_is_not_parked_by_this():
    """The commander directed gas stays unparked and trading. A total-premium
    rail honours that - gas keeps scanning and trades when there is room -
    where parking it would have contradicted the directive."""
    assert exposure.check(0.0, GAS).allowed
    assert exposure.check(SENSEX, GAS).allowed


def test_a_position_exactly_filling_the_budget_is_allowed():
    assert exposure.check(0.0, exposure.MAX_TOTAL_PREMIUM).allowed
    assert not exposure.check(0.0, exposure.MAX_TOTAL_PREMIUM + 1).allowed


def test_remaining_never_goes_negative():
    """An account already over budget has no room, not negative room - a
    negative ceiling fed to `//` would size a short position."""
    assert exposure.remaining_budget(exposure.MAX_TOTAL_PREMIUM * 3) == 0.0
    assert exposure.remaining_budget(-5_000.0) == exposure.MAX_TOTAL_PREMIUM


def test_the_refusal_says_why_and_with_what_numbers():
    verdict = exposure.check(SENSEX + NIFTY, GOLDM)
    assert not verdict.allowed
    assert "already open" in verdict.reason
    assert "47,619" in verdict.reason
    assert "16.80%" in verdict.reason


# ============================================ it is wired to the sizing seam
def test_the_router_takes_the_account_figure():
    import inspect

    from bots.execution.options_router import OptionsRouter

    sig = inspect.signature(OptionsRouter.route_to_options)
    assert "portfolio_open_premium" in sig.parameters
    assert sig.parameters["portfolio_open_premium"].default is None


def test_every_entry_path_supplies_it():
    """Three call sites: the index arena, the MCX arena and manual entry. One
    left unwired is a path with no account ceiling at all."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    calls = src.count("route_to_options(")
    wired = src.count("portfolio_open_premium=self._account_open_premium()")
    assert calls == wired, (
        f"{calls} call sites but {wired} pass the account exposure")


def test_an_unmeasurable_exposure_blocks_rather_than_allows():
    """`_account_open_premium` returns infinity on failure, which leaves no
    room. `_strategy_covers` already fails OPEN on an empty scope and that is
    a bug, not a precedent."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _account_open_premium")[1].split(
        "def _record_exit_reason")[0]
    assert 'float("inf")' in body
    assert "UNKNOWN BLOCKS" in body
    assert exposure.remaining_budget(float("inf")) == 0.0


def test_the_exposure_uses_entry_premium_not_the_mark():
    """The budget came from losses measured against ENTRY premium, so the
    exposure must share that base. Marking to market would relax the rail
    precisely when positions were losing."""
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _account_open_premium")[1].split(
        "def _record_exit_reason")[0]
    assert "entry_price" in body
    assert "current_price" not in body


def test_phantoms_carry_no_risk():
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _account_open_premium")[1].split(
        "def _record_exit_reason")[0]
    assert "PHANTOM" in body


def test_it_searches_every_paper_account():
    """Index and commodity books are separate accounts. Counting only one
    would under-report exposure by the whole of the other league.

    THIS TEST PASSED FOR EIGHT MONTHS WHILE THE BUG IT DESCRIBES WAS LIVE.
    It asserted `"paper_venues" in body and "paper_venue" in body` - two
    names that were both present and neither of which is the MCX venue.
    `mcx_venue` is its own attribute on the orchestrator, so commodity
    premium consumed none of the budget: on 2026-11-11 a GOLDM put of 25,125
    opened against a 47,619 ceiling and this rail measured zero.

    A rail that checks for a NAME is not a rail on the behaviour. So it now
    MEASURES, with a position in the MCX account and nothing in the index
    one - which is the exact state that used to read as an empty account.
    """
    from types import SimpleNamespace

    from bots.autonomous.autonomous_bot import AutonomousTradingBot
    from bots.execution.models import TradeStatus

    class Stub:
        _account_open_premium = AutonomousTradingBot._account_open_premium
        _paper_account_ids = AutonomousTradingBot._paper_account_ids

    mcx_only = {
        "paper": SimpleNamespace(positions={}),
        "paper_mcx": SimpleNamespace(positions={"p": SimpleNamespace(
            status=TradeStatus.OPEN, entry_price=2512.5, quantity=10.0,
            failure_reason=None)}),
    }
    bot = Stub()
    bot.orchestrator = SimpleNamespace(
        paper_venue=SimpleNamespace(_account_id="paper"),
        mcx_venue=SimpleNamespace(_account_id="paper_mcx"),
        paper_venues={},
        portfolio_store=SimpleNamespace(load_account=lambda a: mcx_only[a]))

    assert bot._account_open_premium() == pytest.approx(25_125.0), (
        "MCX premium must consume the account-wide budget")


# ============================================== the per-strategy cap survives
def test_the_chest_cap_is_untouched():
    """This rail is additional, not a replacement. A single position is still
    capped at a third of its own chest."""
    assert MAX_PREMIUM_CHEST_FRACTION == 0.33
    router_src = (ROOT / "src" / "bots" / "execution"
                  / "options_router.py").read_text(encoding="utf-8")
    assert "risk_budget * MAX_PREMIUM_CHEST_FRACTION" in router_src


def test_an_account_skip_is_not_reported_as_a_chest_problem():
    """A misattributed refusal sends the next reader to fix the wrong number -
    the same way a missing boot record once read as an unreadable repository."""
    router_src = (ROOT / "src" / "bots" / "execution"
                  / "options_router.py").read_text(encoding="utf-8")
    assert "account_room" in router_src
    assert "exposure.check(" in router_src


# ====================================== the rail is EXERCISED, not just read
# 2026-11-09, found in the boot log four minutes after the restart that was
# supposed to make this rail live:
#
#   [ERROR] Account exposure could not be measured (name 'TradeStatus' is not
#   defined); treating the budget as exhausted rather than unlimited.
#
# Every test above passes against that code, because every test above reads
# the SOURCE. `_account_open_premium` used `TradeStatus` as if it were a
# module-level name in `autonomous_bot`; it is imported locally inside each
# method that needs it. The helper raised NameError on its first line of real
# work, the except returned infinity, and the fail-closed design did its job
# perfectly - it blocked every entry for the rest of the MCX session.
#
# FAIL-CLOSED HIDES A BUG EXACTLY AS WELL AS IT STOPS A TRADE. A rail whose
# only safe failure is silence must be called by a test, not grepped.
class _FakeStore:
    def __init__(self, accounts):
        self._accounts = accounts

    def load_account(self, account_id):
        return self._accounts[account_id]


class _FakeVenue:
    def __init__(self, account_id):
        self._account_id = account_id


class _FakeOrchestrator:
    def __init__(self, accounts, index_id="paper_main", mcx_ids=("paper_mcx",)):
        self.paper_venue = _FakeVenue(index_id)
        self.paper_venues = {k: _FakeVenue(k) for k in mcx_ids}
        self.portfolio_store = _FakeStore(accounts)


def _account_with(account_id, rows):
    """rows: (quantity, entry_price, status, failure_reason)"""
    from bots.execution.models import TradeDirection, TradeStatus
    from bots.portfolio.models import Account, Position

    acct = Account(account_id=account_id, initial_balance=100_000.0,
                   cash=100_000.0)
    for i, (qty, price, status, failure) in enumerate(rows):
        acct.positions[f"{account_id}-{i}"] = Position(
            position_id=f"{account_id}-{i}",
            market="NATURALGAS26NOV285PE",
            direction=TradeDirection.LONG,
            quantity=qty,
            entry_price=price,
            current_price=price * 0.5,     # halved, to catch a mark-to-market
            status=status,
            failure_reason=failure,
        )
    return acct


def _bot_with(orchestrator):
    from bots.autonomous.autonomous_bot import AutonomousTradingBot

    bot = object.__new__(AutonomousTradingBot)
    bot.orchestrator = orchestrator
    return bot


def _open():
    from bots.execution.models import TradeStatus
    return TradeStatus.OPEN


def _closed():
    from bots.execution.models import TradeStatus
    return TradeStatus.CLOSED


def test_it_runs_at_all_and_returns_a_number():
    """THE REGRESSION. This is the test that was missing on 2026-11-09."""
    orch = _FakeOrchestrator({
        "paper_main": _account_with("paper_main", [(65, 261.90, _open(), None)]),
        "paper_mcx": _account_with("paper_mcx", []),
    })
    total = _bot_with(orch)._account_open_premium()
    assert total != float("inf"), "the rail could not measure, so it blocks everything"
    assert total == pytest.approx(NIFTY, abs=1.0)


def test_it_adds_up_both_leagues():
    orch = _FakeOrchestrator({
        "paper_main": _account_with("paper_main", [(20, 601.95, _open(), None)]),
        "paper_mcx": _account_with("paper_mcx", [(1250, 15.50, _open(), None)]),
    })
    assert _bot_with(orch)._account_open_premium() == pytest.approx(
        SENSEX + GAS, abs=1.0)


def test_closed_and_phantom_rows_carry_nothing():
    orch = _FakeOrchestrator({
        "paper_main": _account_with("paper_main", [
            (20, 601.95, _closed(), None),
            (65, 261.90, _open(), "PHANTOM: 2026-07-15 reduce-only runaway"),
        ]),
        "paper_mcx": _account_with("paper_mcx", []),
    })
    assert _bot_with(orch)._account_open_premium() == 0.0


def test_it_prices_the_entry_not_the_halved_mark():
    """current_price is half of entry in the fixture above. A mark-to-market
    reading would report half the exposure and relax the rail on a loser."""
    orch = _FakeOrchestrator({
        "paper_main": _account_with("paper_main", [(65, 261.90, _open(), None)]),
        "paper_mcx": _account_with("paper_mcx", []),
    })
    assert _bot_with(orch)._account_open_premium() == pytest.approx(
        NIFTY, abs=1.0)


def test_a_broken_store_blocks_rather_than_allows():
    class _Exploding:
        def load_account(self, account_id):
            raise RuntimeError("database is locked")

    orch = _FakeOrchestrator({})
    orch.portfolio_store = _Exploding()
    assert _bot_with(orch)._account_open_premium() == float("inf")
    assert exposure.remaining_budget(float("inf")) == 0.0


def test_no_identifiable_account_blocks():
    orch = _FakeOrchestrator({}, index_id=None, mcx_ids=())
    orch.paper_venue = None
    assert _bot_with(orch)._account_open_premium() == float("inf")
