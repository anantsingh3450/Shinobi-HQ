from __future__ import annotations

import os

import pytest

from integrations.data.factory import ProviderFactory
from integrations.data.models import ProviderConfig, MarketDataMode
from integrations.data.mock_provider import MockMarketDataProvider


class TestProviderFactory:
    def test_create_market_data_provider_default(self) -> None:
        provider = ProviderFactory.create_market_data_provider()
        assert isinstance(provider, MockMarketDataProvider)
        assert provider.get_price("EUR/USD") == 1.0850

    def test_create_market_data_provider_mock_explicit(self) -> None:
        config = ProviderConfig(market_data_mode=MarketDataMode.MOCK)
        provider = ProviderFactory.create_market_data_provider(config)
        assert isinstance(provider, MockMarketDataProvider)
        assert provider.get_price("UNKNOWN") == 100.0

    def test_create_market_data_provider_kite_raises_not_implemented(self) -> None:
        config = ProviderConfig(market_data_mode=MarketDataMode.KITE)
        with pytest.raises(NotImplementedError, match="KiteMarketDataProvider is a placeholder"):
            ProviderFactory.create_market_data_provider(config)

    def test_create_market_data_provider_env_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOKAGE_MARKET_DATA_MODE", "mock")
        provider = ProviderFactory.create_market_data_provider()
        assert isinstance(provider, MockMarketDataProvider)

    def test_create_market_data_provider_env_variable_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOKAGE_MARKET_DATA_MODE", "invalid-mode")
        with pytest.raises(ValueError, match="Unsupported market data mode"):
            ProviderConfig.from_env()
