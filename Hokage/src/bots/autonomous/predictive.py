"""Predictive Intelligence Layer for Hokage.

Contains engines for market regime classification, macroeconomic correlations tracking,
geopolitical event impact projection, sector flow forecasts, conviction grading,
automated no-trade logic, and prediction accuracy tracking.
"""
from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.PredictiveIntel")


class MarketRegimeEngine:
    """Classifies current market state with a calculated confidence score."""

    def __init__(self, orchestrator: HokageOrchestrator, cache: IntelligenceCache) -> None:
        """Initialize MarketRegimeEngine."""
        self.orchestrator = orchestrator
        self.cache = cache

    def classify_regime(self) -> dict[str, Any]:
        """Classify active market regime (BULL, BEAR, SIDEWAYS, RISK-ON/OFF)."""
        logger.info("Classifying market regime.")
        
        # Query indicators via price source (or mocks if offline)
        try:
            nifty_price = self.orchestrator.price_source.get_price("NIFTY 50")
            if not isinstance(nifty_price, (int, float)) or isinstance(nifty_price, bool):
                nifty_price = 23500.0
        except Exception:
            nifty_price = 23500.0

        # Query VIX state delta
        vix_delta = 0.0
        try:
            risk_state = self.cache.read_intelligence("risk_state.json")
            vix_delta = risk_state.get("vix_impact_delta", 0.0)
        except Exception:
            pass

        # Regime classification heuristics
        regime = "SIDEWAYS"
        confidence = 0.65
        factors = ["Sideways price consolidation on main domestic index"]

        if nifty_price > 24000.0:
            regime = "BULL"
            confidence = 0.85
            factors = ["Index above key psychological resistance level of 24000", "Strong domestic inflows"]
        elif nifty_price < 22000.0:
            regime = "BEAR"
            confidence = 0.75
            factors = ["Index down below critical support thresholds", "FII selloffs active"]

        # Risk mode overlay
        risk_mode = "RISK-ON"
        if vix_delta >= 1.5:
            risk_mode = "RISK-OFF"
            confidence = max(0.50, confidence - 0.10)
            factors.append("Elevated VIX delta. System triggered RISK-OFF overlay stance.")

        prediction_result = {
            "prediction": f"{regime}_{risk_mode}",
            "confidence": round(confidence, 2),
            "reasoning_factors": factors,
            "classified_at": datetime.now(timezone.utc).isoformat()
        }

        # Persist to intelligence cache and dynamic prediction logs
        self.cache.write_intelligence("market_regime.json", prediction_result)
        self._write_predictions_log("market_regime", prediction_result)
        return prediction_result

    def _write_predictions_log(self, name: str, data: dict[str, Any]) -> None:
        """Write copy of prediction record inside intelligence/predictions/."""
        predictions_dir = self.cache.get_cache_file_path("predictions")
        predictions_dir.mkdir(parents=True, exist_ok=True)
        file_path = predictions_dir / f"{name}.json"
        try:
            with file_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
        except Exception as exc:
            logger.error(f"Failed to log prediction details for {name}: {exc}")


