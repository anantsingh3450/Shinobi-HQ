"""The EIA module must refuse the release vacuum, and must know what day it is.

BUILT 2026-08-27 from open sources. Natural gas has something no other asset
Hokage trades has: a scheduled weekly information release.

  * The EIA Weekly Natural Gas Storage Report prints EVERY THURSDAY at 10:30 ET
    — 20:00 IST — and MCX natural gas is a cash-settled derivative of NYMEX
    Henry Hub that follows it within seconds.
  * Gas return volatility is measurably higher on Thursdays than on any other
    weekday (academic), and a 10 Bcf surprise moves the front month 10-20 cents
    almost instantly (practitioner). Two independent sources, one hour.

HOKAGE WAS BLIND TO IT TWICE. MarketContext carried no weekday at all, so a
weekly event was inexpressible; and every live gas window (RangeFade,
09:30-17:00) closes three hours before the print. The most informative hour of
the gas week had no module in it.

THE VACUUM IS THE POINT OF THIS FILE. The same sources are blunt that the print
itself is untradeable: repricing completes "by 10:30:01", spreads go from a tick
wide to ten wide, "the worst fills of the week happen between 10:30 and 10:35",
and stops at sensible technical levels "get vacuumed in both directions". A
module that fires at 20:00 is not trading the event, it is donating to it. So
the refusal to fire before 20:15 is the load-bearing behaviour here, and it is
tested harder than the entry is.

SAMPLE SIZE, RECORDED SO IT CANNOT BE FORGOTTEN. Kite serves 200 days of
15-minute candles: about 28 Thursdays, ~14 per half, against a MIN_N of 40
everywhere else. This module CANNOT reach the ship bar on data that exists.
DIRECTION_BY_ASSET is therefore empty and stays empty until measured.
"""
from __future__ import annotations

from datetime import date

import pytest

from bots.strategy.components.mcx_entries import (
    MCX_ENTRY_MODULES,
    EIAReactionEntry,
    RangeFadeEntry,
)

THURSDAY = date(2026, 8, 27)
WEDNESDAY = date(2026, 8, 26)


class _Ctx:
    def __init__(self, minutes, session_date, closes, atr=1.0, symbol="NATURALGAS"):
        self.symbol = symbol
        self.closes = tuple(closes)
        self.price = closes[-1]
        self.minutes_into_session = minutes
        # MCX modules gate on the WALL CLOCK from 2026-10-20/21. Every
        # case here was written for a normal 09:00 open, where the two
        # agree exactly, so the clock follows the same offset and no
        # assertion changes meaning.
        self.minute_of_day = None if minutes is None else 9 * 60 + minutes
        self.session_date = session_date
        self.atr = atr
        self.vwap = closes[-1]
        self.ema9 = closes[-1]
        self.ema21 = closes[-1]
        self.above_vwap = False
        self.trend_up = False

    @property
    def weekday(self):
        return None if self.session_date is None else self.session_date.weekday()

    def distance_from_vwap_pct(self):
        return 0.0


def _spike(up: bool, size: float = 2.0, minutes: int = 675, day=THURSDAY):
    """19:45 close 300, release bar closes `size` away, current bar flat."""
    release = 300.0 + (size if up else -size)
    return _Ctx(minutes, day, [300.0, release, release])


# ------------------------------------------------------- the vacuum, refused
@pytest.mark.parametrize("minutes", [0, 300, 645, 660, 674])
def test_it_never_fires_before_the_release_bar_has_closed(minutes):
    """660 is 20:00 IST — the print itself. Firing there buys the ten-wide
    spread the whole edge is supposed to avoid."""
    sig = EIAReactionEntry().evaluate(_spike(True, minutes=minutes))
    assert not sig.should_enter


def test_the_release_minute_refusal_says_why():
    sig = EIAReactionEntry().evaluate(_spike(True, minutes=EIAReactionEntry.RELEASE_MIN))
    assert "vacuum" in sig.reason


def test_the_release_minute_matches_hokages_own_scan_clock():
    """Hokage's 2026-08-26 log stamped the 20:00:26 scan '(660min into session)'.
    If this constant drifts, the module aims at the wrong hour entirely."""
    assert EIAReactionEntry.RELEASE_MIN == 660
    assert EIAReactionEntry.WINDOW_START_MIN > EIAReactionEntry.RELEASE_MIN


def test_the_window_is_wide_enough_to_survive_one_missed_scan():
    """A weekly event gets one chance. A single-scan window turns a restart —
    which has already swallowed three entry notifications — into a lost week."""
    span = EIAReactionEntry.WINDOW_END_MIN - EIAReactionEntry.WINDOW_START_MIN
    assert span >= 30


