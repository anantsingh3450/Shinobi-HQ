"""Domain models for BacktestBot.

These models represent the result of validating a StrategyProposal
against historical data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Result produced by a backtest run."""

    proposal_id: str

    total_trades: int

    win_rate: float

    net_profit: float

    max_drawdown: float

    profit_factor: float

    passed: bool

    summary: str