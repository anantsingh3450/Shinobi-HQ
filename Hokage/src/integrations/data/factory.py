from __future__ import annotations

from integrations.data.interfaces import MarketDataProvider
from integrations.data.models import ProviderConfig, MarketDataMode
from integrations.data.mock_provider import MockMarketDataProvider


class ProviderFactory:
    """Factory that instantiates market data adapters based on runtime config."""

    @staticmethod
    def create_market_data_provider(
        config: ProviderConfig | None = None,
    ) -> MarketDataProvider:
        """Create the configured MarketDataProvider implementation."""
        config = config or ProviderConfig.from_env()

        if config.market_data_mode is MarketDataMode.MOCK:
            return MockMarketDataProvider()

        if config.market_data_mode is MarketDataMode.KITE:
            raise NotImplementedError(
                "KiteMarketDataProvider is a placeholder integration point. "
                "Implement Kite API access in Phase 4."
            )

        if config.market_data_mode is MarketDataMode.ALPHA_VANTAGE:
            raise NotImplementedError(
                "AlphaVantage provider is not implemented in Phase 3A. "
                "Use HOKAGE_MARKET_DATA_MODE=mock for current behavior."
            )

        raise ValueError(
            f"Unrecognized market data mode: {config.market_data_mode}"
        )