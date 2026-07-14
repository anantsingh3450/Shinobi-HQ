"""Options Router: converts directional underlying signals into option orders.

Hokage executes DERIVATIVES, never spot. For option-routed underlyings the
directional signal computed on the underlying (futures/index data) becomes a
BOUGHT option — never sold — so maximum loss is capped at the premium paid:

  BUY  (bullish)  -> BUY nearest-expiry ATM CE
  SELL (bearish)  -> BUY nearest-expiry ATM PE

Contract resolution reads the venue's REAL instruments dump via the market
data provider (`resolve_option_contract`): real tradingsymbol, real expiry,
real strike, real lot size. Nothing is string-guessed. When no live contract
or premium quote is available the router raises OptionsRoutingError and the
caller must NOT trade (fail closed) — a directional signal must never fall
back to an instrument class the commander has not approved.
"""

import logging
from typing import Any

from integrations.brokers.models import OrderRequest, OrderSide
from integrations.data.models import Instrument, Exchange, AssetClass

logger = logging.getLogger("Hokage.OptionsRouter")

#: Underlyings that route to options, keyed by INTERNAL symbol.
_OPTION_ROUTED_UNDERLYINGS = {
    "NIFTY": Exchange.NSE,
    "CRUDE_OIL": Exchange.MCX,
    "CRUDEOIL": Exchange.MCX,
}

#: An option position's premium notional (premium x lot size) may consume at
#: most this fraction of account cash. Conservative single-position cap.
MAX_PREMIUM_CASH_FRACTION = 0.5


class OptionsRoutingError(RuntimeError):
    """No tradable option contract could be resolved — caller must not trade."""


class OptionsRouter:
    """Translates a directional underlying signal into a real options order."""

    def __init__(self, price_source: Any = None) -> None:
        self.price_source = price_source

    @staticmethod
    def routes(symbol: str) -> bool:
        """True when this underlying executes as options."""
        return symbol.upper().strip() in _OPTION_ROUTED_UNDERLYINGS

    def route_to_options(
        self,
        req: OrderRequest,
        current_price: float,
        available_cash: float | None = None,
    ) -> OrderRequest:
        """Convert a directional underlying OrderRequest into an option BUY.

        Args:
            req: The directional order sized/approved on the underlying.
            current_price: Live underlying price (strike anchor).
            available_cash: Account cash for the premium affordability check;
                None skips the check (paper venue enforces its own balance).

        Raises:
            OptionsRoutingError: when no live contract resolves, the premium
                quote is unavailable, or the premium is unaffordable.
        """
        symbol_upper = req.instrument.symbol.upper().strip()
        if symbol_upper not in _OPTION_ROUTED_UNDERLYINGS:
            return req
        if symbol_upper.endswith(("CE", "PE")):
            return req

        if req.side == OrderSide.BUY:
            option_type, direction_label = "CE", "Bullish"
        elif req.side == OrderSide.SELL:
            option_type, direction_label = "PE", "Bearish"
        else:
            raise OptionsRoutingError(f"Unknown order side {req.side} for {symbol_upper}.")

        resolver = getattr(self.price_source, "resolve_option_contract", None)
        if resolver is None:
            raise OptionsRoutingError(
                f"Market data provider {type(self.price_source).__name__} exposes no real "
                f"option chain; refusing to fabricate a contract for {symbol_upper}."
            )
        contract = resolver(symbol_upper, option_type, current_price)
        if not contract or not contract.get("tradingsymbol") or contract.get("lot_size", 0) <= 0:
            raise OptionsRoutingError(
                f"No live {option_type} contract found for {symbol_upper} near {current_price}."
            )

        option_symbol = contract["tradingsymbol"]
        lot_size = float(contract["lot_size"])

        # Real premium quote: provenance for the instrument we actually buy.
        try:
            premium_quote = self.price_source.get_quote(option_symbol)
            premium = float(premium_quote.price)
        except Exception as exc:
            raise OptionsRoutingError(
                f"Premium quote unavailable for {option_symbol}: {exc}"
            ) from exc
        if premium <= 0:
            raise OptionsRoutingError(f"Invalid premium {premium} for {option_symbol}.")

        premium_notional = premium * lot_size
        if available_cash is not None and premium_notional > available_cash * MAX_PREMIUM_CASH_FRACTION:
            raise OptionsRoutingError(
                f"Premium notional ₹{premium_notional:,.0f} for {option_symbol} exceeds "
                f"{MAX_PREMIUM_CASH_FRACTION:.0%} of available cash ₹{available_cash:,.0f}."
            )

        logger.info(
            f"OptionsRouter: {direction_label} signal on {symbol_upper} @ {current_price:.2f} "
            f"-> BUY {option_symbol} (strike {contract['strike']}, expiry {contract['expiry']}, "
            f"1 lot = {lot_size:g}, premium ~₹{premium:.2f}, notional ~₹{premium_notional:,.0f})"
        )

        exchange = Exchange.MCX if contract["exchange"] == "MCX" else Exchange.NSE
        asset_class = AssetClass.COMMODITY if exchange == Exchange.MCX else AssetClass.INDEX
        metadata = dict(req.instrument.metadata or {})
        metadata.update(
            {
                "is_option": True,
                "underlying": symbol_upper,
                "underlying_price": current_price,
                "strike": contract["strike"],
                "expiry": str(contract["expiry"]),
                "option_type": option_type,
                "lot_size": lot_size,
                "premium_at_entry": premium,
                "kite_symbol": f"{contract['exchange']}:{option_symbol}",
            }
        )
        new_instrument = Instrument(
            symbol=option_symbol,
            asset_class=asset_class,
            exchange=exchange,
            currency="INR",
            metadata=metadata,
        )
        # Always BUY the option (loss capped at premium); one lot = lot_size units.
        return OrderRequest(
            instrument=new_instrument,
            side=OrderSide.BUY,
            quantity=lot_size,
            order_type=req.order_type,
            venue_id=req.venue_id,
            strategy_id=req.strategy_id,
            execution_reason=f"Options routing: {direction_label} {symbol_upper} -> BUY {option_symbol}",
            playbook_id=req.playbook_id,
            volatility_regime=req.volatility_regime,
        )
