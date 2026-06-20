"""Port interfaces (protocols) for Execution Bot dependencies.

These protocols define the boundaries between the Execution Bot application
layer and external infrastructure. Implementations live in ``engine/``,
``store/``, and ``integrations/``.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.execution.models import TradeRecord
from bots.strategy.models import StrategyProposal


@runtime_checkable
class PriceSource(Protocol):
    """Adapter that retrieves the current price for a market instrument.

    The MVP uses ``MockPriceSource``. Future integration uses
    ``KitePriceSource`` (Zerodha) without any change to ``PaperEngine``.
    """

    def get_price(self, market: str) -> float:
        """Return the current price for the given market symbol.

        Args:
            market: Instrument identifier (e.g. ``"EUR/USD"``).

        Returns:
            Current price as a float.
        """


@runtime_checkable
class ExecutionEngine(Protocol):
    """Adapter that converts a StrategyProposal into a TradeRecord.

    The paper mode implementation simulates a fill. A future live
    implementation would send an order to a real broker.
    """

    def execute(self, proposal: StrategyProposal) -> TradeRecord:
        """Simulate or place a trade from the given strategy proposal.

        Args:
            proposal: The strategy to execute.

        Returns:
            A ``TradeRecord`` representing the executed position.
        """


@runtime_checkable
class TradeStore(Protocol):
    """Adapter that persists and retrieves trade records."""

    def save(self, trade: TradeRecord) -> None:
        """Persist a trade record.

        Args:
            trade: The trade to store.
        """

    def load_all(self) -> tuple[TradeRecord, ...]:
        """Load all persisted trade records.

        Returns:
            All stored trades in insertion order.
        """
