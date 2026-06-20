"""Hokage Orchestrator — drives the bot pipeline.

Wires all bots together and exposes named pipeline methods that the
CommandRouter calls. No business logic lives here.
"""
from __future__ import annotations

from pathlib import Path

from bots.backtest.backtest_bot import BacktestBot
from bots.backtest.engine.simple_backtest_engine import HeuristicBacktestEngine
from bots.execution.engine.paper_engine import PaperEngine
from bots.execution.execution_bot import ExecutionBot
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.portfolio.portfolio_bot import PortfolioBot
from bots.portfolio.store import JsonPortfolioStore
from bots.research.models import ResearchQuery
from bots.research.research_bot import ResearchBot
from bots.risk.risk_bot import RiskBot
from bots.risk.rules import (
    CompositeRiskManager,
    MaxDrawdownRiskRule,
    MaxPositionSizeRiskRule,
)
from bots.strategy.generators import HeuristicStrategyGenerator
from bots.strategy.strategy_bot import StrategyBot
from integrations.data.dummy_source import DummyResearchSource
from integrations.data.factory import ProviderFactory

_PAPER_TRADES_DIR = Path("data/paper_trades")
_PORTFOLIO_DIR = Path("data/portfolio")
_PAPER_ACCOUNT_ID = "paper"


class HokageOrchestrator:
    """Core workflow engine that drives the bot pipeline."""

    def __init__(self) -> None:
        """Initialize orchestrator with all configured bots."""
        # Research phase
        self.research_bot = ResearchBot(sources=[DummyResearchSource()])

        # Strategy phase — generator injected via DI
        self.strategy_bot = StrategyBot(generator=HeuristicStrategyGenerator())

        # Backtest phase — engine injected via DI
        self.backtest_bot = BacktestBot(engine=HeuristicBacktestEngine())

        # Risk phase — manager injected via DI
        self.risk_bot = RiskBot(
            manager=CompositeRiskManager(
                [
                    MaxDrawdownRiskRule(),
                    MaxPositionSizeRiskRule(),
                ]
            )
        )

        # Shared market data provider for execution and risk entry price
        self.price_source = ProviderFactory.create_market_data_provider()

        # Execution phase — engine and store injected via DI
        self.execution_bot = ExecutionBot(
            engine=PaperEngine(price_source=self.price_source),
            store=JsonTradeStore(_PAPER_TRADES_DIR),
        )

        # Portfolio persistence
        self.portfolio_store = JsonPortfolioStore(_PORTFOLIO_DIR)

    # ------------------------------------------------------------------
    # Pipeline: Research → Strategy
    # ------------------------------------------------------------------

    def execute_research_to_strategy(self, query_text: str) -> dict:
        """Run Research → Strategy and return a formatted StrategyProposal dict.

        Preserved for backward compatibility with the existing ``research``
        command. Does not invoke ExecutionBot.

        Args:
            query_text: The natural language research query.

        Returns:
            Dictionary of StrategyProposal fields for CLI display.
        """
        query = ResearchQuery(text=query_text)
        report = self.research_bot.research(query, persist=False)
        proposal = self.strategy_bot.generate(report)

        return {
            "name": proposal.name,
            "market": proposal.market,
            "description": proposal.description,
            "entry_rule": proposal.entry_rule,
            "exit_rule": proposal.exit_rule,
            "stop_loss_rule": proposal.stop_loss_rule,
            "take_profit_rule": proposal.take_profit_rule,
            "timeframe": proposal.timeframe,
            "confidence_score": proposal.confidence_score,
            "sources_cited": ", ".join(proposal.sources_cited),
        }

    # ------------------------------------------------------------------
    # Pipeline: Research → Strategy → PaperExecution → TradeStore
    # ------------------------------------------------------------------

    def execute_paper_trade(self, query_text: str) -> dict:
        """Run the full pipeline: Research → Strategy → PaperExecution.

        Persists the resulting TradeRecord to data/paper_trades/trades.jsonl.

        Args:
            query_text: The natural language research query.

        Returns:
            Dictionary of TradeRecord fields for CLI display.
        """
        # 1. Research
        query = ResearchQuery(text=query_text)
        report = self.research_bot.research(query, persist=False)

        # 2. Strategy
        proposal = self.strategy_bot.generate(report)

        # 3. Paper execution + persistence
        trade = self.execution_bot.execute(proposal, persist=True)

        return {
            "trade_id": trade.trade_id,
            "proposal_id": trade.proposal_id,
            "market": trade.market,
            "direction": trade.direction.value,
            "quantity": trade.quantity,
            "entry_price": trade.entry_price,
            "simulated_value": trade.simulated_value,
            "status": trade.status.value,
            "mode": trade.mode.value,
            "strategy_name": trade.strategy_name,
            "sources_cited": ", ".join(trade.sources_cited),
            "executed_at": trade.executed_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Pipeline: Research → Strategy → Backtest → Risk → Execution → Portfolio
    # ------------------------------------------------------------------

    def execute_full_pipeline(self, query_text: str) -> dict:
        """Run the full pipeline: Research → Strategy → Backtest → Risk → Execution → Portfolio.

        Validates the strategy against historical data and risk policies before
        execution. After the trade executes, updates and persists the paper
        account state.

        Args:
            query_text: The natural language research query.

        Returns:
            Dictionary with backtest, risk, and trade result fields for CLI display.

        Raises:
            ValueError: If the backtest or risk check fails.
        """
        # 1. Research
        query = ResearchQuery(text=query_text)
        report = self.research_bot.research(query, persist=False)

        # 2. Strategy
        proposal = self.strategy_bot.generate(report)

        # 3. Backtest
        backtest_result = self.backtest_bot.validate_strategy(proposal)
        if not backtest_result.passed:
            raise ValueError(
                f"Backtest failed: {backtest_result.summary}. "
                f"Win rate={backtest_result.win_rate}%, "
                f"Drawdown={backtest_result.max_drawdown}%."
            )

        # 4. Risk
        entry_price = self.price_source.get_price(proposal.market)
        account = self.portfolio_store.load_account(_PAPER_ACCOUNT_ID)
        risk_verdict = self.risk_bot.check_proposal(account, proposal, entry_price)
        if not risk_verdict.is_approved:
            raise ValueError(f"Risk check failed: {risk_verdict.reason}")

        # 5. Paper execution + persistence
        trade = self.execution_bot.execute(proposal, persist=True)

        # 6. Portfolio update
        portfolio_bot = PortfolioBot(account)
        portfolio_bot.apply_trade(trade)
        self.portfolio_store.save_account(account)

        return {
            # Backtest results
            "backtest_passed": backtest_result.passed,
            "total_trades": backtest_result.total_trades,
            "win_rate": backtest_result.win_rate,
            "net_profit": backtest_result.net_profit,
            "max_drawdown": backtest_result.max_drawdown,
            "profit_factor": backtest_result.profit_factor,
            "backtest_summary": backtest_result.summary,
            "risk_approved": risk_verdict.is_approved,
            "risk_reason": risk_verdict.reason,
            # Trade results
            "trade_id": trade.trade_id,
            "proposal_id": trade.proposal_id,
            "market": trade.market,
            "direction": trade.direction.value,
            "quantity": trade.quantity,
            "entry_price": trade.entry_price,
            "simulated_value": trade.simulated_value,
            "status": trade.status.value,
            "mode": trade.mode.value,
            "strategy_name": trade.strategy_name,
            "sources_cited": ", ".join(trade.sources_cited),
            "executed_at": trade.executed_at.isoformat(),
        }
