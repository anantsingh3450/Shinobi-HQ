"""Discrepancy Classifier — categorizes, evaluates severity, and assesses risk of discrepancies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class DiscrepancyType(StrEnum):
    """Categorization of discrepancies found during reconciliation."""

    MISSING_POSITION = "MISSING_POSITION"
    PHANTOM_POSITION = "PHANTOM_POSITION"
    DUPLICATE_POSITION = "DUPLICATE_POSITION"
    REJECTED_ORDER = "REJECTED_ORDER"
    PARTIAL_FILL = "PARTIAL_FILL"
    CANCELLED_ORDER = "CANCELLED_ORDER"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    ORPHANED_TRADE = "ORPHANED_TRADE"
    LEDGER_INCONSISTENCY = "LEDGER_INCONSISTENCY"


class SeverityLevel(StrEnum):
    """Urgency and risk rating of a discrepancy."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """A detected mismatch between the broker and local ledger states."""

    discrepancy_id: str
    type: DiscrepancyType
    asset: str
    severity: SeverityLevel
    details: dict[str, Any]
    risk_estimate: str
    requires_freeze: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize discrepancy for reporting and storage."""
        return {
            "discrepancy_id": self.discrepancy_id,
            "type": self.type.value,
            "asset": self.asset,
            "severity": self.severity.value,
            "details": self.details,
            "risk_estimate": self.risk_estimate,
            "requires_freeze": self.requires_freeze,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Discrepancy:
        """Deserialize discrepancy."""
        return cls(
            discrepancy_id=data["discrepancy_id"],
            type=DiscrepancyType(data["type"]),
            asset=data["asset"],
            severity=SeverityLevel(data["severity"]),
            details=data["details"],
            risk_estimate=data["risk_estimate"],
            requires_freeze=data["requires_freeze"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class DiscrepancyClassifier:
    """Classifies discrepancies, estimates risk, and decides gating rules."""

    @staticmethod
    def classify(
        discrepancy_id: str,
        dtype: DiscrepancyType,
        asset: str,
        details: dict[str, Any],
    ) -> Discrepancy:
        """Evaluate a discrepancy to determine its severity, risk level, and freeze status."""
        severity = SeverityLevel.LOW
        requires_freeze = False
        risk_estimate = ""

        if dtype == DiscrepancyType.PHANTOM_POSITION:
            severity = SeverityLevel.CRITICAL
            requires_freeze = True
            risk_estimate = (
                f"Phantom position detected on broker for {asset}. "
                f"Hokage has unmanaged financial exposure of quantity {details.get('broker_qty', 0)}. "
                "High risk of capital loss as local risk/exit bots are unaware of this exposure."
            )

        elif dtype == DiscrepancyType.DUPLICATE_POSITION:
            severity = SeverityLevel.CRITICAL
            requires_freeze = True
            risk_estimate = (
                f"Duplicate open positions detected for {asset}. "
                "Risk of over-leveraging and conflicting execution triggers. "
                "Requires immediate strategy freeze and manual cleanup."
            )

        elif dtype == DiscrepancyType.MISSING_POSITION:
            severity = SeverityLevel.HIGH
            requires_freeze = True
            risk_estimate = (
                f"Local ledger expects an open position in {asset}, but it is missing on the broker. "
                "Risk of exit orders failing, leading to state corruption and incorrect risk metrics. "
                "Strategy frozen to prevent additional orphan orders."
            )

        elif dtype == DiscrepancyType.QUANTITY_MISMATCH:
            local_qty = details.get("local_qty", 0.0)
            broker_qty = details.get("broker_qty", 0.0)
            diff = abs(local_qty - broker_qty)
            
            if broker_qty > local_qty:
                severity = SeverityLevel.CRITICAL
                requires_freeze = True
                risk_estimate = (
                    f"Broker quantity ({broker_qty}) is higher than local ledger ({local_qty}) for {asset}. "
                    f"Over-exposure of {diff} units. Unmanaged market risk. Asset frozen."
                )
            else:
                # Broker quantity is lower than expected
                severity = SeverityLevel.HIGH
                requires_freeze = True
                risk_estimate = (
                    f"Broker quantity ({broker_qty}) is lower than local ledger ({local_qty}) for {asset}. "
                    f"Under-exposure of {diff} units. Risk of partial fill or unrecorded manual exit. Asset frozen."
                )

        elif dtype == DiscrepancyType.PRICE_MISMATCH:
            local_price = details.get("local_price", 0.0)
            broker_price = details.get("broker_price", 0.0)
            pct_diff = (
                abs(local_price - broker_price) / local_price
                if local_price > 0
                else 0.0
            )

            if pct_diff > 0.05:
                severity = SeverityLevel.HIGH
                requires_freeze = True
                risk_estimate = (
                    f"Severe entry price mismatch of {pct_diff * 100:.2f}% for {asset}. "
                    f"Local: {local_price}, Broker: {broker_price}. "
                    "Distorts stop-loss, profit-target, and risk calculations. Asset frozen."
                )
            elif pct_diff > 0.01:
                severity = SeverityLevel.MEDIUM
                requires_freeze = False
                risk_estimate = (
                    f"Moderate price mismatch of {pct_diff * 100:.2f}% for {asset}. "
                    "May lead to minor deviations in performance tracking."
                )
            else:
                severity = SeverityLevel.LOW
                requires_freeze = False
                risk_estimate = f"Minor price mismatch for {asset} within acceptable noise thresholds."

        elif dtype == DiscrepancyType.ORPHANED_TRADE:
            severity = SeverityLevel.HIGH
            requires_freeze = False
            risk_estimate = (
                f"Orphaned trade {details.get('trade_id')} found in local ledger without associated position. "
                "Indicates potential trade leakage or booking failure. Needs audit."
            )

        elif dtype == DiscrepancyType.LEDGER_INCONSISTENCY:
            severity = SeverityLevel.HIGH
            requires_freeze = True
            risk_estimate = (
                "Local ledger accounting is inconsistent. "
                f"Detail: {details.get('message', 'balance mismatch')}. "
                "Freezing strategy to protect capital and prevent corrupted trade triggers."
            )

        elif dtype == DiscrepancyType.REJECTED_ORDER:
            severity = SeverityLevel.HIGH
            requires_freeze = False
            risk_estimate = (
                f"Order {details.get('order_id')} rejected by broker. "
                f"Reason: {details.get('reason', 'unknown')}. "
                "Missed execution. Action required to verify strategy logic."
            )

        elif dtype == DiscrepancyType.PARTIAL_FILL:
            severity = SeverityLevel.MEDIUM
            requires_freeze = False
            risk_estimate = (
                f"Order {details.get('order_id')} is partially filled. "
                f"Filled: {details.get('filled_qty')}/{details.get('total_qty')}. "
                "Requires monitoring. System will re-sync on completion or cancellation."
            )

        elif dtype == DiscrepancyType.CANCELLED_ORDER:
            severity = SeverityLevel.LOW
            requires_freeze = False
            risk_estimate = f"Order {details.get('order_id')} was cancelled on the broker."

        elif dtype == DiscrepancyType.STATUS_MISMATCH:
            severity = SeverityLevel.MEDIUM
            requires_freeze = False
            risk_estimate = (
                f"Status mismatch for {asset}. "
                f"Local: {details.get('local_status')}, Broker: {details.get('broker_status')}. "
                "Requires cache refresh or state re-sync."
            )

        return Discrepancy(
            discrepancy_id=discrepancy_id,
            type=dtype,
            asset=asset,
            severity=severity,
            details=details,
            risk_estimate=risk_estimate,
            requires_freeze=requires_freeze,
        )
