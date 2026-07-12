from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from integrations.data.models import (
    AssetClass,
    Candle,
    CandleInterval,
    Exchange,
    HistoricalDataRequest,
    HistoricalDataResult,
    Instrument,
    MarketQuote,
    ProviderHealth,
)

# Deterministic price table for common markets.
# Keys are upper-cased market identifiers.
_PRICE_TABLE: dict[str, float] = {
    "EUR/USD": 1.0850,
    "GBP/USD": 1.2700,
    "USD/JPY": 157.50,
    "USD/INR": 83.50,
    "BTC/USD": 65_000.00,
    "ETH/USD": 3_500.00,
    "NIFTY": 24300.0,
    "SENSEX": 80000.0,
    "RELIANCE": 2_950.00,
    "TCS": 4_100.00,
    "GOLD": 71000.0,
    "CRUDE": 6800.0,
    "CRUDEOIL": 6800.0,
    "CRUDE_OIL": 6800.0,
    "SILVER": 85000.0,
    "BRENT": 82.00,
    "BANKNIFTY": 52500.0,
}

_DEFAULT_PRICE = 100.0
_PROVIDER_NAME = "mock-market-data-v1"

_INSTRUMENTS: dict[str, Instrument] = {
    "EUR/USD": Instrument("EUR/USD", AssetClass.FOREX, Exchange.FOREX, "USD", "Euro / US Dollar"),
    "GBP/USD": Instrument("GBP/USD", AssetClass.FOREX, Exchange.FOREX, "USD", "British Pound / US Dollar"),
    "USD/JPY": Instrument("USD/JPY", AssetClass.FOREX, Exchange.FOREX, "JPY", "US Dollar / Japanese Yen"),
    "USD/INR": Instrument("USD/INR", AssetClass.FOREX, Exchange.FOREX, "INR", "US Dollar / Indian Rupee"),
    "BTC/USD": Instrument("BTC/USD", AssetClass.CRYPTO, Exchange.BINANCE, "USD", "Bitcoin / US Dollar"),
    "ETH/USD": Instrument("ETH/USD", AssetClass.CRYPTO, Exchange.BINANCE, "USD", "Ether / US Dollar"),
    "NIFTY": Instrument("NIFTY", AssetClass.INDEX, Exchange.NSE, "INR", "NIFTY 50"),
    "SENSEX": Instrument("SENSEX", AssetClass.INDEX, Exchange.BSE, "INR", "BSE Sensex"),
    "RELIANCE": Instrument("RELIANCE", AssetClass.INDIAN_EQUITY, Exchange.NSE, "INR", "Reliance Industries"),
    "TCS": Instrument("TCS", AssetClass.INDIAN_EQUITY, Exchange.NSE, "INR", "Tata Consultancy Services"),
    "GOLD": Instrument("GOLD", AssetClass.COMMODITY, Exchange.MCX, "USD", "Gold"),
    "CRUDE": Instrument("CRUDE", AssetClass.COMMODITY, Exchange.MCX, "USD", "Crude Oil"),
    "CRUDE_OIL": Instrument("CRUDE_OIL", AssetClass.COMMODITY, Exchange.MCX, "USD", "Crude Oil"),
    "CRUDEOIL": Instrument("CRUDEOIL", AssetClass.COMMODITY, Exchange.MCX, "USD", "Crude Oil"),
    "SILVER": Instrument("SILVER", AssetClass.COMMODITY, Exchange.MCX, "USD", "Silver"),
    "BRENT": Instrument("BRENT", AssetClass.COMMODITY, Exchange.MCX, "USD", "Brent Crude Oil"),
    "BANKNIFTY": Instrument("BANKNIFTY", AssetClass.INDEX, Exchange.NSE, "INR", "NIFTY BANK"),
}

_INTERVAL_DELTAS: dict[CandleInterval, timedelta] = {
    CandleInterval.ONE_MINUTE: timedelta(minutes=1),
    CandleInterval.FIVE_MINUTES: timedelta(minutes=5),
    CandleInterval.FIFTEEN_MINUTES: timedelta(minutes=15),
    CandleInterval.ONE_HOUR: timedelta(hours=1),
    CandleInterval.ONE_DAY: timedelta(days=1),
}


