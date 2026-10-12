"""93.1% of the tally was one bucket, and over half of it was not a decision.

The gate tally ranks what is blocking entries so the commander can see what is
worth tuning. On 2026-10-12 it said:

    ENTRY_SIGNAL   93.1%   "Entry modules stood aside (league)"

which reads as "the entry modules are the bottleneck, tune them". They were
not. Of the day's 91 stand-asides:

    26  SessionShift asked about CRUDEOIL and NATURALGAS -- assets it does
        not cover at all. Nothing was judged.
    26  SessionShift asked hours before its 17:00 window opens.
    29  MacroBreakout genuinely evaluating and declining ("price 55340.20
        still inside 55260.00-55697.00 range").
     7  index entries killed by thin volume -- the ONLY actionable signal of
        the day, buried at 4.9%.

All of the first three landed in ENTRY_SIGNAL because every message begins
"EntrySignal: ...". A coverage fact and a closed clock are not stand-aside
judgements, and no threshold can change either -- only changing the lineup
can. Counting them as tunable quality rejections points the commander at the
wrong knob.

COVERAGE exists so `tunable` tells the truth about them without anyone having
to remember the distinction.
"""
from __future__ import annotations

import pytest

from bots.autonomous.gate_analytics import (
    GATE_KINDS,
    GateId,
    GateKind,
    classify_reason,
)


# ----------------------------------------------- coverage is not a decision
@pytest.mark.parametrize("reason", [
    "EntrySignal: SessionShift: not scoped to CRUDEOIL.",
    "EntrySignal: SessionShift: not scoped to NATURALGAS.",
    "EntrySignal: RangeFade: not scoped to GOLDM.",
])
def test_an_asset_no_strategy_covers_is_COVERAGE(reason):
    assert classify_reason(reason) is GateId.STRATEGY_SCOPE


def test_coverage_is_not_tunable():
    """No threshold makes SessionShift cover CRUDEOIL. Only the lineup can,
    and reporting it as tunable sends the commander to the wrong knob."""
    from bots.autonomous.gate_analytics import GateStat

    assert GATE_KINDS[GateId.STRATEGY_SCOPE] is GateKind.COVERAGE
    from bots.autonomous.gate_analytics import GATE_LABELS

    tally = GateStat(
        gate=GateId.STRATEGY_SCOPE,
        label=GATE_LABELS[GateId.STRATEGY_SCOPE],
        kind=GATE_KINDS[GateId.STRATEGY_SCOPE],
        count=26, share_pct=28.6, assets=("CRUDEOIL",), samples=(),
    )
    assert tally.tunable is False


# ------------------------------------------- a closed clock is SESSION_TIME
@pytest.mark.parametrize("reason", [
    "EntrySignal: SessionShift: SessionShift: outside the 17:00-18:30 IST "
    "US-overlap window (720min into session).",
    "EntrySignal: SessionShift: SessionShift: outside the 17:00-19:30 IST "
    "US-overlap window (30min into session).",
])
def test_outside_the_window_is_a_time_gate_not_a_stand_aside(reason):
    """SESSION_TIME already existed; these were landing in ENTRY_SIGNAL purely
    because the message starts with the module name."""
    assert classify_reason(reason) is GateId.SESSION_TIME


def test_the_window_gate_stays_tunable():
    """Unlike coverage, a window IS a threshold -- WINDOW_END_MIN was tuned
    per-asset for GOLDM on measured evidence."""
    assert GATE_KINDS[GateId.SESSION_TIME] is GateKind.QUALITY


# --------------------------------- a real stand-aside is still a stand-aside
@pytest.mark.parametrize("reason", [
    "EntrySignal: MacroBreakout: MacroBreakout: price 55340.20 still inside "
    "55260.00-55697.00 range.",
    "EntrySignal: MacroBreakout: MacroBreakout: price 22570.00 still inside "
    "22516.40-22720.00 range.",
])
def test_a_judged_decline_is_still_ENTRY_SIGNAL(reason):
    """The cheap wrong fix is to move everything out of ENTRY_SIGNAL. A module
    that looked at the price and declined is exactly what it is for."""
    assert classify_reason(reason) is GateId.ENTRY_SIGNAL


def test_the_volume_gate_is_untouched():
    """7 of 91 today, and the only thing actually worth acting on."""
    assert classify_reason(
        "VolumeEngine: THIN_TAPE: Volume ratio 0.400x < required 0.500x "
        "(trend entry)."
    ) is GateId.VOLUME


# --------------------------------------------------------- ordering matters
def test_the_new_rules_precede_the_generic_entrysignal_rule():
    """First match wins, and every one of these messages begins
    "EntrySignal: ...". Behind the generic rule they would never fire."""
    from bots.autonomous.gate_analytics import _RULES

    keys = [k for k, _ in _RULES]
    assert keys.index("not scoped to") < keys.index("entrysignal")
    assert keys.index("overlap window") < keys.index("entrysignal")


def test_reentry_rules_still_precede_the_entry_prefix_rule():
    """Pre-existing ordering constraint: "re-entry ..." must not fall through
    to the "entry-" rule. Inserting rules must not have disturbed it."""
    from bots.autonomous.gate_analytics import _RULES

    keys = [k for k, _ in _RULES]
    assert keys.index("re-entry cooldown") < keys.index("entry-")
    assert keys.index("re-entry cap") < keys.index("entry-")


# ------------------------------------------------- the real day, end to end
def test_the_day_that_motivated_this_splits_four_ways():
    """Before: one bucket at 93.1%. After: a lineup gap, a clock, judged
    declines and the volume gate, each visible on its own."""
    day = (
        ["EntrySignal: SessionShift: not scoped to CRUDEOIL."] * 13
        + ["EntrySignal: SessionShift: not scoped to NATURALGAS."] * 13
        + ["EntrySignal: SessionShift: SessionShift: outside the 17:00-19:30 "
           "IST US-overlap window (30min into session)."] * 26
        + ["EntrySignal: MacroBreakout: MacroBreakout: price 22570.00 still "
           "inside 22516.40-22720.00 range."] * 29
        + ["VolumeEngine: THIN_TAPE: Volume ratio 0.400x < required 0.500x "
           "(trend entry)."] * 7
    )
    import collections

    tally = collections.Counter(classify_reason(r) for r in day)
    assert tally[GateId.STRATEGY_SCOPE] == 26
    assert tally[GateId.SESSION_TIME] == 26
    assert tally[GateId.ENTRY_SIGNAL] == 29
    assert tally[GateId.VOLUME] == 7
    assert tally[GateId.ENTRY_SIGNAL] / len(day) < 0.40, (
        "ENTRY_SIGNAL must no longer swallow the whole day"
    )
