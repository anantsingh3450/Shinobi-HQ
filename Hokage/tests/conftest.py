"""Shared pytest fixtures for Research Bot tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from bots.research.models import ResearchFinding, ResearchQuery, SourceReference


@dataclass(frozen=True, slots=True)
class MockResearchSource:
    """Test double implementing the ``ResearchSource`` protocol."""

    _source_id: str
    _name: str
    findings: tuple[ResearchFinding, ...] = ()
    queries_seen: tuple[ResearchQuery, ...] = ()

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def name(self) -> str:
        return self._name

    def search(self, query: ResearchQuery) -> tuple[ResearchFinding, ...]:
        object.__setattr__(self, "queries_seen", self.queries_seen + (query,))
        return self.findings


def make_source_reference(
    source_id: str = "mock-source",
    name: str = "Mock Source",
) -> SourceReference:
    """Build a minimal valid ``SourceReference`` for tests."""
    return SourceReference(
        source_id=source_id,
        name=name,
        retrieved_at=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        url="https://example.com/article",
    )


def make_finding(
    title: str,
    *,
    relevance_score: float = 0.8,
    source_id: str = "mock-source",
) -> ResearchFinding:
    """Build a minimal valid ``ResearchFinding`` for tests."""
    return ResearchFinding(
        title=title,
        summary=f"Summary for {title}",
        details=f"Details for {title}",
        relevance_score=relevance_score,
        sources=(make_source_reference(source_id=source_id),),
        tags=("test",),
    )


@pytest.fixture
def sample_query() -> ResearchQuery:
    """A valid research query."""
    return ResearchQuery(
        text="EUR/USD macro outlook",
        topics=("forex", "macro"),
        context={"prior_note": "Focus on ECB policy"},
        max_sources=2,
    )


@pytest.fixture
def sample_finding() -> ResearchFinding:
    """A valid research finding."""
    return make_finding("ECB rate path stabilizes EUR")


@pytest.fixture
def mock_source(sample_finding: ResearchFinding) -> MockResearchSource:
    """A mock source returning one finding."""
    return MockResearchSource(
        _source_id="market-data",
        _name="Market Data",
        findings=(sample_finding,),
    )
