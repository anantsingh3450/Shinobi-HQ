"""The trail protected one trade in 107. Now it arms at +5% and holds breakeven.

Measured 2026-08-24 over 107 distinct trades, after the corpus was deduplicated
and put excursions were sign-corrected:

    50 trades reached profit.  TWENTY finished in a LOSS.
    Every one of the twenty had peaked under +11.11%, so the trail — which was
    only offered once peak*(1-0.10) cleared entry — never armed on any of them.

        SENSEX2681378500PE   peaked +8.13%   ended -22.11%
        SENSEX2672378000CE   peaked +7.14%   ended -28.36%
        NIFTY2680424300CE    peaked +6.04%   ended -17.64%

    274 percentage-points of premium surrendered, mean 13.70pp each, with
    nothing underneath but the -12% hard backstop.

THE SHAPE OF THE FIX. Arming earlier with the OLD floor would have broken the
rung's founding invariant: at +5% peak, peak*0.90 = 0.945 of entry, so an armed
trail would sit BELOW entry and permit a winner to become a loser. Taking
max(trail, entry) keeps that invariant exactly and adds a breakeven floor for
the modest winners the proportional trail could never reach.

WHAT THESE TESTS PIN, in order of importance:
  1. the floor never sits below entry, at any peak
  2. it arms at +5% rather than +11.11%
  3. a large winner still gets the proportional trail, not a breakeven scratch
  4. the reason string still contains TRAIL_LOCK, or the exit grader silently
     regrades every trailing exit as PREMATURE again
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

FRACTION = Bot._OPTION_TRAIL_LOCK_FRACTION
ARM = Bot._OPTION_TRAIL_ARM_PCT


def _floor(entry: float, peak: float):
    """The shipped floor rule, isolated. Kept honest by
    test_the_ladder_uses_max_of_trail_and_entry below."""
    if peak < entry * (1.0 + ARM):
        return None
    return max(peak * (1.0 - FRACTION), entry)


# --------------------------------------------------------------- the invariant
@pytest.mark.parametrize("peak_pct", [5.0, 6.0, 8.13, 11.11, 15.0, 30.0, 100.0])
def test_the_floor_is_never_below_entry(peak_pct):
    """The rung exists so a winner cannot round-trip into a loser. Arming
    earlier must not buy protection by giving that up."""
    entry = 100.0
    f = _floor(entry, entry * (1 + peak_pct / 100.0))
    assert f is not None
    assert f >= entry, f"peak +{peak_pct}% put the floor at {f}, below entry"


# ------------------------------------------------------------------- arming
def test_it_does_not_arm_below_five_percent():
    assert _floor(100.0, 104.9) is None


def test_it_arms_at_five_percent():
    assert _floor(100.0, 105.0) == pytest.approx(100.0)


def test_the_old_threshold_left_these_twenty_unprotected():
    """The give-backs, at their real peaks. Under the old rule none armed."""
    for peak_pct, ended in ((8.13, -22.11), (7.14, -28.36), (6.04, -17.64),
                            (7.02, -9.26), (5.34, -12.64)):
        entry = 100.0
        peak = entry * (1 + peak_pct / 100.0)
        assert peak * (1 - FRACTION) < entry, "old rule would have armed"
        f = _floor(entry, peak)
        assert f == pytest.approx(entry), "new rule must hold breakeven"
        assert f > entry * (1 + ended / 100.0), "must beat where it actually ended"


# ------------------------------------------------- large winners keep the trail
def test_a_large_winner_still_gets_the_proportional_trail():
    """Above +11.11% the trail out-floors breakeven and must win, or a runner
    would be capped at entry and the rung would lose its original purpose."""
    entry, peak = 100.0, 130.0
    f = _floor(entry, peak)
    assert f == pytest.approx(117.0)
    assert f > entry


def test_the_crossover_is_exactly_the_old_arming_point():
    """At +11.11% the two floors coincide — below it breakeven binds, above it
    the trail does. The old rule was that crossover with nothing beneath."""
    entry = 100.0
    crossover = entry / (1 - FRACTION)
    assert _floor(entry, crossover) == pytest.approx(entry, abs=0.01)
    assert _floor(entry, crossover * 1.10) > entry


# ------------------------------------------------------------ the reason string
def test_both_labels_still_say_trail_lock():
    """position_review greps the reason for TRAIL_LOCK to grade an exit
    TRAILING. Lose the token and every trailing exit silently becomes
    PREMATURE again — the exact bug fixed on 2026-08-19."""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(Bot._evaluate_option_exit_ladder))
    tree = ast.parse(src)
    literals = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    trail_labels = [s for s in literals if "TRAIL_LOCK" in s]
    assert len(trail_labels) >= 2, (
        "both the breakeven and proportional labels must carry TRAIL_LOCK"
    )


def test_the_ladder_uses_max_of_trail_and_entry():
    """Guards production against the helper above drifting from it."""
    import inspect

    src = inspect.getsource(Bot._evaluate_option_exit_ladder)
    assert "max(trail_floor, entry_premium)" in src, (
        "the floor must be the greater of the trail and entry, or an early arm "
        "puts it below entry and a winner can become a loser"
    )
    assert "_OPTION_TRAIL_ARM_PCT" in src, "arming must read the constant"
