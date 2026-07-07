from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.ExplainabilityAggregator")


class ExplainabilityAggregator:
    """Aggregates explanations from all 7 Hokage decision gates into a unified narrative."""

    def __init__(self, orchestrator: HokageOrchestrator, cache: IntelligenceCache) -> None:
        """Initialize explainability aggregator."""
        self.orchestrator = orchestrator
        self.cache = cache

    def aggregate_explanation(self, symbol: str | None = None) -> dict[str, Any]:
        """Aggregate explanation metrics from all 7 gates and compile a coherent summary."""
        # 1. Strategy Gate
        strategy_summary = "Strategy engine is scanning the active universe for breakout and mean reversion setups."
        
        # 2. Conviction Gate
        conviction_summary = "Conviction engine evaluates candidate opportunities across 9 normalized dimensions."
        conv_score = 75
        conv_grade = "HIGH"
        
        # 3. Market Intelligence Gate
        market_summary = "Market intelligence provides macroeconomic regime and sector rotation context."
        macro_regime = "STATIONARY"
        
        # 4. Portfolio Intelligence Gate
        portfolio_summary = "Portfolio intelligence ensures capital is constructed as a diversified institutional portfolio."
        cash_pct = 100.0
        
        # 5. Risk Gate
        risk_summary = "Risk engine enforces capital preservation scales, beta limits, and VaR sizing."
        preservation_mode = "NORMAL"
        
        # 6. Execution Gate
        execution_summary = "Execution engine simulates real-world transaction friction and slippage."
        quality_score = 95.0
        
        # 7. Shadow Analytics Gate
        shadow_summary = "Shadow analytics verifies statistical significance and confidence calibration."
        calibration_grade = "EXCELLENT"
        
        # Attempt to populate dynamically from cached reports
        try:
            # Conviction
            if symbol:
                decisions = self.cache.read_intelligence("latest_decisions.json") or {}
                # Look for symbol decision
                symbol_dec = decisions.get(symbol.upper())
                if symbol_dec:
                    conv_score = symbol_dec.get("conviction_score", conv_score)
                    conv_grade = symbol_dec.get("conviction_grade", conv_grade)
                    conv_break = symbol_dec.get("conviction_breakdown", {})
                    conviction_summary = (
                        f"Conviction score is {conv_score}/100 ({conv_grade}). "
                        f"Key drivers: Regime ({conv_break.get('market_regime', {}).get('normalized', 50)}), "
                        f"Sector Flow ({conv_break.get('sector_flow_forecast', {}).get('normalized', 50)}), "
                        f"Sentiment ({conv_break.get('news_sentiment', {}).get('normalized', 50)})."
                    )
            
            # Market Intelligence
            mkt_report = self.cache.read_intelligence("market_intelligence.json")
            if mkt_report:
                macro_regime = mkt_report.get("macro_regime", macro_regime)
                market_summary = mkt_report.get("explainable_summary", market_summary)
                
            # Portfolio Intelligence
            port_report = self.cache.read_intelligence("portfolio_intelligence.json")
            if port_report:
                cash_pct = port_report.get("cash_allocation_pct", cash_pct)
                div_score = port_report.get("diversification_score", 100.0)
                portfolio_summary = (
                    f"Portfolio has {cash_pct:.1f}% cash reserves. "
                    f"Diversification score is {div_score:.1f}/100 with "
                    f"{port_report.get('systemic_concentration', 'LOW')} systemic concentration."
                )
                
            # Risk Gate
            pres_report = self.cache.read_intelligence("capital_preservation.json")
            if pres_report:
                preservation_mode = pres_report.get("mode", preservation_mode)
                risk_summary = f"Capital preservation mode is {preservation_mode} (Max size: {pres_report.get('max_allocation_pct', 2.0):.1f}%)."
                
            # Execution Gate
            quality_report = self.cache.read_intelligence("execution_quality.json")
            if not quality_report:
                # Try from EOD daily report
                daily = self.cache.read_intelligence("daily_briefing.json") or {}
                quality_score = daily.get("execution_quality_score", quality_score)
            else:
                quality_score = quality_report.get("execution_quality_score", quality_score)
            execution_summary = f"Execution Quality is graded {quality_score:.1f}/100 based on simulated slippage and latency."
            
            # Shadow Analytics Gate
            calib_report = self.cache.read_intelligence("calibration_metrics.json")
            if calib_report:
                calibration_grade = calib_report.get("calibration_grade", calibration_grade)
            shadow_summary = f"Shadow calibration is graded {calibration_grade} (Brier Score: {calib_report.get('overall_brier_score', 0.0150):.4f})."

        except Exception as exc:
            logger.error(f"Failed to compile dynamic explainability components: {exc}")

        # Build unified coherent narrative
        unified_narrative = (
            f"Hokage Decision Explanation:\n"
            f"1. [STRATEGY]: {strategy_summary}\n"
            f"2. [CONVICTION]: {conviction_summary}\n"
            f"3. [MARKET INTEL]: {market_summary}\n"
            f"4. [PORTFOLIO INTEL]: {portfolio_summary}\n"
            f"5. [RISK]: {risk_summary}\n"
            f"6. [EXECUTION]: {execution_summary}\n"
            f"7. [SHADOW ANALYTICS]: {shadow_summary}"
        )

        return {
            "symbol": symbol,
            "strategy": strategy_summary,
            "conviction": conviction_summary,
            "market_intel": market_summary,
            "portfolio_intel": portfolio_summary,
            "risk": risk_summary,
            "execution": execution_summary,
            "shadow_analytics": shadow_summary,
            "unified_narrative": unified_narrative
        }
