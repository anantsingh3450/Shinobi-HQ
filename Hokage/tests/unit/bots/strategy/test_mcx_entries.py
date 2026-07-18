"""The four MCX Arena entry engines: distinct hypotheses, distinct windows,
each judged on the same MarketContext shape the index Dojo uses."""
from __future__ import annotations

from bots.strategy.components.mcx_entries import (
    SessionShiftEntry,
    EventRiderEntry,
    RangeFadeEntry,
    TrendRiderEntry,
    MCX_ENTRY_MODULES,
)
from bots.strategy.components.models import MarketContext

_CLOSES = tuple(100.0 + i * 0.05 for i in range(30))


def _ctx(minutes_into_session, ema9=100.5, ema21=99.0, vwap=100.0, price=101.0, closes=None):
    c = closes if closes is not None else _CLOSES
    return MarketContext(
        symbol="CRUDEOIL", price=price, ema9=ema9, ema21=ema21, vwap=vwap,
        closes=c, highs=tuple(x * 1.001 for x in c), lows=tuple(x * 0.999 for x in c),
        minutes_into_session=minutes_into_session,
    )


def test_four_distinct_modules_registered():
    assert len(MCX_ENTRY_MODULES) == 4
    ids = {m.module_id for m in MCX_ENTRY_MODULES.values()}
    assert len(ids) == 4  # no accidental duplicate module_id


def test_sessionshift_only_fires_in_us_overlap_window():
    mod = SessionShiftEntry()
    # Uptrend context, but 10:00 (60min in) — outside the window.
    sig = mod.evaluate(_ctx(minutes_into_session=60))
    assert not sig.should_enter and "17:00-19:30" in sig.reason
    # Same uptrend, 17:30 (510min in) — inside the window, fires long.
    sig = mod.evaluate(_ctx(minutes_into_session=510))
    assert sig.should_enter and sig.direction == "long"


def test_sessionshift_stands_aside_without_session_clock():
    sig = SessionShiftEntry().evaluate(_ctx(minutes_into_session=None))
    assert not sig.should_enter and "clock unknown" in sig.reason


def test_eventrider_requires_thrust_inside_narrow_window():
    mod = EventRiderEntry()
    flat_closes = tuple([100.0] * 30)
    thrust_closes = _CLOSES[:-3] + (100.5, 100.9, 101.5)  # sharp recent thrust up

    # Outside the window entirely (10:00, 60min in), even with a real thrust.
    sig = mod.evaluate(_ctx(minutes_into_session=60, closes=thrust_closes, price=101.5))
    assert not sig.should_enter and "17:00-18:30" in sig.reason

    # Inside the window but a flat tape -> no thrust to ride.
    sig = mod.evaluate(_ctx(minutes_into_session=500, closes=flat_closes, price=100.0))
    assert not sig.should_enter and "below the" in sig.reason

    # Inside the window with a genuine thrust (price matches the closes' own trajectory).
    sig = mod.evaluate(_ctx(minutes_into_session=500, closes=thrust_closes, price=thrust_closes[-1]))
    assert sig.should_enter and sig.direction == "long"


def test_rangefade_only_fires_in_quiet_hours_and_refuses_a_trend():
    mod = RangeFadeEntry()
    # Overstretched but OUTSIDE the quiet window (19:00, 600min).
    sig = mod.evaluate(_ctx(minutes_into_session=600, vwap=100.0, price=100.35))
    assert not sig.should_enter and "09:30-16:30" in sig.reason
    # Overstretched INSIDE the quiet window (12:00, 180min) -> fade short.
    sig = mod.evaluate(_ctx(minutes_into_session=180, ema9=100.1, ema21=100.0, vwap=100.0, price=100.35))
    assert sig.should_enter and sig.direction == "short"
    # A real trend inside the window must NOT be faded.
    sig = mod.evaluate(_ctx(minutes_into_session=180, ema9=101.0, ema21=99.0, vwap=100.0, price=100.35))
    assert not sig.should_enter and "trending" in sig.reason


def test_trendrider_needs_confirmed_trend_in_late_evening_window():
    mod = TrendRiderEntry()
    strong_up = tuple(100.0 + i * 0.15 for i in range(30))  # clear upward run
    last_price = strong_up[-1]
    # Confirmed uptrend but too early (16:00, 420min) — outside 18:00-22:30.
    sig = mod.evaluate(_ctx(minutes_into_session=420, ema9=101.0, ema21=99.0, vwap=100.0, price=last_price, closes=strong_up))
    assert not sig.should_enter and "18:00-22:30" in sig.reason
    # Same trend, inside the window (19:00, 600min) -> fires long.
    sig = mod.evaluate(_ctx(minutes_into_session=600, ema9=101.0, ema21=99.0, vwap=100.0, price=last_price, closes=strong_up))
    assert sig.should_enter and sig.direction == "long"


def test_never_fabricates_on_insufficient_bars():
    mod = TrendRiderEntry()
    sig = mod.evaluate(_ctx(minutes_into_session=600, ema9=101.0, ema21=99.0, vwap=100.0, price=101.5, closes=(100.0, 100.1)))
    assert not sig.should_enter and "need" in sig.reason
