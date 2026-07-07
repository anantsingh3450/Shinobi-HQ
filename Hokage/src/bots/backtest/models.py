"""Domain models for BacktestBot.

These models represent the result of validating a StrategyProposal
against historical data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from shared.utils import utc_now


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

    market: str = ""
    timeframe: str = ""
    start: datetime | None = None
    end: datetime | None = None
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    after_tax_net_profit: float | None = None
    tax_estimate: float | None = None
    equity_curve: tuple[float, ...] = field(default_factory=tuple)
    provider: str = "heuristic"
    generated_at: datetime = field(default_factory=utc_now)
