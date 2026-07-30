"""The bias engine must read TODAY's tape, and must require a real margin.

2026-07-30, reproduced from live Kite candles:
  NIFTY as-of 09:45 -> BULLISH, on price 24275.60 vs VWAP 24269.47. That is a
  6.13-point edge on a 24,275 index: 0.025%, one tick of noise. Only THREE of
  today's bars existed, so ~93% of the 42-bar EMA21 window was previous
  sessions — the "bias" was reporting yesterday's trend. A CE was allowed at
  09:46 and stopped out 40 minutes later; by 10:00 the same symbol read MIXED.

Two independent defects: no margin on the VWAP leg, and no requirement that the
session actually have enough bars to have a trend.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from bots.autonomous.autonomous_bot import AutonomousTradingBot

_BIAS = AutonomousTradingBot._compute_underlying_bias


def _candle(ts: datetime, close: float, high: float | None = None, low: float | None = None):
    return SimpleNamespace(
        timestamp=ts,
        open=close,
        high=high if high is not None else close + 5.0,
        low=low if low is not None else close - 5.0,
        close=close,
        volume=1000.0,
    )


def _bot(candles):
    res = SimpleNamespace(candles=candles)
    price_source = MagicMock()
    price_source.get_historical_candles.return_value = res
    bot = SimpleNamespace(
        orchestrator=SimpleNamespace(price_source=price_source),
        _BIAS_MIN_SESSION_BARS=AutonomousTradingBot._BIAS_MIN_SESSION_BARS,
        _BIAS_VWAP_ATR_FRACTION=AutonomousTradingBot._BIAS_VWAP_ATR_FRACTION,
    )
    return bot


def _series(session_bars: int, *, rising: bool, prior_days: int = 2):
    """Bars for `prior_days` past sessions plus `session_bars` bars today."""
    candles = []
    base = 24000.0
    day0 = date(2026, 7, 28)
    for d in range(prior_days):
        for b in range(25):
            ts = datetime(day0.year, day0.month, day0.day + d, 4, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * b)
            base += 4.0 if rising else -4.0
            candles.append(_candle(ts, base))
    today = day0 + timedelta(days=prior_days)
    for b in range(session_bars):
        ts = datetime(today.year, today.month, today.day, 4, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * b)
        base += 30.0 if rising else -30.0
        candles.append(_candle(ts, base))
    return candles


def test_three_bars_of_today_is_not_a_tape():
    """The exact 09:46 condition: yesterday's trend must not become today's."""
    bot = _bot(_series(session_bars=3, rising=True))
    assert _BIAS(bot, "NIFTY") == "MIXED"


def test_direction_is_named_once_the_session_has_enough_bars():
    bot = _bot(_series(session_bars=12, rising=True))
    assert _BIAS(bot, "NIFTY") == "BULLISH"

    bot = _bot(_series(session_bars=12, rising=False))
    assert _BIAS(bot, "NIFTY") == "BEARISH"


def test_the_floor_is_six_bars_ninety_minutes():
    assert AutonomousTradingBot._BIAS_MIN_SESSION_BARS == 6

    below = _bot(_series(session_bars=5, rising=True))
    assert _BIAS(below, "NIFTY") == "MIXED"


def test_price_sitting_on_vwap_is_not_a_direction():
    """A market on its VWAP has not chosen; that is what MIXED is for."""
    candles = _series(session_bars=12, rising=True)
    # Flatten today's bars so price lands essentially on VWAP, keeping a wide
    # high/low range so ATR — and therefore the required margin — stays large.
    today = candles[-12:]
    for c in today:
        c.close = 24500.0
        c.open = 24500.0
        c.high = 24560.0
        c.low = 24440.0
    assert _BIAS(_bot(candles), "NIFTY") == "MIXED"


def test_noise_sized_vwap_edge_is_rejected():
    """0.025% of the index counted as bullish before this fix."""
    candles = _series(session_bars=12, rising=True)
    for c in candles[-12:]:
        c.close = 24269.0
        c.open = 24269.0
        c.high = 24299.0   # ATR ~60 -> margin ~30 points required
        c.low = 24239.0
    # Nudge the last close a mere 6 points above the flat VWAP.
    candles[-1].close = 24275.13
    assert _BIAS(_bot(candles), "NIFTY") == "MIXED"


def test_margin_requirement_is_half_an_atr():
    assert AutonomousTradingBot._BIAS_VWAP_ATR_FRACTION == 0.5


def test_no_candles_still_returns_none_not_a_direction():
    bot = _bot([])
    assert _BIAS(bot, "NIFTY") is None
