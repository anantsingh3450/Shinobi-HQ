"""Portfolio Manager Personality Layer for Hokage.

Adjusts max exposure limits, trade frequency, conviction thresholds, holding periods,
and sizing parameters based on active trading personality mode.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Hokage.PersonalityEngine")


class PortfolioManagerPersonalityLayer:
    """Manages trading personalities and scales limits dynamically based on market state."""

    def __init__(self, mode: str = "ADAPTIVE") -> None:
        """Initialize PortfolioManagerPersonalityLayer."""
        self.configured_mode = mode.upper()

    def resolve_personality_profile(
        self,
        market_regime: str = "NORMAL",
        vix_impact_delta: float = 0.0,
        drawdown_pct: float = 0.0,
        is_recovery_mode: bool = False,
    ) -> dict[str, Any]:
        """Resolve active personality mode and compute scaled limits.
        
        Adaptive rules:
          - Recovery state -> RECOVERY
          - RISK_OFF or High Volatility -> DEFENSIVE
          - RISK_ON -> AGGRESSIVE
          - NORMAL/SIDEWAYS -> BALANCED
        """
        active_mode = self.configured_mode
        
        # Override if mode is ADAPTIVE
        if active_mode == "ADAPTIVE":
            if is_recovery_mode or drawdown_pct >= 10.0:
                active_mode = "RECOVERY"
            elif "RISK-OFF" in market_regime or "BEAR" in market_regime or vix_impact_delta >= 2.0:
                active_mode = "DEFENSIVE"
            elif "RISK-ON" in market_regime or "BULL" in market_regime:
                active_mode = "AGGRESSIVE"
            else:
                active_mode = "BALANCED"

        # Personality parameter mappings
        if active_mode == "AGGRESSIVE":
            profile = {
                "active_mode": "AGGRESSIVE",
                "max_portfolio_exposure_pct": 40.0,
                "max_allocation_per_trade_pct": 3.0,
                "min_conviction_threshold": 40,  # lower bar
                "holding_period_desc": "1-3 Days",
                "trade_frequency_limit": "HIGH",
                "sizing_scale": 1.2
            }
        elif active_mode == "DEFENSIVE":
            profile = {
                "active_mode": "DEFENSIVE",
                "max_portfolio_exposure_pct": 15.0,
                "max_allocation_per_trade_pct": 1.0,
                "min_conviction_threshold": 71,  # require HIGH
                "holding_period_desc": "5-10 Days",
                "trade_frequency_limit": "LOW",
                "sizing_scale": 0.6
            }
        elif active_mode == "RECOVERY":
            profile = {
                "active_mode": "RECOVERY",
                "max_portfolio_exposure_pct": 10.0,
                "max_allocation_per_trade_pct": 0.5,
                "min_conviction_threshold": 80,  # require ELITE/HIGH
                "holding_period_desc": "3-7 Days",
                "trade_frequency_limit": "VERY LOW",
                "sizing_scale": 0.5
            }
        else:  # BALANCED
            profile = {
                "active_mode": "BALANCED",
                "max_portfolio_exposure_pct": 25.0,
                "max_allocation_per_trade_pct": 2.0,
                "min_conviction_threshold": 51,  # MODERATE
                "holding_period_desc": "2-5 Days",
                "trade_frequency_limit": "NORMAL",
                "sizing_scale": 1.0
            }

        return profile
