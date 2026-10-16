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
# NEVER send real Telegram messages from tests. Also scrub any real telegram
# credentials that leaked into the process environment (e.g. developer shell).
_os.environ.setdefault("HOKAGE_DISABLE_TELEGRAM", "true")
# NEVER ping the dead man's switch from tests. Its URL is a capability token:
# a forged heartbeat would turn the real watch off silently, and a test that
# reached it would do exactly that.
_os.environ.setdefault("HOKAGE_DISABLE_DEADMAN", "true")
_os.environ.pop("HOKAGE_DEADMAN_URL", None)
_os.environ.pop("TELEGRAM_BOT_TOKEN", None)
_os.environ.pop("TELEGRAM_CHAT_ID", None)
# Sandbox the ENTIRE brain for the suite. PathResolver defaults to the
# CWD-relative "hokage_brain" when no explicit root is passed, so any test
# building a default orchestrator/store used to write trades, positions, and
# audit rows straight into the PRODUCTION brain (2026-07-13 incident: pytest
# runs planted GBP/USD ghost positions in hokage.db that the live bot then
# tried to square off all evening). One throwaway root per test session.
import tempfile as _tempfile
_os.environ["HOKAGE_BRAIN_ROOT"] = _tempfile.mkdtemp(prefix="hokage_test_brain_")

# And close the .env fallback. brain_root() reads HOKAGE_BRAIN_ROOT from `.env`
# when the environment does not carry it, because the liveness probe, the prune
# tool, the candle archive and the weekly audit are launched by PowerShell and
# cron rather than through the bot's entry point. A test that clears the
# variable set above would otherwise fall through to `.env` and resolve the
# REAL brain -- the 2026-07-13 incident, reintroduced by another route.
#
# A config seam rather than environment detection inside src, which Project Law
# forbids (tests/test_no_mock_sniffing_in_src.py).
from hokage.memory import resolver as _resolver
_resolver.CONSULT_DOTENV = False

# Where the REAL brain lives, exported once for the handful of tests that
# legitimately need it: the hermeticity guard (which must know the address it
# is forbidding) and a few read-only tests that inspect live portfolio state.
#
# It has to be published here because the brain is relocatable. Those tests
# used to find it by walking up for a directory literally named
# `hokage_brain` — which stopped existing in the repo on 2026-10-09 when the
# brain moved to C:/Hokage, out of OneDrive. The whole suite then died at
# COLLECTION with a bare StopIteration, and the hermeticity guard would have
# gone on "passing" against a path that was no longer anything.
#
# Read straight from .env, because CONSULT_DOTENV was just switched off and
# HOKAGE_BRAIN_ROOT now points at the sandbox.
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent.parent
_env_file = _REPO_ROOT / ".env"
_configured = ""
if _env_file.exists():
    _configured = _resolver._parse_brain_root(
        _env_file.read_text(encoding="utf-8-sig")
    )
_os.environ["HOKAGE_PRODUCTION_BRAIN"] = str(
    _Path(_configured).resolve() if _configured
    else (_REPO_ROOT / "hokage_brain").resolve()
)
_os.environ["HOKAGE_REPO_ROOT"] = str(_REPO_ROOT)

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

