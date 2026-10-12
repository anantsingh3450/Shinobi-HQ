"""A refusal that contradicts itself is worse than no explanation.

The journal carried this three times on 2026-10-12:

    VolumeEngine: THIN_TAPE: Volume ratio 0.50x < required 0.50x (trend entry)

0.50 is not less than 0.50. The gate was correct -- the real ratio was just
under 0.5 and `.2f` rounded both sides to the same number -- but the sentence
read like an off-by-epsilon bug, and I spent time chasing one.

That matters more here than it would elsewhere. The whole no-trade journal
exists because the commander asked why Hokage was not trading and got a
shrug. An explanation that looks wrong undermines the feature it belongs to.

The constants are NOT touched by any of this. They are risk parameters and
only the commander changes those.
"""
from __future__ import annotations

import re

import pytest

from bots.autonomous.intelligence import VolumeEngine


@pytest.fixture
def engine():
    return VolumeEngine.__new__(VolumeEngine)


def _ratio_and_threshold(message: str) -> tuple[float, float]:
    found = re.findall(r"([0-9]+\.[0-9]+)x", message)
    assert len(found) >= 2, f"expected two numbers in: {message}"
    return float(found[0]), float(found[1])


# ------------------------------------------------- the sentence must read true
def test_a_near_miss_refusal_does_not_contradict_itself(engine):
    """THE bug. 0.4996 displayed as 0.50 against a threshold of 0.50 -- and
    .3f alone does not fix it, because 0.4996 rounds to 0.500 as well. The
    shown value is floored so the inequality always holds."""
    ok, msg = engine.validate_breakout(
        current_volume=0.4996, avg_volume=1.0, entry_family="trend")
    assert ok is False
    ratio, threshold = _ratio_and_threshold(msg)
    assert ratio < threshold, f"the reason reads as a contradiction: {msg}"


@pytest.mark.parametrize("ratio", [0.4999999, 0.4999, 0.4996, 0.499, 0.45])
def test_every_near_miss_still_reads_true(engine, ratio):
    _, msg = engine.validate_breakout(
        current_volume=ratio, avg_volume=1.0, entry_family="trend")
    shown, threshold = _ratio_and_threshold(msg)
    assert shown < threshold, msg


def test_a_breakout_near_miss_reads_true_too(engine):
    ok, msg = engine.validate_breakout(
        current_volume=1.0996, avg_volume=1.0, entry_family="breakout")
    assert ok is False
    shown, threshold = _ratio_and_threshold(msg)
    assert shown < threshold, msg


# ---------------------------------------------------- the gate is unchanged
@pytest.mark.parametrize("entry_family,at_bar", [
    ("trend", VolumeEngine.TREND_MIN_RATIO),
    ("breakout", VolumeEngine.BREAKOUT_MIN_RATIO),
])
def test_exactly_at_the_bar_still_passes(engine, entry_family, at_bar):
    """The comparison is `<`, so equality passes. Changing the message must
    not have moved the boundary."""
    ok, _ = engine.validate_breakout(
        current_volume=at_bar, avg_volume=1.0, entry_family=entry_family)
    assert ok is True


@pytest.mark.parametrize("entry_family,bar", [
    ("trend", VolumeEngine.TREND_MIN_RATIO),
    ("breakout", VolumeEngine.BREAKOUT_MIN_RATIO),
])
def test_just_under_the_bar_still_fails(engine, entry_family, bar):
    ok, _ = engine.validate_breakout(
        current_volume=bar - 0.001, avg_volume=1.0, entry_family=entry_family)
    assert ok is False


def test_no_baseline_is_not_a_refusal(engine):
    ok, msg = engine.validate_breakout(0.0, 0.0, "trend")
    assert ok is True
    assert "unavailable" in msg.lower()


def test_the_risk_constants_are_untouched():
    """These are risk parameters. Only the commander moves them, and a
    message fix must never be cover for a quiet change."""
    assert VolumeEngine.BREAKOUT_MIN_RATIO == 1.1
    assert VolumeEngine.TREND_MIN_RATIO == 0.5


# ------------------------------------------- the docstring must not go stale
def test_the_docstring_states_no_threshold_numbers():
    """It used to claim ">= 1.2x" and ">= 0.8x" while the constants were 1.1
    and 0.5. A docstring with the wrong threshold is how someone later
    "corrects" the constant to match the comment."""
    doc = VolumeEngine.validate_breakout.__doc__ or ""
    body = doc.split("docstring used to say")[0]
    stray = re.findall(r">=\s*[0-9]+\.[0-9]+x", body)
    assert not stray, f"hardcoded thresholds back in the docstring: {stray}"
    assert "BREAKOUT_MIN_RATIO" in doc and "TREND_MIN_RATIO" in doc


def test_the_shown_ratio_is_never_higher_than_the_real_one(engine):
    """Flooring, not rounding. Overstating a ratio that failed is how the
    sentence contradicts itself in the first place."""
    _, msg = engine.validate_breakout(
        current_volume=0.4999999, avg_volume=1.0, entry_family="trend")
    shown, threshold = _ratio_and_threshold(msg)
    assert shown <= 0.4999999
    assert shown < threshold, msg
