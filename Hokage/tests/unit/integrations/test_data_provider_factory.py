from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.data.factory import ProviderFactory
from integrations.data.models import (
    AssetClass,
    CandleInterval,
    Exchange,
    HistoricalDataRequest,
    ProviderConfig,
    MarketDataMode,
)
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

    def test_create_market_data_provider_kite(self) -> None:
        from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
        from unittest.mock import MagicMock
        config = ProviderConfig(market_data_mode=MarketDataMode.KITE)
        mock_conn = MagicMock()
        provider = ProviderFactory.create_market_data_provider(config, connection_manager=mock_conn)
        assert isinstance(provider, KiteMarketDataProvider)

    def test_create_market_data_provider_env_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOKAGE_MARKET_DATA_MODE", "mock")
        provider = ProviderFactory.create_market_data_provider()
        assert isinstance(provider, MockMarketDataProvider)

    def test_create_market_data_provider_env_variable_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOKAGE_MARKET_DATA_MODE", "invalid-mode")
        with pytest.raises(ValueError, match="Unsupported market data mode"):
            ProviderConfig.from_env()

    def test_mock_provider_resolves_multi_market_instruments(self) -> None:
        provider = MockMarketDataProvider()

        reliance = provider.resolve_instrument("RELIANCE")
        bitcoin = provider.resolve_instrument("BTC/USD")
        euro = provider.resolve_instrument("EUR/USD")

        assert reliance.asset_class is AssetClass.INDIAN_EQUITY
        assert reliance.exchange is Exchange.NSE
        assert bitcoin.asset_class is AssetClass.CRYPTO
        assert euro.asset_class is AssetClass.FOREX

    def test_mock_provider_quote_contains_provenance(self) -> None:
        provider = MockMarketDataProvider()

        quote = provider.get_quote("NIFTY")

        assert quote.price == 22500.0
        assert quote.instrument.currency == "INR"
        assert quote.provider == provider.provider_name
        assert quote.bid is not None
        assert quote.ask is not None

    def test_mock_provider_historical_candles_are_deterministic(self) -> None:
        provider = MockMarketDataProvider()
        instrument = provider.resolve_instrument("EUR/USD")
        request = HistoricalDataRequest(
            instrument=instrument,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 6, tzinfo=UTC),
            interval=CandleInterval.ONE_DAY,
        )

        first = provider.get_historical_candles(request)
        second = provider.get_historical_candles(request)

        assert first.candles == second.candles
        assert len(first.candles) == 5
        assert first.provider == provider.provider_name
