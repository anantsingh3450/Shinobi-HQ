from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.execution.interfaces import PriceSource


@runtime_checkable
class MarketDataProvider(PriceSource, Protocol):
    """Market data provider adapter used by Hokage.

    This protocol extends the existing PriceSource abstraction used by
    the paper trading engine and preserves compatibility for future live
    and fallback market data providers.
    """

    pass
