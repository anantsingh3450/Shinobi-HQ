# ??  MOCK-ONLY STUB: Both branches of this module return synthetic mock data.
# Real data provider integration is pending. Do NOT use for live trading decisions.
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Hokage.FIIDIIEngine")


class FIIDIIEngine:
    """Trends and analyzes FII (Foreign Institutional) & DII (Domestic Institutional) flow data."""

    def __init__(self, provider_config: dict[str, Any]) -> None:
        """Initialize flows engine with configuration-driven provider settings."""
        self.provider_config = provider_config
        self.provider_type = provider_config.get("type", "mock_flows")

    def fetch_flows(self) -> dict[str, Any]:
        """Fetch latest daily institutional flows snapshot."""
        if self.provider_type == "mock_flows":
            return self._get_mock_flows()
        return self._get_mock_flows()

    def determine_regime(self, flows: dict[str, Any]) -> str:
        """Determine institutional positioning regime: BULLISH, BEARISH, or NEUTRAL."""
        fii_net = flows.get("fii_net_crores", 0.0)
        dii_net = flows.get("dii_net_crores", 0.0)
        combined = fii_net + dii_net
        
        if combined > 1000.0:
            return "BULLISH"
        elif combined < -1000.0:
            return "BEARISH"
        return "NEUTRAL"

    def _get_mock_flows(self) -> dict[str, Any]:
        """Generate high-fidelity daily FII and DII flow mock stats."""
        return {
            "fii_buy_crores": 12450.50,
            "fii_sell_crores": 11200.20,
            "fii_net_crores": 1250.30,
            
            "dii_buy_crores": 8900.80,
            "dii_sell_crores": 8100.10,
            "dii_net_crores": 800.70,
            
            "combined_net_crores": 2051.00,
            "trend_5day_fii": "ACCUMULATION", # ACCUMULATION or DISTRIBUTION
            "trend_5day_dii": "ACCUMULATION"
        }
