from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class BrainMetadata:
    """Canonical metadata for the Portable Hokage Brain."""

    brain_id: UUID
    brain_name: str
    owner_name: str
    display_name: str
    brain_role: str
    brain_type: str = "PRIMARY"
    parent_brain_id: UUID | None = None
    brain_generation: int = 0
    schema_version: int = 1
    created_at: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    brain_fingerprint: str = ""

    def to_dict(self) -> dict:
        return {
            "brain_id": str(self.brain_id),
            "brain_name": self.brain_name,
            "owner_name": self.owner_name,
            "display_name": self.display_name,
            "brain_role": self.brain_role,
            "brain_type": self.brain_type,
            "parent_brain_id": str(self.parent_brain_id) if self.parent_brain_id else None,
            "brain_generation": self.brain_generation,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "brain_fingerprint": self.brain_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BrainMetadata:
        parent_id = data.get("parent_brain_id")
        return cls(
            brain_id=UUID(data["brain_id"]),
            brain_name=data["brain_name"],
            owner_name=data["owner_name"],
            display_name=data["display_name"],
            brain_role=data["brain_role"],
            brain_type=data.get("brain_type", "PRIMARY"),
            parent_brain_id=UUID(parent_id) if parent_id else None,
            brain_generation=data["brain_generation"],
            schema_version=data["schema_version"],
            created_at=data["created_at"],
            brain_fingerprint=data.get("brain_fingerprint", ""),
        )
