"""Unit tests for the Research Bot application service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bots.research.models import ResearchFinding, ResearchQuery, ResearchReport
from bots.research.research_bot import (
    DefaultResearchSynthesizer,
    JsonReportWriter,
    ResearchBot,
)
from tests.conftest import MockResearchSource, make_finding


class TestDefaultResearchSynthesizer:
    def test_synthesizes_executive_summary_from_findings(
        self,
        sample_query: ResearchQuery,
        sample_finding: ResearchFinding,
    ) -> None:
        synthesizer = DefaultResearchSynthesizer()
        report = synthesizer.synthesize(sample_query, (sample_finding,))

        assert "EUR/USD macro outlook" in report.executive_summary
        assert report.findings == (sample_finding,)
        assert report.metadata["finding_count"] == "1"

    def test_handles_empty_findings(self, sample_query: ResearchQuery) -> None:
        synthesizer = DefaultResearchSynthesizer()
        report = synthesizer.synthesize(sample_query, ())

        assert "No findings were collected" in report.executive_summary
        assert report.metadata["finding_count"] == "0"


class TestJsonReportWriter:
    def test_writes_json_file(self, tmp_path: Path, sample_query: ResearchQuery) -> None:
        writer = JsonReportWriter(tmp_path)
        report = ResearchReport(
            query=sample_query,
            findings=(),
            executive_summary="Empty report.",
        )

        output_path = writer.write(report)

        assert output_path.exists()
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["report_id"] == report.report_id
        assert payload["executive_summary"] == "Empty report."


class TestResearchBot:
    def test_research_collects_from_configured_sources(
        self,
        mock_source: MockResearchSource,
        sample_query: ResearchQuery,
    ) -> None:
        bot = ResearchBot(sources=[mock_source], report_writer=None)
        report = bot.research(sample_query, persist=False)

        assert len(report.findings) == 1
        assert report.findings[0].title == "ECB rate path stabilizes EUR"
        assert mock_source.queries_seen == (sample_query,)

    def test_research_respects_max_sources_limit(self, sample_query: ResearchQuery) -> None:
        sources = [
            MockResearchSource(
                _source_id=f"source-{index}",
                _name=f"Source {index}",
                findings=(make_finding(f"Finding {index}", relevance_score=0.5 + index * 0.1),),
            )
            for index in range(3)
        ]
        bot = ResearchBot(sources=sources)
        query = ResearchQuery(text=sample_query.text, max_sources=2)

        report = bot.research(query, persist=False)

        assert report.metadata["sources_consulted"] == "2"
        assert len(report.findings) == 2

    def test_research_filters_by_relevance(self, sample_query: ResearchQuery) -> None:
        source = MockResearchSource(
            _source_id="mixed",
            _name="Mixed",
            findings=(
                make_finding("High relevance", relevance_score=0.9),
                make_finding("Low relevance", relevance_score=0.2),
            ),
        )
        bot = ResearchBot(sources=[source], min_relevance_score=0.5)

        report = bot.research(sample_query, persist=False)

        assert [finding.title for finding in report.findings] == ["High relevance"]

    def test_research_deduplicates_by_title(self, sample_query: ResearchQuery) -> None:
        source = MockResearchSource(
            _source_id="dup",
            _name="Duplicate",
            findings=(
                make_finding("Shared Theme", relevance_score=0.95),
                make_finding("shared theme", relevance_score=0.5),
                make_finding("Unique Theme", relevance_score=0.7),
            ),
        )
        bot = ResearchBot(sources=[source])

        report = bot.research(sample_query, persist=False)

        assert [finding.title for finding in report.findings] == [
            "Shared Theme",
            "Unique Theme",
        ]

    def test_research_ranks_by_relevance_descending(self, sample_query: ResearchQuery) -> None:
        source = MockResearchSource(
            _source_id="rank",
            _name="Rank",
            findings=(
                make_finding("Medium", relevance_score=0.6),
                make_finding("High", relevance_score=0.95),
                make_finding("Low", relevance_score=0.4),
            ),
        )
        bot = ResearchBot(sources=[source], min_relevance_score=0.0)

        report = bot.research(sample_query, persist=False)

        scores = [finding.relevance_score for finding in report.findings]
        assert scores == sorted(scores, reverse=True)

    def test_research_persists_when_writer_configured(
        self,
        tmp_path: Path,
        mock_source: MockResearchSource,
        sample_query: ResearchQuery,
    ) -> None:
        writer = JsonReportWriter(tmp_path)
        bot = ResearchBot(sources=[mock_source], report_writer=writer)

        report = bot.research(sample_query)

        assert "output_path" in report.metadata
        output_path = Path(report.metadata["output_path"])
        assert output_path.exists()

    def test_research_skips_persistence_when_disabled(
        self,
        tmp_path: Path,
        mock_source: MockResearchSource,
        sample_query: ResearchQuery,
    ) -> None:
        writer = JsonReportWriter(tmp_path)
        bot = ResearchBot(sources=[mock_source], report_writer=writer)

        report = bot.research(sample_query, persist=False)

        assert "output_path" not in report.metadata
        assert list(tmp_path.glob("*.json")) == []

    def test_requires_at_least_one_source(self) -> None:
        with pytest.raises(ValueError, match="At least one research source"):
            ResearchBot(sources=[])

    def test_rejects_invalid_min_relevance_score(self, mock_source: MockResearchSource) -> None:
        with pytest.raises(ValueError, match="min_relevance_score"):
            ResearchBot(sources=[mock_source], min_relevance_score=1.5)

    def test_rejects_invalid_max_findings(self, mock_source: MockResearchSource) -> None:
        with pytest.raises(ValueError, match="max_findings"):
            ResearchBot(sources=[mock_source], max_findings=0)

    def test_merges_findings_from_multiple_sources(self, sample_query: ResearchQuery) -> None:
        sources = [
            MockResearchSource(
                _source_id="news",
                _name="News",
                findings=(make_finding("News finding", relevance_score=0.8),),
            ),
            MockResearchSource(
                _source_id="data",
                _name="Data",
                findings=(make_finding("Data finding", relevance_score=0.7),),
            ),
        ]
        bot = ResearchBot(sources=sources)

        report = bot.research(sample_query, persist=False)

        assert len(report.findings) == 2
        assert report.metadata["raw_finding_count"] == "2"