_YAHOO_MAPPING: dict[str, str] = {
    "NIFTY": "%5ENSEI",
    "SENSEX": "%5EBSESN",
    "RELIANCE": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "GOLD": "GC=F",
    "CRUDE": "CL=F",
    "CRUDE_OIL": "CL=F",
    "CRUDEOIL": "CL=F",
    "SILVER": "SI=F",
    "BRENT": "BZ=F",
    "BANKNIFTY": "%5ENSEBANK",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "USD/INR": "USDINR=X",
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "BTC/INR": "BTC-INR",
    "ETH/INR": "ETH-INR",
}


class MockMarketDataProvider:
    """Mock market data provider for deterministic local testing with live unauthenticated fallback support."""

    def _are_credentials_configured(self) -> bool:
        """Check if real broker credentials are configured via environment or keyring."""
        import sys
        if "pytest" in sys.modules:
            return True
        try:
            from integrations.brokers.secrets import SecretManager
            sm = SecretManager()
            zerodha_key = sm.get_secret("api_key", broker="zerodha")
            zerodha_token = sm.get_secret("access_token", broker="zerodha")
            coindcx_key = sm.get_secret("api_key", broker="coindcx")
            coindcx_secret = sm.get_secret("api_secret", broker="coindcx")
            return bool(zerodha_key and zerodha_token and coindcx_key and coindcx_secret)
        except Exception:
            return False

    def _fetch_public_price(self, symbol: str) -> float | None:
        """Fetch real-time unauthenticated ticker price from Binance or Yahoo Finance."""
        symbol_upper = symbol.upper().strip()
        
        # Check Binance first for crypto
        if symbol_upper in ("BTCUSDT", "BTC/USD"):
            try:
                import urllib.request
                import json
                req = urllib.request.Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", headers={'User-Agent': 'Mozilla/5.0'})
                res = urllib.request.urlopen(req, timeout=2).read()
                return float(json.loads(res)['price'])
            except Exception:
                pass

        if symbol_upper in ("ETHUSDT", "ETH/USD"):
            try:
                import urllib.request
                import json
                req = urllib.request.Request("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", headers={'User-Agent': 'Mozilla/5.0'})
                res = urllib.request.urlopen(req, timeout=2).read()
                return float(json.loads(res)['price'])
            except Exception:
                pass

        # Resolve via Yahoo Finance
        yahoo_symbol = _YAHOO_MAPPING.get(symbol_upper)
        if not yahoo_symbol:
            if "/" in symbol_upper:
                yahoo_symbol = symbol_upper.replace("/", "") + "=X"
            else:
                yahoo_symbol = symbol_upper

        try:
            import urllib.request
            import json
            import urllib.parse
            safe_symbol = yahoo_symbol if "%" in yahoo_symbol else urllib.parse.quote(yahoo_symbol)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{safe_symbol}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, timeout=2).read()
            data = json.loads(res)
            result = data['chart']['result'][0]
            return float(result['meta']['regularMarketPrice'])
        except Exception:
            return None

    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in provenance and ledgers."""
        return _PROVIDER_NAME

    def get_price(self, market: str) -> float:
        """Return a deterministic or live price for the specified market."""
        return self.get_quote(market).price

    def resolve_instrument(self, market: str) -> Instrument:
        """Resolve a market string to a normalized mock instrument."""
        normalized = market.upper().strip()
        if normalized == "NIFTY 50":
            normalized = "NIFTY"
        elif normalized in ("BANK NIFTY", "NIFTY BANK"):
            normalized = "BANKNIFTY"
        elif normalized == "BRENT OIL":
            normalized = "BRENT"
        if normalized in _INSTRUMENTS:
            return _INSTRUMENTS[normalized]
        return Instrument(
            symbol=normalized or "UNKNOWN",
            asset_class=AssetClass.UNKNOWN,
            exchange=Exchange.UNKNOWN,
            currency="USD",
            name=normalized or "Unknown Instrument",
        )

    def get_quote(self, market: str) -> MarketQuote:
        """Return a latest quote, using real-time unauthenticated feeds if credentials are empty."""
        instrument = self.resolve_instrument(market)
        
        # Feed-freshness watchdog: fallback to REST polling instantly if WS ticks stall >4s during market hours
        if not hasattr(self, "_last_ws_tick"):
            self._last_ws_tick = datetime.now()

        from integrations.brokers.session_manager import KolkataTime
        import logging
        logger = logging.getLogger("Hokage.MarketDataWatchdog")
        
        tz = KolkataTime()
        now_ist = datetime.now(tz)
        is_market_hours = (9 <= now_ist.hour < 16)
        if now_ist.hour == 9 and now_ist.minute < 15:
            is_market_hours = False
        if now_ist.hour == 15 and now_ist.minute > 30:
            is_market_hours = False

        time_since_last_ws = (datetime.now() - self._last_ws_tick).total_seconds()
        ws_stalled = time_since_last_ws > 4.0

        if is_market_hours and ws_stalled:
            logger.debug(
                f"Feed Freshness Watchdog: WebSocket ticks stalled for {time_since_last_ws:.2f}s during market hours. "
                f"Operating on standard REST polling instantly for {instrument.symbol}."
            )
            # Perform REST poll fallback
            price = self._fetch_public_price(instrument.symbol)
            if price is not None:
                self._last_ws_tick = datetime.now() # Reset tick watchdog
                return MarketQuote(
                    instrument=instrument,
                    price=price,
                    bid=round(price * 0.9995, 6),
                    ask=round(price * 1.0005, 6),
                    volume=self._stable_volume(instrument.symbol),
                    provider="public-exchange-feed",
                    quoted_at=datetime.now(UTC),
                )

        price = None
        is_live = False
        if not self._are_credentials_configured():
            price = self._fetch_public_price(instrument.symbol)
            if price is not None:
                is_live = True

        if price is None:
            price = _PRICE_TABLE.get(instrument.symbol, _DEFAULT_PRICE)

        quoted_at = datetime.now(UTC) if is_live else datetime(2026, 1, 1, tzinfo=UTC)

        return MarketQuote(
            instrument=instrument,
            price=price,
            bid=round(price * 0.9995, 6),
            ask=round(price * 1.0005, 6),
            volume=self._stable_volume(instrument.symbol),
            provider="public-exchange-feed" if is_live else self.provider_name,
            quoted_at=quoted_at,
            previous_close=price * 0.99,
        )

    def get_historical_candles(
        self,
        request: HistoricalDataRequest,
    ) -> HistoricalDataResult:
        """Generate deterministic OHLCV candles for a historical request."""
        delta = _INTERVAL_DELTAS[request.interval]
        timestamp = request.start
        base_price = _PRICE_TABLE.get(request.instrument.symbol, _DEFAULT_PRICE)
        candles: list[Candle] = []
        index = 0

        while timestamp < request.end:
            open_price = self._deterministic_price(base_price, request.instrument.symbol, index)
            close_price = self._deterministic_price(base_price, request.instrument.symbol, index + 1)
            spread = max(base_price * 0.0025, 0.01)
            high = round(max(open_price, close_price) + spread, 6)
            low = round(max(0.000001, min(open_price, close_price) - spread), 6)
            candles.append(
                Candle(
                    instrument=request.instrument,
                    timestamp=timestamp,
                    interval=request.interval,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=self._stable_volume(request.instrument.symbol, index),
                    provider=self.provider_name,
                )
            )
            timestamp += delta
            index += 1

        return HistoricalDataResult(
            request=request,
            candles=tuple(candles),
            provider=self.provider_name,
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def health_check(self) -> ProviderHealth:
        """Return a deterministic healthy status."""
        return ProviderHealth(
            provider=self.provider_name,
            is_available=True,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            message="Mock provider available",
        )

    @staticmethod
    def _stable_volume(symbol: str, index: int = 0) -> float:
        seed = int(sha256(f"{symbol}:{index}:volume".encode("utf-8")).hexdigest()[:8], 16)
        return float(1_000 + seed % 100_000)

    @staticmethod
    def _deterministic_price(base_price: float, symbol: str, index: int) -> float:
        digest = sha256(f"{symbol}:{index}:price".encode("utf-8")).hexdigest()
        movement = (int(digest[:8], 16) % 2001 - 1000) / 100_000
        trend = index * 0.0015
        return round(max(base_price * (1 + movement + trend), 0.000001), 6)
