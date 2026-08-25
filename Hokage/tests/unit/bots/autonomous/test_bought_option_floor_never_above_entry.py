"""A bought option's protective floor must never be seeded above its entry.

2026-08-25, twice in eighty minutes:

    SILVERM26SEP245000PE   entry 6839.50   floor that fired 7181.48
    GOLDM26AUG161000PE     entry 1664.00   floor that fired 1747.20

Both are entry x 1.05 — `tracked_entry_price * (1.0 + self.tsl_percent)`, taken
because `side == OrderSide.SELL`. That `side` is the UNDERLYING SIGNAL's
direction: the router turns a bearish signal into BUY A PUT, so the position is
LONG the premium while the recorded side says SELL. Same root cause as the
inverted put excursions fixed on 2026-08-22.

A floor above entry is a ceiling, not a stop. And because the floor only ever
RISES, that seeded value out-ranked every real rung — the breakeven floor
shipped hours earlier was computed correctly, labelled correctly, and then
silently discarded because 1.05x entry was already sitting there.

Both trades won, which is luck of direction. The same seeding on a trade that
dipped to +4% before running would have cut a winner off at the knees.

THE THIRD FAULT, in the same two lines of log: the message named the floor it
had COMPUTED, not the floor that FIRED. `stop_label` is only written when a
candidate replaces the stored floor, but `stop_price` is also seeded at entry
with no label — so an unlabelled seeded floor borrowed the candidate's words
and announced "breakeven floor held at entry 6839.50" while 7181.48 did the
work.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

TSL = 0.05


def _seeded_floor(entry: float) -> float:
    """What the entry paths now seed. Kept honest by the source tests below."""
    return entry * (1.0 - TSL)


# ------------------------------------------------------------- the invariant
@pytest.mark.parametrize("entry", [6839.50, 1664.00, 11.35, 12761.00, 390.70])
def test_the_seeded_floor_is_always_below_entry(entry):
    assert _seeded_floor(entry) < entry


def test_the_two_real_cases_no_longer_seed_a_ceiling():
    for entry, fired in ((6839.50, 7181.48), (1664.00, 1747.20)):
        assert fired == pytest.approx(entry * 1.05, abs=0.02), "the observed value"
        assert _seeded_floor(entry) < entry < fired


def test_a_breakeven_floor_can_now_win_the_max():
    """The floor is chosen by max(). Breakeven equals entry, so it only takes
    effect if the seeded value sits BELOW entry."""
    entry = 6839.50
    breakeven = entry
    assert max(_seeded_floor(entry), breakeven) == pytest.approx(breakeven)


# ------------------------------------------------------------- the source
def test_no_entry_path_seeds_a_stop_above_entry():
    """The bug in one expression: `entry * (1.0 + self.tsl_percent)`."""
    src = inspect.getsource(inspect.getmodule(Bot))
    assert "1.0 + self.tsl_percent" not in src, (
        "a bought option is long its premium — call or put — so its floor is "
        "never entry * (1 + tsl)"
    )


def test_every_stop_price_seed_subtracts_the_tsl():
    module_src = inspect.getsource(inspect.getmodule(Bot))
    seeds = [ln.strip() for ln in module_src.splitlines()
             if '"stop_price"' in ln and "tsl_percent" in ln]
    assert seeds, "expected at least one seeded stop_price"
    for line in seeds:
        assert "1.0 - self.tsl_percent" in line, line


# --------------------------------------------------- the label follows the floor
def test_the_label_is_not_borrowed_when_another_floor_is_in_force():
    """An unlabelled floor must be described generically, never given the
    candidate's words."""
    src = textwrap.dedent(inspect.getsource(Bot._evaluate_option_exit_ladder))
    marker = "THE LABEL MUST DESCRIBE THE FLOOR THAT ACTUALLY FIRED"
    assert marker in src

    tree = ast.parse(src)
    # The guard must compare the computed floor against the active one.
    compares = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "abs"
    ]
    assert compares, "the label choice must test whether the computed floor is active"
    assert "TRAIL_LOCK: protective floor" in src, (
        "an unlabelled active floor needs an honest generic description"
    )
