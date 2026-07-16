"""The volume gate must measure VOLUME, not the time of day.

The bug this pins: today's *partial* cumulative volume was divided by the
average *complete* session, so the ratio climbed from ~0 to ~1 purely as the
day aged. On 2026-07-15 NIFTY that ran 0.20x at 09:15 to 0.87x at 15:15 and
never reached the 1.20x breakout bar at any hour — the breakout family could
not fire on any day, and CRUDE_OIL's "THIN_TAPE 0.35x" was just 18:15 o'clock.

The fix compares today's cumulative volume at time T against the typical
cumulative volume at the same T on prior sessions. These tests use a synthetic
intraday volume curve — a deliberately steep one — so that a regression to any
whole-session denominator shows up as a ratio that tracks the clock.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot


#: Volume traded in each successive 15-minute bar of a session. Front-loaded,
#: like a real session: an hour in, only a fraction of the day has traded.
_BAR_VOLUMES = [500.0, 300.0, 200.0, 100.0, 100.0, 100.0, 100.0, 100.0]
_SESSION_TOTAL = sum(_BAR_VOLUMES)  # 1500


def _candles_for_day(day: date, scale: float = 1.0, bars: int | None = None):
    """One session of 15-minute candles starting 09:15, volumes scaled."""
    out = []
    count = len(_BAR_VOLUMES) if bars is None else bars
    for i, vol in enumerate(_BAR_VOLUMES[:count]):
        out.append(SimpleNamespace(
            timestamp=datetime.combine(day, time(9, 15)) + timedelta(minutes=15 * i),
            volume=vol * scale,
            open=100.0, high=101.0, low=99.0, close=100.0,
        ))
    return out


def _bot_with_candles(candles):
    """An AutonomousTradingBot whose price source returns exactly `candles`.

    __init__ is bypassed: this exercises _get_volume_context, and constructing
    the full bot would drag in the scanner, journal, and Telegram uplink.
    """
    bot = object.__new__(AutonomousTradingBot)
    price_source = MagicMock()
    price_source.resolve_instrument.return_value = SimpleNamespace(symbol="NIFTY")
    price_source.get_historical_candles.return_value = SimpleNamespace(candles=candles)
    bot.orchestrator = SimpleNamespace(price_source=price_source)
    return bot


def _quote():
    return SimpleNamespace(volume=12345.0)


class TestTimeOfDayNormalisation:
    def test_early_session_normal_volume_reads_as_normal_not_thin(self):
        """The core regression. One bar into the session, today has traded 500
        of a typical 1500-volume day. The old denominator called that 0.33x —
        THIN_TAPE — when the tape is perfectly normal for 09:15."""
        today = date(2026, 7, 15)
        candles = []
        for i in range(1, 6):
            candles += _candles_for_day(today - timedelta(days=i))
        candles += _candles_for_day(today, bars=1)  # only 09:15 has traded

        current, typical = _bot_with_candles(candles)._get_volume_context("NIFTY", _quote())

        assert current == pytest.approx(500.0)
        # Compared against 09:15 on prior days (500), not the full session.
        assert typical == pytest.approx(500.0)
        assert current / typical == pytest.approx(1.0)

    def test_genuine_early_surge_clears_the_breakout_bar(self):
        """NIFTY's real 09:15 on 2026-07-15: a true surge the old denominator
        buried at 0.20x. Normalised it must be able to exceed 1.2x."""
        today = date(2026, 7, 15)
        candles = []
        for i in range(1, 6):
            candles += _candles_for_day(today - timedelta(days=i))
        candles += _candles_for_day(today, scale=1.5, bars=1)  # 750 vs typical 500

        current, typical = _bot_with_candles(candles)._get_volume_context("NIFTY", _quote())

        assert current / typical == pytest.approx(1.5)
        assert current / typical > 1.2, "a real surge must be able to clear the breakout bar"

    def test_genuinely_dead_tape_still_reads_as_thin(self):
        """Normalisation must not whitewash a dead tape into normal."""
        today = date(2026, 7, 15)
        candles = []
        for i in range(1, 6):
            candles += _candles_for_day(today - timedelta(days=i))
        candles += _candles_for_day(today, scale=0.2, bars=1)  # 100 vs typical 500

        current, typical = _bot_with_candles(candles)._get_volume_context("NIFTY", _quote())

        assert current / typical == pytest.approx(0.2)
        assert current / typical < 0.8

    def test_ratio_does_not_drift_upward_as_the_session_ages(self):
        """The old gate's signature failure: an identical-volume day scored
        higher and higher purely because the clock advanced. Ratio must stay
        flat across the session when today matches the typical curve."""
        today = date(2026, 7, 15)
        prior = []
        for i in range(1, 6):
            prior += _candles_for_day(today - timedelta(days=i))

        ratios = []
        for bars in range(1, len(_BAR_VOLUMES) + 1):
            candles = prior + _candles_for_day(today, bars=bars)
            current, typical = _bot_with_candles(candles)._get_volume_context("NIFTY", _quote())
            ratios.append(current / typical)

        assert all(r == pytest.approx(1.0) for r in ratios), f"ratio tracks the clock: {ratios}"


class TestDoctrineSkipsRatherThanGuesses:
    def test_too_few_prior_sessions_skips_the_gate(self):
        """Two days of history is not a volume profile. Skip, never guess."""
        today = date(2026, 7, 15)
        candles = _candles_for_day(today - timedelta(days=1)) + _candles_for_day(today, bars=1)
        assert _bot_with_candles(candles)._get_volume_context("NIFTY", _quote()) is None

    def test_no_candles_skips_the_gate(self):
        assert _bot_with_candles([])._get_volume_context("NIFTY", _quote()) is None

    def test_time_of_day_with_no_peer_history_skips_the_gate(self):
        """Today has traded past any hour prior sessions ever reached (a session
        extension). With no peer bucket there is no honest comparison."""
        today = date(2026, 7, 15)
        candles = []
        for i in range(1, 6):
            candles += _candles_for_day(today - timedelta(days=i), bars=2)
        candles += _candles_for_day(today, bars=8)  # far past prior sessions' end
        assert _bot_with_candles(candles)._get_volume_context("NIFTY", _quote()) is None

    def test_zero_volume_today_skips_the_gate(self):
        today = date(2026, 7, 15)
        candles = []
        for i in range(1, 6):
            candles += _candles_for_day(today - timedelta(days=i))
        candles += _candles_for_day(today, scale=0.0, bars=1)
        assert _bot_with_candles(candles)._get_volume_context("NIFTY", _quote()) is None

    def test_unresolvable_instrument_skips_the_gate(self):
        bot = _bot_with_candles([])
        bot.orchestrator.price_source.resolve_instrument.return_value = None
        assert bot._get_volume_context("NIFTY", _quote()) is None

    def test_provider_failure_skips_the_gate_rather_than_crashing_the_scan(self):
        bot = _bot_with_candles([])
        bot.orchestrator.price_source.get_historical_candles.side_effect = RuntimeError("feed down")
        assert bot._get_volume_context("NIFTY", _quote()) is None

    def test_partial_peer_session_is_not_averaged_in_as_complete(self):
        """A prior day that closed early never reached this clock time. Counting
        its short total as if it were a full comparison would understate the
        baseline and wave through thin tape."""
        today = date(2026, 7, 15)
        candles = []
        for i in range(1, 5):
            candles += _candles_for_day(today - timedelta(days=i))     # full days
        candles += _candles_for_day(today - timedelta(days=5), bars=1)  # closed after 09:15
        candles += _candles_for_day(today, bars=4)                      # now 10:00

        current, typical = _bot_with_candles(candles)._get_volume_context("NIFTY", _quote())

        # 10:00 cumulative = 500+300+200+100 = 1100 on the four full days only.
        assert current == pytest.approx(1100.0)
        assert typical == pytest.approx(1100.0)
