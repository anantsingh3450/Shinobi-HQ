"""Trading Session Manager for Hokage.

Manages trading sessions, calendars, timezones, and holidays for all exchanges
independently. Determines whether an asset is currently tradable.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time, timezone, tzinfo, timedelta

from integrations.data.models import Exchange, AssetClass

logger = logging.getLogger("Hokage.TradingSession")


class KolkataTime(tzinfo):
    """Kolkata Time Zone (IST) — always UTC+5:30."""

    def utcoffset(self, dt):
        return timedelta(hours=5, minutes=30)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "IST"


class EasternTime(tzinfo):
    """Eastern Time Zone (EST/EDT) with DST support."""

    def utcoffset(self, dt):
        if self._is_dst(dt):
            return timedelta(hours=-4)
        return timedelta(hours=-5)

    def dst(self, dt):
        if self._is_dst(dt):
            return timedelta(hours=1)
        return timedelta(0)

    def tzname(self, dt):
        if self._is_dst(dt):
            return "EDT"
        return "EST"

    def _is_dst(self, dt):
        if dt is None:
            return False
        # Naive datetime comparison
        d = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
        
        # DST in US starts on the second Sunday of March and ends on the first Sunday of November.
        march_1 = datetime(dt.year, 3, 1)
        first_sun_march = 1 + (6 - march_1.weekday()) % 7
        dst_start = datetime(dt.year, 3, first_sun_march + 7, 2, 0)
        
        nov_1 = datetime(dt.year, 11, 1)
        dst_end = datetime(dt.year, 11, 1 + (6 - nov_1.weekday()) % 7, 2, 0)
        
        return dst_start <= d < dst_end


class TradingSessionManager:
    """Manages trading calendars, sessions, and tradability of assets across all exchanges."""

    def __init__(self) -> None:
        # Standard Indian holidays for 2026 (YYYY-MM-DD)
        self.indian_holidays = {
            "2026-01-01",  # New Year
            "2026-01-26",  # Republic Day
            "2026-03-06",  # Holi
            "2026-04-02",  # Good Friday
            "2026-05-01",  # May Day
            "2026-08-15",  # Independence Day
            "2026-10-02",  # Gandhi Yananti
            "2026-12-25",  # Christmas
        }
        # US holidays for 2026
        self.us_holidays = {
            "2026-01-01",  # New Year
            "2026-01-19",  # MLK Day
            "2026-02-16",  # Washington's Birthday
            "2026-05-25",  # Memorial Day
            "2026-07-04",  # Independence Day
            "2026-09-07",  # Labor Day
            "2026-11-26",  # Thanksgiving
            "2026-12-25",  # Christmas
        }

    def resolve_exchange(self, asset: str) -> Exchange:
        """Resolve the exchange for a given asset symbol."""
        asset_upper = asset.upper().strip()
        
        # Crypto
        if "/" in asset_upper and ("USDT" in asset_upper or "USD" in asset_upper or "BTC" in asset_upper or "ETH" in asset_upper):
            return Exchange.BINANCE
        if asset_upper in ("BTC", "ETH", "SOL", "XRP", "BTCUSDT", "ETHUSDT"):
            return Exchange.BINANCE

        # Forex
        if asset_upper in ("EURUSD", "EUR/USD", "USDINR", "USD/INR", "GBPUSD", "GBP/USD"):
            return Exchange.FOREX

        # MCX. Bug fixed 2026-07-18: "SILVER" was missing from the substring
        # chain (only an exact-match entry existed) — a SILVER/SILVERM OPTION
        # tradingsymbol (e.g. "SILVERM26AUG...PE") fell through to the NSE
        # default instead of resolving to MCX.
        if (
            asset_upper in ("GOLD", "GOLDM", "CRUDE", "CRUDE_OIL", "CRUDEOIL", "NATURALGAS", "SILVER", "SILVERM", "COPPER")
            or "CRUDEOIL" in asset_upper
            or "NATURALGAS" in asset_upper
            or "GOLD" in asset_upper
            or "SILVER" in asset_upper
        ):
            return Exchange.MCX

        # NASDAQ / US Equity
        if asset_upper in ("AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "NASDAQ"):
            return Exchange.NASDAQ

        # Default to NSE for typical Indian equities
        return Exchange.NSE

    def resolve_asset_class(self, asset: str) -> AssetClass:
        """Resolve the asset class for a given symbol based on exchange."""
        exchange = self.resolve_exchange(asset)
        if exchange in (Exchange.NSE, Exchange.BSE):
            return AssetClass.INDIAN_EQUITY
        elif exchange in (Exchange.NYSE, Exchange.NASDAQ):
            return AssetClass.GLOBAL_EQUITY
        elif exchange == Exchange.MCX:
            return AssetClass.COMMODITY
        elif exchange == Exchange.BINANCE:
            return AssetClass.CRYPTO
        elif exchange == Exchange.FOREX:
            return AssetClass.FOREX
        else:
            return AssetClass.UNKNOWN

    def get_timezone(self, exchange: Exchange) -> tzinfo:
        """Get the timezone for a given exchange."""
        if exchange in (Exchange.NSE, Exchange.BSE, Exchange.MCX):
            return KolkataTime()
        elif exchange in (Exchange.NASDAQ, Exchange.NYSE):
            return EasternTime()
        else:
            return timezone.utc

    def get_exchange_status(self, exchange: Exchange, current_time: datetime | None = None) -> str:
        """Determine the session status for an exchange at the given time.
        
        Returns one of: OPEN, CLOSED, PRE_OPEN, POST_CLOSE, MAINTENANCE.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        elif current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        tz = self.get_timezone(exchange)
        local_dt = current_time.astimezone(tz)
        local_date_str = local_dt.strftime("%Y-%m-%d")
        day_of_week = local_dt.weekday()  # 0 = Monday, 6 = Sunday
        local_time = local_dt.time()

        # Crypto is 24/7
        if exchange == Exchange.BINANCE:
            # Simple scheduled maintenance Sunday 03:00 to 03:15 UTC
            utc_dt = current_time.astimezone(timezone.utc)
            if utc_dt.weekday() == 6 and dt_time(3, 0) <= utc_dt.time() <= dt_time(3, 15):
                return "MAINTENANCE"
            return "OPEN"

        # Weekday checks for traditional markets
        if day_of_week >= 5:  # Saturday or Sunday
            return "CLOSED"

        # Holiday checks
        if exchange in (Exchange.NSE, Exchange.BSE, Exchange.MCX):
            if local_date_str in self.indian_holidays:
                return "CLOSED"
        elif exchange in (Exchange.NASDAQ, Exchange.NYSE):
            if local_date_str in self.us_holidays:
                return "CLOSED"

        # Session hour checks
        if exchange in (Exchange.NSE, Exchange.BSE):
            # Pre-open: 09:00 - 09:15 IST
            if dt_time(9, 0) <= local_time < dt_time(9, 15):
                return "PRE_OPEN"
            # Open: 09:15 - 15:30 IST
            elif dt_time(9, 15) <= local_time < dt_time(15, 30):
                return "OPEN"
            # Post-close: 15:30 - 16:00 IST
            elif dt_time(15, 30) <= local_time < dt_time(16, 0):
                return "POST_CLOSE"
            else:
                return "CLOSED"

        elif exchange == Exchange.MCX:
            # MCX: 09:00 - 23:30 IST
            if dt_time(9, 0) <= local_time < dt_time(23, 30):
                return "OPEN"
            else:
                return "CLOSED"

        elif exchange in (Exchange.NASDAQ, Exchange.NYSE):
            # Pre-open: 04:00 - 09:30 EST
            if dt_time(4, 0) <= local_time < dt_time(9, 30):
                return "PRE_OPEN"
            # Open: 09:30 - 16:00 EST
            elif dt_time(9, 30) <= local_time < dt_time(16, 0):
                return "OPEN"
            # Post-close: 16:00 - 20:00 EST
            elif dt_time(16, 0) <= local_time < dt_time(20, 0):
                return "POST_CLOSE"
            else:
                return "CLOSED"

        elif exchange == Exchange.FOREX:
            # Forex runs 24h on weekdays.
            # Opens Monday 00:00 UTC to Friday 23:59 UTC.
            utc_dt = current_time.astimezone(timezone.utc)
            if utc_dt.weekday() == 0 and utc_dt.time() >= dt_time(0, 0):
                return "OPEN"
            elif 1 <= utc_dt.weekday() <= 3:
                return "OPEN"
            elif utc_dt.weekday() == 4 and utc_dt.time() <= dt_time(23, 59):
                return "OPEN"
            else:
                return "CLOSED"

        return "CLOSED"

    def is_tradable(self, asset: str, current_time: datetime | None = None) -> bool:
        """Check if a specific asset is currently tradable based on resolved exchange and time."""
        exchange = self.resolve_exchange(asset)
        status = self.get_exchange_status(exchange, current_time)
        return status == "OPEN"
