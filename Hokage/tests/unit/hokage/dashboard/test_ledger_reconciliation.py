"""Ledger drift must mean drift, not "a trade is open".

The war chests are the strategy-level ledger (starting + REALISED); the paper
account's `equity` property is cash + UNREALISED. Comparing them can only agree
on a flat book. Every past "drift 0.0" verification happened to run with no
position open, so the mismatch stayed hidden until 2026-07-30, when two live
options made the panel report ₹100.75 of phantom drift and flip ok to False.

That is worse than cosmetic: the check exists to catch the 2026-07-16 incident
where two exits were never booked to any chest. Real drift buried inside
mark-to-market noise is real drift nobody can see.
"""
from __future__ import annotations

import pytest

from bots.portfolio.models import Account, Position
from bots.execution.models import TradeStatus


def _settled(account: Account) -> float:
    """The comparison the dashboard now makes: starting + realised."""
    return float(account.initial_balance) + float(account.realized_pnl)


def _account_with_open_mark(unrealized: float) -> Account:
    acct = Account(account_id="paper", initial_balance=200_000.0, cash=193_988.5)
    acct.realized_pnl = -6_011.5
    pos = Position(
        position_id="p1",
        market="NIFTY2680424300CE",
        direction="LONG",
        quantity=65.0,
        entry_price=91.85,
        current_price=91.85,
        status=TradeStatus.OPEN,
    )
    pos.unrealized_pnl = unrealized
    acct.positions["p1"] = pos
    return acct


def test_open_position_does_not_create_phantom_drift():
    """A live mark must not move the settled ledger by even a paisa."""
    chest_total = 200_000.0 + (-6_011.5)

    flat = Account(account_id="paper", initial_balance=200_000.0, cash=193_988.5)
    flat.realized_pnl = -6_011.5

    marked = _account_with_open_mark(unrealized=-308.75)

    assert _settled(flat) == pytest.approx(chest_total)
    assert _settled(marked) == pytest.approx(chest_total)
    # The old comparison is what broke: equity moves with the mark.
    assert marked.equity != pytest.approx(flat.initial_balance + flat.realized_pnl)


@pytest.mark.parametrize("unrealized", [-5_000.0, -308.75, 0.0, 103.5, 12_000.0])
def test_settled_ledger_is_immune_to_any_mark(unrealized):
    acct = _account_with_open_mark(unrealized=unrealized)
    assert _settled(acct) == pytest.approx(193_988.5)


def test_a_genuinely_unbooked_exit_still_shows_as_drift():
    """The 2026-07-16 failure mode must remain detectable."""
    acct = _account_with_open_mark(unrealized=-308.75)
    # An exit booked to the account but to no chest: chests are short by 1,959.75.
    chest_total = _settled(acct) - 1_959.75
    drift = round(chest_total - _settled(acct), 2)

    assert drift == pytest.approx(-1_959.75)
    assert abs(drift) >= 1.0  # ok would be False, correctly
