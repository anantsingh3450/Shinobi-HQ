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

    #: Maximum tolerated bid-ask spread by asset class (percent of price).
    #: Options (CE/PE) naturally quote wider than equities/futures — a 1.5%
    #: spread on a ₹100 premium is ₹1.5 slippage, acceptable for derivatives.
    #: Equities/futures get the strict 0.20% cap (commander-approved fix of a
    #: silent loosening that applied 1.5% flat to everything).
    MAX_SPREAD_EQUITY_PCT = 0.20
    MAX_SPREAD_OPTION_PCT = 1.5

    def check_liquidity(self, spread_pct: float, bid_ask_size_ratio: float | None, is_option: bool = False) -> tuple[bool, str]:
        """Verify liquidity is sufficient for low slippage execution.

        Args:
            spread_pct: bid-ask spread as a percent of price.
            bid_ask_size_ratio: order-book depth ratio (1.0 = balanced), or
                None when the venue supplied no depth data — the imbalance
                check is then skipped; a neutral ratio must never be invented.
            is_option: True for option contracts (CE/PE) — wider spread allowed.
        """
        max_spread = self.MAX_SPREAD_OPTION_PCT if is_option else self.MAX_SPREAD_EQUITY_PCT
        if spread_pct > max_spread:
            return False, f"LIQUIDITY_TRAP: Bid-ask spread {spread_pct:.2f}% exceeds max allowed {max_spread:.2f}%."
        # Depth-imbalance bounds restored to 5.0x/0.2x (revert of a silent
        # loosening to 10.0x/0.1x; tests encode 5x as the trap threshold).
        if bid_ask_size_ratio is not None and (bid_ask_size_ratio > 5.0 or bid_ask_size_ratio < 0.2):
            return False, f"LIQUIDITY_TRAP: Extreme book depth imbalance (bid/ask ratio={bid_ask_size_ratio:.2f}x)."
        return True, "Liquidity profile satisfied."


class VolumeEngine:
    """Detects fake breakouts and confirms abnormal volume strength."""

    # Commander-approved 2026-07-14: the volume-surge demand is a BREAKOUT
    # confirmation concept. Trend/pullback entries occur on quiet retracement
    # tape by design, so demanding a 1.2x surge starved the flagship family
    # all day. Breakouts keep the surge bar; trend entries only reject a
    # genuinely dead tape.
    #
    # These ratios are only meaningful because the caller now supplies a
    # TIME-OF-DAY-NORMALISED baseline (see _get_volume_context): the observed
    # ratio compares today's cumulative volume against the typical cumulative
    # volume at the same clock time. Against the old whole-session denominator
    # the ratio just tracked the clock — it topped out at 0.87x on NIFTY, so
    # BREAKOUT_MIN_RATIO was unreachable at every hour of every day and the
    # breakout family could never fire. 1.0x now means "normal for this time
    # of day"; do not reinterpret these numbers without re-reading that method.
    #
    # Commander-approved 2026-07-15, AFTER the baseline was corrected: 0.8x was
    # itself calibrated against the broken clock-denominator, so it was never
    # evidence-based. Against an honest baseline 0.8x rejects a tape running at
    # 80% of typical — quiet, not dead — which is stricter than this gate's
    # stated intent. 0.5x is the "genuinely dead tape" line the comment above
    # always described. Breakout keeps 1.2x: a surge bar should demand a surge.
    #
    # Commander-approved 2026-07-18: breakout bar 1.2 -> 1.1. The 1.2x bar was
    # written before the baseline fix and never recalibrated on honest ratios.
    # First live evidence (2026-07-17 final hour): MacroBreakout fired on a
    # genuine BANKNIFTY rally three scans running and was refused at 1.14x /
    # 1.15x / 1.19x — missing the bar by 0.01x at 15:00 while the breakout ran
    # without us. 1.1x still demands above-typical tape, not a surge fantasy.
    BREAKOUT_MIN_RATIO = 1.1
    TREND_MIN_RATIO = 0.5

    def validate_breakout(
        self,
        current_volume: float,
        avg_volume: float,
        entry_family: str = "breakout",
    ) -> tuple[bool, str]:
        """Volume gate with entry-family-aware thresholds.

        entry_family "breakout": requires a surge (>= 1.2x average) to reject
        fake breakouts. Any other family (trend/pullback/mean-reversion):
        requires only a live tape (>= 0.8x average).
        """
        if avg_volume <= 0:
            return True, "Volume baseline unavailable."

        volume_ratio = current_volume / avg_volume
        is_breakout = entry_family.lower() == "breakout"
        min_ratio = self.BREAKOUT_MIN_RATIO if is_breakout else self.TREND_MIN_RATIO
        if volume_ratio < min_ratio:
            label = "FAKE_BREAKOUT" if is_breakout else "THIN_TAPE"
            return False, (
                f"{label}: Volume ratio {volume_ratio:.2f}x < required "
                f"{min_ratio:.2f}x ({entry_family} entry)."
            )
        if volume_ratio >= 2.0:
            return True, f"ABNORMAL_VOLUME: Entry confirmed by strong volume flow ({volume_ratio:.2f}x)."
        return True, f"Volume support satisfied ({volume_ratio:.2f}x, {entry_family} entry)."


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
