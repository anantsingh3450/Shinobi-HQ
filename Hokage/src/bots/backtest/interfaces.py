"""Interfaces for BacktestBot.

Defines the contract that all backtest engines must implement.
"""

from __future__ import annotations

from typing import Protocol

from bots.backtest.models import BacktestResult
from bots.strategy.models import StrategyProposal


class BacktestEngine(Protocol):
    """Contract for any backtest implementation."""

    def run_backtest(
        self,
        proposal: StrategyProposal,
    ) -> BacktestResult:
        """Execute a backtest and return the result."""
