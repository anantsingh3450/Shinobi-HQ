"""Excursion envelope (MFE/MAE) — the raw material for component attribution.

MFE (max favourable excursion) measures how far price ran in the position's
favour = ENTRY quality. Capture efficiency (realized / MFE) separates a bad
exit from a bad entry. These were previously mocked constants (-2.0 and
return_pct + 1.0), which made every attribution downstream fiction. They are
now measured live during the hold.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from integrations.brokers.models import OrderSide


@pytest.fixture
def bot():
    b = AutonomousTradingBot.__new__(AutonomousTradingBot)
    b.intraday_override = {}
    b._get_validated_live_price = MagicMock(return_value=(None, "no data"))
    b._now_ist = lambda: datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc)
    return b


def test_excursion_pcts_long_signs_favourable_and_adverse():
    mfe, mae = AutonomousTradingBot._excursion_pcts(
        entry_price=100.0, peak_price=110.0, trough_price=95.0, side="BUY"
    )
    assert mfe == 10.0   # ran 10% our way
    assert mae == -5.0   # took 5% of heat


def test_excursion_pcts_short_inverts_direction():
    """For a short, price FALLING is favourable — the signs must invert, or a
    profitable short would be scored as a losing entry."""
    mfe, mae = AutonomousTradingBot._excursion_pcts(
        entry_price=100.0, peak_price=90.0, trough_price=104.0, side="SELL"
    )
    assert mfe == 10.0
    assert mae == -4.0


def test_excursion_pcts_unknown_extreme_stays_none_never_zero():
    """A missing extreme must read as unknown so attribution skips the trade —
    a fabricated 0.0 would score the entry as 'never went our way'."""
    mfe, mae = AutonomousTradingBot._excursion_pcts(
        entry_price=100.0, peak_price=None, trough_price=None, side="BUY"
    )
    assert mfe is None and mae is None

    # A zero/absent entry price cannot yield a percentage of anything.
    assert AutonomousTradingBot._excursion_pcts(0.0, 110.0, 90.0, "BUY") == (None, None)


def test_option_ladder_records_both_extremes_during_hold(bot):
    """The premium ladder must widen the envelope on every evaluation, so a
    spike that later round-trips is still credited to the entry."""
    tracking = {"entry_price": 200.0, "peak_price": 200.0}

    # Premium spikes to 260 (entry was right), then round-trips back to 205.
    for premium in (260.0, 205.0):
        _, _, tracking = bot._evaluate_option_exit_ladder(
            symbol="NIFTY25JUL24300CE",
            quantity=75.0,
            entry_premium=200.0,
            current_premium=premium,
            tracking=tracking,
            now_ist=bot._now_ist(),
            is_mcx=False,
        )

    assert tracking["peak_price"] == 260.0
    assert tracking["trough_price"] == 200.0

    mfe, _ = AutonomousTradingBot._excursion_pcts(
        entry_price=200.0, peak_price=tracking["peak_price"],
        trough_price=tracking["trough_price"], side="BUY",
    )
    # Exit at 205 realized +2.5% of an available +30% — a good entry the exit
    # gave back, which is exactly what capture efficiency must expose.
    assert mfe == 30.0
    realized_pct = (205.0 - 200.0) / 200.0 * 100.0
    assert round(realized_pct / mfe, 4) == 0.0833


def test_generic_ladder_records_trough_for_long(bot):
    """Non-option path (futures/equity) must track the adverse leg too."""
    tracking = {"entry_price": 100.0, "peak_price": 100.0, "initial_qty": 1.0}
    bot._get_atr_for_symbol = MagicMock(return_value=5.0)

    _, _, tracking = bot._evaluate_cascading_exits(
        symbol="NIFTY", side=OrderSide.BUY, quantity=1.0,
        average_price=100.0, current_price=97.0,
        tracking=tracking, is_tick=True, venue=None,
    )

    assert tracking["trough_price"] == 97.0
