"""Paper trading engine — implements ExecutionEngine for simulated fills.

This is the core of Phase 1 paper execution. It receives a StrategyProposal,
fetches a price from the injected PriceSource, infers trade direction from the
entry rule text, and produces a TradeRecord.

No real capital is involved. ExecutionMode is locked to PAPER.
"""
from __future__ import annotations

from bots.execution.interfaces import PriceSource
from bots.execution.models import ExecutionMode, TradeDirection, TradeRecord, TradeStatus
from bots.strategy.models import StrategyProposal


class PaperEngine:
    """Simulates trade execution using a pluggable PriceSource.

    Direction is inferred from the entry_rule text of the StrategyProposal:
    - If the rule contains "short" → TradeDirection.SHORT
    - Otherwise                   → TradeDirection.LONG (safe default)

    This keeps PaperEngine stateless and deterministic. The PriceSource
    abstraction means KitePriceSource (Zerodha) can replace MockPriceSource
    later without touching this class.

    Example:
        >>> engine = PaperEngine(price_source=MockPriceSource())
        >>> trade = engine.execute(proposal)
    """

    def __init__(
        self,
        price_source: PriceSource,
        default_quantity: float = 1.0,
    ) -> None:
        """Configure the paper engine.

        Args:
            price_source:     Adapter that returns the current price for a market.
            default_quantity: Units to simulate per trade. Defaults to 1.0.
        """
        if default_quantity <= 0:
            raise ValueError("default_quantity must be positive.")
        self._price_source = price_source
        self._default_quantity = default_quantity

    @property
    def price_source(self) -> PriceSource:
        """The configured price source."""
        return self._price_source

    def execute(self, proposal: StrategyProposal) -> TradeRecord:
        """Simulate a trade from the given strategy proposal.

        Steps:
            1. Fetch current price for proposal.market via PriceSource.
            2. Infer direction from proposal.entry_rule.
            3. Construct and return a TradeRecord (always PAPER, always OPEN).

        Args:
            proposal: The StrategyProposal to execute.

        Returns:
            A completed TradeRecord with full provenance.
        """
        price = self._price_source.get_price(proposal.market)
        direction = self._infer_direction(proposal.entry_rule)
        quantity = self._default_quantity
        simulated_value = round(quantity * price, 6)

        return TradeRecord(
            proposal_id=proposal.proposal_id,
            market=proposal.market,
            direction=direction,
            quantity=quantity,
            entry_price=price,
            simulated_value=simulated_value,
            mode=ExecutionMode.PAPER,
            status=TradeStatus.OPEN,
            strategy_name=proposal.name,
            sources_cited=proposal.sources_cited,
        )

    @staticmethod
    def _infer_direction(entry_rule: str) -> TradeDirection:
        """Infer trade direction from entry rule text.

        Args:
            entry_rule: The entry rule string from a StrategyProposal.

        Returns:
            TradeDirection.SHORT if "short" appears in the rule (case-insensitive),
            TradeDirection.LONG otherwise.
        """
        if "short" in entry_rule.lower():
            return TradeDirection.SHORT
        return TradeDirection.LONG
