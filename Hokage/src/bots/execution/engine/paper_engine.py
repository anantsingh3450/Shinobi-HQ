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
from bots.execution.friction import ExecutionFrictionModel, ZeroFrictionModel, get_market_volatility


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
        friction_model: ExecutionFrictionModel | None = None,
    ) -> None:
        """Configure the paper engine.

        Args:
            price_source:     Adapter that returns the current price for a market.
            default_quantity: Units to simulate per trade. Defaults to 1.0.
            friction_model:   Pluggable model simulating spreads, slippage, latency, and fills.
        """
        if default_quantity <= 0:
            raise ValueError("default_quantity must be positive.")
        self._price_source = price_source
        self._default_quantity = default_quantity
        self._friction_model = friction_model or ZeroFrictionModel()

    @property
    def price_source(self) -> PriceSource:
        """The configured price source."""
        return self._price_source

    @property
    def friction_model(self) -> ExecutionFrictionModel:
        """The configured friction model."""
        return self._friction_model

    def execute(
        self,
        proposal: StrategyProposal,
        quantity: float | None = None,
        limit_price: float | None = None,
    ) -> TradeRecord:
        """Simulate a trade from the given strategy proposal.

        Steps:
            1. Fetch current price for proposal.market via PriceSource.
            2. Infer direction from proposal.entry_rule.
            3. Calculate dynamic market volatility.
            4. Apply the pluggable friction model.
            5. Enforce 0.2% slippage ceiling on limit orders.
            6. Construct and return a TradeRecord (always PAPER, always OPEN).

        Args:
            proposal: The StrategyProposal to execute.
            quantity: Optional quantity override. If None, uses default_quantity.
            limit_price: Optional limit price for slippage checking.

        Returns:
            A completed TradeRecord with full provenance and friction metrics.
        """
        price = self._price_source.get_price(proposal.market)
        direction = self._infer_direction(proposal.entry_rule)
        qty = quantity if quantity is not None else self._default_quantity

        # Calculate dynamic market volatility from candles/spread
        vol = get_market_volatility(self._price_source, proposal.market)

        # Apply friction model (spread, slippage, partial fills, latency) without sleeping
        res = self._friction_model.apply_friction(
            market=proposal.market,
            direction=direction,
            quantity=qty,
            mid_price=price,
            market_volatility=vol,
        )

        fill_price = res["fill_price"]
        filled_qty = res["filled_quantity"]

        # Enforce 0.2% slippage protection ceiling on limit orders
        if limit_price is not None and limit_price > 0:
            max_slippage = 0.002
            if direction == TradeDirection.LONG:
                ceiling = limit_price * (1.0 + max_slippage)
                if fill_price > ceiling:
                    fill_price = round(ceiling, 6)
            elif direction == TradeDirection.SHORT:
                floor = limit_price * (1.0 - max_slippage)
                if fill_price < floor:
                    fill_price = round(floor, 6)

        simulated_value = round(filled_qty * fill_price, 6)

        # Build friction metadata payload
        profile_name = "ZERO"
        if hasattr(self._friction_model, "profile") and self._friction_model.profile:
            profile_name = self._friction_model.profile.value

        friction_metrics = {
            "requested_quantity": qty,
            "filled_quantity": filled_qty,
            "mid_price": price,
            "fill_price": fill_price,
            "slippage_price": round(abs(fill_price - price), 6),
            "slippage_pct": round((abs(fill_price - price) / price) * 100.0, 4) if price > 0 else 0.0,
            "latency_ms": res["latency_ms"],
            "partial_fill": filled_qty < qty,
            "profile": profile_name,
        }

        return TradeRecord(
            proposal_id=proposal.proposal_id,
            market=proposal.market,
            direction=direction,
            quantity=filled_qty,
            entry_price=fill_price,
            simulated_value=simulated_value,
            mode=ExecutionMode.PAPER,
            status=TradeStatus.OPEN,
            strategy_name=proposal.name,
            sources_cited=proposal.sources_cited,
            friction_metrics=friction_metrics,
            playbook_id=getattr(proposal, "playbook_id", None),
            volatility_regime=getattr(proposal, "volatility_regime", None),
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

