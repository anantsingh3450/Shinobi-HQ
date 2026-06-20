"""Simple heuristic backtest engine.

Provides a deterministic MVP implementation for validating
StrategyProposal objects before RiskBot and ExecutionBot.
"""

from __future__ import annotations

from bots.backtest.interfaces import BacktestEngine
from bots.backtest.models import BacktestResult
from bots.strategy.models import StrategyProposal


class HeuristicBacktestEngine(BacktestEngine):
    """Simple deterministic backtest implementation."""

    def run_backtest(
        self,
        proposal: StrategyProposal,
    ) -> BacktestResult:
        """Generate a repeatable backtest result from proposal confidence."""

        confidence = proposal.confidence_score

        total_trades = max(10, int(confidence * 100))

        win_rate = round(40 + (confidence * 40), 2)

        net_profit = round((confidence - 0.5) * 10000, 2)

        max_drawdown = round(max(5.0, 30 - (confidence * 20)), 2)

        profit_factor = round(1.0 + confidence, 2)

        passed = (
            win_rate >= 50
            and net_profit > 0
            and max_drawdown < 20
        )

        summary = (
            f"Backtest completed for {proposal.name}. "
            f"Win Rate={win_rate}%, "
            f"Net Profit={net_profit}, "
            f"Drawdown={max_drawdown}%."
        )

        return BacktestResult(
            proposal_id=proposal.proposal_id,
            total_trades=total_trades,
            win_rate=win_rate,
            net_profit=net_profit,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            passed=passed,
            summary=summary,
        )