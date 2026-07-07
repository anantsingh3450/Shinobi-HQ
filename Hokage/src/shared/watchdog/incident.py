from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

logger = logging.getLogger("Hokage.Watchdog.Incident")


@dataclass
class Incident:
    """An immutable incident record created by the Watchdog upon failure detection."""
    incident_id: str
    timestamp: datetime
    severity: str  # INFO, WARNING, HIGH, CRITICAL, FATAL
    subsystem: str
    root_cause: str
    detected_by: str
    automatic_actions: str
    recommended_actions: str
    commander_acknowledgement: bool
    resolution: str  # e.g. "RESOLVED", "UNRESOLVED", "RESTARTED", "WAITING_FOR_COMMANDER"
    duration: float | None = None  # in seconds, None if unresolved

    def to_dict(self) -> dict[str, any]:
        """Convert Incident instance to a serializable dictionary."""
        return {
            "incident_id": self.incident_id,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity,
            "subsystem": self.subsystem,
            "root_cause": self.root_cause,
            "detected_by": self.detected_by,
            "automatic_actions": self.automatic_actions,
            "recommended_actions": self.recommended_actions,
            "commander_acknowledgement": 1 if self.commander_acknowledgement else 0,
            "resolution": self.resolution,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, any]) -> Incident:
        """Construct Incident instance from a dictionary."""
        ack = data.get("commander_acknowledgement", 0)
        return cls(
            incident_id=data["incident_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            severity=data["severity"],
            subsystem=data["subsystem"],
            root_cause=data["root_cause"],
            detected_by=data["detected_by"],
            automatic_actions=data["automatic_actions"],
            recommended_actions=data["recommended_actions"],
            commander_acknowledgement=bool(ack),
            resolution=data["resolution"],
            duration=float(data["duration"]) if data.get("duration") is not None else None,
        )


class IncidentJournal:
    """Manages the lifecycle of immutable incidents. Never deletes incidents."""

    @staticmethod
    def create_incident(
        severity: str,
        subsystem: str,
        root_cause: str,
        detected_by: str = "Watchdog",
        automatic_actions: str = "None",
        recommended_actions: str = "Inspect logs and verify subsystem connectivity.",
    ) -> Incident:
        """Helper to instantiate a new incident with a unique ID."""
        return Incident(
            incident_id=f"inc-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            severity=severity.upper(),
            subsystem=subsystem,
            root_cause=root_cause,
            detected_by=detected_by,
            automatic_actions=automatic_actions,
            recommended_actions=recommended_actions,
            commander_acknowledgement=False,
            resolution="UNRESOLVED",
            duration=None,
        )
