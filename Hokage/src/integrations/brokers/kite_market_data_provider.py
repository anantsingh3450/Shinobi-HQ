from __future__ import annotations

from datetime import datetime
from integrations.brokers.kite_connection import KiteConnectionManager
from integrations.brokers.models import utc_now
from integrations.data.interfaces import MarketDataProvider
from integrations.data.models import (
    AssetClass,
    Exchange,
    Instrument,
    MarketQuote,
    Candle,
    CandleInterval,
    HistoricalDataRequest,
    HistoricalDataResult,
    ProviderHealth,
)


class KiteMarketDataProvider(MarketDataProvider):
    """Kite Connect market data provider implementation.

    Conforms to the MarketDataProvider protocol.
    """

    def __init__(self, connection_manager: KiteConnectionManager) -> None:
        """Initialize KiteMarketDataProvider.

        Args:
            connection_manager: The active session connection manager.
        """
        self._connection_manager = connection_manager
        self._watchlist: list[str] = []

    @property
    def provider_name(self) -> str:
        return "kite"

    def resolve_instrument(self, market: str) -> Instrument:
        """Resolve a market string (e.g. INFY, NSE:INFY) into an Instrument."""
        parts = market.split(":")
        if len(parts) == 2:
            exchange_str = parts[0].upper()
            symbol = parts[1]
        else:
            exchange_str = "NSE"
            symbol = market

        exchange = Exchange.NSE if exchange_str == "NSE" else Exchange.BSE
        return Instrument(
            symbol=symbol,
            asset_class=AssetClass.INDIAN_EQUITY,
            exchange=exchange,
            currency="INR"
        )

    def get_price(self, market: str) -> float:
        """Retrieve latest price for compatibility with PriceSource."""
        quote = self.get_quote(market)
        return quote.price

    def get_quote(self, market: str) -> MarketQuote:
        """Retrieve latest market quote from Kite Connect API."""
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
        if is_market_hours and time_since_last_ws > 4.0:
            logger.debug(
                f"Feed Freshness Watchdog: WebSocket ticks stalled for {time_since_last_ws:.2f}s during market hours. "
                f"Operating on standard REST polling instantly for {market}."
            )
            self._last_ws_tick = datetime.now() # Reset watchdog tick on fallback trigger

        import time
        import urllib3
        import requests

        client = self._connection_manager.get_kite_client()
        inst = self.resolve_instrument(market)

        exchange_str = inst.exchange.value if inst.exchange.value in ("NSE", "BSE", "MCX") else "NSE"
        kite_symbol = f"{exchange_str}:{inst.symbol}"

        max_retries = 3
        quotes = {}
        for attempt in range(max_retries):
            try:
                quotes = client.quote([kite_symbol])
                break
            except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError, Exception) as e:
                if attempt == max_retries - 1:
                    logger.error(f"Kite API Network Error on {kite_symbol} after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Kite API Network Error fetching {kite_symbol}. Retrying in {wait_time}s... ({e})")
                time.sleep(wait_time)

        data = quotes.get(kite_symbol, {})
        last_price = float(data.get("last_price", 0.0))
        if last_price <= 0:
            raise ValueError(f"Could not retrieve price for {kite_symbol}")

        # Kite full-quote depth lives under data["depth"]["buy"/"sell"] (five
        # levels of {price, quantity, orders}); there are no top-level
        # "buy"/"sell" keys. The old code read those nonexistent keys and fell
        # back to bid = ask = last_price, so the spread was always 0.0 and the
        # liquidity gate could never see a real spread. Missing depth is now
        # reported as None, never as a fake zero-spread book.
        depth = data.get("depth") or {}
        buy_levels = depth.get("buy") or []
        sell_levels = depth.get("sell") or []

        bid = None
        ask = None
        if buy_levels and float(buy_levels[0].get("price", 0.0)) > 0:
            bid = float(buy_levels[0]["price"])
        if sell_levels and float(sell_levels[0].get("price", 0.0)) > 0:
            ask = float(sell_levels[0]["price"])

        # Order-book pressure: total pending buy/sell quantities. Fall back to
        # summing the five visible depth levels when totals are absent.
        bid_qty = float(data.get("buy_quantity", 0.0)) or sum(
            float(lv.get("quantity", 0.0)) for lv in buy_levels
        )
        ask_qty = float(data.get("sell_quantity", 0.0)) or sum(
            float(lv.get("quantity", 0.0)) for lv in sell_levels
        )

        previous_close = data.get("ohlc", {}).get("close")

        return MarketQuote(
            instrument=inst,
            price=last_price,
            provider=self.provider_name,
            quoted_at=utc_now(),
            bid=bid,
            ask=ask,
            volume=float(data.get("volume", 0.0)),
            previous_close=previous_close,
            bid_qty=bid_qty if bid_qty > 0 else None,
            ask_qty=ask_qty if ask_qty > 0 else None
        )

    def get_historical_candles(
        self,
        request: HistoricalDataRequest,
    ) -> HistoricalDataResult:
        """Retrieve historical data candles."""
        import time
        import urllib3
        import requests
        import logging
        logger = logging.getLogger("Hokage.MarketDataWatchdog")
        
        client = self._connection_manager.get_kite_client()
        inst = request.instrument
        exchange_str = inst.exchange.value if inst.exchange.value in ("NSE", "BSE", "MCX") else "NSE"
        kite_symbol = f"{exchange_str}:{inst.symbol}"

        max_retries = 3
        quotes = {}
        for attempt in range(max_retries):
            try:
                quotes = client.quote([kite_symbol])
                break
            except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError, Exception):
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

        token = quotes.get(kite_symbol, {}).get("instrument_token")
        if not token:
            raise ValueError(f"Could not retrieve instrument token for {kite_symbol}")

        # Map CandleInterval to Zerodha interval strings
        interval_map = {
            CandleInterval.ONE_MINUTE: "minute",
            CandleInterval.FIVE_MINUTES: "5minute",
            CandleInterval.FIFTEEN_MINUTES: "15minute",
            CandleInterval.ONE_HOUR: "60minute",
            CandleInterval.ONE_DAY: "day"
        }
        kite_interval = interval_map.get(request.interval, "day")

        candles_data = client.historical_data(
            instrument_token=token,
            from_date=request.start,
            to_date=request.end,
            interval=kite_interval
        )

        candles = []
        for c in candles_data:
            ts = c.get("date")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            candles.append(
                Candle(
                    instrument=inst,
                    timestamp=ts,
                    interval=request.interval,
                    open=float(c.get("open")),
                    high=float(c.get("high")),
                    low=float(c.get("low")),
                    close=float(c.get("close")),
                    volume=float(c.get("volume", 0.0)),
                    provider=self.provider_name
                )
            )

        return HistoricalDataResult(
            request=request,
            candles=tuple(candles),
            provider=self.provider_name,
            generated_at=utc_now()
        )

    def health_check(self) -> ProviderHealth:
        """Validate if Zerodha connection is operational."""
        try:
            client = self._connection_manager.get_kite_client()
            client.profile()
            return ProviderHealth(
                provider=self.provider_name,
                is_available=True,
                checked_at=utc_now(),
                message="OK"
            )
        except Exception as e:
            return ProviderHealth(
                provider=self.provider_name,
                is_available=False,
                checked_at=utc_now(),
                message=str(e)
            )

    # ------------------------------------------------------------------
    # Watchlist Support
    # ------------------------------------------------------------------

    def add_to_watchlist(self, market: str) -> None:
        """Add instrument market string to local watchlist."""
        if market not in self._watchlist:
            self._watchlist.append(market)

    def remove_from_watchlist(self, market: str) -> None:
        """Remove instrument market string from local watchlist."""
        if market in self._watchlist:
            self._watchlist.remove(market)

    def get_watchlist(self) -> list[str]:
        """Get the current watchlist of instrument symbols."""
        return list(self._watchlist)
