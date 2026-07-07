"""Domain models for the Research Bot.

These dataclasses define the core vocabulary of the research pipeline. They are
pure data structures with no external dependencies, suitable for use as the
``ResearchReport`` contract consumed by Strategy Bot and Hokage orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4
from shared.utils import utc_now


@dataclass(frozen=True, slots=True)
class ResearchQuery:
    """A research request submitted to the Research Bot.

    Attributes:
        text: Primary natural-language research question or topic.
        topics: Optional explicit topic tags that narrow the search scope.
        context: Additional key-value context (e.g. prior improvement notes).
        max_sources: Upper bound on distinct sources consulted for this query.
    """

    text: str
    topics: tuple[str, ...] = ()
    context: dict[str, str] = field(default_factory=dict)
    max_sources: int = 5

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Research query text must not be empty.")
        if self.max_sources < 1:
            raise ValueError("max_sources must be at least 1.")


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Metadata identifying where a finding was retrieved from.

    Attributes:
        source_id: Stable identifier for the integration adapter.
        name: Human-readable source name.
        url: Optional canonical URL for the retrieved content.
        retrieved_at: UTC timestamp when the content was fetched.
    """

    source_id: str
    name: str
    retrieved_at: datetime
    url: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty.")
        if not self.name.strip():
            raise ValueError("source name must not be empty.")


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    """A single piece of intelligence collected from one or more sources.

    Attributes:
        title: Short headline describing the finding.
        summary: One-paragraph overview suitable for quick scanning.
        details: Extended narrative or supporting evidence.
        relevance_score: Normalized relevance to the query in ``[0.0, 1.0]``.
        sources: Provenance records for this finding.
        tags: Optional categorical labels (e.g. ``"macro"``, ``"equity"``).
    """

    title: str
    summary: str
    details: str
    relevance_score: float
    sources: tuple[SourceReference, ...]
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("finding title must not be empty.")
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0.0 and 1.0.")
        if not self.sources:
            raise ValueError("each finding must cite at least one source.")


@dataclass(frozen=True, slots=True)
class ResearchReport:
    """Structured output of the Research Bot for downstream consumers.

    This is the canonical handoff artifact written to ``data/research/`` and
    consumed by Strategy Bot via Hokage orchestration.

    Attributes:
        report_id: Unique identifier for this report instance.
        query: The original research request.
        findings: Ranked, deduplicated findings collected from sources.
        executive_summary: High-level synthesis across all findings.
        generated_at: UTC timestamp when the report was produced.
        metadata: Optional pipeline metadata (e.g. source counts, bot version).
    """

    query: ResearchQuery
    findings: tuple[ResearchFinding, ...]
    executive_summary: str
    generated_at: datetime = field(default_factory=utc_now)
    report_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.executive_summary.strip():
            raise ValueError("executive_summary must not be empty.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a JSON-compatible dictionary."""
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "executive_summary": self.executive_summary,
            "metadata": dict(self.metadata),
            "query": {
                "text": self.query.text,
                "topics": list(self.query.topics),
                "context": dict(self.query.context),
                "max_sources": self.query.max_sources,
            },
            "findings": [
                {
                    "title": finding.title,
                    "summary": finding.summary,
                    "details": finding.details,
                    "relevance_score": finding.relevance_score,
                    "tags": list(finding.tags),
                    "sources": [
                        {
                            "source_id": source.source_id,
                            "name": source.name,
                            "url": source.url,
                            "retrieved_at": source.retrieved_at.isoformat(),
                        }
                        for source in finding.sources
                    ],
                }
                for finding in self.findings
            ],
        }
