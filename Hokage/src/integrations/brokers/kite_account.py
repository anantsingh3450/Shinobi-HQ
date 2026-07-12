from __future__ import annotations

from typing import Any
from integrations.brokers.kite_connection import KiteConnectionManager
from integrations.brokers.models import (
    AccountBalance,
    VenuePosition,
    VenueHolding,
    OrderSide,
)
from integrations.data.models import Instrument, AssetClass, Exchange


class KiteAccountService:
    """Retrieves account profiles, funds, positions, and holdings from Zerodha."""

    def __init__(self, connection_manager: KiteConnectionManager) -> None:
        self._connection_manager = connection_manager

    def get_profile(self) -> dict[str, Any]:
        """Fetch active account user profile details."""
        client = self._connection_manager.get_kite_client()
        return client.profile()

    def get_account_balance(self, venue_id: str = "kite_main") -> AccountBalance:
        """Fetch available funds and margin utilization."""
        client = self._connection_manager.get_kite_client()
        margins = client.margins()
        
        try:
            import json
            with open("C:/Users/anant/OneDrive/Documents/AI PROJECT/AI COMMAND CENTRE/Hokage/scratch/margins_dump.json", "w") as f:
                json.dump(margins, f)
        except Exception:
            pass
        
        # Parse equity and commodity funds
        equity = margins.get("equity", {})
        commodity = margins.get("commodity", {})
        
        net = float(equity.get("net", 0.0)) + float(commodity.get("net", 0.0))
        cash = float(equity.get("available", {}).get("cash", 0.0)) + float(commodity.get("available", {}).get("cash", 0.0))
        margin_used = float(equity.get("utilised", {}).get("debits", 0.0)) + float(commodity.get("utilised", {}).get("debits", 0.0))
        
        return AccountBalance(
            venue_id=venue_id,
            total_equity=net,
            cash=cash,
            margin_available=cash,
            margin_used=margin_used,
            currency="INR"
        )

    def get_positions(self, venue_id: str = "kite_main") -> list[VenuePosition]:
        """Fetch open derivatives/intraday positions."""
        client = self._connection_manager.get_kite_client()
        pos_data = client.positions()
        
        net_positions = pos_data.get("net", [])
        positions = []
        for pos in net_positions:
            qty = float(pos.get("quantity", 0.0))
            if qty == 0:
                continue
                
            side = OrderSide.BUY if qty > 0 else OrderSide.SELL
            abs_qty = abs(qty)
            
            inst = Instrument(
                symbol=pos.get("tradingsymbol", ""),
                asset_class=AssetClass.INDIAN_EQUITY,
                exchange=Exchange.NSE if pos.get("exchange") == "NSE" else Exchange.BSE
            )
            
            positions.append(
                VenuePosition(
                    instrument=inst,
                    side=side,
                    quantity=abs_qty,
                    average_price=float(pos.get("average_price", 0.0)),
                    current_price=float(pos.get("last_price", 0.0)),
                    unrealized_pnl=float(pos.get("unrealised", 0.0)),
                    venue_id=venue_id,
                    metadata={"product": pos.get("product", "")}
                )
            )
        return positions

    def get_holdings(self, venue_id: str = "kite_main") -> list[VenueHolding]:
        """Fetch delivery holdings portfolio."""
        client = self._connection_manager.get_kite_client()
        holdings_data = client.holdings()
        
        holdings = []
        for hold in holdings_data:
            qty = float(hold.get("quantity", 0.0))
            if qty == 0:
                continue
                
            inst = Instrument(
                symbol=hold.get("tradingsymbol", ""),
                asset_class=AssetClass.INDIAN_EQUITY,
                exchange=Exchange.NSE if hold.get("exchange") == "NSE" else Exchange.BSE
            )
            
            holdings.append(
                VenueHolding(
                    instrument=inst,
                    quantity=qty,
                    average_price=float(hold.get("average_price", 0.0)),
                    current_price=float(hold.get("last_price", 0.0)),
                    unrealized_pnl=float(hold.get("pnl", 0.0)),
                    venue_id=venue_id,
                    metadata={"isin": hold.get("isin", "")}
                )
            )
        return holdings
