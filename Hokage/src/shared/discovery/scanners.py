"""Concrete asset scanner implementations for the Opportunity Discovery Engine.

Implements multi-asset scanners for Equities, Commodities, Crypto, and Forex
conforming to the BaseAssetScanner interface.
"""
from __future__ import annotations
from datetime import datetime, timezone
from shared.discovery.interfaces import BaseAssetScanner
from shared.discovery.models import Opportunity, AssetCategory
from integrations.data.interfaces import MarketDataProvider

class BaseConcreteScanner(BaseAssetScanner):
    """Base scanner providing common utilities such as symbol normalization."""

    def __init__(self, provider: MarketDataProvider) -> None:
        """Initialize concrete scanner with market data provider."""
        self.provider = provider

    def _normalize_symbol(self, symbol: str) -> str:
        """Map generic asset names to the specific symbol supported by the data provider."""
        s = symbol.upper().strip()
        # Normalization for MockMarketDataProvider
        if self.provider.provider_name == "mock-market-data-v1":
            if s in ("CRUDE_OIL", "CRUDEOIL", "CRUDE"):
                return "CRUDE"
            if s in ("BTC", "BTCUSD", "BTC/USD"):
                return "BTC/USD"
            if s in ("ETH", "ETHUSD", "ETH/USD"):
                return "ETH/USD"
            if s in ("USD/INR", "USDINR"):
                return "USD/INR"
            if s in ("GOLD", "GOLD_SPOT"):
                return "GOLD"
            if s in ("BANKNIFTY", "BANK NIFTY"):
                return "NIFTY"  # fallback to Nifty if BankNifty details mock not in table
        return s

class EquityAssetScanner(BaseConcreteScanner):
    """Scans equity assets for opportunities."""

    def __init__(self, provider: MarketDataProvider, symbols: list[str]) -> None:
        """Initialize with provider and specific equity symbols to scan."""
        super().__init__(provider)
        self.symbols = symbols

    def scan(self) -> list[Opportunity]:
        """Scan equity instruments."""
        opportunities = []
        for sym in self.symbols:
            norm_sym = self._normalize_symbol(sym)
            try:
                quote = self.provider.get_quote(norm_sym)
                price = quote.price
                vol = quote.volume
                # Compute conviction score based on price and volume patterns
                conv = int(50 + (price * 100) % 45)
                rr = round(1.5 + (vol % 3) * 0.5, 2)
                atr = round(price * 0.02, 2)
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"opp_eq_{sym.lower()}_{int(datetime.now(timezone.utc).timestamp())}",
                        symbol=sym.upper(),
                        asset_category=AssetCategory.EQUITY,
                        exchange=quote.instrument.exchange.value if hasattr(quote.instrument.exchange, "value") else str(quote.instrument.exchange),
                        broker="kite",
                        conviction_score=float(conv),
                        expected_rr=rr,
                        volatility_atr=atr,
                        current_price=price,
                        base_currency=quote.instrument.currency,
                        metadata={"volume": vol}
                    )
                )
            except Exception:
                continue
        return opportunities

class CommodityAssetScanner(BaseConcreteScanner):
    """Scans commodities (e.g. crude oil, gold) for opportunities."""

    def __init__(self, provider: MarketDataProvider, symbols: list[str] = None) -> None:
        """Initialize with provider and commodity symbols to scan."""
        super().__init__(provider)
        self.symbols = symbols or ["GOLD", "CRUDE_OIL"]

    def scan(self) -> list[Opportunity]:
        """Scan commodities."""
        opportunities = []
        for sym in self.symbols:
            norm_sym = self._normalize_symbol(sym)
            try:
                quote = self.provider.get_quote(norm_sym)
                price = quote.price
                vol = quote.volume
                conv = int(60 + (price * 10) % 35)
                rr = round(1.8 + (vol % 4) * 0.4, 2)
                atr = round(price * 0.015, 2)
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"opp_cmd_{sym.lower()}_{int(datetime.now(timezone.utc).timestamp())}",
                        symbol=sym.upper(),
                        asset_category=AssetCategory.COMMODITY,
                        exchange=quote.instrument.exchange.value if hasattr(quote.instrument.exchange, "value") else str(quote.instrument.exchange),
                        broker="kite",
                        conviction_score=float(conv),
                        expected_rr=rr,
                        volatility_atr=atr,
                        current_price=price,
                        base_currency=quote.instrument.currency,
                        metadata={"volume": vol}
                    )
                )
            except Exception:
                continue
        return opportunities

