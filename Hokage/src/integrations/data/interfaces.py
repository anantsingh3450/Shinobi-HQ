from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.execution.interfaces import PriceSource
from integrations.data.models import (
    HistoricalDataRequest,
    HistoricalDataResult,
    Instrument,
    MarketQuote,
    ProviderHealth,
)


@runtime_checkable
class MarketDataProvider(PriceSource, Protocol):
    """Market data provider adapter used by Hokage.

    This protocol extends the existing PriceSource abstraction used by
    the paper trading engine and preserves compatibility for future live
    and fallback market data providers.
    """

    @property
    def provider_name(self) -> str:
        """Stable provider identifier for provenance and ledgers."""
        ...

    def resolve_instrument(self, market: str) -> Instrument:
        """Resolve a market string into a normalized instrument."""
        ...

    def get_quote(self, market: str) -> MarketQuote:
        """Return the latest normalized quote for a market."""
        ...

    def get_historical_candles(
        self,
        request: HistoricalDataRequest,
    ) -> HistoricalDataResult:
        """Return normalized historical candles for backtesting."""
        ...

    def health_check(self) -> ProviderHealth:
        """Return provider availability status."""
        ...
