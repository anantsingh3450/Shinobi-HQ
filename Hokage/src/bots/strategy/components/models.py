"""Shared value objects for pluggable strategy components.

A strategy is a triple: (EntryModule, ExitModule, RiskModule). Splitting them
apart is what makes evolution possible — you cannot judge an entry against an
exit while they are welded into one function, and you cannot breed a new
strategy from "best entry + best exit" unless the parts are separable.

MarketContext is built ONCE per symbol per scan from real live candles and
handed to every module, so all competitors are judged on identical data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MarketContext:
    """Live tape snapshot for one symbol. Every field is measured, never faked.

    Optional fields are None when the feed could not supply them; a module must
    stand aside on missing data rather than assume a value (commander doctrine:
    gates skip on missing data, they never fabricate).
    """

    symbol: str
    price: float
    ema9: float
    ema21: float
    vwap: float
    #: Closes of the intraday series, oldest first (last element == price).
    closes: tuple[float, ...]
    #: Highs/lows of the same series, used for range/breakout logic.
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    atr: float | None = None
    regime: str = "UNKNOWN"
    #: India VIX as a percentile of its trailing range (0.0-1.0), None if absent.
    vix_percentile: float | None = None
    #: Minutes since the session opened; None when the session clock is unknown.
    minutes_into_session: int | None = None
    #: Calendar date of the session being traded, read off the LAST CANDLE — not
    #: from the wall clock, which would silently fabricate a date on any replay
    #: or backtest and make an event module untestable.
    #:
    #: Added 2026-08-27. Until then no module could know what day it was, so a
    #: recurring weekly event was literally inexpressible. Open-source research
    #: on natural gas says the EIA storage report lands every Thursday 10:30 ET
    #: (20:00 IST) and that gas return volatility is measurably higher on
    #: Thursdays than any other day — the single most informative hour of the
    #: gas week, and Hokage was blind to which day it was.
    #:
    #: None when the feed could not supply candles. A module reading it must
    #: stand aside on None rather than guess a weekday.
    session_date: "date | None" = None
    #: Minutes since midnight IST of the LAST CANDLE, 0..1439. Read off the
    #: tape for the same reason session_date is: a wall-clock read would
    #: fabricate a time on any replay or backtest.
    #:
    #: Added 2026-10-20, after an MCX evening-only session cost a whole
    #: window. SessionShift gated on `minutes_into_session` against constants
    #: written for a 09:00 open — so on Dussehra, when MCX opened at 17:00 and
    #: ran the evening session only, its 17:00-18:30 window mapped to
    #: 01:00-02:30 and never arrived. Both metals were evaluated ten times and
    #: refused every one with "outside the window (30min into session)" while
    #: the clock read 17:30.
    #:
    #: minutes_into_session is still the right question for "how far into the
    #: day are we" (an opening-range module wants exactly that). This answers
    #: the different question "what time is it", which is what a module gated
    #: on an external market's hours actually needs.
    #:
    #: None when the feed supplied no candles. A module reading it must stand
    #: aside rather than guess the hour.
    minute_of_day: int | None = None

    @property
    def weekday(self) -> int | None:
        """Monday=0 .. Sunday=6, or None when the session date is unknown."""
        return None if self.session_date is None else self.session_date.weekday()

    @property
    def trend_up(self) -> bool:
        return self.ema9 > self.ema21

    @property
    def above_vwap(self) -> bool:
        return self.price > self.vwap

    def distance_from_vwap_pct(self) -> float:
        """Signed stretch from the session's volume-weighted fair value."""
        if self.vwap <= 0:
            return 0.0
        return (self.price - self.vwap) / self.vwap * 100.0


@dataclass(frozen=True)
class EntrySignal:
    """A module's verdict on entering. `direction` is only meaningful when
    `should_enter` is True."""

    should_enter: bool
    direction: str = ""  # "long" | "short"
    reason: str = ""
    #: 0-100. Honest self-assessment of setup quality; consumed by sizing.
    confidence: float = 0.0

    @classmethod
    def stand_aside(cls, reason: str) -> "EntrySignal":
        return cls(should_enter=False, reason=reason)
