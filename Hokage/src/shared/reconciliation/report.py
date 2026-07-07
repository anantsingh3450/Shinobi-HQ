"""Reconciliation Report — aggregates discrepancies, calculates health score, and formats output.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shared.reconciliation.classifier import Discrepancy, SeverityLevel


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Aggregated output of a single reconciliation session."""

    report_id: str
    timestamp: datetime
    health_score: float
    discrepancies: list[Discrepancy]
    risk_estimate: str
    frozen_assets: list[str]
    is_critical: bool
    requires_action: bool

    @classmethod
    def generate(cls, discrepancies: list[Discrepancy]) -> ReconciliationReport:
        """Create a report from a list of detected discrepancies, calculating health score."""
        # 1. Calculate health score
        score = 100.0
        is_critical = False
        requires_action = False
        frozen_assets = []
        risk_summaries = []

        for d in discrepancies:
            if d.severity == SeverityLevel.CRITICAL:
                score -= 40.0
                is_critical = True
                requires_action = True
            elif d.severity == SeverityLevel.HIGH:
                score -= 20.0
                requires_action = True
            elif d.severity == SeverityLevel.MEDIUM:
                score -= 10.0
            elif d.severity == SeverityLevel.LOW:
                score -= 2.0

            if d.requires_freeze:
                frozen_assets.append(d.asset)

            risk_summaries.append(f"- [{d.severity.value}] {d.asset}: {d.risk_estimate}")

        score = max(0.0, score)

        # 2. Formulate risk estimate summary
        if not discrepancies:
            risk_estimate = "Broker and local state are in perfect alignment. Zero discrepancies detected."
        else:
            risk_estimate = (
                f"Detected {len(discrepancies)} discrepancies. "
                f"System Health: {score:.1f}/100. "
                "Discrepancies detail:\n" + "\n".join(risk_summaries)
            )

        return cls(
            report_id=f"rep-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc),
            health_score=score,
            discrepancies=discrepancies,
            risk_estimate=risk_estimate,
            frozen_assets=list(set(frozen_assets)),
            is_critical=is_critical,
            requires_action=requires_action,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize report for storage."""
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "health_score": self.health_score,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "risk_estimate": self.risk_estimate,
            "frozen_assets": self.frozen_assets,
            "is_critical": self.is_critical,
            "requires_action": self.requires_action,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReconciliationReport:
        """Deserialize report."""
        return cls(
            report_id=data["report_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            health_score=data["health_score"],
            discrepancies=[Discrepancy.from_dict(d) for d in data.get("discrepancies", [])],
            risk_estimate=data["risk_estimate"],
            frozen_assets=data.get("frozen_assets", []),
            is_critical=data.get("is_critical", False),
            requires_action=data.get("requires_action", False),
        )

    def generate_briefing(self) -> str:
        """Generate a clean, professional textual report for CLI display."""
        status_line = "SYSTEM CRITICAL" if self.is_critical else ("ATTENTION REQUIRED" if self.requires_action else "HEALTHY")
        
        brief = [
            "============================================================",
            f"            HOKAGE BROKER RECONCILIATION REPORT",
            "============================================================",
            f"Report ID : {self.report_id}",
            f"Timestamp : {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Status    : {status_line}",
            f"Health    : {self.health_score:.1f}/100",
            "------------------------------------------------------------",
        ]

        if not self.discrepancies:
            brief.append("Status: PERFECT MATCH. No discrepancies found.")
        else:
            brief.append(f"Outstanding Discrepancies: {len(self.discrepancies)}")
            for idx, d in enumerate(self.discrepancies, 1):
                brief.append(
                    f"[{idx}] {d.type.value} | Severity: {d.severity.value} | Asset: {d.asset}"
                )
                brief.append(f"    Risk: {d.risk_estimate}")
                if d.requires_freeze:
                    brief.append("    Action taken: FREEZING asset executions.")

        if self.frozen_assets:
            brief.append("------------------------------------------------------------")
            brief.append(f"Currently Frozen Assets: {', '.join(self.frozen_assets)}")

        brief.append("============================================================")
        return "\n".join(brief)
