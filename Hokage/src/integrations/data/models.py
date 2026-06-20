from __future__ import annotations

import os
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Configuration for provider selection."""

    market_data_mode: MarketDataMode = MarketDataMode.MOCK

    @classmethod
    def from_env(cls) -> ProviderConfig:
        mode = os.getenv("HOKAGE_MARKET_DATA_MODE", MarketDataMode.MOCK.value)
        return cls(market_data_mode=MarketDataMode.from_string(mode))
