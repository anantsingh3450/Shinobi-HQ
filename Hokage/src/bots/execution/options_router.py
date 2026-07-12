"""Options Router to intercept trades and route them to derivatives (CE/PE).

Kite Connect symbol format for MCX Crude Oil Options:
  CRUDEOIL{YY}{MON}{STRIKE}{CE|PE}
  e.g. CRUDEOIL26JUL6800CE

Key rules:
  - Strike step is 50 (nearest 50) for Crude Oil.
  - The system always BUYS options (never sells), capping loss to premium only.
  - BUY signal → CE (Call), SELL signal → PE (Put).
  - Quantity is set to 1 lot (lot size = 100 barrels on MCX Crude mini is 10, standard is 100).
"""

import logging
from datetime import datetime
from typing import Any

from integrations.brokers.models import OrderRequest, OrderSide
from integrations.data.models import Instrument, Exchange, AssetClass

logger = logging.getLogger("Hokage.OptionsRouter")

# MCX Crude Oil lot sizes
CRUDE_LOT_SIZE = 100   # Standard lot = 100 barrels
CRUDE_MINI_LOT_SIZE = 10  # Mini lot = 10 barrels (lower capital)

# Month abbreviations that Kite uses (3-letter, uppercase)
_MONTH_MAP = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"
}


class OptionsRouter:
    """Translates a directional CRUDEOIL signal into an MCX options order."""

    def __init__(self, price_source: Any = None, use_mini_lot: bool = True) -> None:
        self.price_source = price_source
        # Use mini lot by default so capital requirement is ~10x smaller
        self.lot_size = CRUDE_MINI_LOT_SIZE if use_mini_lot else CRUDE_LOT_SIZE

    def _get_nearest_strike(self, price: float, step: int = 50) -> int:
        """Round to the nearest option strike step (50 for Crude Oil)."""
        return step * round(price / step)

    def _build_kite_option_symbol(self, strike: int, option_type: str) -> str:
        """
        Build the exact Kite Connect symbol string for an MCX Crude Oil option.

        Format: CRUDEOIL{YY}{MON}{STRIKE}{CE|PE}
        e.g.  : CRUDEOIL26JUL6800CE

        Note: Kite uses the CURRENT month's near expiry contract.
        If today is within 5 days of expiry, automatically rolls to next month.
        """
        now = datetime.now()
        year_str = now.strftime("%y")

        # Check if we're near expiry (last 5 trading days of month → roll to next)
        # MCX Crude options typically expire on the last Tuesday before 20th of each month
        # For simplicity, if we're past the 18th, roll to next month
        if now.day >= 18:
            # Roll to next month
            next_month = now.month + 1 if now.month < 12 else 1
            next_year = now.year if now.month < 12 else now.year + 1
            month_str = _MONTH_MAP[next_month]
            year_str = str(next_year)[-2:]
        else:
            month_str = _MONTH_MAP[now.month]

        symbol = f"CRUDEOIL{year_str}{month_str}{strike}{option_type}"
        return symbol

    def route_crude_oil_options(self, req: OrderRequest, current_price: float) -> OrderRequest:
        """
        Transform a CRUDEOIL directional order into an options order.

        Directional mapping:
          BUY  (Bullish) → BUY CE (Call Option)
          SELL (Bearish) → BUY PE (Put Option)

        We always BUY the option — never sell — to cap maximum loss to the premium paid.
        """
        if not req.instrument or "CRUDEOIL" not in req.instrument.symbol.upper():
            return req

        # Already an option — skip routing
        sym = req.instrument.symbol.upper()
        if sym.endswith("CE") or sym.endswith("PE"):
            return req

        # Map direction to option type
        if req.side == OrderSide.BUY:
            option_type = "CE"
            direction_label = "Bullish"
        elif req.side == OrderSide.SELL:
            option_type = "PE"
            direction_label = "Bearish"
        else:
            logger.warning(f"OptionsRouter: Unknown side {req.side}. Skipping options routing.")
            return req

        # Calculate ATM strike
        strike = self._get_nearest_strike(current_price, step=50)
        option_symbol = self._build_kite_option_symbol(strike, option_type)
        
        # Open Interest & Volume Pre-Check
        if self.price_source:
            # Check adjacent strikes if ATM is illiquid
            test_strikes = [strike, strike + 50, strike - 50, strike + 100, strike - 100]
            for attempt_strike in test_strikes:
                test_symbol = self._build_kite_option_symbol(attempt_strike, option_type)
                try:
                    # In mock mode or if quote fails, it throws ValueError. We handle it.
                    quote = self.price_source.get_quote(test_symbol)
                    if quote and quote.volume is not None and quote.volume > 0:
                        if attempt_strike != strike:
                            logger.info(f"OptionsRouter: ATM strike {strike} had no volume. Shifting to liquid strike {attempt_strike}.")
                        strike = attempt_strike
                        option_symbol = test_symbol
                        break
                except Exception:
                    continue

        logger.info(
            f"OptionsRouter: {direction_label} signal on CRUDEOIL @ ₹{current_price:.0f} "
            f"→ BUY {option_symbol} (ATM strike ₹{strike}, 1 lot = {self.lot_size} barrels)"
        )

        # Build new frozen Instrument (dataclass is frozen — must create new instance)
        metadata = req.instrument.metadata.copy() if req.instrument.metadata else {}
        metadata.update({
            "is_option": True,
            "underlying": "CRUDEOIL",
            "underlying_price": current_price,
            "strike": strike,
            "option_type": option_type,
            "lot_size": self.lot_size,
            "kite_symbol": f"MCX:{option_symbol}",
        })

        new_instrument = Instrument(
            symbol=option_symbol,
            asset_class=AssetClass.COMMODITY,
            exchange=Exchange.MCX,
            currency="INR",
            metadata=metadata
        )

        # Build new OrderRequest — always BUY (option buyer), quantity = 1 lot
        new_req = OrderRequest(
            instrument=new_instrument,
            side=OrderSide.BUY,
            quantity=float(self.lot_size),   # 1 lot
            order_type=req.order_type,
            venue_id=req.venue_id,
            strategy_id=req.strategy_id,
            execution_reason=f"Options CE/PE routing: {direction_label} on {option_symbol}",
            playbook_id=req.playbook_id,
            volatility_regime=req.volatility_regime
        )

        return new_req
