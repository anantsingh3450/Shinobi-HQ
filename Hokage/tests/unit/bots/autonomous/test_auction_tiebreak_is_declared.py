"""The arena's tie-break was the alphabet, and it flipped the experiment.

2026-10-27 evening, natural gas. RiderTrend won all 14 ties; TrendRider won
none. The night before, TrendRider won both ties and RiderTrend none. Nothing
about gas changed. What changed was the order of keys in a JSON file:

    before-mirrors    ... rangefade | sessionshift | trendrider
    before-unarchive  ... trendrider | faderange | ridertrend   <- appended
    after             ... faderange | rangefade | ridertrend | sessionshift | trendrider

Some write re-sorted the portfolio alphabetically. The auction kept the first
firing module it met and replaced it only on a STRICTLY higher confidence, so
the first key in the file won every exact tie - and "ridertrend" sorts before
"trendrider".

A mirror carries its original's confidence BY DESIGN (pinned by its own test,
so it cannot steal the asset by inflating itself), which means the pair ties
on every single scan. The commander's hypothesis was therefore being decided
by a string comparison, and the two evenings were not comparable.

WHAT THIS FILE PROTECTS:

  1. THE ORDER IS DECLARED IN CODE, not inherited from a file. The same field
     must produce the same winner however it is iterated.
  2. THE EXPERIMENT DOES NOT DISPLACE THE MEASURED STRATEGY. On a tie the
     original wins; the mirror is scored by signal_archive and needs no fill.
  3. A MIRROR IS NOT BARRED FROM TRADING. It still out-bids a different
     module on higher confidence and still wins alone.

Same family as every other wound here: a measurement that was quietly
fiction, and a thing that silently stopped behaving as it had the day before.
"""
from __future__ import annotations

import itertools

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.strategy.components.mcx_entries import (
    MCX_ENTRY_MODULES,
    FadeRangeEntry,
    RangeFadeEntry,
    RiderTrendEntry,
    TrendRiderEntry,
)

key = Bot._auction_key


class _Mod:
    def __init__(self, is_mirror=False):
        if is_mirror:
            self.IS_MIRROR = True


ORIGINAL = _Mod()
MIRROR = _Mod(is_mirror=True)


def _win(field):
    """The winner of one auction field, by the production rule alone."""
    return min(field, key=lambda c: key(c[0], c[1], c[2]))[1]


#: The real 17:30 gas field from 2026-10-27, which RiderTrend took.
FIELD_1730 = [
    (80.0, "strat-eventrider-mcx-v1", ORIGINAL),
    (82.0, "strat-ridertrend-mcx-v1", MIRROR),
    (82.0, "strat-trendrider-mcx-v1", ORIGINAL),
]


# ------------------------------------------ 1. the order is declared in code
def test_the_same_field_gives_the_same_winner_however_it_is_iterated():
    """THE WHOLE DEFECT. A portfolio rewrite must never change who trades."""
    winners = {_win(list(order)) for order in itertools.permutations(FIELD_1730)}
    assert winners == {"strat-trendrider-mcx-v1"}, (
        "the winner changed with iteration order - this is the 2026-10-27 bug")


def test_alphabetical_order_no_longer_decides_a_tie():
    """'ridertrend' < 'trendrider', and that is what used to settle it."""
    assert _win(FIELD_1730) == "strat-trendrider-mcx-v1"


def test_two_non_mirrors_tied_resolve_identically_in_either_order():
    field = [(70.0, "strat-eventrider-mcx-v1", ORIGINAL),
             (70.0, "strat-sessionshift-mcx-v1", ORIGINAL)]
    assert _win(field) == _win(list(reversed(field)))


# --------------------------- 2. the experiment does not displace the measured
def test_on_an_exact_tie_the_original_wins_and_the_mirror_does_not():
    field = [(82.0, "strat-ridertrend-mcx-v1", MIRROR),
             (82.0, "strat-trendrider-mcx-v1", ORIGINAL)]
    assert _win(field) == "strat-trendrider-mcx-v1"


