from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MarketDataMode(StrEnum):
    MOCK = "mock"
    KITE = "kite"
    ALPHA_VANTAGE = "alpha-vantage"

    @classmethod
    def from_string(cls, mode: str) -> MarketDataMode:
        normalized = mode.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(
            f"Unsupported market data mode '{mode}'. "
            f"Supported modes: {', '.join(item.value for item in cls)}."
        )


class AssetClass(StrEnum):
    """Normalized asset classes supported by Hokage market data."""

    INDIAN_EQUITY = "indian_equity"
    GLOBAL_EQUITY = "global_equity"
    FOREX = "forex"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    INDEX = "index"
    FNO = "fno"
    UNKNOWN = "unknown"


class Exchange(StrEnum):
    """Normalized exchange or venue identifiers."""

    NSE = "NSE"
    BSE = "BSE"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    FOREX = "FOREX"
    MCX = "MCX"
    BINANCE = "BINANCE"
    GLOBAL = "GLOBAL"
    UNKNOWN = "UNKNOWN"


class CandleInterval(StrEnum):
    """Supported historical candle intervals."""

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"


@dataclass(frozen=True, slots=True)
class Instrument:
    """Provider-neutral market instrument identity."""

    symbol: str
    asset_class: AssetClass = AssetClass.UNKNOWN
    exchange: Exchange = Exchange.UNKNOWN
    currency: str = "USD"
    name: str | None = None
    provider_symbol: str | None = None
    metadata: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("instrument symbol must not be empty.")
        if not self.currency.strip():
            raise ValueError("instrument currency must not be empty.")


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """Normalized latest-price quote."""

    instrument: Instrument
    price: float
    provider: str
    quoted_at: datetime
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("quote price must be positive.")
        if not self.provider.strip():
            raise ValueError("quote provider must not be empty.")


@dataclass(frozen=True, slots=True)
class Candle:
    """Normalized OHLCV candle."""

    instrument: Instrument
    timestamp: datetime
    interval: CandleInterval
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if any(price <= 0 for price in prices):
            raise ValueError("candle prices must be positive.")
        if self.high < max(self.open, self.close):
            raise ValueError("candle high must be at least open and close.")
        if self.low > min(self.open, self.close):
            raise ValueError("candle low must be at most open and close.")
        if self.volume < 0:
            raise ValueError("candle volume cannot be negative.")
        if not self.provider.strip():
            raise ValueError("candle provider must not be empty.")


@dataclass(frozen=True, slots=True)
class HistoricalDataRequest:
    """Request for normalized historical candles."""

    instrument: Instrument
    start: datetime
    end: datetime
    interval: CandleInterval = CandleInterval.ONE_DAY

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            object.__setattr__(self, "start", self.start.replace(tzinfo=UTC))
        if self.end.tzinfo is None:
            object.__setattr__(self, "end", self.end.replace(tzinfo=UTC))
        if self.end <= self.start:
            raise ValueError("historical data end must be after start.")


@dataclass(frozen=True, slots=True)
class HistoricalDataResult:
    """Provider response containing normalized historical candles."""

    request: HistoricalDataRequest
    candles: tuple[Candle, ...]
    provider: str
    generated_at: datetime

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("historical data provider must not be empty.")


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Provider health/status snapshot."""

    provider: str
    is_available: bool
    checked_at: datetime
    message: str = "OK"


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Configuration for provider selection."""

    market_data_mode: MarketDataMode = MarketDataMode.MOCK

    @classmethod
    def from_env(cls) -> ProviderConfig:
        mode = os.getenv("HOKAGE_MARKET_DATA_MODE", MarketDataMode.MOCK.value)
        return cls(market_data_mode=MarketDataMode.from_string(mode))
