"""Shared pytest fixtures for Research Bot tests."""

from __future__ import annotations

# Force credential isolation for the whole suite via the production-supported
# config flag (NOT an in-production test sniff). SecretManager and other
# components honor HOKAGE_TEST_MODE=true to use isolated in-memory credentials
# instead of the real OS keyring. Set at conftest import so it is in effect
# before any SecretManager is constructed.
import os as _os
_os.environ.setdefault("HOKAGE_TEST_MODE", "true")
# Keep the suite hermetic: never let the mock data provider reach out to
# Binance/Yahoo public feeds during tests. Production leaves this unset.
_os.environ.setdefault("HOKAGE_DISABLE_PUBLIC_FEED", "true")
# Never make real external LLM (Gemini) calls during tests.
_os.environ.setdefault("HOKAGE_DISABLE_LLM", "true")

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

from integrations.brokers.models import OrderResponse, OrderStatus, OrderSide, OrderRequest

@pytest.fixture
def filled_order_response():
    def _factory(req: OrderRequest) -> OrderResponse:
        return OrderResponse(
            venue_order_id="TEST_ORDER_1",
            venue_id="paper_main",
            instrument=req.instrument,
            side=req.side,
            status=OrderStatus.FILLED,
            quantity=req.quantity,
            filled_quantity=req.quantity,
            average_price=req.price if req.price and req.price > 0 else 100.0,
        )
    return _factory

@pytest.fixture
def partial_order_response():
    def _factory(req: OrderRequest) -> OrderResponse:
        return OrderResponse(
            venue_order_id="TEST_ORDER_2",
            venue_id="paper_main",
            instrument=req.instrument,
            side=req.side,
            status=OrderStatus.PARTIALLY_FILLED,
            quantity=req.quantity,
            filled_quantity=req.quantity / 2.0,
            average_price=req.price if req.price and req.price > 0 else 100.0,
        )
    return _factory

@pytest.fixture
def rejected_order_response():
    def _factory(req: OrderRequest) -> OrderResponse:
        return OrderResponse(
            venue_order_id="TEST_ORDER_3",
            venue_id="paper_main",
            instrument=req.instrument,
            side=req.side,
            status=OrderStatus.REJECTED,
            quantity=req.quantity,
            filled_quantity=0.0,
            average_price=0.0,
            error_message="Insufficient margin"
        )
    return _factory

@pytest.fixture
def timeout_order_response():
    def _factory(req: OrderRequest) -> None:
        return None
    return _factory

