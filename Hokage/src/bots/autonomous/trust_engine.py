"""Elder Trust Engine for Hokage.

Measures and scores the system's historical trading consistency, drawdown controls,
and risk compliance, outputting an Elder Trust Score (0-100) and grade.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.TrustEngine")


class ElderTrustEngine:
    """Calculates and monitors the Elder Trust Score representing capital deployment authority."""

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize ElderTrustEngine."""
        self.cache = cache
        self.state_file = "elder_trust.json"

    def calculate_trust_score(
        self,
        prediction_accuracy: float = 100.0,
        drawdown_pct: float = 0.0,
        consistency_score: float = 100.0,
        risk_compliance: float = 100.0,
        conviction_accuracy: float = 100.0,
    ) -> dict[str, Any]:
        """Compute trust score using weighted performance indices.
        
        Outputs score in range 0-100 and mapped grade:
          - A (>=90)
          - B (80-89)
          - C (70-79)
          - D (60-69)
          - F (<60)
        """
        # Drawdown Control Score: 100 - (drawdown * 4) capped between 0 and 100
        drawdown_control = max(0.0, min(100.0, 100.0 - (drawdown_pct * 4.0)))

        # Weighted score:
        # Prediction Accuracy: 25%
        # Drawdown Control: 25%
        # Consistency Score: 20%
        # Risk Compliance: 15%
        # Conviction Accuracy: 15%
        score_val = (
            (prediction_accuracy * 0.25) +
            (drawdown_control * 0.25) +
            (consistency_score * 0.20) +
            (risk_compliance * 0.15) +
            (conviction_accuracy * 0.15)
        )

        trust_score = int(score_val + 0.5)
        trust_score = max(0, min(100, trust_score))

        # Grade mappings
        if trust_score >= 90:
            grade = "A"
        elif trust_score >= 80:
            grade = "B"
        elif trust_score >= 70:
            grade = "C"
        elif trust_score >= 60:
            grade = "D"
        else:
            grade = "F"

        result = {
            "trust_score": trust_score,
            "grade": grade,
            "metrics": {
                "prediction_accuracy": round(prediction_accuracy, 1),
                "drawdown_control": round(drawdown_control, 1),
                "drawdown_pct": round(drawdown_pct, 2),
                "consistency": round(consistency_score, 1),
                "risk_compliance": round(risk_compliance, 1),
                "conviction_accuracy": round(conviction_accuracy, 1)
            },
            "evaluated_at": datetime.now(timezone.utc).isoformat()
        }

        # Cache results
        self.cache.write_intelligence(self.state_file, result)
        return result
