"""Marks must be written back to EVERY venue's book, not just the index one.

2026-08-18: a live CRUDEOIL call sat in the MCX Arena stored at its entry price
of 454.50 while it genuinely traded at 468.20 — +1,370 of unrealized P&L that
appeared nowhere. The mark-to-market write-back loaded exactly one account:

    self.orchestrator.portfolio_store.load_account(
        self.orchestrator.paper_venue._account_id     # "paper" — the INDEX book
    )

`paper_venue` is paper_main. The MCX Arena is a SEPARATE PaperVenue with
account_id "paper_mcx", so its positions were never marked at all.

EXITS WERE NEVER AFFECTED. The exit ladder fetches its own live_price and
compares against that, which is why the same CRUDEOIL position closed correctly
on TARGET_HIT an hour later. What was wrong was every number the commander
READS: MCX equity, unrealized P&L, the dashboard positions table, and the drift
panel that compares realized chests against mark-to-market equity.

This is the same shape as the exit-loop venue bug fixed the day before: the
loop was taught about multiple venues, the write-back was not. Hence a test
that pins the general rule rather than the two venues that exist today.
"""
from __future__ import annotations

import pytest

from bots.execution.models import TradeStatus


class _Position:
    def __init__(self, market: str, entry: float) -> None:
        self.market = market
        self.entry_price = entry
        self.current_price = entry
        self.unrealized_pnl = 0.0
        self.status = TradeStatus.OPEN
        self.quantity = 100.0

    def update_price(self, price: float) -> None:
        self.current_price = price
        self.unrealized_pnl = (price - self.entry_price) * self.quantity


class _Account:
    def __init__(self, positions: dict) -> None:
        self.positions = positions


class _Store:
    """Records which account_ids were loaded and which were saved."""

    def __init__(self, accounts: dict) -> None:
        self._accounts = accounts
        self.loaded: list[str] = []
        self.saved: list[str] = []

    def load_account(self, account_id: str):
        self.loaded.append(account_id)
        if account_id not in self._accounts:
            raise KeyError(account_id)
        return self._accounts[account_id]

    def save_account(self, account) -> None:
        for aid, acc in self._accounts.items():
            if acc is account:
                self.saved.append(aid)


class _Venue:
    def __init__(self, venue_id: str, account_id: str) -> None:
        self.venue_id = venue_id
        self._account_id = account_id


def _write_back(marked_to_market, positions_with_venue, store, fallback_venue):
    """The shipped write-back, isolated from the 400-line exit loop.

    Kept in lockstep with autonomous_bot.py by test_the_shipped_code_iterates_
    every_venue below, which reads the real source.
    """
    account_ids: list[str] = []
    for _pos, _venue in positions_with_venue:
        _aid = getattr(_venue, "_account_id", None)
        if _aid and _aid not in account_ids:
            account_ids.append(_aid)
    if not account_ids:
        account_ids = [fallback_venue._account_id]

    for _account_id in account_ids:
        account = store.load_account(_account_id)
        changed = False
        for position in account.positions.values():
            live = marked_to_market.get(position.market)
            if live is not None and position.status == TradeStatus.OPEN:
                position.update_price(live)
                changed = True
        if changed:
            store.save_account(account)


def test_the_exact_2026_08_18_state_mcx_position_gets_marked():
    crude = _Position("CRUDEOIL26SEP8100CE", 454.50)
    store = _Store({
        "paper": _Account({}),
        "paper_mcx": _Account({"p1": crude}),
    })
    index_venue = _Venue("paper_main", "paper")
    mcx_venue = _Venue("paper_mcx", "paper_mcx")

    _write_back({"CRUDEOIL26SEP8100CE": 468.20},
                [(crude, mcx_venue)], store, index_venue)

    assert crude.current_price == pytest.approx(468.20)
    assert crude.unrealized_pnl == pytest.approx(1370.0)
    assert "paper_mcx" in store.saved


def test_both_books_are_marked_when_both_hold_positions():
    nifty = _Position("NIFTY2681824450PE", 120.90)
    crude = _Position("CRUDEOIL26SEP8100CE", 454.50)
    store = _Store({
        "paper": _Account({"p1": nifty}),
        "paper_mcx": _Account({"p2": crude}),
    })
    index_venue = _Venue("paper_main", "paper")
    mcx_venue = _Venue("paper_mcx", "paper_mcx")

    _write_back(
        {"NIFTY2681824450PE": 131.40, "CRUDEOIL26SEP8100CE": 468.20},
        [(nifty, index_venue), (crude, mcx_venue)],
        store, index_venue,
    )

    assert nifty.current_price == pytest.approx(131.40)
    assert crude.current_price == pytest.approx(468.20)
    assert sorted(store.saved) == ["paper", "paper_mcx"]


def test_an_account_is_loaded_once_even_with_several_positions_in_it():
    a = _Position("GOLDM26AUG150000CE", 100.0)
    b = _Position("SILVERM26AUG237000PE", 200.0)
    store = _Store({"paper_mcx": _Account({"p1": a, "p2": b})})
    mcx = _Venue("paper_mcx", "paper_mcx")

    _write_back({"GOLDM26AUG150000CE": 110.0, "SILVERM26AUG237000PE": 190.0},
                [(a, mcx), (b, mcx)], store, mcx)

    assert store.loaded == ["paper_mcx"]
    assert store.saved == ["paper_mcx"]


def test_a_closed_position_is_never_re_marked():
    pos = _Position("CRUDEOIL26SEP8100CE", 454.50)
    pos.status = TradeStatus.CLOSED
    store = _Store({"paper_mcx": _Account({"p1": pos})})
    mcx = _Venue("paper_mcx", "paper_mcx")

    _write_back({"CRUDEOIL26SEP8100CE": 468.20}, [(pos, mcx)], store, mcx)

    assert pos.current_price == pytest.approx(454.50)
    assert store.saved == []


def test_a_venue_without_an_account_id_falls_back_rather_than_crashing():
    """A live broker venue has no _account_id. It must not take the paper
    write-back down with it — marks are reporting, never a reason to stop."""
    pos = _Position("NIFTY2681824450PE", 120.90)
    store = _Store({"paper": _Account({"p1": pos})})
    index_venue = _Venue("paper_main", "paper")

    class _Live:
        venue_id = "zerodha_live"

    _write_back({"NIFTY2681824450PE": 131.40},
                [(pos, _Live())], store, index_venue)

    assert pos.current_price == pytest.approx(131.40)
    assert store.saved == ["paper"]


def test_the_shipped_code_iterates_every_venue_not_just_paper_venue():
    """Guards the real source, so the helper above cannot drift from it.

    The bug was one hardcoded account_id. If that line ever comes back, the
    isolated helper would still pass while production silently stops marking
    the MCX book again.
    """
    import inspect

    from bots.autonomous.autonomous_bot import AutonomousTradingBot

    src = inspect.getsource(AutonomousTradingBot._monitor_and_manage_positions) \
        if hasattr(AutonomousTradingBot, "_monitor_and_manage_positions") else None
    if src is None:  # method renamed; fall back to the whole class
        src = inspect.getsource(AutonomousTradingBot)

    marker = "Mark the paper book to market"
    assert marker in src, "mark-to-market write-back not found"
    block = src[src.index(marker):]
    block = block[:2000]
    assert "for _account_id in account_ids:" in block, (
        "the write-back must loop over every venue's account, not one hardcoded id"
    )
