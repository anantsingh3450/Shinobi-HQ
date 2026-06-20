"""Execution Bot application service.

Thin orchestrator — contains no business logic. Delegates to an injected
ExecutionEngine and optionally persists via an injected TradeStore.
"""
from __future__ import annotations

from bots.execution.interfaces import ExecutionEngine, TradeStore
from bots.execution.models import TradeRecord
from bots.strategy.models import StrategyProposal


class ExecutionBot:
    """Executes a StrategyProposal and optionally persists the resulting trade.

    The bot depends on injected adapters and follows clean-architecture
    boundaries: domain models in ``models.py``, ports in ``interfaces.py``,
    orchestration here.

    Example:
        >>> from bots.execution import ExecutionBot
        >>> bot = ExecutionBot(engine=paper_engine, store=trade_store)
        >>> trade = bot.execute(proposal)
    """

    def __init__(
        self,
        engine: ExecutionEngine,
        store: TradeStore | None = None,
    ) -> None:
        """Configure the Execution Bot.

        Args:
            engine: Adapter that converts a StrategyProposal into a TradeRecord.
            store:  Optional persistence adapter. If None, trades are not saved.
        """
        self._engine = engine
        self._store = store

    @property
    def engine(self) -> ExecutionEngine:
        """The configured execution engine."""
        return self._engine

    def execute(
        self,
        proposal: StrategyProposal,
        *,
        persist: bool = True,
    ) -> TradeRecord:
        """Execute a strategy proposal and return the resulting trade.

        Args:
            proposal: The strategy to execute.
            persist:  When True and a store is configured, save the trade.

        Returns:
            The completed TradeRecord.
        """
        trade = self._engine.execute(proposal)

        if persist and self._store is not None:
            self._store.save(trade)

        return trade
