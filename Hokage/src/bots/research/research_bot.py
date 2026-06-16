"""Research Bot application service.

Orchestrates the research pipeline: accept a query, search configured sources,
filter and deduplicate findings, synthesize a structured report, and optionally
persist the result to ``data/research/``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from bots.research.interfaces import ReportWriter, ResearchSource, ResearchSynthesizer
from bots.research.models import ResearchFinding, ResearchQuery, ResearchReport, utc_now


class DefaultResearchSynthesizer:
    """Default synthesizer that builds an executive summary from top findings.

    This implementation is deterministic and requires no LLM integration.
    Replace or wrap with an LLM-backed synthesizer via ``integrations/llm/``
    when richer narrative synthesis is needed.
    """

    def synthesize(
        self,
        query: ResearchQuery,
        findings: tuple[ResearchFinding, ...],
        *,
        metadata: dict[str, str] | None = None,
    ) -> ResearchReport:
        """Build a report with an executive summary derived from findings."""
        if not findings:
            executive_summary = (
                f"No findings were collected for query: {query.text.strip()}"
            )
        else:
            headline_titles = ", ".join(finding.title for finding in findings[:3])
            executive_summary = (
                f"Research on '{query.text.strip()}' identified "
                f"{len(findings)} finding(s). Key themes: {headline_titles}."
            )

        report_metadata = dict(metadata or {})
        report_metadata.setdefault("synthesizer", "default")
        report_metadata["finding_count"] = str(len(findings))

        return ResearchReport(
            query=query,
            findings=findings,
            executive_summary=executive_summary,
            generated_at=utc_now(),
            metadata=report_metadata,
        )


class JsonReportWriter:
    """Writes ``ResearchReport`` artifacts as JSON files under a directory."""

    def __init__(self, output_directory: Path) -> None:
        """Initialize the writer.

        Args:
            output_directory: Target folder (typically ``data/research/``).
        """
        self._output_directory = output_directory

    @property
    def output_directory(self) -> Path:
        """Directory where report files are written."""
        return self._output_directory

    def write(self, report: ResearchReport) -> Path:
        """Persist the report as ``{report_id}.json``."""
        self._output_directory.mkdir(parents=True, exist_ok=True)
        output_path = self._output_directory / f"{report.report_id}.json"
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output_path


class ResearchBot:
    """Gathers and synthesizes market and domain intelligence.

    The bot depends on injected ``ResearchSource`` adapters (configured at
    runtime) and follows clean-architecture boundaries: domain models in
    ``models.py``, ports in ``interfaces.py``, orchestration here.

    Example:
        >>> from bots.research import ResearchBot, ResearchQuery
        >>> bot = ResearchBot(sources=[my_market_source, my_news_source])
        >>> report = bot.research(ResearchQuery(text="EUR/USD macro outlook"))
    """

    def __init__(
        self,
        sources: Sequence[ResearchSource],
        *,
        report_writer: ReportWriter | None = None,
        synthesizer: ResearchSynthesizer | None = None,
        min_relevance_score: float = 0.0,
        max_findings: int = 20,
    ) -> None:
        """Configure the Research Bot.

        Args:
            sources: Ordered collection of search adapters to consult.
            report_writer: Optional persistence adapter for ``data/research/``.
            synthesizer: Report builder; defaults to ``DefaultResearchSynthesizer``.
            min_relevance_score: Findings below this score are discarded.
            max_findings: Maximum findings retained after ranking.
        """
        if not sources:
            raise ValueError("At least one research source must be configured.")
        if not 0.0 <= min_relevance_score <= 1.0:
            raise ValueError("min_relevance_score must be between 0.0 and 1.0.")
        if max_findings < 1:
            raise ValueError("max_findings must be at least 1.")

        self._sources = tuple(sources)
        self._report_writer = report_writer
        self._synthesizer = synthesizer or DefaultResearchSynthesizer()
        self._min_relevance_score = min_relevance_score
        self._max_findings = max_findings

    @property
    def sources(self) -> tuple[ResearchSource, ...]:
        """Configured research sources."""
        return self._sources

    def research(
        self,
        query: ResearchQuery,
        *,
        persist: bool = True,
    ) -> ResearchReport:
        """Execute the full research pipeline for a query.

        Steps:
            1. Consult each configured source up to ``query.max_sources``.
            2. Merge, filter, deduplicate, and rank findings.
            3. Synthesize a structured ``ResearchReport``.
            4. Optionally persist via the configured ``ReportWriter``.

        Args:
            query: The research request to process.
            persist: When ``True`` and a writer is configured, save the report.

        Returns:
            The completed research report.
        """
        active_sources = self._sources[: query.max_sources]
        collected = self._collect_findings(query, active_sources)
        filtered = self._filter_findings(collected)
        ranked = self._rank_findings(filtered)
        deduplicated = self._deduplicate_findings(ranked)
        trimmed = deduplicated[: self._max_findings]

        metadata = {
            "sources_consulted": str(len(active_sources)),
            "sources_available": str(len(self._sources)),
            "raw_finding_count": str(len(collected)),
        }

        report = self._synthesizer.synthesize(
            query,
            trimmed,
            metadata=metadata,
        )

        if persist and self._report_writer is not None:
            output_path = self._report_writer.write(report)
            enriched_metadata = dict(report.metadata)
            enriched_metadata["output_path"] = str(output_path)
            report = ResearchReport(
                query=report.query,
                findings=report.findings,
                executive_summary=report.executive_summary,
                generated_at=report.generated_at,
                report_id=report.report_id,
                metadata=enriched_metadata,
            )

        return report

    def _collect_findings(
        self,
        query: ResearchQuery,
        sources: Sequence[ResearchSource],
    ) -> tuple[ResearchFinding, ...]:
        """Gather raw findings from each source."""
        findings: list[ResearchFinding] = []
        for source in sources:
            findings.extend(source.search(query))
        return tuple(findings)

    def _filter_findings(
        self,
        findings: Sequence[ResearchFinding],
    ) -> tuple[ResearchFinding, ...]:
        """Drop findings below the configured relevance threshold."""
        return tuple(
            finding
            for finding in findings
            if finding.relevance_score >= self._min_relevance_score
        )

    @staticmethod
    def _rank_findings(
        findings: Sequence[ResearchFinding],
    ) -> tuple[ResearchFinding, ...]:
        """Sort findings by descending relevance."""
        return tuple(
            sorted(findings, key=lambda finding: finding.relevance_score, reverse=True)
        )

    @staticmethod
    def _deduplicate_findings(
        findings: Sequence[ResearchFinding],
    ) -> tuple[ResearchFinding, ...]:
        """Remove duplicate titles, keeping the highest-scored occurrence."""
        seen: set[str] = set()
        unique: list[ResearchFinding] = []
        for finding in findings:
            key = finding.title.strip().casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)
        return tuple(unique)
