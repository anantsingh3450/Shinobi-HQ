"""A gate that tallies as UNCLASSIFIED is a blocker nobody will look at.

The gate tally is how the commander decides which gate to investigate. It
works by matching free text against a rule table, which means the table and
the code that writes the text are a CONTRACT held together by nothing. It has
drifted twice already:

  * STRATEGY_SCOPE needed a rule added after "not scoped to" messages were
    tallying as judged stand-asides, which made a coverage fact look like a
    strategy declining a trade.
  * The no-coverage message added on 2026-10-13 needed two more rules, because
    it is phrased "is scoped to" rather than "not scoped to" and would
    otherwise have landed in UNCLASSIFIED - the one blocker that must never be
    hard to see.

So this pins the contract from the other end: every gate's REAL emitted
message, copied from the source that writes it, must classify to that gate.

WHY THESE MESSAGES IN PARTICULAR. Ten of the 23 gates have never fired once in
2,539 recorded decisions, and six of those are SAFETY gates - RISK_OFF,
CAPITAL_PRESERVATION, CASH, WAR_CHEST, ALLOCATION_ZERO, CORRELATION_CAP. They
are unexercised, not broken: each has an emit site and each classifies
correctly today. But a rule that has never run in production is held up only
by tests, and CORRELATION_CAP had no assertion on its gate id at all. If one
of these ever does fire - and they fire on drawdown, on an exhausted chest, on
a correlated book, which is to say on the worst day - its message must land in
its own bucket rather than in UNCLASSIFIED.
"""
from __future__ import annotations

import pathlib

import pytest

from bots.autonomous.gate_analytics import GATE_KINDS, GateId, classify_reason

SRC = pathlib.Path("src/bots/autonomous/autonomous_bot.py")

#: (gate, a message the production code actually writes). Each string is a
#: literal substring of src/bots/autonomous/autonomous_bot.py, which the test
#: below verifies - a paraphrase here would pin nothing.
REAL_MESSAGES: list[tuple[GateId, str]] = [
    (GateId.RISK_OFF,
     "Fast Trading Brain: Cached risk state is RISK-OFF."),
    (GateId.CAPITAL_PRESERVATION,
     "Fast Trading Brain: Capital Preservation Mode is NO TRADE."),
    (GateId.CASH,
     "Insufficient account cash balance."),
    (GateId.WAR_CHEST,
     "War chest exhausted for "),
    (GateId.ALLOCATION_ZERO,
     "Allocation sized to 0% by Capital Preservation sizing engine"),
    (GateId.CORRELATION_CAP,
     "CorrelationCap: already "),
    (GateId.IV_PREMIUM,
     "IV premium guard: India VIX at "),
    (GateId.OBSERVATION_WINDOW,
     "Opening Bell Observation Protocol: Prohibited from executing entry orders"),
    (GateId.STRATEGY_SCOPE,
     "not scoped to "),
    (GateId.BIAS,
     "Bias engine: "),
]


@pytest.mark.parametrize(
    "gate,message", REAL_MESSAGES, ids=[g.name for g, _ in REAL_MESSAGES]
)
def test_the_message_production_writes_classifies_to_its_own_gate(gate, message):
    assert classify_reason(message) is gate, (
        f"{gate.name} writes {message!r} and it tallies as "
        f"{classify_reason(message).name}"
    )


@pytest.mark.parametrize(
    "gate,message", REAL_MESSAGES, ids=[g.name for g, _ in REAL_MESSAGES]
)
def test_the_message_is_really_in_the_source(gate, message):
    """A paraphrase would pin nothing. If production rewords a refusal, this
    fails and the rule table gets looked at - which is the whole point."""
    src = SRC.read_text(encoding="utf-8")
    assert message in src, (
        f"{gate.name}: this test's copy of the message is no longer what "
        f"production writes"
    )


def test_nothing_real_lands_in_unclassified():
    for gate, message in REAL_MESSAGES:
        assert classify_reason(message) is not GateId.UNCLASSIFIED


def test_an_unknown_refusal_still_becomes_unclassified():
    """The bucket must keep working. A best guess would quietly corrupt the
    tally the commander uses to choose what to tune."""
    assert classify_reason("something nobody has written yet") is GateId.UNCLASSIFIED
    assert classify_reason("") is GateId.UNCLASSIFIED


def test_every_safety_gate_in_this_list_is_still_a_safety_gate():
    """These six are the ones that fire on the worst day - a drawdown, an
    exhausted chest, a correlated book. Reclassifying one as QUALITY would
    make it tunable, and a safety limit is not a knob."""
    for gate in (GateId.RISK_OFF, GateId.CAPITAL_PRESERVATION, GateId.CASH,
                 GateId.WAR_CHEST, GateId.ALLOCATION_ZERO,
                 GateId.CORRELATION_CAP):
        assert GATE_KINDS[gate].name == "SAFETY", gate.name


def test_every_defined_gate_has_a_rule_that_can_reach_it():
    """A GateId with no rule can never be tallied, so it would silently
    contribute nothing to the one report that ranks blockers."""
    import bots.autonomous.gate_analytics as ga

    reachable = {gate for _, gate in ga._RULES}
    # UNCLASSIFIED is the fallthrough and correctly has no rule of its own.
    missing = set(GateId) - reachable - {GateId.UNCLASSIFIED}
    assert not missing, f"gates no rule can ever produce: {[g.name for g in missing]}"
