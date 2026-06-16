"""Port interfaces for Research Bot dependencies.

These protocols define the boundaries between the Research Bot application
layer and external infrastructure (data integrations, persistence, LLM
synthesis). Implementations live in ``integrations/`` or test doubles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from bots.research.models import ResearchFinding, ResearchQuery, ResearchReport


@runtime_checkable
class ResearchSource(Protocol):
    """Adapter that searches a configured external or internal data source.

    Each integration (market data, news, knowledge vault, etc.) implements
    this protocol and is injected into ``ResearchBot`` at construction time.
    """

    @property
    def source_id(self) -> str:
        """Stable identifier used in provenance and configuration."""

    @property
    def name(self) -> str:
        """Human-readable label for logs and report citations."""

    def search(self, query: ResearchQuery) -> tuple[ResearchFinding, ...]:
        """Collect findings relevant to the given query.

        Args:
            query: The research request to satisfy.

        Returns:
            Raw findings from this source. The bot handles ranking,
            deduplication, and synthesis across all sources.
        """


@runtime_checkable
class ResearchSynthesizer(Protocol):
    """Combines collected findings into a structured ``ResearchReport``."""

    def synthesize(
        self,
        query: ResearchQuery,
        findings: tuple[ResearchFinding, ...],
        *,
        metadata: dict[str, str] | None = None,
    ) -> ResearchReport:
        """Produce a final report from filtered findings.

        Args:
            query: The original research request.
            findings: Pre-filtered, ranked findings from all sources.
            metadata: Optional pipeline metadata to attach to the report.

        Returns:
            A complete ``ResearchReport`` ready for persistence or handoff.
        """


@runtime_checkable
class ReportWriter(Protocol):
    """Persists a ``ResearchReport`` to the configured output location."""

    def write(self, report: ResearchReport) -> Path:
        """Write the report and return the path of the persisted artifact.

        Args:
            report: The report to persist.

        Returns:
            Absolute or relative path to the written file.
        """
