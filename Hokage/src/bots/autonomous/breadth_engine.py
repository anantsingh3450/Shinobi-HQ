# ??  MOCK-ONLY STUB: Both branches of this module return synthetic mock data.
# Real data provider integration is pending. Do NOT use for live trading decisions.
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Hokage.BreadthEngine")


class BreadthEngine:
    """Computes and trends market breadth indicators (Advance/Decline, internally held assets)."""

    def __init__(self, provider_config: dict[str, Any]) -> None:
        """Initialize breadth engine with configuration-driven provider settings."""
        self.provider_config = provider_config
        self.provider_type = provider_config.get("type", "mock_breadth")

    def fetch_breadth(self) -> dict[str, Any]:
        """Fetch latest index internals breadth snapshot."""
        if self.provider_type == "mock_breadth":
            return self._get_mock_breadth()
        return self._get_mock_breadth()

    def get_market_health_score(self, breadth: dict[str, Any]) -> float:
        """Calculate market internal health score (0-100) based on breadth ratio."""
        ad_ratio = breadth.get("ad_ratio", 1.0)
        above_200ma = breadth.get("percent_above_200ma", 50.0)
        above_50ma = breadth.get("percent_above_50ma", 50.0)
        
        # Weighted calculation
        ad_score = min(100.0, ad_ratio * 40.0) # 40 points max
        ma_score = (above_200ma * 0.4) + (above_50ma * 0.2) # 60 points max
        
        return max(0.0, min(100.0, round(ad_score + ma_score, 1)))

    def _get_mock_breadth(self) -> dict[str, Any]:
        """Generate high-fidelity mock breadth statistics."""
        return {
            "advances": 32,
            "declines": 18,
            "unchanged": 0,
            "ad_ratio": 1.78, # 32 / 18
            "percent_above_50ma": 68.0,
            "percent_above_200ma": 74.0,
            "new_highs": 8,
            "new_lows": 1,
            "volume_advancing_pct": 65.20
        }
