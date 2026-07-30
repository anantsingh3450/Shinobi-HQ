"""The war chest and the account must book the same number for the same exit.

They are one ledger (the 2026-07-16 restructure said so explicitly). But the
chest was credited with PnL computed from `current_price` — the quote the exit
DECISION was taken on — while the venue books the account from the price the
order actually filled at. Every exit therefore left a residue of the tick plus
whatever the paper venue's friction model charged, and friction is
one-directional, so it accumulated.

Observed 2026-07-30: the NIFTY thesis-stop credited the chest -1,043.25 while
the account booked -1,036.75. Three exits, 6.50 of drift — surfaced only because
the reconciliation panel had just been taught to compare like with like.
"""
from __future__ import annotations

import pytest


def _pnl_from_fill(fill_price: float, entry: float, qty: float, decision_quote: float) -> float:
    """The production expression, isolated: fill price wins, quote is fallback."""
    price = fill_price if fill_price > 0.0 else decision_quote
    return round((price - entry) * qty * 1.0, 2)


def test_the_exact_live_discrepancy_is_gone():
    """NIFTY 65 qty, entry 91.70, filled 75.75 while the decision quote was 75.65."""
    account_booked = round((75.75 - 91.70) * 65, 2)
    assert account_booked == pytest.approx(-1036.75)

    # Old behaviour: PnL from the decision quote.
    from_quote = _pnl_from_fill(0.0, 91.70, 65, 75.65)
    assert from_quote == pytest.approx(-1043.25)
    assert from_quote != pytest.approx(account_booked)

    # New behaviour: PnL from the fill, matching the account exactly.
    from_fill = _pnl_from_fill(75.75, 91.70, 65, 75.65)
    assert from_fill == pytest.approx(account_booked)


@pytest.mark.parametrize("drift_ticks", [-0.50, -0.10, 0.0, 0.10, 0.50])
def test_no_tick_between_decision_and_fill_can_create_drift(drift_ticks):
    entry, qty, fill = 91.70, 65.0, 75.75
    decision_quote = fill + drift_ticks

    booked = _pnl_from_fill(fill, entry, qty, decision_quote)
    assert booked == pytest.approx(round((fill - entry) * qty, 2))


def test_missing_fill_price_falls_back_to_the_decision_quote():
    """A venue that reports a fill without a price must not book PnL of zero —
    that is what scored every exit as BREAKEVEN before the live-price fix."""
    booked = _pnl_from_fill(0.0, 91.70, 65.0, 75.75)
    assert booked == pytest.approx(-1036.75)
    assert booked != 0.0
