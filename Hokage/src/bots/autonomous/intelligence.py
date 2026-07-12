"""Modular Intelligence Engines for Hokage.

Provides independent specialist engines to improve trade quality and risk management:
- SessionBehaviorEngine
- LiquidityEngine
- VolumeEngine
- PositionManagementEngine
- AdaptiveSizingEngine
- TradeQualityEngine
- AdvancedMarketRegimeEngine
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, time

logger = logging.getLogger("Hokage.Intelligence")


class AdvancedMarketRegimeEngine:
    """Classifies trend and volatility regimes dynamically."""

    def classify_regime(self, trend_score: float, vix_impact_delta: float) -> str:
        """Classify combined regime."""
        if vix_impact_delta >= 3.0:
            return "PANIC_BEAR"
        elif vix_impact_delta >= 1.8:
            return "VOLATILE_MIXED"
        elif trend_score >= 0.6:
            return "STRONG_BULL"
        elif trend_score <= -0.6:
            return "STRONG_BEAR"
        return "SIDEWAYS"


class SessionBehaviorEngine:
    """Applies session-specific constraints based on time of day (IST)."""

    def get_current_session(self) -> str:
        """Resolve current trading session time in IST."""
        # Convert UTC to IST
        try:
            import zoneinfo
            tz_ist = zoneinfo.ZoneInfo("Asia/Kolkata")
            now_ist = datetime.now(timezone.utc).astimezone(tz_ist).time()
        except Exception:
            from datetime import timedelta
            tz_ist = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(timezone.utc).astimezone(tz_ist).time()
        
        if time(9, 15) <= now_ist < time(10, 30):
            return "OPEN_SESSION"
        elif time(10, 30) <= now_ist < time(14, 30):
            return "MID_SESSION"
        elif time(14, 30) <= now_ist <= time(15, 30):
            return "CLOSE_SESSION"
        return "OFF_MARKET"

    def filter_opportunity(self, session: str, entry_rule: str) -> tuple[bool, str]:
        """Validate if the strategy rule matches the active session profile."""
        rule_lower = entry_rule.lower()
        if session == "OPEN_SESSION":
            # Highly volatile session, breakouts are good
            return True, "Volatile morning breakouts favored."
        elif session == "MID_SESSION":
            # Mean reversion session, avoid chasing high breakout momentum
            if "breakout" in rule_lower or "momentum" in rule_lower:
                return False, "Breakout trades suspended during mid-session mean-reverting environment."
            return True, "Mean reversion setups permitted."
        elif session == "CLOSE_SESSION":
            # Trend continuation favored
            if "breakout" in rule_lower:
                return False, "New breakout trades suspended near market close."
            return True, "Trend continuation setups permitted."
        return True, "Default session compliance."


class LiquidityEngine:
    """Protects against bid-ask spreads and order book skew traps."""

    def check_liquidity(self, spread_pct: float, bid_ask_size_ratio: float) -> tuple[bool, str]:
        """Verify liquidity is sufficient for low slippage execution.
        
        Note: Options (CE/PE) naturally have wider spreads than equities.
        A 1.5% spread on a ₹100 premium = ₹1.5 slippage which is acceptable.
        """
        # Options-aware threshold: 1.5% for derivatives, 0.20% for equities
        max_spread = 1.5  # Widened to accommodate options bid-ask spreads
        if spread_pct > max_spread:
            return False, f"LIQUIDITY_TRAP: Bid-ask spread {spread_pct:.2f}% exceeds max allowed {max_spread:.2f}%."
        if bid_ask_size_ratio > 10.0 or bid_ask_size_ratio < 0.1:
            return False, f"LIQUIDITY_TRAP: Extreme book depth imbalance (bid/ask ratio={bid_ask_size_ratio:.2f}x)."
        return True, "Liquidity profile satisfied."


class VolumeEngine:
    """Detects fake breakouts and confirms abnormal volume strength."""

    def validate_breakout(self, current_volume: float, avg_volume: float) -> tuple[bool, str]:
        """Verify breakout volume support to reject fake breakouts.
        
        Note: Threshold lowered to 1.2x (from 1.5x) to allow early morning 
        setups where volume has not yet fully built up.
        """
        if avg_volume <= 0:
            return True, "Volume baseline unavailable."
        
        volume_ratio = current_volume / avg_volume
        if volume_ratio < 1.2:
            return False, f"FAKE_BREAKOUT: Volume ratio {volume_ratio:.2f}x < required 1.20x."
        if volume_ratio >= 2.0:
            return True, f"ABNORMAL_VOLUME: Breakout confirmed by strong volume flow ({volume_ratio:.2f}x)."
        return True, f"Volume support satisfied ({volume_ratio:.2f}x)."


class PositionManagementEngine:
    """Dynamically adjusts stop level parameters (TSL/TP) based on VIX delta."""

    def get_adapted_exit_percentages(
        self,
        base_tsl: float,
        base_tp: float,
        vix_impact_delta: float
    ) -> tuple[float, float]:
        """Widen stops under high VIX, tighten during low VIX."""
        if vix_impact_delta >= 2.0:
            # Widen stop to prevent noise stopout
            adapted_tsl = base_tsl * 1.5
            adapted_tp = base_tp * 1.3
        elif vix_impact_delta <= -1.0:
            # Tighten stops to lock in gains
            adapted_tsl = base_tsl * 0.8
            adapted_tp = base_tp * 0.9
        else:
            adapted_tsl = base_tsl
            adapted_tp = base_tp
        return round(adapted_tsl, 4), round(adapted_tp, 4)


class AdaptiveSizingEngine:
    """Scales allocation dynamically based on performance, drawdown, and volatility."""

    def get_adapted_allocation(
        self,
        base_alloc_pct: float,
        regime: str,
        drawdown_pct: float,
        vix_impact_delta: float
    ) -> float:
        """Determine scaled allocation percentage."""
        multiplier = 1.0
        
        # Scale down in high volatility/panic regimes
        if regime in ("PANIC_BEAR", "VOLATILE_MIXED"):
            multiplier *= 0.5
        elif regime == "STRONG_BULL":
            multiplier *= 1.2

        # Scale down if drawdown is high
        if drawdown_pct >= 5.0:
            multiplier *= 0.5
        elif drawdown_pct >= 2.0:
            multiplier *= 0.8

        # Scale down if VIX impact is elevated
        if vix_impact_delta >= 1.5:
            multiplier *= 0.7

        adapted = base_alloc_pct * multiplier
        return round(max(0.1, min(5.0, adapted)), 2)


class TradeQualityEngine:
    """Continuously reassesses open positions to trigger early emergency exits."""

    def evaluate_open_position(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        vix_impact_delta: float,
        market_regime: str,
        volume_ratio: float = 1.0
    ) -> tuple[bool, str]:
        """Return True if position quality has degraded, requiring an emergency exit."""
        # 1. Emergency exit if market switches to PANIC_BEAR
        if market_regime == "PANIC_BEAR":
            return True, "EMERGENCY_EXIT: Market regime transitioned to PANIC_BEAR."

        # 2. VIX spike trigger
        if vix_impact_delta >= 4.0:
            return True, "EMERGENCY_EXIT: High volatility VIX shock delta >= 4.0."

        # 3. Reversal signal on abnormal selling volume (for LONG trades)
        if current_price < entry_price and volume_ratio >= 3.0:
            return True, "EMERGENCY_EXIT: Sharp downward breakout matched by abnormal selling volume."

        return False, "Position quality stable."
