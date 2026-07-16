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

    #: Universe symbols that trade as derivatives: mapped to the nearest-expiry
    #: FUTURES contract on the real venue (Hokage trades futures/options, never
    #: spot). Key = internal symbol; value = (kite exchange, underlying name).
    _FUTURES_UNDERLYINGS: dict[str, tuple[str, str]] = {
        "NIFTY": ("NFO", "NIFTY"),
        "BANKNIFTY": ("NFO", "BANKNIFTY"),
        "CRUDE_OIL": ("MCX", "CRUDEOIL"),
        "CRUDEOIL": ("MCX", "CRUDEOIL"),
        "GOLD": ("MCX", "GOLD"),
        "SILVER": ("MCX", "SILVER"),
        "NATURALGAS": ("MCX", "NATURALGAS"),
    }

    #: Index quote symbols (benchmarks like the circuit-breaker feed, and BSE
    #: index spots). Quoted directly — these have no futures chain to read a
    #: spot from, unlike the NFO/MCX underlyings above.
    _INDEX_QUOTE_SYMBOLS: dict[str, tuple[str, str]] = {
        "NIFTY 50": ("NSE", "NIFTY 50"),
        "INDIA VIX": ("NSE", "INDIA VIX"),
        "SENSEX": ("BSE", "SENSEX"),
    }

    #: Index underlyings whose spot is quoted on BSE and whose options list on
    #: BFO. Kept separate from _FUTURES_UNDERLYINGS: there is no BSE index
    #: futures contract to derive a spot from, so the index itself is the quote.
    _BSE_INDEX_UNDERLYINGS: dict[str, str] = {
        "SENSEX": "SENSEX",
    }

    def __init__(self, connection_manager: KiteConnectionManager) -> None:
        """Initialize KiteMarketDataProvider.

        Args:
            connection_manager: The active session connection manager.
        """
        self._connection_manager = connection_manager
        self._watchlist: list[str] = []
        #: (exchange, underlying) -> (resolved_on_date, tradingsymbol)
        self._futures_symbol_cache: dict[tuple[str, str], tuple[object, str]] = {}

    @property
    def provider_name(self) -> str:
        return "kite"

    def _nearest_futures_symbol(self, kite_exchange: str, underlying: str) -> str:
        """Resolve the nearest-expiry (front-month) futures tradingsymbol.

        Cached per calendar day so expired contracts roll automatically at the
        next trading day's first quote.
        """
        from datetime import date
        today = date.today()
        cached = self._futures_symbol_cache.get((kite_exchange, underlying))
        if cached and cached[0] == today:
            return cached[1]

        client = self._connection_manager.get_kite_client()
        contracts = client.instruments(kite_exchange)
        futures = []
        for inst in contracts:
            if inst.get("name") != underlying or inst.get("instrument_type") != "FUT":
                continue
            expiry = inst.get("expiry")
            expiry_date = expiry.date() if hasattr(expiry, "date") and not isinstance(expiry, date) else expiry
            if expiry_date and expiry_date >= today:
                futures.append((expiry_date, inst["tradingsymbol"]))
        if not futures:
            raise ValueError(
                f"No live futures contract found for {underlying} on {kite_exchange}."
            )
        futures.sort()
        tradingsymbol = futures[0][1]
        self._futures_symbol_cache[(kite_exchange, underlying)] = (today, tradingsymbol)
        return tradingsymbol

    #: Option tradingsymbol prefixes and the exchange their contracts live on.
    #: Prefix -> exchange for quoting an option tradingsymbol. BSE index options
    #: (SENSEX/BANKEX) live on BFO, a different segment from NFO; without these
    #: a resolved SENSEX contract could not be quoted and every entry died at the
    #: premium fetch. Longer prefixes MUST precede shorter ones they contain
    #: ("BANKNIFTY" before "NIFTY"), or the wrong exchange wins the match.
    _OPTION_EXCHANGE_PREFIXES: tuple[tuple[str, str], ...] = (
        ("BANKNIFTY", "NFO"),
        ("NIFTY", "NFO"),
        ("SENSEX", "BFO"),
        ("BANKEX", "BFO"),
        ("CRUDEOIL", "MCX"),
        ("GOLD", "MCX"),
        ("SILVER", "MCX"),
        ("NATURALGAS", "MCX"),
    )

    def _kite_quote_symbol(self, market: str) -> str:
        """Map an internal market symbol to the real Kite quote symbol.

        Derivative universe symbols resolve to their front-month futures
        contract; known indices resolve to the exchange index symbol; option
        tradingsymbols (…CE/…PE) resolve to their derivatives exchange;
        anything else falls back to NSE equity naming.
        """
        market_upper = market.upper().strip()
        if market_upper in self._INDEX_QUOTE_SYMBOLS:
            exch, sym = self._INDEX_QUOTE_SYMBOLS[market_upper]
            return f"{exch}:{sym}"
        if market_upper in self._FUTURES_UNDERLYINGS:
            exch, underlying = self._FUTURES_UNDERLYINGS[market_upper]
            return f"{exch}:{self._nearest_futures_symbol(exch, underlying)}"
        if market_upper.endswith(("CE", "PE")):
            for prefix, exch in self._OPTION_EXCHANGE_PREFIXES:
                if market_upper.startswith(prefix):
                    return f"{exch}:{market_upper}"
        inst = self.resolve_instrument(market)
        exchange_str = inst.exchange.value if inst.exchange.value in ("NSE", "BSE", "MCX") else "NSE"
        return f"{exchange_str}:{inst.symbol}"

    #: MCX publishes commodity option lot sizes as 1 (per-contract) in the
    #: Kite instruments dump for both options AND their underlying futures —
    #: there is no way to read the real economic lot size from the API. This
    #: is MCX's own published contract specification (unit of trading per
    #: exchange circulars), not a Hokage assumption: CRUDEOIL = 100 barrels.
    #: Only commodities Hokage is authorised to trade need an entry here.
    _MCX_CONTRACT_MULTIPLIER: dict[str, float] = {
        "CRUDEOIL": 100.0,
    }

    #: Refuse to buy an option with less life than this. The resolver picks the
    #: NEAREST expiry, and MCX/BFO list contracts expiring the SAME DAY: on
    #: 2026-07-15 Hokage bought CRUDEOIL26JUL7750CE (expiry 2026-07-16) — an OTM
    #: option with one day left, at ~Rs 63 premium against a 7660 spot. Cheap
    #: because it was nearly dead, not because it was good. Buying options means
    #: theta is already the enemy; a 0-1 DTE contract is a lottery ticket whose
    #: premium decays to zero within hours, and it exits at breakeven or -100%.
    #: 2 days is the floor that removes expiry-day roulette while still allowing
    #: the weekly index cycles (NIFTY/SENSEX) the strategies actually trade.
    _MIN_DAYS_TO_EXPIRY = 2

    def resolve_option_contract(
        self,
        underlying: str,
        option_type: str,
        spot_price: float,
    ) -> dict | None:
        """Resolve the real nearest-expiry option contract closest to ATM.

        Reads the venue's actual instruments dump — no synthetic symbol
        construction, no guessed expiries. Returns a dict with tradingsymbol,
        exchange, strike, expiry, and lot_size, or None when no live contract
        matches (callers must fail closed: no trade, never a fabricated
        contract).
        """
        from datetime import date

        underlying_upper = underlying.upper().strip().replace("_", "")
        mapping = {
            "NIFTY": ("NFO", "NIFTY"),
            "BANKNIFTY": ("NFO", "BANKNIFTY"),
            "SENSEX": ("BFO", "SENSEX"),
            "BANKEX": ("BFO", "BANKEX"),
            "CRUDEOIL": ("MCX", "CRUDEOIL"),
            "GOLD": ("MCX", "GOLD"),
            "SILVER": ("MCX", "SILVER"),
            "NATURALGAS": ("MCX", "NATURALGAS"),
        }
        if underlying_upper not in mapping or option_type not in ("CE", "PE") or spot_price <= 0:
            return None
        kite_exchange, chain_name = mapping[underlying_upper]

        client = self._connection_manager.get_kite_client()
        contracts = client.instruments(kite_exchange)
        today = date.today()

        candidates = []
        for inst in contracts:
            if inst.get("name") != chain_name or inst.get("instrument_type") != option_type:
                continue
            expiry = inst.get("expiry")
            expiry_date = expiry.date() if hasattr(expiry, "date") and not isinstance(expiry, date) else expiry
            strike = float(inst.get("strike") or 0.0)
            if not expiry_date or strike <= 0:
                continue
            if (expiry_date - today).days < self._MIN_DAYS_TO_EXPIRY:
                continue
            candidates.append((expiry_date, abs(strike - spot_price), strike, inst))
        if not candidates:
            return None

        nearest_expiry = min(c[0] for c in candidates)
        atm = min((c for c in candidates if c[0] == nearest_expiry), key=lambda c: c[1])
        contract = atm[3]
        option_lot = float(contract.get("lot_size") or 0.0)

        # Kite reports MCX commodity option lot_size as 1 (per-contract) —
        # confirmed against the live instruments dump for both options AND
        # their underlying futures, so there is no larger lot to borrow from
        # within the dump itself. Apply MCX's own published contract-size
        # multiplier instead (e.g. 100 barrels/lot for CRUDEOIL).
        if option_lot <= 1.0 and kite_exchange == "MCX":
            multiplier = self._MCX_CONTRACT_MULTIPLIER.get(chain_name)
            if multiplier:
                option_lot = multiplier

        return {
            "tradingsymbol": contract["tradingsymbol"],
            "exchange": kite_exchange,
            "strike": atm[2],
            "expiry": nearest_expiry,
            "lot_size": option_lot,
        }

    def resolve_instrument(self, market: str) -> Instrument:
        """Resolve a market string (e.g. INFY, NSE:INFY) into an Instrument.

        The Instrument keeps the INTERNAL symbol (e.g. CRUDE_OIL) so tracking,
        risk, and exit bookkeeping stay keyed consistently; only outbound Kite
        API calls use the mapped tradingsymbol.
        """
        parts = market.split(":")
        if len(parts) == 2:
            exchange_str = parts[0].upper()
            symbol = parts[1]
        else:
            exchange_str = ""
            symbol = market

        symbol_upper = symbol.upper().strip()
        if symbol_upper in self._FUTURES_UNDERLYINGS:
            fut_exchange, _ = self._FUTURES_UNDERLYINGS[symbol_upper]
            if fut_exchange == "MCX":
                return Instrument(
                    symbol=symbol,
                    asset_class=AssetClass.COMMODITY,
                    exchange=Exchange.MCX,
                    currency="INR",
                )
            return Instrument(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                exchange=Exchange.NSE,
                currency="INR",
            )

        # BSE indices are quoted on BSE and traded on BFO. Without this they fell
        # through to the equity default below and were labelled NSE/INDIAN_EQUITY
        # — the wrong exchange for every downstream venue and gate decision.
        if symbol_upper in self._BSE_INDEX_UNDERLYINGS:
            return Instrument(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                exchange=Exchange.BSE,
                currency="INR",
            )

        exchange = Exchange.BSE if exchange_str == "BSE" else Exchange.NSE
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
        kite_symbol = self._kite_quote_symbol(market)

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
        kite_symbol = self._kite_quote_symbol(inst.symbol)

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

        # Kite reads historical_data timestamps as EXCHANGE-LOCAL (IST) and
        # drops any tzinfo. Callers pass UTC (datetime.now(timezone.utc)), so a
        # 05:01 UTC "to_date" was read as 05:01 IST — before the 09:15 open —
        # and silently truncated the ENTIRE current session. Every intraday
        # consumer (bias engine, ATR) then ran on yesterday's tape. Convert to
        # IST so "now" means now on the exchange's clock.
        from integrations.brokers.session_manager import KolkataTime
        _ist = KolkataTime()
        from_date = request.start.astimezone(_ist) if request.start.tzinfo else request.start
        to_date = request.end.astimezone(_ist) if request.end.tzinfo else request.end

        candles_data = client.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
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