def test_this_restores_the_2026_10_26_behaviour():
    """Both evenings become comparable again: TrendRider holds gas, and
    RiderTrend is recorded on every tie by the signal archive."""
    assert key(82.0, "strat-trendrider-mcx-v1", ORIGINAL) < \
           key(82.0, "strat-ridertrend-mcx-v1", MIRROR)


def test_the_mirror_still_loses_a_tie_even_when_it_sorts_first():
    """Not a rename. 'faderange' sorts before 'rangefade' too."""
    field = [(60.0, "strat-faderange-mcx-v1", MIRROR),
             (60.0, "strat-rangefade-mcx-v1", ORIGINAL)]
    assert _win(field) == "strat-rangefade-mcx-v1"


# ------------------------------------- 3. a mirror is not barred from trading
def test_a_mirror_still_wins_on_genuinely_higher_confidence():
    """It is out-bidding a DIFFERENT module, not its own original. Only the
    tie was ever the problem."""
    field = [(82.0, "strat-ridertrend-mcx-v1", MIRROR),
             (80.0, "strat-eventrider-mcx-v1", ORIGINAL)]
    assert _win(field) == "strat-ridertrend-mcx-v1"


def test_a_mirror_alone_still_wins():
    """Its original can be archived or out of scope. Barring it outright
    would end the experiment rather than fix its tie-break."""
    assert _win([(60.0, "strat-ridertrend-mcx-v1", MIRROR)]) == \
        "strat-ridertrend-mcx-v1"


# ------------------------------------------- the primary rule is unchanged
def test_confidence_still_decides_before_anything_else():
    field = [(90.0, "strat-ridertrend-mcx-v1", MIRROR),
             (50.0, "strat-trendrider-mcx-v1", ORIGINAL)]
    assert _win(field) == "strat-ridertrend-mcx-v1"


def test_a_higher_confidence_non_mirror_still_beats_a_lower_one():
    field = [(55.0, "strat-eventrider-mcx-v1", ORIGINAL),
             (75.0, "strat-sessionshift-mcx-v1", ORIGINAL)]
    assert _win(field) == "strat-sessionshift-mcx-v1"


def test_a_missing_confidence_is_not_a_crash_and_ranks_last():
    assert key(None, "strat-x", ORIGINAL) > key(1.0, "strat-x", ORIGINAL)


# ----------------------------------------- the flag is on the real modules
@pytest.mark.parametrize("sid", ["strat-ridertrend-mcx-v1",
                                 "strat-faderange-mcx-v1"])
def test_the_real_mirrors_are_flagged_as_mirrors(sid):
    assert getattr(MCX_ENTRY_MODULES[sid], "IS_MIRROR", False) is True


@pytest.mark.parametrize("sid", ["strat-trendrider-mcx-v1",
                                 "strat-rangefade-mcx-v1",
                                 "strat-eventrider-mcx-v1",
                                 "strat-sessionshift-mcx-v1",
                                 "strat-eiareaction-mcx-v1"])
def test_the_originals_are_not_flagged(sid):
    assert getattr(MCX_ENTRY_MODULES[sid], "IS_MIRROR", False) is False


def test_the_flag_rides_on_the_mirror_base_not_on_each_subclass():
    """So a mirror added later cannot be forgotten."""
    assert RiderTrendEntry.IS_MIRROR and FadeRangeEntry.IS_MIRROR
    assert not getattr(TrendRiderEntry, "IS_MIRROR", False)
    assert not getattr(RangeFadeEntry, "IS_MIRROR", False)


def test_the_real_pair_ties_so_the_tie_break_is_what_decides_them():
    """If this ever stops being true the mirror is inflating itself, which a
    separate test already forbids - but the tie-break's whole reason for
    existing is that these two are equal on every scan."""
    assert key(82.0, "strat-trendrider-mcx-v1",
               MCX_ENTRY_MODULES["strat-trendrider-mcx-v1"])[0] == \
           key(82.0, "strat-ridertrend-mcx-v1",
               MCX_ENTRY_MODULES["strat-ridertrend-mcx-v1"])[0]
