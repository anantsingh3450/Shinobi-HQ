from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.MarketIntelligence")


class MarketIntelligenceEngine:
    """The Conductor Orchestrator for Hokage's Market Intelligence Layer (Phase 6.8).

    Composes specialist engines into one unified, explainable, and configuration-driven
    Market Intelligence Report.
    """

    def __init__(self, orchestrator: HokageOrchestrator, cache: IntelligenceCache) -> None:
        """Initialize orchestrator."""
        self.orchestrator = orchestrator
        self.cache = cache
        self.config_path = orchestrator.resolver.resolve_brain_root().parent / "config" / "market_intelligence.json"
        
        # Load configuration
        self.config = self._load_config()

        # Instantiate specialist modules with their configuration-driven provider settings
        providers = self.config.get("providers", {})
        
        from bots.autonomous.economic_calendar import EconomicCalendarEngine
        from bots.autonomous.earnings_calendar import EarningsCalendarEngine
        from bots.autonomous.fii_dii_engine import FIIDIIEngine
        from bots.autonomous.options_intelligence import OptionsIntelligenceEngine
        from bots.autonomous.breadth_engine import BreadthEngine
        from bots.autonomous.sector_rotation import SectorRotationEngine
        from bots.autonomous.research_intel import NewsIntelligenceEngine, GeopoliticalIntelligenceEngine, MarketScanner

        self.economic_calendar = EconomicCalendarEngine(providers.get("economic_calendar", {}))
        self.earnings_calendar = EarningsCalendarEngine(providers.get("earnings_calendar", {}))
        self.fii_dii = FIIDIIEngine(providers.get("fii_dii", {}))
        self.options_intel = OptionsIntelligenceEngine(providers.get("options_data", {}))
        self.breadth = BreadthEngine(providers.get("market_breadth", {}))
        
        # Reuse existing engines
        self.sector_rotation = SectorRotationEngine(orchestrator, cache)
        self.news_intel = NewsIntelligenceEngine(cache)
        self.geopolitical = GeopoliticalIntelligenceEngine(self.news_intel, cache)
        self.market_scanner = MarketScanner(orchestrator, cache)

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from disk, falling back to defaults if not found."""
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to parse market_intelligence.json: {e}")
                
        # Baseline fallback configuration
        return {
            "enabled": True,
            "watchlists": ["TCS", "INFY", "RELIANCE", "HDFCBANK", "ICICIBANK", "ONGC", "LT", "SBIN"],
            "scoring_parameters": {
                "max_conviction_adjustment": 10.0,
                "min_report_confidence_threshold": 50.0,
                "rotation_score_multiplier": 5.0,
                "macro_alignment_bonus": 3.0
            },
            "providers": {
                "economic_calendar": {"type": "mock_economic"},
                "earnings_calendar": {"type": "mock_earnings"},
                "fii_dii": {"type": "mock_flows"},
                "options_data": {"type": "mock_options"},
                "market_breadth": {"type": "mock_breadth"}
            }
        }

    def compute_unified_report(self) -> dict[str, Any]:
        """Collect all specialist metrics and compile the unified Market Intelligence Report."""
        if not self.config.get("enabled", True):
            return {"enabled": False, "confidence": 0.0, "macro_regime": "STATIONARY"}
            
        # 1. Fetch indices
        indices = self.market_scanner.scan_indices()
        
        # 2. Fetch news and geopolitical risks
        raw_events = self.news_intel.fetch_news_events()
        geo_assessments = self.geopolitical.assess_geopolitical_impact()
        
        # 3. Fetch specialist modules outputs
        economic_events = self.economic_calendar.fetch_events()
        watchlists = self.config.get("watchlists", [])
        earnings_releases = self.earnings_calendar.fetch_releases(watchlists)
        flows = self.fii_dii.fetch_flows()
        options_nifty = self.options_intel.fetch_options_metrics("NIFTY")
        breadth = self.breadth.fetch_breadth()
        rotation = self.sector_rotation.compute_rotation()
        
        # 4. Compute composite macro signals
        event_impact = self.economic_calendar.compute_impact_score(economic_events)
        flows_regime = self.fii_dii.determine_regime(flows)
        options_regime = self.options_intel.classify_sentiment(options_nifty)
        breadth_health = self.breadth.get_market_health_score(breadth)
        
        # Resolve overall macro regime based on combining signals
        macro_regime = "RISK-ON"
        reasons_list = []
        
        if event_impact < -0.30:
            macro_regime = "INFLATION SHOCK"
            reasons_list.append(f"Economic event impact is negative ({event_impact})")
        elif flows_regime == "BEARISH" or options_regime == "OVERBOUGHT":
            macro_regime = "RISK-OFF"
            reasons_list.append(f"Institutional flows are Bearish and option PCR indicates Overbought skew")
        else:
            reasons_list.append("General parameters are supportive of capital deployment")
            
        if breadth_health > 60.0:
            reasons_list.append(f"Breadth Health is strong at {breadth_health}%")
            
        # 5. Compute Orchestrator confidence (0-100)
        # Factors: completeness of inputs, provider mock fallback penalizations
        base_confidence = 100.0
        providers = self.config.get("providers", {})
        
        # Penalize for mock provider types (e.g. mock_economic, mock_flows etc.)
        for key, p_cfg in providers.items():
            p_type = p_cfg.get("type", "")
            if "mock" in p_type or "Fallback" in p_type:
                base_confidence -= 8.0 # deduct 8% per mock fallback source
                
        # Deduct if outputs are missing or empty
        if not economic_events:
            base_confidence -= 15.0
        if not raw_events:
            base_confidence -= 15.0
            
        confidence = max(0.0, min(100.0, base_confidence))

        # 6. Generate human-readable summary explaining the "why"
        top_sector = rotation.get("strongest", ["unknown"])[0].upper()
        bot_sector = rotation.get("weakest", ["unknown"])[0].upper()
        
        summary_text = (
            f"Macro regime is {macro_regime} (Confidence: {confidence:.0f}%) with event impact score {event_impact}. "
            f"Breadth health is {breadth_health:.1f}% with A/D ratio of {breadth.get('ad_ratio', 1.0):.2f}. "
            f"FII/DII flows are {flows_regime} ({flows.get('combined_net_crores', 0.0):+.1f} Cr). "
            f"Sector rotation reveals capital rotating out of {bot_sector} into {top_sector}."
        )

        report = {
            "enabled": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
            "macro_regime": macro_regime,
            "event_impact_score": event_impact,
            "breadth_health_score": breadth_health,
            "breadth": breadth,
            "flows_regime": flows_regime,
            "flows": flows,
            "options_regime": options_regime,
            "options": options_nifty,
            "economic_events": economic_events,
            "earnings_releases": earnings_releases,
            "sector_rotation": rotation,
            "indices": indices,
            "geopolitical_assessments": geo_assessments,
            "explainable_summary": summary_text,
            "reasons": reasons_list
        }
        
        # Write to cache
        self.cache.write_intelligence("market_intelligence.json", report)
        
        # Publish to EventBus for real-time streaming and audit trail
        try:
            from hokage.dashboard.event_bus import EventBus
            EventBus().publish("MARKET_INTEL_REPORT", report)
        except Exception:
            pass

        return report

    def get_or_compute_report(self) -> dict[str, Any]:
        """Load report from cache if fresh, otherwise compute fresh."""
        try:
            report = self.cache.read_intelligence("market_intelligence.json")
            if report:
                # check freshness (within 5 minutes)
                gen_time = datetime.fromisoformat(report["generated_at"])
                if (datetime.now(timezone.utc) - gen_time).total_seconds() < 300:
                    return report
        except Exception:
            pass
            
        return self.compute_unified_report()

    def get_opportunity_adjustments(self, symbol: str, sector: str) -> dict[str, Any]:
        """Calculate advisory scoring adjustments and explanations for a candidate asset."""
        report = self.get_or_compute_report()
        
        # Zero adjustment if report confidence is too low
        min_conf = self.config.get("scoring_parameters", {}).get("min_report_confidence_threshold", 50.0)
        if report.get("confidence", 100.0) < min_conf:
            return {
                "adjustment_score": 0.0,
                "adjustment_reason": f"No market intelligence adjustment: Report confidence ({report.get('confidence', 0.0):.0f}%) is below minimum threshold ({min_conf}%)."
            }

        macro = report.get("macro_regime", "STATIONARY")
        rotation = report.get("sector_rotation", {})
        
        adjustment = 0.0
        reasons = []

        # 1. Macro Regime adjustment
        # RISK-ON gives a bonus to high-beta sectors (IT, Crypto)
        # RISK-OFF penalizes them or favors commodities/gold
        sector_lower = sector.lower()
        if macro == "RISK-ON":
            if sector_lower in ("it", "crypto", "defence"):
                adjustment += 3.0
                reasons.append("RISK-ON macro regime favors growth sectors (+3)")
        elif macro == "RISK-OFF":
            if sector_lower in ("it", "crypto"):
                adjustment -= 4.0
                reasons.append("RISK-OFF macro regime penalizes speculative sectors (-4)")
            elif sector_lower in ("commodity", "metals"):
                adjustment += 2.0
                reasons.append("RISK-OFF macro regime favors defensive/commodity sectors (+2)")
        elif macro == "INFLATION SHOCK":
            if sector_lower == "commodity":
                adjustment += 4.0
                reasons.append("INFLATION SHOCK regime favors hard commodities (+4)")
            else:
                adjustment -= 3.0
                reasons.append(f"INFLATION SHOCK regime reduces non-commodity sector score (-3)")

        # 2. Sector Rotation alignment
        strongest = [s.lower() for s in rotation.get("strongest", [])]
        weakest = [s.lower() for s in rotation.get("weakest", [])]
        
        if sector_lower in strongest:
            adjustment += 5.0
            reasons.append(f"Sector {sector} ranks in top rotation strength (+5)")
        elif sector_lower in weakest:
            adjustment -= 5.0
            reasons.append(f"Sector {sector} ranks in bottom rotation strength (-5)")

        # Limit adjustments to configured max
        max_adj = self.config.get("scoring_parameters", {}).get("max_conviction_adjustment", 10.0)
        final_adjustment = max(-max_adj, min(max_adj, adjustment))

        reason_str = " | ".join(reasons) if reasons else "No specific macro or sector rotation adjustments applied."
        return {
            "adjustment_score": float(final_adjustment),
            "adjustment_reason": reason_str
        }
