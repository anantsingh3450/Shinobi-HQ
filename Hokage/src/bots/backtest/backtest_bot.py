"""Backtest Bot orchestration service.

Delegates strategy validation to an injected BacktestEngine.
"""

from __future__ import annotations

from bots.backtest.interfaces import BacktestEngine
from bots.backtest.models import BacktestResult
from bots.strategy.models import StrategyProposal


class BacktestBot:
    """Orchestrates strategy validation."""

    def __init__(self, engine: BacktestEngine) -> None:
        """Initialize with a backtest engine."""
        self._engine = engine

    @property
    def engine(self) -> BacktestEngine:
        """Configured backtest engine."""
        return self._engine

    def validate_strategy(
        self,
        proposal: StrategyProposal,
    ) -> BacktestResult:
        """Run a backtest and return the result."""
        return self._engine.run_backtest(proposal)