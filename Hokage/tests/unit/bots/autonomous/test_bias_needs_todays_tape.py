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
        _BIAS_RULE_BY_SYMBOL=AutonomousTradingBot._BIAS_RULE_BY_SYMBOL,
        _BIAS_REVERSION_ATR=AutonomousTradingBot._BIAS_REVERSION_ATR,
        _BIAS_PULLBACK_ATR=AutonomousTradingBot._BIAS_PULLBACK_ATR,
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


def test_index_rule_ignores_vwap_entirely():
    """Rewritten 2026-08-05. These two tests pinned the VWAP-margin leg of the
    index bias. That leg is gone: NSE index spot reports volume 0, so its "VWAP"
    was a plain mean of closes, and measurement showed gating persistence with it
    dropped t from 2.45 to 1.34. The index rule is now persistence + EMA and
    never reads VWAP, so a flat tape sitting on its mean must read MIXED for a
    different reason — no 3-bar push — not because of a margin test."""
    candles = _series(session_bars=12, rising=True)
    for c in candles[-12:]:
        c.close = 24500.0
        c.open = 24500.0
        c.high = 24560.0
        c.low = 24440.0
    assert _BIAS(_bot(candles), "NIFTY") == "MIXED"


def _flat_series(base: float, session_bars: int, prior_days: int = 2):
    """A quiet tape at a given price level. Built at ONE price scale so ATR is
    not polluted by a jump between the prior sessions and today — the mistake
    that made the first version of the test below assert nonsense."""
    candles = []
    day0 = date(2026, 7, 28)
    for d in range(prior_days):
        for b in range(25):
            ts = datetime(day0.year, day0.month, day0.day + d, 4, 0,
                          tzinfo=timezone.utc) + timedelta(minutes=15 * b)
            candles.append(_candle(ts, base, high=base + 2.0, low=base - 2.0))
    today = day0 + timedelta(days=prior_days)
    for b in range(session_bars):
        ts = datetime(today.year, today.month, today.day, 4, 0,
                      tzinfo=timezone.utc) + timedelta(minutes=15 * b)
        candles.append(_candle(ts, base, high=base + 2.0, low=base - 2.0))
    return candles


def test_crudeoil_fades_a_stretch_instead_of_chasing_it():
    """CRUDEOIL measured mean-reverting: vwap_reversion t=+3.90 (60m), +5.14
    (120m), while persistence measured t=-3.27. Opposite rule, same engine."""
    candles = _flat_series(7000.0, session_bars=12)
    stretched = candles[-1]
    stretched.close = 7010.0          # ~5 ATR above a 7000 VWAP
    stretched.high = 7011.0
    assert _BIAS(_bot(candles), "CRUDEOIL") == "BEARISH"

    candles = _flat_series(7000.0, session_bars=12)
    stretched = candles[-1]
    stretched.close = 6990.0
    stretched.low = 6989.0
    assert _BIAS(_bot(candles), "CRUDEOIL") == "BULLISH"


def test_crudeoil_near_vwap_stands_aside():
    candles = _flat_series(7000.0, session_bars=12)
    assert _BIAS(_bot(candles), "CRUDEOIL") == "MIXED"


def test_unlisted_symbol_falls_back_to_the_index_rule():
    assert "NIFTY" not in AutonomousTradingBot._BIAS_RULE_BY_SYMBOL
    assert AutonomousTradingBot._BIAS_RULE_BY_SYMBOL["CRUDEOIL"] == "mean_reversion"
    assert AutonomousTradingBot._BIAS_RULE_BY_SYMBOL["SILVERM"] == "trend_pullback"


def test_naturalgas_uses_trend_pullback_not_the_index_default():
    """It was never in the table, so it inherited persistence — which measures
    as noise on it (t=+1.06 at 60m). Trend-pullback measures t=+2.97 at 120m."""
    assert AutonomousTradingBot._BIAS_RULE_BY_SYMBOL["NATURALGAS"] == "trend_pullback"


def test_goldm_is_deliberately_absent_from_the_rule_table():
    """CORRECTION 2026-08-06. GOLDM shipped as trend_pullback on a t=+2.43 that
    does not reproduce: re-measured on front-month futures it is NEGATIVE at
    both horizons (t=-0.16 at 60m, -0.07 at 120m), while the persistence default
    measures t=+2.25 and +2.91. Absence here is the fix, not an oversight."""
    assert "GOLDM" not in AutonomousTradingBot._BIAS_RULE_BY_SYMBOL




def test_margin_requirement_is_half_an_atr():
    assert AutonomousTradingBot._BIAS_VWAP_ATR_FRACTION == 0.5


def test_no_candles_still_returns_none_not_a_direction():
    bot = _bot([])
    assert _BIAS(bot, "NIFTY") is None
