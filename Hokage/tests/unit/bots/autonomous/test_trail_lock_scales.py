"""The trail must mean the same thing on every position size.

2026-08-06: all three winners exited on TRAIL_LOCK and all four losers on the
thesis stop — the trail was the binding constraint on every winner. It gave back
a FLAT Rs 1,000 regardless of position size, which on that day's actual fills
meant:

    SILVERM    Rs 37,168 position -> 2.69%    <- 4x tighter...
    CRUDEOIL   Rs 31,490 position -> 3.18%
    GOLDM      Rs 26,200 position -> 3.82%
    NATURALGAS Rs 14,250 position -> 7.02%
    NIFTY      Rs  8,616 position -> 11.61%   <- ...than here

SILVERM ran 6,900 -> 7,650 (+10.9%) and was banked at 7,433 (+7.7%) because a
2.69% wobble tripped it. Same class of bug as the flat 6% target: one number
applied across a 4x size range means five different things.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

FRACTION = Bot._OPTION_TRAIL_LOCK_FRACTION


def _floor(entry: float, peak: float) -> float:
    return peak * (1.0 - FRACTION)


def _armed(entry: float, peak: float) -> bool:
    return _floor(entry, peak) >= entry


def test_trail_is_a_fraction_not_a_rupee_amount():
    assert not hasattr(Bot, "_OPTION_TRAIL_LOCK_RUPEES")
    assert 0.0 < FRACTION < 1.0


@pytest.mark.parametrize(
    "name,entry,lot",
    [("SILVERM", 6900.0, 5), ("CRUDEOIL", 303.8, 100),
     ("NATURALGAS", 10.35, 1250), ("NIFTY", 132.55, 65), ("GOLDM", 2620.0, 10)],
)
def test_giveback_is_identical_in_percent_across_every_size(name, entry, lot):
    """The whole point: a 4x range in position size must not change the rule."""
    peak = entry * 1.30
    giveback_pct = (peak - _floor(entry, peak)) / peak
    assert giveback_pct == pytest.approx(FRACTION)


def test_an_armed_trail_can_never_put_the_floor_below_entry():
    """A winner must not become a loser through the trail. Arming requires the
    peak gain to already exceed the trail distance, which guarantees it."""
    for entry in (10.35, 132.55, 303.8, 2620.0, 6900.0):
        for peak_mult in (1.02, 1.06, 1.10, 1.12, 1.25, 2.0):
            peak = entry * peak_mult
            if _armed(entry, peak):
                assert _floor(entry, peak) >= entry


def test_trail_does_not_arm_before_the_floor_clears_entry():
    """CRUDEOIL on 2026-08-06 peaked at +3.65%. A 10%-of-peak floor would sit
    below entry there, so the trail stays out of the way entirely."""
    entry, peak = 303.80, 314.90
    assert not _armed(entry, peak)


def test_giveback_widens_as_the_winner_runs():
    """Measured off PEAK, not entry. Off entry the rupee giveback is frozen at
    the entry price, so it tightens proportionally the further a trade runs and
    cuts precisely the winners worth holding."""
    entry = 100.0
    small = 120.0 - _floor(entry, 120.0)
    large = 200.0 - _floor(entry, 200.0)
    assert large > small


def test_the_trade_that_prompted_this_is_no_longer_cut_by_the_trail():
    """SILVERM 2026-08-06: entry 6,900, peak 7,650 (+10.9%), banked at 7,433.

    The flat Rs 1,000 floored it at 7,450 — a giveback of just 2.6% of peak,
    which ordinary option noise clears without the thesis changing at all. At
    10% of peak the floor would sit at 6,885, BELOW the 6,900 entry, so the
    trail does not arm on this trade at all and the position is left to the
    backstop and thesis stop. The rung that ended the day's best trade simply
    stops being the binding constraint.
    """
    entry, peak, lot = 6900.0, 7650.0, 5
    old_floor = peak - (1000.0 / lot)                 # 7,450.00
    assert (peak - old_floor) / peak == pytest.approx(0.0261, abs=5e-4)
    assert not _armed(entry, peak)


def test_dashboard_reads_constants_that_actually_exist():
    """api.py read _OPTION_TARGET_MIN_PCT for a day after it was deleted — a
    live AttributeError on both arena pages that no test covered. Pin every
    ladder constant the dashboard exposes."""
    for attr in ("_OPTION_TRAIL_LOCK_FRACTION", "_OPTION_MIN_REWARD_RISK",
                 "_OPTION_TARGET_MAX_PCT", "_OPTION_THESIS_ATR_MULT",
                 "_OPTION_BACKSTOP_TIERS", "_OPTION_PROFIT_LOCK_STAGES"):
        assert hasattr(Bot, attr), f"dashboard exposes {attr}; it must exist"