class MacroCorrelationEngine:
    """Tracks correlations between macroeconomic drivers (Oil, Gold, Yields) and sectors."""

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize MacroCorrelationEngine."""
        self.cache = cache
        
        # Hardcoded baseline correlation coefficients
        self.correlations = {
            "oil_energy": 0.75,
            "oil_aviation": -0.65,
            "gold_risk_off": 0.80,
            "usdinr_it": 0.60,
            "bond_yield_banking": 0.45,
            "vix_broad_market": -0.70
        }

    def get_correlations(self) -> dict[str, float]:
        """Fetch and return mapped correlation factors."""
        self.cache.write_intelligence("macro_correlations.json", self.correlations)
        return self.correlations


class EventImpactPredictor:
    """Predicts news headlines impact deltas on target market sectors."""

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize EventImpactPredictor."""
        self.cache = cache
        
        # Impact projection weights mapping keywords to sector deltas
        self.impact_matrix = {
            "rbi": {"banking": 0.02, "financials": 0.02, "realty": 0.015},
            "fed": {"banking": 0.01, "it": 0.02},
            "oil": {"energy": 0.03, "aviation": -0.04, "logistics": -0.015},
            "red sea": {"energy": 0.02, "aviation": -0.03, "logistics": -0.02},
            "war": {"energy": 0.04, "broad_market": -0.03},
            "conflict": {"energy": 0.025, "broad_market": -0.02},
            "inflation": {"banking": -0.015, "fmcg": 0.01},
            "rate cut": {"banking": 0.025, "realty": 0.03, "auto": 0.02}
        }

    def predict_event_impact(self, news_events: list[dict[str, Any]]) -> dict[str, Any]:
        """Assess headlines and project specific sector deltas before open."""
        sector_deltas: dict[str, float] = {}
        factors = []
        
        # Aggregate impact weights
        matches_found = 0
        for ev in news_events:
            combined = (ev.get("title", "") + " " + ev.get("description", "")).lower()
            for kw, deltas in self.impact_matrix.items():
                if kw in combined:
                    matches_found += 1
                    factors.append(f"Headline matched keyword '{kw}' -> projecting sector shifts.")
                    for sec, delta in deltas.items():
                        sector_deltas[sec] = round(sector_deltas.get(sec, 0.0) + delta, 4)

        # Cap deltas within realistic bounds
        for sec in list(sector_deltas.keys()):
            sector_deltas[sec] = max(-0.15, min(0.15, sector_deltas[sec]))

        # Calculate confidence based on keyword match hits
        confidence = 0.50
        if matches_found >= 3:
            confidence = 0.85
        elif matches_found > 0:
            confidence = 0.70

        prediction_result = {
            "prediction": sector_deltas,
            "confidence": confidence,
            "reasoning_factors": factors or ["No significant macro triggers matched news headlines."],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        # Persist prediction details
        self.cache.write_intelligence("market_sentiment.json", prediction_result)
        
        # Write copy in predictions directory
        predictions_dir = self.cache.get_cache_file_path("predictions")
        predictions_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (predictions_dir / "event_impact.json").open("w", encoding="utf-8") as fh:
                json.dump(prediction_result, fh, indent=2, sort_keys=True)
        except Exception as exc:
            logger.error(f"Failed to write event impact prediction log: {exc}")

        return prediction_result


class SectorFlowForecastEngine:
    """Forecasts likely capital flows and sector rotation vectors over 1-5 trading sessions."""

    def __init__(
        self,
        correlation_engine: MacroCorrelationEngine,
        event_predictor: EventImpactPredictor,
        cache: IntelligenceCache,
    ) -> None:
        """Initialize SectorFlowForecastEngine."""
        self.correlation_engine = correlation_engine
        self.event_predictor = event_predictor
        self.cache = cache

    def forecast_flows(self, regime_data: dict[str, Any], event_impacts: dict[str, Any]) -> dict[str, Any]:
        """Generate capital rotation predictions."""
        logger.info("Forecasting sector capital flows.")
        correlations = self.correlation_engine.get_correlations()
        event_deltas = event_impacts.get("prediction", {})
        regime = regime_data.get("prediction", "SIDEWAYS_RISK-ON")

        forecast = {}
        sectors = ["banking", "it", "energy", "pharma", "fmcg", "metals", "auto", "defence"]
        
        factors = []
        # Calculate sector coefficients
        for sec in sectors:
            # Baseline momentum relative to regime
            base_score = 0.0
            if "BULL" in regime:
                base_score = 0.02
                if sec in ("banking", "auto"):
                    base_score += 0.01
            elif "BEAR" in regime:
                base_score = -0.02
                if sec in ("fmcg", "pharma"):
                    base_score += 0.015  # defensive outperformance

            # News delta weight
            news_delta = event_deltas.get(sec, 0.0)
            
            # Macro correlations weight (Oil, USDINR adjustments)
            macro_factor = 0.0
            if sec == "energy" and event_deltas.get("energy", 0) > 0:
                macro_factor = correlations.get("oil_energy", 0.75) * 0.02
            elif sec == "it" and event_deltas.get("it", 0) > 0:
                macro_factor = correlations.get("usdinr_it", 0.60) * 0.02

            total_coefficient = round(base_score + news_delta + macro_factor, 4)
            forecast[sec] = total_coefficient
            
            if total_coefficient > 0.02:
                factors.append(f"Sector '{sec}' shows capital flow indicators pointing to inflow.")
            elif total_coefficient < -0.02:
                factors.append(f"Sector '{sec}' shows capital flow indicators pointing to outflow.")

        # Rank sectors
        sorted_sectors = sorted(sectors, key=lambda s: forecast[s], reverse=True)

        # Confidence calculation
        confidence = 0.70
        if "RISK-OFF" in regime:
            confidence = 0.60
            factors.append("System in RISK-OFF mode, reducing forecasting model confidence limits.")

        prediction_result = {
            "prediction": {
                "forecast_flows": forecast,
                "strongest_forecast": sorted_sectors[:2],
                "weakest_forecast": sorted_sectors[-2:]
            },
            "confidence": confidence,
            "reasoning_factors": factors or ["Sectors show flat consolidation projections."],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        # Write cache files
        self.cache.write_intelligence("sector_rotation.json", prediction_result)
        
        # Write copy in predictions directory
        predictions_dir = self.cache.get_cache_file_path("predictions")
        predictions_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (predictions_dir / "sector_flow.json").open("w", encoding="utf-8") as fh:
                json.dump(prediction_result, fh, indent=2, sort_keys=True)
        except Exception as exc:
            logger.error(f"Failed to write sector flow forecast prediction log: {exc}")

        return prediction_result


from bots.autonomous.conviction import ConvictionScoreEngine, NoTradeDecisionEngine


class PredictionAccuracyTracker:
    """Tracks prediction results and calculates rolling accuracy statistics."""

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize PredictionAccuracyTracker."""
        self.cache = cache
        self._accuracy_file = self.cache.get_cache_file_path("prediction_accuracy.json")
        self.stats = self._load_stats()

    def _load_stats(self) -> dict[str, Any]:
        """Load accuracy metrics from cache or bootstrap defaults."""
        if self._accuracy_file.exists():
            try:
                with self._accuracy_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {
            "overall_accuracy": 100.0,
            "total_predictions": 0,
            "correct_predictions": 0,
            "regime_prediction_accuracy": 100.0,
            "event_prediction_accuracy": 100.0,
            "sector_forecast_accuracy": 100.0,
            "opportunity_ranking_accuracy": 100.0,
            "by_category": {
                "market_regime": {"total": 0, "correct": 0, "accuracy": 100.0},
                "event_impact": {"total": 0, "correct": 0, "accuracy": 100.0},
                "sector_flow": {"total": 0, "correct": 0, "accuracy": 100.0},
                "opportunity_ranking": {"total": 0, "correct": 0, "accuracy": 100.0}
            },
            "history": []
        }

    def record_prediction(
        self,
        category: str,
        prediction_val: Any,
        confidence: float,
        outcome_val: Any,
        correct: bool,
    ) -> None:
        """Update metrics for a single prediction and recompute rolling percentages."""
        # Standardize category name
        norm_cat = category.lower().replace(" ", "_")
        if norm_cat in ("market_regime", "regime"):
            cat_key = "market_regime"
        elif norm_cat in ("event_impact", "event"):
            cat_key = "event_impact"
        elif norm_cat in ("sector_flow", "sector"):
            cat_key = "sector_flow"
        elif norm_cat in ("opportunity_ranking", "opportunity"):
            cat_key = "opportunity_ranking"
        else:
            cat_key = norm_cat

        self.stats["total_predictions"] += 1
        if correct:
            self.stats["correct_predictions"] += 1

        self.stats["overall_accuracy"] = round(
            (self.stats["correct_predictions"] / self.stats["total_predictions"]) * 100.0, 2
        )

        cat_stats = self.stats["by_category"].setdefault(
            cat_key, {"total": 0, "correct": 0, "accuracy": 100.0}
        )
        cat_stats["total"] += 1
        if correct:
            cat_stats["correct"] += 1
        cat_stats["accuracy"] = round((cat_stats["correct"] / cat_stats["total"]) * 100.0, 2)

        # Update flat keys for rolling accuracy compliance
        self.stats["regime_prediction_accuracy"] = self.stats["by_category"].get("market_regime", {}).get("accuracy", 100.0)
        self.stats["event_prediction_accuracy"] = self.stats["by_category"].get("event_impact", {}).get("accuracy", 100.0)
        self.stats["sector_forecast_accuracy"] = self.stats["by_category"].get("sector_flow", {}).get("accuracy", 100.0)
        self.stats["opportunity_ranking_accuracy"] = self.stats["by_category"].get("opportunity_ranking", {}).get("accuracy", 100.0)

        self.stats["history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": cat_key,
            "prediction": prediction_val,
            "confidence": confidence,
            "outcome": outcome_val,
            "correct": correct
        })

        # Save stats back to cache
        try:
            with self._accuracy_file.open("w", encoding="utf-8") as fh:
                json.dump(self.stats, fh, indent=2, sort_keys=True)
            logger.info("Saved prediction accuracy statistics.")
        except Exception as exc:
            logger.error(f"Failed to save prediction accuracy stats: {exc}")
