"""Backward-compatible mock price source.

MockPriceSource now delegates to MockMarketDataProvider so Phase 1 paper
execution and Phase 3B market data share one deterministic price table.
"""
from __future__ import annotations

from integrations.data.mock_provider import MockMarketDataProvider


class MockPriceSource(MockMarketDataProvider):
    """Compatibility wrapper for code that imports the old price source."""

