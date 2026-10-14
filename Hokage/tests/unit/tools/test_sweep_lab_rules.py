"""The rules that decide whether a swept knob becomes a proposal.

2026-08-26, the commander asked why Hokage is not improving on his own. From
his own brain: 117 autopsies on disk, 0 improvement proposals, 0 applied, ever.
He could MEASURE (weekly_audit) and PRUNE (evolution Tier 1). The middle step —
try a knob at another setting and say whether it is better — was only ever done
by Claude, by hand, in a chat session.

sweep_lab is that step. What it must never become is a machine that searches a
grid and reports its maximum, because the maximum of seven noisy cells is
usually noise. These are the rules that stop it:

  1. n >= 40 on BOTH halves
  2. t >= the ship bar on BOTH halves (a flat 2.0 until 2026-10-14,
     now corrected for the size of the grid this lab searches)
  3. beats the incumbent on BOTH halves, not just the searched one
  4. hold-out gain >= 0.05 ATR

Rule 3 carries the weight. The candidate is chosen on one half and must prove
itself on the other, which is exactly the discipline that killed the crude
horizon lead (+2.06 pooled, +0.82 under geometry, nothing surviving a split).

These tests exercise the rules directly rather than through a market: the
measurement code is shared with stop_lab and holdout_lab and is exercised there,
while the DECISION is new and is where a mistake would silently ship a change.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "sweep_lab", ROOT / "tools" / "research" / "sweep_lab.py"
)
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)


def cell(n, mean, t):
    return (n, mean, t)


#: RELATIVE TO THE BAR, NOT A LITERAL. These were t=3.0 and t=2.2, which
#: silently meant "above 2.0" and "also above 2.0". On 2026-10-14 the ship bar
#: stopped being a flat 2.0 and became the value corrected for the size of the
#: grid this lab searches, so a fixed 3.0 was no longer reliably a winner.
#: Priced off the live bar, these fixtures hold whatever it becomes.
_BAR = sl.ship_bar()
GOOD = cell(80, 0.60, _BAR + 1.0)
INCUMBENT = cell(80, 0.30, _BAR - 0.2)


# ------------------------------------------------------------- the four rules
def test_a_clear_winner_is_proposed():
    ok, why = sl.survives(GOOD, GOOD, INCUMBENT, INCUMBENT)
    assert ok, why


def test_too_few_signals_on_either_half_is_refused():
    thin = cell(sl.MIN_N - 1, 0.90, _BAR + 2.0)
    assert not sl.survives(thin, GOOD, INCUMBENT, INCUMBENT)[0]
    assert not sl.survives(GOOD, thin, INCUMBENT, INCUMBENT)[0]


def test_clearing_the_bar_on_only_one_half_is_refused():
    """The FRAGILE shape — strong where it was searched, absent where it was
    not. This is what a manufactured edge looks like."""
    weak = cell(80, 0.60, 1.4)
    assert not sl.survives(GOOD, weak, INCUMBENT, INCUMBENT)[0]
    assert not sl.survives(weak, GOOD, INCUMBENT, INCUMBENT)[0]


def test_beating_the_incumbent_on_only_the_hold_out_is_refused():
    """The rule that makes the answer mean something. A candidate that wins the
    half it was selected on and loses the other has told you nothing."""
    strong_inc_train = cell(80, 0.95, 3.5)
    ok, why = sl.survives(GOOD, GOOD, strong_inc_train, INCUMBENT)
    assert not ok
    assert "today" in why


def test_a_gain_inside_the_noise_is_refused():
    barely = cell(80, INCUMBENT[1] + sl.MIN_GAIN_ATR / 2, 3.0)
    ok, why = sl.survives(barely, barely, INCUMBENT, INCUMBENT)
    assert not ok
    assert "noise" in why


def test_exactly_at_the_gain_floor_is_accepted():
    """0.35 - 0.30 is 0.04999999999999999 in binary floating point, so a
    tolerance-free `< MIN_GAIN_ATR` refused a gain of exactly the floor and said
    "gain +0.050 ATR is inside the noise" while doing it. Found by this test."""
    at = cell(80, INCUMBENT[1] + sl.MIN_GAIN_ATR, 3.0)
    ok, why = sl.survives(at, at, INCUMBENT, INCUMBENT)
    assert ok, why


# --------------------------------------------------------- plateau selection
def _scored(hold_edges: dict, knob="K"):
    return {(knob, v): {"train": cell(80, e, 3.0), "hold": cell(80, e, 3.0)}
            for v, e in hold_edges.items()}


def test_the_middle_of_a_plateau_is_chosen_over_its_best_edge():
    """NATURALGAS, 2026-08-26. The trend guard confirmed at 0.08, 0.10 and 0.12;
    0.08 scored best and 0.10 was shipped, because 0.06 had already fallen below
    the sample floor — so 0.08 sat one step from a cliff. A setting whose
    neighbours also work survives a small measurement error; the best-scoring
    boundary is the one most likely to have been lucky."""
    grid = (0.06, 0.08, 0.10, 0.12, 0.16, 0.20)
    qualified = {0.08, 0.10, 0.12}
    scored = _scored({0.08: 0.72, 0.10: 0.50, 0.12: 0.35})
    assert sl.pick(grid, qualified, scored, "K") == 0.10


def test_two_adjacent_winners_are_not_a_plateau():
    """Two cells do not establish a region, so fall back to the best hold-out
    edge rather than picking an arbitrary one of the pair."""
    grid = (1, 2, 3, 4)
    scored = _scored({2: 0.40, 3: 0.90})
    assert sl.pick(grid, {2, 3}, scored, "K") == 3


def test_scattered_winners_fall_back_to_the_best():
    grid = (1, 2, 3, 4, 5)
    scored = _scored({1: 0.40, 5: 0.90})
    assert sl.pick(grid, {1, 5}, scored, "K") == 5


def test_the_longest_run_wins_when_there_are_several():
    grid = (1, 2, 3, 4, 5, 6, 7)
    scored = _scored({1: 0.9, 2: 0.9, 4: 0.5, 5: 0.5, 6: 0.5})
    assert sl.pick(grid, {1, 2, 4, 5, 6}, scored, "K") == 5


def test_nothing_qualifying_proposes_nothing():
    assert sl.pick((1, 2, 3), set(), {}, "K") is None


# ------------------------------------------------------- per-asset variants
def test_a_per_asset_knob_is_written_into_its_own_table():
    """Edge does not travel between assets. A sweep that set the class scalar
    would move every asset the module trades — the mistake STRETCH_PCT_BY_ASSET
    was created to prevent when one crude band bought 57% more losing trades."""
    from bots.strategy.components.mcx_entries import RangeFadeEntry

    spec = RangeFadeEntry.TUNABLES["MAX_TREND_GAP_PCT"]
    live = RangeFadeEntry()
    out = sl.variants(live, "MAX_TREND_GAP_PCT", spec, "NATURALGAS", (0.30,))
    _, clone = out[0]

    assert clone.MAX_TREND_GAP_PCT_BY_ASSET["NATURALGAS"] == 0.30
    assert clone.MAX_TREND_GAP_PCT == RangeFadeEntry.MAX_TREND_GAP_PCT
    assert live.MAX_TREND_GAP_PCT_BY_ASSET["NATURALGAS"] == 0.10, (
        "the live module must never be mutated by a sweep"
    )


def test_a_none_value_clears_the_override_rather_than_storing_none():
    """`None` on the direction knob means 'both sides', which is the ABSENCE of
    an entry. Storing None would read as a scoped direction that matches
    nothing, and the module would stop trading that asset entirely."""
    from bots.strategy.components.mcx_entries import SessionShiftEntry, _direction_allowed

    spec = SessionShiftEntry.TUNABLES["DIRECTION"]
    _, clone = sl.variants(SessionShiftEntry(), "DIRECTION", spec, "GOLDM", (None,))[0]

    assert "GOLDM" not in clone.DIRECTION_BY_ASSET
    assert _direction_allowed(clone, "GOLDM", "long")
    assert _direction_allowed(clone, "GOLDM", "short")


def test_the_incumbent_of_a_table_only_knob_comes_from_its_declared_default():
    """DIRECTION has no class-level scalar to read, so without a declared
    default the sweep would compare every candidate against an AttributeError."""
    from bots.strategy.components.mcx_entries import SessionShiftEntry

    spec = SessionShiftEntry.TUNABLES["DIRECTION"]
    live = SessionShiftEntry()
    assert sl.effective(live, "DIRECTION", spec, "GOLDM") == "short"
    assert sl.effective(live, "DIRECTION", spec, "CRUDEOIL") is None


# ------------------------------------------------------------ tier discipline
@pytest.mark.parametrize("module_name", ["RangeFadeEntry", "SessionShiftEntry"])
def test_no_live_module_declares_a_sweepable_that_raises_risk(module_name):
    """Tier ASK — anything that widens a stop, raises a cap or increases size —
    may be reported but never written as a proposal. The cheapest way to keep
    that true is for no live module to declare one at all."""
    import bots.strategy.components.mcx_entries as mod

    tunables = getattr(getattr(mod, module_name), "TUNABLES", {})
    assert tunables, module_name
    for knob, spec in tunables.items():
        assert spec["tier"] == sl.TIER_PROPOSE, f"{module_name}.{knob}"
        assert not any(w in knob.upper() for w in ("STOP", "SIZE", "LOT", "RISK")), knob


def test_the_grid_keeps_its_declared_order():
    """`pick` reads adjacency off the grid to find a plateau, so re-sorting it
    would silently destroy the notion of a neighbour — and would crash outright
    on the direction grid, which mixes None with strings.

    Checked on the lines that BUILD the grid rather than on the whole function,
    which legitimately sorts the pair list for stable output."""
    import inspect

    lines = [ln.strip() for ln in inspect.getsource(sl.sweep).splitlines()
             if "grid" in ln and "=" in ln]
    assert lines, "expected the grid to be built inside sweep()"
    for line in lines:
        assert "sorted(" not in line, line


def test_a_direction_grid_survives_an_incumbent_that_is_not_in_it():
    """The grid gains the incumbent so it can be scored alongside the
    candidates. Doing that by sorting the union raises TypeError the moment the
    grid holds both None and a string, which the direction knob always does."""
    grid = (None, "long", "short")
    assert sl.pick(grid, {"long"}, _scored({"long": 0.5}, "DIRECTION"),
                   "DIRECTION") == "long"
