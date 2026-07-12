"""Opportunity Discovery Engine for Hokage.

Decouples the scanning pipeline from static watchlists, generating asset
opportunity lists dynamically based on Elder-configured constraints.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bots.autonomous.research_intel import MarketScanner
    from bots.autonomous.cache import IntelligenceCache


class OpportunityDiscoveryEngine:
    """Discovers trading candidates dynamically based on constraint modes."""

    def __init__(self, scanner: MarketScanner, cache: IntelligenceCache | None = None) -> None:
        """Initialize engine."""
        self.scanner = scanner
        self.cache = cache
        
        # Heuristic sector mapping
        self._sector_mappings = {
            "it": ["TCS", "INFY"],
            "energy": ["RELIANCE", "ONGC"],
            "banking": ["HDFCBANK", "ICICIBANK", "SBIN"],
            "financials": ["HDFCBANK", "ICICIBANK", "SBIN"],
            "logistics": ["LT"]
        }

    def discover_opportunities(
        self,
        mode: str = "OPEN_MARKET",
        constraints: list[str] | str | None = None,
    ) -> list[str]:
        """Resolve dynamic opportunity list based on constraint mode.
        
        Supported modes:
          - OPEN_MARKET: Scans the full market universe.
          - SECTOR_RESTRICTED: Scans symbols belonging to target sectors.
          - WATCHLIST_RESTRICTED: Scans user-specified watchlist.
          - SINGLE_ASSET: Scans a single specific asset.
        """
        mode_upper = mode.upper()
        full_universe = self.scanner.get_market_opportunity_universe()

        prediction = []
        factors = [f"Discovery scan mode set to {mode_upper}"]

        if mode_upper == "SINGLE_ASSET":
            if isinstance(constraints, str):
                prediction = [constraints.upper()]
            elif isinstance(constraints, list) and len(constraints) > 0:
                prediction = [constraints[0].upper()]
            else:
                prediction = ["TCS"]
            factors.append(f"Single asset scanning constraint enforced: {prediction}")

        elif mode_upper == "WATCHLIST_RESTRICTED":
            if isinstance(constraints, list):
                prediction = [s.upper() for s in constraints]
            else:
                prediction = ["TCS", "INFY", "RELIANCE"]
            factors.append(f"Watchlist restricted scanning constraint enforced: {prediction}")

        elif mode_upper == "SECTOR_RESTRICTED":
            if not constraints:
                prediction = ["RELIANCE", "ONGC"]  # Energy fallback
                factors.append("Sector restricted mode default fallback to energy sector")
            else:
                target_sectors = [constraints] if isinstance(constraints, str) else constraints
                selected = []
                for sec in target_sectors:
                    mapped = self._sector_mappings.get(sec.lower())
                    if mapped:
                        selected.extend(mapped)
                prediction = list(set(selected)) if selected else ["RELIANCE"]
                factors.append(f"Sector constraints: {target_sectors}. Resolved assets: {prediction}")

        else:
            # Default to OPEN_MARKET mode
            prediction = full_universe
            factors.append(f"Open market scan mode resolving complete universe: {prediction}")

        # Compute confidence engine output
        confidence = 0.85
        if self.cache:
            try:
                risk_state = self.cache.read_intelligence("risk_state.json")
                if risk_state:
                    vix_delta = risk_state.get("vix_impact_delta", 0.0)
                    risk_status = risk_state.get("risk_on_off_status", "RISK-ON")
                    if vix_delta > 1.5:
                        confidence -= 0.10
                        factors.append(f"Discovery confidence adjusted downwards due to vix delta of {vix_delta}")
                    if risk_status == "RISK-OFF":
                        confidence -= 0.15
                        factors.append("Discovery confidence adjusted downwards due to RISK-OFF stance")
            except Exception:
                pass

        if not prediction:
            confidence = 0.0
            factors.append("No opportunities discovered. Confidence set to 0.0")
        
        confidence = max(0.0, min(1.0, confidence))

        prediction_result = {
            "prediction": prediction,
            "confidence": round(confidence, 2),
            "reasoning_factors": factors,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        # Persist predictions alongside other components
        if self.cache:
            predictions_dir = self.cache.get_cache_file_path("predictions")
            predictions_dir.mkdir(parents=True, exist_ok=True)
            file_path = predictions_dir / "opportunity_rankings.json"
            try:
                with file_path.open("w", encoding="utf-8") as fh:
                    json.dump(prediction_result, fh, indent=2, sort_keys=True)
            except Exception:
                pass

        return prediction
