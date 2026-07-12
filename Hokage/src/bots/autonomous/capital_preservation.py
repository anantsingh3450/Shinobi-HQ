"""Capital Preservation Engine for Hokage.

Coordinates risk scaling, losing streak cap rules, drawdown monitoring,
and enforces RECOVERY MODE constraints when capital preservation is prioritized.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.CapitalPreservation")


class CapitalPreservationEngine:
    """Monitors stress indicators and drawdowns to scale risk limits."""

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize CapitalPreservationEngine."""
        self.cache = cache
        self.state_file = "capital_preservation.json"

    def evaluate_risk_profile(
        self,
        consecutive_losses: int = 0,
        drawdown_pct: float = 0.0,
        prediction_win_rate: float = 100.0,
        vix_impact_delta: float = 0.0,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Assess indicators and return active risk constraints and rules."""
        if not enabled:
            result = {
                "mode": "NORMAL",
                "max_allocation_pct": 2.0,
                "min_conviction_threshold": 51,
                "max_portfolio_exposure_pct": 30.0,
                "reasons": ["Capital preservation checks bypassed by commander profile setting."],
                "evaluated_at": datetime.now(timezone.utc).isoformat()
            }
            self.cache.write_intelligence(self.state_file, result)
            return result

        # Determine base mode and constraints
        mode = "NORMAL"
        max_allocation_pct = 2.0
        min_conviction_threshold = 51  # default MODERATE conviction required
        max_portfolio_exposure_pct = 30.0
        reasons = []

        # Enforce rules based on parameters
        # 1. Drawdown Checks
        if drawdown_pct >= 15.0:
            mode = "NO TRADE"
            max_allocation_pct = 0.0
            min_conviction_threshold = 100
            max_portfolio_exposure_pct = 0.0
            reasons.append(f"Severe drawdown of {drawdown_pct:.1f}% exceeds 15% threshold.")
        elif drawdown_pct >= 10.0:
            mode = "RECOVERY"
            max_allocation_pct = 0.5
            min_conviction_threshold = 71  # require HIGH conviction
            max_portfolio_exposure_pct = 10.0
            reasons.append(f"Moderate drawdown of {drawdown_pct:.1f}% triggers recovery mode limits.")

        # 2. Losing Streak Checks
        if mode != "NO TRADE" and consecutive_losses >= 5:
            # Scale down allocation limits
            max_allocation_pct = min(max_allocation_pct, 1.0)
            if mode == "NORMAL":
                mode = "RECOVERY"
                min_conviction_threshold = 71
                max_portfolio_exposure_pct = 10.0
            reasons.append(f"Losing streak of {consecutive_losses} consecutive losses active.")

        # 3. Volatility / Stress checks
        if mode != "NO TRADE" and vix_impact_delta >= 2.0:
            max_allocation_pct = min(max_allocation_pct, 1.0)
            reasons.append(f"Market stress detected with VIX delta of {vix_impact_delta:.1f}.")

        # 4. Prediction Degradation Checks
        if mode != "NO TRADE" and prediction_win_rate < 50.0:
            max_allocation_pct = min(max_allocation_pct, 1.0)
            if mode == "NORMAL":
                mode = "RECOVERY"
                min_conviction_threshold = 71
                max_portfolio_exposure_pct = 10.0
            reasons.append(f"Prediction degradation detected. Rolling win rate is {prediction_win_rate:.1f}%.")

        if not reasons:
            reasons.append("Safe market conditions, operating in Normal Mode.")

        result = {
            "mode": mode,
            "max_allocation_pct": round(max_allocation_pct, 2),
            "min_conviction_threshold": min_conviction_threshold,
            "max_portfolio_exposure_pct": round(max_portfolio_exposure_pct, 2),
            "reasons": reasons,
            "evaluated_at": datetime.now(timezone.utc).isoformat()
        }

        # Cache results
        self.cache.write_intelligence(self.state_file, result)
        return result

class RiskManager:
    """Core portfolio kill-switch. Monitors global P&L and max daily drawdown."""
    def __init__(self, bot_instance: Any, max_daily_drawdown_pct: float = 15.0):
        self.bot = bot_instance
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self._killed = False
        
    def check_portfolio_health(self, current_equity: float, starting_equity: float) -> bool:
        """Checks if drawdown is breached. If so, halts trading and liquidates."""
        if self._killed or starting_equity <= 0:
            return False
            
        drawdown = ((starting_equity - current_equity) / starting_equity) * 100.0
        if drawdown >= self.max_daily_drawdown_pct:
            logger.critical(f"PORTFOLIO KILL-SWITCH TRIGGERED. Drawdown {drawdown:.1f}% exceeds limit {self.max_daily_drawdown_pct}%.")
            
            # 1. Engage kill switch
            self.bot.intraday_override['halted'] = True
            self.bot.gatekeeper_state = "KILL_SWITCH_ENGAGED"
            self._killed = True
            
            # 2. Send Telegram alert
            if getattr(self.bot, 'telegram_bot', None):
                self.bot.telegram_bot.send_message(
                    "🚨 *CRITICAL PORTFOLIO KILL-SWITCH ENGAGED* 🚨\n"
                    f"Max daily drawdown of {self.max_daily_drawdown_pct}% breached.\n"
                    "All autonomous trading has been forcefully halted and positions are being liquidated."
                )
            
            # 3. Attempt to liquidate all active positions
            try:
                for asset, pos_data in list(self.bot._active_positions_tracking.items()):
                    logger.warning(f"Kill-Switch liquidating {asset}")
                    self.bot._execute_partial_exit(asset, pos_data, size_pct=1.0, reason="KILL_SWITCH")
            except Exception as e:
                logger.error(f"Error liquidating positions during kill-switch: {e}")
                
            return False
        return True
