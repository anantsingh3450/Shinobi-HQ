"""Unit tests for Research Bot domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bots.research.models import (
    ResearchFinding,
    ResearchQuery,
    ResearchReport,
    SourceReference,
)
from tests.conftest import make_finding, make_source_reference


class TestResearchQuery:
    def test_valid_query(self) -> None:
        query = ResearchQuery(text="  Oil supply dynamics  ", topics=("energy",))
        assert query.text == "  Oil supply dynamics  "
        assert query.topics == ("energy",)
        assert query.max_sources == 5

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            ResearchQuery(text="   ")

    def test_rejects_invalid_max_sources(self) -> None:
        with pytest.raises(ValueError, match="max_sources"):
            ResearchQuery(text="valid", max_sources=0)


class TestSourceReference:
    def test_valid_reference(self) -> None:
        ref = make_source_reference()
        assert ref.source_id == "mock-source"
        assert ref.url == "https://example.com/article"

    def test_rejects_empty_source_id(self) -> None:
        with pytest.raises(ValueError, match="source_id"):
            SourceReference(
                source_id=" ",
                name="Name",
                retrieved_at=datetime.now(UTC),
            )


class TestResearchFinding:
    def test_valid_finding(self, sample_finding: ResearchFinding) -> None:
        assert sample_finding.relevance_score == 0.8
        assert len(sample_finding.sources) == 1

    def test_rejects_invalid_relevance(self) -> None:
        with pytest.raises(ValueError, match="relevance_score"):
            make_finding("Title", relevance_score=1.5)

    def test_rejects_missing_sources(self) -> None:
        with pytest.raises(ValueError, match="at least one source"):
            ResearchFinding(
                title="Title",
                summary="Summary",
                details="Details",
                relevance_score=0.5,
                sources=(),
            )


class TestResearchReport:
    def test_valid_report(self, sample_query: ResearchQuery, sample_finding: ResearchFinding) -> None:
        report = ResearchReport(
            query=sample_query,
            findings=(sample_finding,),
            executive_summary="Macro outlook remains constructive.",
        )
        assert report.findings == (sample_finding,)
        assert report.report_id

    def test_rejects_empty_executive_summary(
        self,
        sample_query: ResearchQuery,
        sample_finding: ResearchFinding,
    ) -> None:
        with pytest.raises(ValueError, match="executive_summary"):
            ResearchReport(
                query=sample_query,
                findings=(sample_finding,),
                executive_summary="  ",
            )

    def test_to_dict_serializes_nested_structures(
        self,
        sample_query: ResearchQuery,
        sample_finding: ResearchFinding,
    ) -> None:
        report = ResearchReport(
            query=sample_query,
            findings=(sample_finding,),
            executive_summary="Summary text.",
            metadata={"bot": "research"},
        )
        payload = report.to_dict()

        assert payload["query"]["text"] == sample_query.text
        assert payload["findings"][0]["title"] == sample_finding.title
        assert payload["metadata"]["bot"] == "research"
        assert "generated_at" in payload
