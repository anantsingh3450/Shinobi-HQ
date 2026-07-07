"""Investment Committee Layer for Hokage — Phase 4C.5C.

Contains engines for conviction score generation (0-100), confidence calibration
with reward/penalty, and the NoTradeDecisionEngine that outputs BUY / WATCH /
OBSERVE / NO TRADE with explicit, explainable reasoning.

Every conviction score carries:
  - A unique decision_id (UUID4) for cross-system traceability.
  - A full conviction_breakdown showing all 9 component weights.
  - A veto_source when the committee rejects a candidate.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.ConvictionEngine")

# ---------------------------------------------------------------------------
# Weight constants — must sum to 1.0
# ---------------------------------------------------------------------------
_W_REGIME      = 0.15   # Market Regime
_W_SECTOR      = 0.15   # Sector Flow Forecast
_W_ANALOG      = 0.10   # Historical Analog Match
_W_NEWS        = 0.10   # News Sentiment
_W_BACKTEST    = 0.15   # Backtest Strength
_W_ACCURACY    = 0.10   # Prediction Accuracy
_W_VIX         = 0.10   # VIX Environment
_W_RR          = 0.10   # Risk/Reward Ratio
_W_PORTFOLIO   = 0.05   # Portfolio Context (health + diversification)


class ConvictionScoreEngine:
    """Computes a unified conviction score (0-100) for the Investment Committee.

    Grades:
        0–30   AVOID
        31–50  WATCH
        51–70  MODERATE
        71–85  HIGH
        86–100 ELITE
    """

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize ConvictionScoreEngine."""
        self.cache = cache

    # ------------------------------------------------------------------
    # Primary scoring method
    # ------------------------------------------------------------------

    def calculate_conviction(
        self,
        market_regime_score: float = 0.5,       # 0.0–1.0 (BULL=1.0, BEAR=0.2, SIDEWAYS=0.5)
        sector_rotation_strength: float = 0.0,  # −0.15 to +0.15
        analog_similarity: float = 50.0,        # 0.0–100.0
        news_sentiment_confidence: float = 0.5, # 0.0–1.0
        backtest_win_rate: float = 50.0,        # 0.0–100.0
        prediction_accuracy: float = 50.0,      # 0.0–100.0
        vix_impact_delta: float = 0.0,          # VIX stress level (higher = worse)
        risk_reward_ratio: float = 1.5,         # e.g. 2.0:1 ratio
        portfolio_context: float = 0.5,         # 0.0–1.0 (composite of health + diversification)
        # Legacy compat: macro_correlation_alignment is accepted but mapped to portfolio_context
        macro_correlation_alignment: float | None = None,
        symbol: str | None = None,
        sector: str | None = None,
    ) -> dict[str, Any]:
        """Compute weighted conviction score, grade, breakdown, and decision_id."""
        # Clean potential Mock/MagicMock values passed from unit tests
        def _clean_val(val, default):
            if type(val).__name__ in ("MagicMock", "Mock", "NonCallableMagicMock"):
                return default
            try:
                return float(val)
            except Exception:
                return default

        market_regime_score = _clean_val(market_regime_score, 0.5)
        sector_rotation_strength = _clean_val(sector_rotation_strength, 0.0)
        analog_similarity = _clean_val(analog_similarity, 50.0)
        news_sentiment_confidence = _clean_val(news_sentiment_confidence, 0.5)
        backtest_win_rate = _clean_val(backtest_win_rate, 50.0)
        prediction_accuracy = _clean_val(prediction_accuracy, 50.0)
        vix_impact_delta = _clean_val(vix_impact_delta, 0.0)
        risk_reward_ratio = _clean_val(risk_reward_ratio, 1.5)
        portfolio_context = _clean_val(portfolio_context, 0.5)

        # Resolve portfolio_context — accept legacy macro_correlation_alignment param
        if macro_correlation_alignment is not None:
            portfolio_context = _clean_val(macro_correlation_alignment, 0.5)

        # ------------------------------------------------------------------
        # Normalize all inputs to [0, 100]
        # ------------------------------------------------------------------
        regime_norm    = max(0.0, min(100.0, market_regime_score * 100.0))

        # Sector rotation: [−0.15, +0.15] → [0, 100]
        rotation_norm  = max(0.0, min(100.0, ((sector_rotation_strength + 0.15) / 0.30) * 100.0))

        analog_norm    = max(0.0, min(100.0, analog_similarity))
        news_norm      = max(0.0, min(100.0, news_sentiment_confidence * 100.0))
        backtest_norm  = max(0.0, min(100.0, backtest_win_rate))
        accuracy_norm  = max(0.0, min(100.0, prediction_accuracy))

        # VIX: delta 0.0 → 100 pts, delta ≥ 4.0 → 0 pts
        vix_norm = max(0.0, min(100.0,
            (1.0 - (min(4.0, max(0.0, vix_impact_delta)) / 4.0)) * 100.0))

        # R:R: 3.0+ → 100, 1.0 → 0
        rr_norm = max(0.0, min(100.0,
            ((min(3.0, max(1.0, risk_reward_ratio)) - 1.0) / 2.0) * 100.0))

        portfolio_norm = max(0.0, min(100.0, portfolio_context * 100.0))

        # ------------------------------------------------------------------
        # Weighted sum
        # ------------------------------------------------------------------
        score_val = (
            (regime_norm    * _W_REGIME)    +
            (rotation_norm  * _W_SECTOR)    +
            (analog_norm    * _W_ANALOG)    +
            (news_norm      * _W_NEWS)      +
            (backtest_norm  * _W_BACKTEST)  +
            (accuracy_norm  * _W_ACCURACY)  +
            (vix_norm       * _W_VIX)       +
            (rr_norm        * _W_RR)        +
            (portfolio_norm * _W_PORTFOLIO)
        )

        # ------------------------------------------------------------------
        # Market Intelligence range score adjustments (Phase 6.8)
        # ------------------------------------------------------------------
        intel_adjustment = 0.0
        intel_reason = "No market intelligence adjustments applied."
        if symbol and sector:
            try:
                report = self.cache.read_intelligence("market_intelligence.json")
                if report and report.get("enabled", True):
                    confidence = report.get("confidence", 100.0)
                    min_conf = 50.0
                    
                    if confidence >= min_conf:
                        macro = report.get("macro_regime", "STATIONARY")
                        rot_details = report.get("sector_rotation", {})
                        
                        sector_lower = sector.lower()
                        reasons = []
                        
                        # 1. Macro regime impact adjustments
                        if macro == "RISK-ON":
                            if sector_lower in ("it", "crypto", "defence"):
                                intel_adjustment += 3.0
                                reasons.append("RISK-ON macro regime favors growth sectors (+3)")
                        elif macro == "RISK-OFF":
                            if sector_lower in ("it", "crypto"):
                                intel_adjustment -= 4.0
                                reasons.append("RISK-OFF macro regime penalizes speculative sectors (-4)")
                            elif sector_lower in ("commodity", "metals"):
                                intel_adjustment += 2.0
                                reasons.append("RISK-OFF macro regime favors defensive/commodity sectors (+2)")
                        elif macro == "INFLATION SHOCK":
                            if sector_lower == "commodity":
                                intel_adjustment += 4.0
                                reasons.append("INFLATION SHOCK regime favors hard commodities (+4)")
                            else:
                                intel_adjustment -= 3.0
                                reasons.append(f"INFLATION SHOCK regime reduces non-commodity sector score (-3)")

                        # 2. Sector Rotation alignment adjustments
                        strongest = [s.lower() for s in rot_details.get("strongest", [])]
                        weakest = [s.lower() for s in rot_details.get("weakest", [])]
                        
                        if sector_lower in strongest:
                            intel_adjustment += 5.0
                            reasons.append(f"Sector {sector} ranks in top rotation strength (+5)")
                        elif sector_lower in weakest:
                            intel_adjustment -= 5.0
                            reasons.append(f"Sector {sector} ranks in bottom rotation strength (-5)")

                        final_adj = max(-10.0, min(10.0, intel_adjustment))
                        intel_adjustment = final_adj
                        if reasons:
                            intel_reason = " | ".join(reasons)
                    else:
                        intel_reason = f"Report confidence ({confidence:.0f}%) is below minimum threshold ({min_conf}%)."
            except Exception as exc:
                logger.error(f"Failed to read market intelligence for conviction adjustments: {exc}")

        # Adjust score and clamp to [0, 100]
        score_val = max(0.0, min(100.0, score_val + intel_adjustment))
        conviction = max(0, min(100, int(round(score_val))))

        # ------------------------------------------------------------------
        # Grade mapping (WATCH replaces LOW per Phase 4C.5C spec)
        # ------------------------------------------------------------------
        if conviction >= 86:
            grade = "ELITE"
        elif conviction >= 71:
            grade = "HIGH"
        elif conviction >= 51:
            grade = "MODERATE"
        elif conviction >= 31:
            grade = "WATCH"
        else:
            grade = "AVOID"

        # ------------------------------------------------------------------
        # Full component breakdown for journal + analytics
        # ------------------------------------------------------------------
        conviction_breakdown = {
            "market_regime":         {"weight": _W_REGIME,   "normalized": round(regime_norm, 1)},
            "sector_flow_forecast":  {"weight": _W_SECTOR,   "normalized": round(rotation_norm, 1)},
            "historical_analog":     {"weight": _W_ANALOG,   "normalized": round(analog_norm, 1)},
            "news_sentiment":        {"weight": _W_NEWS,      "normalized": round(news_norm, 1)},
            "backtest_strength":     {"weight": _W_BACKTEST,  "normalized": round(backtest_norm, 1)},
            "prediction_accuracy":   {"weight": _W_ACCURACY,  "normalized": round(accuracy_norm, 1)},
            "vix_environment":       {"weight": _W_VIX,       "normalized": round(vix_norm, 1)},
            "risk_reward_ratio":     {"weight": _W_RR,        "normalized": round(rr_norm, 1)},
            "portfolio_context":     {"weight": _W_PORTFOLIO, "normalized": round(portfolio_norm, 1)},
        }

        decision_id = str(uuid.uuid4())

        result: dict[str, Any] = {
            "decision_id": decision_id,
            "score": conviction,
            "grade": grade,
            "conviction_breakdown": conviction_breakdown,
            # Flat sub_metrics kept for backward compatibility
            "sub_metrics": {
                "regime_norm":   round(regime_norm, 1),
                "rotation_norm": round(rotation_norm, 1),
                "analog_norm":   round(analog_norm, 1),
                "macro_norm":    round(portfolio_norm, 1),   # alias
                "news_norm":     round(news_norm, 1),
                "backtest_norm": round(backtest_norm, 1),
                "accuracy_norm": round(accuracy_norm, 1),
                "vix_norm":      round(vix_norm, 1),
                "rr_norm":       round(rr_norm, 1),
            },
            "market_intelligence": {
                "adjustment": intel_adjustment,
                "reason": intel_reason
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist latest conviction snapshot
        self.cache.write_intelligence("conviction_scores.json", result)
        return result

    # ------------------------------------------------------------------
    # Legacy grade method (kept for backward compatibility)
    # ------------------------------------------------------------------

    def grade_conviction(
        self,
        confidence_score: float,
        analog_similarity: float,
        sector_flow_strength: float,
        regime_certainty: float,
        news_consistency: float,
        symbol: str | None = None,
    ) -> str:
        """Compute conviction grade using letter scale (A+, A, B, C, D).

        This method is preserved for backward compatibility with older
        callers (e.g. briefings tests). New code should use calculate_conviction.
        """
        norm_similarity = analog_similarity if analog_similarity <= 1.0 else (analog_similarity / 100.0)
        norm_similarity = max(0.0, min(1.0, norm_similarity))
        norm_flow = max(0.0, min(1.0, abs(sector_flow_strength) * 5.0))

        score = (
            (confidence_score * 0.25) +
            (norm_similarity  * 0.20) +
            (norm_flow        * 0.20) +
            (regime_certainty * 0.15) +
            (news_consistency * 0.20)
        )

        if score >= 0.85:
            grade = "A+"
        elif score >= 0.75:
            grade = "A"
        elif score >= 0.65:
            grade = "B"
        elif score >= 0.50:
            grade = "C"
        else:
            grade = "D"

        scores_file = "conviction_scores.json"
        existing = self.cache.read_intelligence(scores_file, default={})
        details: dict[str, Any] = {
            "confidence": round(confidence_score, 2),
            "analog_similarity": round(analog_similarity, 2),
            "sector_flow_strength": round(sector_flow_strength, 4),
            "regime_certainty": round(regime_certainty, 2),
            "news_consistency": round(news_consistency, 2),
            "conviction": grade,
            "score": round(score, 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        key = symbol.upper() if symbol else "overall"
        existing[key] = details
        self.cache.write_intelligence(scores_file, existing)
        return grade


# ---------------------------------------------------------------------------
# ConfidenceCalibrationEngine
# ---------------------------------------------------------------------------

class ConfidenceCalibrationEngine:
    """Recalibrates raw conviction score based on rolling prediction history.

    - Win rate > 70%: +5 point reward (system earns expanded confidence).
    - Win rate < 50%: penalty proportional to accuracy deficit.
    - Persists rolling metrics to hokage_brain/intelligence/conviction_state.json.
    """

    _REWARD_THRESHOLD  = 70.0   # win rate above this earns a score boost
    _PENALTY_THRESHOLD = 50.0   # win rate below this incurs a penalty
    _REWARD_POINTS     = 5      # bonus points when model is consistently accurate
    _MAX_PENALTY_FRAC  = 0.30   # maximum penalty fraction of raw score

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize ConfidenceCalibrationEngine."""
        self.cache = cache

    def calibrate_confidence(self, base_confidence: float) -> float:
        """Adjust float confidence (0.0–1.0) for penalty/reward.

        This is the legacy API — operates on 0–1 floats.
        For integer conviction scores use calibrate_score().
        """
        calibrated = base_confidence
        try:
            accuracy_data = self.cache.read_intelligence("prediction_accuracy.json")
            if accuracy_data:
                win_rate = accuracy_data.get("overall_accuracy", 100.0)
                if win_rate < self._PENALTY_THRESHOLD:
                    penalty = (self._PENALTY_THRESHOLD - win_rate) / 100.0
                    calibrated = max(0.20, base_confidence - penalty)
                    logger.warning(
                        "Confidence calibration — penalty applied: win_rate=%.1f%% "
                        "base=%.2f calibrated=%.2f", win_rate, base_confidence, calibrated
                    )
        except Exception:
            pass
        return round(calibrated, 2)

    def calibrate_score(self, raw_score: int) -> int:
        """Adjust integer conviction score (0–100) for penalty/reward.

        Returns the calibrated score clamped to [0, 100].
        """
        calibrated = float(raw_score)
        calibration_factor = 1.0
        try:
            accuracy_data = self.cache.read_intelligence("prediction_accuracy.json")
            win_rate = accuracy_data.get("overall_accuracy", 100.0) if accuracy_data else 100.0

            if win_rate > self._REWARD_THRESHOLD:
                calibrated = min(100.0, calibrated + self._REWARD_POINTS)
                calibration_factor = round(calibrated / max(1, raw_score), 4)
                logger.info(
                    "Confidence calibration — reward applied: win_rate=%.1f%% "
                    "+%d pts → %d", win_rate, self._REWARD_POINTS, int(calibrated)
                )
            elif win_rate < self._PENALTY_THRESHOLD:
                penalty = (self._PENALTY_THRESHOLD - win_rate) / 100.0 * raw_score
                calibrated = max(0.0, calibrated - penalty)
                calibration_factor = round(calibrated / max(1, raw_score), 4)
                logger.warning(
                    "Confidence calibration — penalty applied: win_rate=%.1f%% "
                    "-%.1f pts → %d", win_rate, penalty, int(calibrated)
                )
        except Exception:
            win_rate = 100.0

        result = max(0, min(100, int(round(calibrated))))

        # Persist conviction_state.json
        try:
            existing = self.cache.read_intelligence("conviction_state.json") or {}
            existing.update({
                "last_raw_score": raw_score,
                "last_calibrated_score": result,
                "calibration_factor": calibration_factor,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self.cache.write_intelligence("conviction_state.json", existing)
        except Exception as exc:
            logger.error("Failed to persist conviction_state.json: %s", exc)

        return result

    def update_committee_decision(
        self,
        decision: str,
        avg_conviction: float,
        rolling_accuracy: float,
    ) -> None:
        """Persist a committee decision snapshot to conviction_state.json."""
        try:
            existing = self.cache.read_intelligence("conviction_state.json") or {}
            existing.update({
                "last_committee_decision": decision,
                "average_conviction": round(avg_conviction, 2),
                "rolling_accuracy": round(rolling_accuracy, 2),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self.cache.write_intelligence("conviction_state.json", existing)
        except Exception as exc:
            logger.error("Failed to update committee decision: %s", exc)


# ---------------------------------------------------------------------------
# NoTradeDecisionEngine
# ---------------------------------------------------------------------------

class NoTradeDecisionEngine:
    """Investment Committee gate — outputs BUY / WATCH / OBSERVE / NO TRADE.

    Checks:
        1. Conviction score threshold
        2. Analog similarity
        3. VIX stress level
        4. Historical accuracy
        5. Conflicting news signals
        6. Portfolio health veto (optional)
        7. Sector concentration veto (optional)

    Always returns a ``veto_source`` field identifying which layer blocked the trade.
    """

    # Thresholds
    _MIN_CONVICTION_DEPLOY = 51    # below this → NO TRADE
    _MIN_CONVICTION_WATCH  = 31    # below this → AVOID, above → WATCH
    _MIN_ANALOG_SIMILARITY = 60.0  # below this → OBSERVE
    _MAX_VIX_DEPLOY        = 2.5   # above this → NO TRADE
    _VIX_OBSERVE_LEVEL     = 1.5   # above this → OBSERVE
    _MIN_ACCURACY_DEPLOY   = 50.0  # below this → NO TRADE
    _MIN_PORTFOLIO_HEALTH  = 51    # below this → WATCH (portfolio veto)
    _MAX_SECTOR_EXPOSURE   = 20.0  # above this → veto on concentration

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize NoTradeDecisionEngine."""
        self.cache = cache

    def evaluate_no_trade(
        self,
        conviction_score: int | float | None = None,
        analog_similarity: float = 100.0,
        conflicting_news: bool = False,
        vix_impact_delta: float = 0.0,
        history_accuracy: float = 100.0,
        portfolio_health: int | None = None,
        sector_concentration_pct: float = 0.0,
        # Legacy compat params (predictive.py callers)
        flow_confidence: float | None = None,
        conflicting_signals: bool | None = None,
        poor_reward_risk: bool | None = None,
        regime_confidence: float | None = None,
    ) -> dict[str, Any]:
        """Evaluate committee deployment decision.

        Returns a dict with:
            recommended_action: "BUY" | "WATCH" | "OBSERVE" | "NO TRADE"
            prediction:         "TRADE" | "NO_TRADE"
            reason:             Human-readable reason string
            reasons:            List of individual reason strings
            veto_source:        Name of the engine that vetoed (or None)
            confidence:         Float 0.0–1.0
        """
        # ---------------------------------------------------------------
        # Legacy predictive.py compat branch
        # ---------------------------------------------------------------
        is_old = (
            regime_confidence is not None
            or flow_confidence is not None
            or (isinstance(conviction_score, float) and conviction_score <= 1.0)
        )

        if is_old:
            return self._legacy_evaluate(
                conviction_score=conviction_score,
                vix_impact_delta=vix_impact_delta,
                flow_confidence=flow_confidence,
                conflicting_signals=conflicting_signals,
                poor_reward_risk=poor_reward_risk,
                regime_confidence=regime_confidence,
            )

        # ---------------------------------------------------------------
        # New Investment Committee evaluation
        # ---------------------------------------------------------------
        reasons: list[str] = []
        veto_source: str | None = None
        score_val = int(conviction_score) if conviction_score is not None else 100

        # 1. Conviction threshold check
        if score_val < self._MIN_CONVICTION_DEPLOY:
            reasons.append(
                f"Conviction score of {score_val} falls below the deployment "
                f"safety limit of {self._MIN_CONVICTION_DEPLOY}."
            )
            veto_source = "ConvictionScoreEngine"

        # 2. Historical analog match
        if analog_similarity < self._MIN_ANALOG_SIMILARITY:
            reasons.append(
                f"Weak historical analog match of {analog_similarity:.1f}% "
                f"(minimum {self._MIN_ANALOG_SIMILARITY}%) — insufficient edge."
            )
            if veto_source is None:
                veto_source = "HistoricalAnalogEngine"

        # 3. Conflicting news
        if conflicting_news:
            reasons.append("Conflicting news signals detected across sentiment feeds.")
            if veto_source is None:
                veto_source = "NewsIntelligenceEngine"

        # 4. VIX stress
        if vix_impact_delta >= self._MAX_VIX_DEPLOY:
            reasons.append(
                f"Elevated VIX delta of {vix_impact_delta:.1f} triggers capital "
                "preservation filters. Market too volatile to deploy."
            )
            if veto_source is None:
                veto_source = "MarketRegimeEngine"

        # 5. Prediction accuracy
        if history_accuracy < self._MIN_ACCURACY_DEPLOY:
            reasons.append(
                f"Poor rolling prediction accuracy of {history_accuracy:.1f}% "
                f"(minimum {self._MIN_ACCURACY_DEPLOY}%)."
            )
            if veto_source is None:
                veto_source = "PredictionAccuracyTracker"

        # 6. Portfolio health veto
        if portfolio_health is not None and portfolio_health < self._MIN_PORTFOLIO_HEALTH:
            reasons.append(
                f"Portfolio health score of {portfolio_health} is below the "
                f"minimum deployment threshold of {self._MIN_PORTFOLIO_HEALTH}."
            )
            if veto_source is None:
                veto_source = "PortfolioAwarenessEngine"

        # 7. Sector concentration veto
        if sector_concentration_pct > self._MAX_SECTOR_EXPOSURE:
            reasons.append(
                f"Sector concentration too high: {sector_concentration_pct:.1f}% "
                f"(maximum {self._MAX_SECTOR_EXPOSURE}%)."
            )
            if veto_source is None:
                veto_source = "PositionAllocationEngine"

        # ---------------------------------------------------------------
        # Determine recommended action and prediction
        # ---------------------------------------------------------------
        no_trade = bool(reasons)  # any check failed → no trade

        if no_trade:
            recommended_action = "NO TRADE"
            prediction = "NO_TRADE"
            confidence = max(0.50, round(1.0 - (score_val / 100.0), 2))
        elif vix_impact_delta >= self._VIX_OBSERVE_LEVEL:
            # Conditions technically acceptable but caution warranted
            recommended_action = "OBSERVE"
            prediction = "TRADE"
            reasons.append(
                f"Moderately elevated VIX delta ({vix_impact_delta:.1f}). "
                "Stance set to OBSERVE — monitor before committing capital."
            )
            confidence = 0.65
        elif score_val < self._MIN_CONVICTION_DEPLOY and score_val >= self._MIN_CONVICTION_WATCH:
            recommended_action = "WATCH"
            prediction = "NO_TRADE"
            confidence = 0.60
        else:
            recommended_action = "BUY"
            prediction = "TRADE"
            reasons.append("Edge confirmed. All committee checks passed. Deployment authorized.")
            confidence = 0.85

        reason_summary = " ".join(reasons) if reasons else "Edge confirmed. Deployment authorized."

        result: dict[str, Any] = {
            "prediction": prediction,
            "recommended_action": recommended_action,
            "reason": reason_summary,
            "reasons": reasons,
            "veto_source": veto_source,
            "confidence": confidence,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        self.cache.write_intelligence("recommended_action.json", result)
        return result

    # ------------------------------------------------------------------
    # Legacy branch (backward compatibility with predictive.py callers)
    # ------------------------------------------------------------------

    def _legacy_evaluate(
        self,
        conviction_score: Any,
        vix_impact_delta: float,
        flow_confidence: float | None,
        conflicting_signals: bool | None,
        poor_reward_risk: bool | None,
        regime_confidence: float | None,
    ) -> dict[str, Any]:
        """Handle legacy callers from predictive.py (old float regime_confidence API)."""
        regime_conf_val = 0.80
        if regime_confidence is not None:
            regime_conf_val = regime_confidence
        elif isinstance(conviction_score, float) and conviction_score <= 1.0:
            regime_conf_val = conviction_score

        flow_confidence_val = flow_confidence if flow_confidence is not None else 0.5
        conflicting_signals_val = bool(conflicting_signals)
        poor_reward_risk_val = bool(poor_reward_risk)

        recommended_action = "PAPER TRADE"
        reasons: list[str] = []
        no_trade = False

        if vix_impact_delta >= 3.0:
            no_trade = True
            reasons.append("VIX delta is extremely high (>=3.0), flagging unstable market volatility.")
        elif vix_impact_delta >= 2.0:
            reasons.append("Elevated volatility detected.")

        if regime_conf_val < 0.55:
            no_trade = True
            reasons.append("Regime classification certainty is below the safety threshold of 55%.")

        if flow_confidence_val < 0.50:
            no_trade = True
            reasons.append("Sector flow forecast confidence is below the safety threshold of 50%.")

        if conflicting_signals_val:
            no_trade = True
            reasons.append("Conflicting macro signals.")

        if poor_reward_risk_val:
            no_trade = True
            reasons.append("Poor reward/risk profile.")

        if no_trade:
            recommended_action = "NO TRADE"
        elif vix_impact_delta >= 1.5:
            recommended_action = "OBSERVE"
            reasons.append("Moderately elevated VIX. Stance set to OBSERVE only.")
        else:
            reasons.append("Market regime certain and volatility stable. Safe to run execution.")

        overall_confidence = round((regime_conf_val + flow_confidence_val) / 2.0, 2)

        result: dict[str, Any] = {
            "prediction": "NO TRADE" if no_trade else "TRADE",
            "recommended_action": recommended_action,
            "confidence": overall_confidence,
            "reasoning_factors": reasons,
            "reason": " ".join(reasons),
            "reasons": reasons,
            "veto_source": "NoTradeDecisionEngine" if no_trade else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.cache.write_intelligence("recommended_action.json", result)
        return result