def test_it_stops_firing_after_the_window():
    assert not EIAReactionEntry().evaluate(_spike(True, minutes=705)).should_enter


# -------------------------------------------------------------- the weekday
def test_it_only_fires_on_thursday():
    assert not EIAReactionEntry().evaluate(_spike(True, day=WEDNESDAY)).should_enter


def test_an_unknown_session_date_stands_aside_rather_than_guessing():
    """Doctrine: missing data means stand aside, never assume. A module that
    guessed 'probably Thursday' would trade a made-up event."""
    sig = EIAReactionEntry().evaluate(_spike(True, day=None))
    assert not sig.should_enter
    assert "unknown" in sig.reason


def test_thursday_is_weekday_three():
    assert EIAReactionEntry.EIA_WEEKDAY == 3
    assert THURSDAY.weekday() == 3


# ---------------------------------------------------------------- the entry
def test_a_real_reaction_inside_the_window_fires():
    sig = EIAReactionEntry().evaluate(_spike(True))
    assert sig.should_enter


def test_the_default_stance_fades_the_print():
    """The hypothesis under test: the print is a liquidity event, so a bullish
    spike sells into resting orders and reverses. Recorded here so the result
    cannot be quietly rewritten to match whatever the data says."""
    assert EIAReactionEntry.FADE_THE_PRINT is True
    assert EIAReactionEntry().evaluate(_spike(up=True)).direction == "short"
    assert EIAReactionEntry().evaluate(_spike(up=False)).direction == "long"


def test_following_the_print_inverts_both_sides():
    m = EIAReactionEntry()
    m.FADE_THE_PRINT = False
    assert m.evaluate(_spike(up=True)).direction == "long"
    assert m.evaluate(_spike(up=False)).direction == "short"


def test_a_print_that_barely_moved_the_tape_is_not_an_event():
    small = EIAReactionEntry.MIN_REACTION_ATR / 2
    assert not EIAReactionEntry().evaluate(_spike(True, size=small)).should_enter


def test_a_missing_atr_stands_the_entry_down():
    """The reaction is measured in ATR. Without one there is no threshold, and
    a fabricated ATR is worse than a missing one — that lesson cost a GOLDM
    stop seven times too wide on 2026-08-25."""
    ctx = _spike(True)
    ctx.atr = None
    sig = EIAReactionEntry().evaluate(ctx)
    assert not sig.should_enter
    assert "ATR" in sig.reason


def test_too_few_bars_stands_aside():
    ctx = _Ctx(675, THURSDAY, [300.0, 302.0])
    assert not EIAReactionEntry().evaluate(ctx).should_enter


# --------------------------------------------------- unmeasured means unscoped
def test_no_direction_is_scoped_until_it_has_been_measured():
    """~28 Thursdays exist in total, against a MIN_N of 40. This module cannot
    reach the ship bar, so it must not arrive claiming a side."""
    assert EIAReactionEntry.DIRECTION_BY_ASSET == {}


def test_it_is_registered_so_the_labs_can_see_it():
    assert MCX_ENTRY_MODULES["strat-eiareaction-mcx-v1"].module_id == \
        "entry-eiareaction-mcx-v1"


def test_its_tunables_never_touch_risk():
    for knob, spec in EIAReactionEntry.TUNABLES.items():
        assert spec["tier"] == "propose", knob


# ------------------------------------------- the weekday knob on RangeFade
def test_rangefade_skips_no_weekday_until_measured():
    assert RangeFadeEntry.SKIP_WEEKDAYS_BY_ASSET == {}


def test_rangefade_honours_a_weekday_skip_when_one_is_set():
    module = RangeFadeEntry()
    module.SKIP_WEEKDAYS_BY_ASSET = {"NATURALGAS": (3,)}
    ctx = _Ctx(200, THURSDAY, [300.0] * 5)
    ctx.vwap = 302.0            # a dip worth fading on any other day
    ctx.price = 300.0
    sig = module.evaluate(ctx)
    assert not sig.should_enter
    assert "weekday" in sig.reason


def test_a_weekday_skip_does_not_leak_to_another_asset():
    module = RangeFadeEntry()
    module.SKIP_WEEKDAYS_BY_ASSET = {"NATURALGAS": (3,)}
    ctx = _Ctx(200, THURSDAY, [300.0] * 5, symbol="CRUDEOIL")
    ctx.vwap = 300.0
    assert "weekday" not in module.evaluate(ctx).reason