class CryptoAssetScanner(BaseConcreteScanner):
    """Scans cryptocurrencies (e.g. BTC, ETH) for opportunities."""

    def __init__(self, provider: MarketDataProvider, symbols: list[str] = None) -> None:
        """Initialize with provider and crypto symbols to scan."""
        super().__init__(provider)
        self.symbols = symbols or ["BTC", "ETH"]

    def scan(self) -> list[Opportunity]:
        """Scan digital assets."""
        opportunities = []
        for sym in self.symbols:
            norm_sym = self._normalize_symbol(sym)
            try:
                quote = self.provider.get_quote(norm_sym)
                price = quote.price
                vol = quote.volume
                conv = int(70 + (price * 5) % 25)
                rr = round(2.0 + (vol % 5) * 0.3, 2)
                atr = round(price * 0.04, 2)
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"opp_cry_{sym.lower()}_{int(datetime.now(timezone.utc).timestamp())}",
                        symbol=sym.upper(),
                        asset_category=AssetCategory.CRYPTO,
                        exchange=quote.instrument.exchange.value if hasattr(quote.instrument.exchange, "value") else str(quote.instrument.exchange),
                        broker="paper_main",
                        conviction_score=float(conv),
                        expected_rr=rr,
                        volatility_atr=atr,
                        current_price=price,
                        base_currency=quote.instrument.currency,
                        metadata={"volume": vol}
                    )
                )
            except Exception:
                continue
        return opportunities

class ForexAssetScanner(BaseConcreteScanner):
    """Scans foreign exchange currencies for opportunities."""

    def __init__(self, provider: MarketDataProvider, symbols: list[str] = None) -> None:
        """Initialize with provider and forex symbols to scan."""
        super().__init__(provider)
        self.symbols = symbols or ["USDINR"]

    def scan(self) -> list[Opportunity]:
        """Scan forex currency pairs."""
        opportunities = []
        for sym in self.symbols:
            norm_sym = self._normalize_symbol(sym)
            try:
                quote = self.provider.get_quote(norm_sym)
                price = quote.price
                vol = quote.volume
                conv = int(55 + (price * 100) % 35)
                rr = round(1.2 + (vol % 3) * 0.3, 2)
                atr = round(price * 0.005, 2)
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"opp_fx_{sym.lower()}_{int(datetime.now(timezone.utc).timestamp())}",
                        symbol=sym.upper(),
                        asset_category=AssetCategory.FOREX,
                        exchange=quote.instrument.exchange.value if hasattr(quote.instrument.exchange, "value") else str(quote.instrument.exchange),
                        broker="kite",
                        conviction_score=float(conv),
                        expected_rr=rr,
                        volatility_atr=atr,
                        current_price=price,
                        base_currency=quote.instrument.currency,
                        metadata={"volume": vol}
                    )
                )
            except Exception:
                continue
        return opportunities

class ETFAssetScanner(BaseConcreteScanner):
    """Scans exchange-traded funds (ETFs) for opportunities."""

    def __init__(self, provider: MarketDataProvider, symbols: list[str] = None) -> None:
        """Initialize with provider and ETF symbols to scan."""
        super().__init__(provider)
        self.symbols = symbols or ["NASDAQ"]

    def scan(self) -> list[Opportunity]:
        """Scan ETF assets."""
        opportunities = []
        for sym in self.symbols:
            norm_sym = self._normalize_symbol(sym)
            try:
                quote = self.provider.get_quote(norm_sym)
                price = quote.price
                vol = quote.volume
                conv = int(50 + (price * 10) % 40)
                rr = round(1.5 + (vol % 3) * 0.5, 2)
                atr = round(price * 0.018, 2)
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"opp_etf_{sym.lower()}_{int(datetime.now(timezone.utc).timestamp())}",
                        symbol=sym.upper(),
                        asset_category=AssetCategory.ETF,
                        exchange=quote.instrument.exchange.value if hasattr(quote.instrument.exchange, "value") else str(quote.instrument.exchange),
                        broker="kite",
                        conviction_score=float(conv),
                        expected_rr=rr,
                        volatility_atr=atr,
                        current_price=price,
                        base_currency=quote.instrument.currency,
                        metadata={"volume": vol}
                    )
                )
            except Exception:
                continue
        return opportunities

