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
