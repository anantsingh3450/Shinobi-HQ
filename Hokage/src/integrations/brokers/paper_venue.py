from __future__ import annotations

from pathlib import Path

from bots.execution.engine.paper_engine import PaperEngine
from bots.execution.execution_bot import ExecutionBot
from bots.execution.friction import ExecutionFrictionModel
from bots.execution.models import TradeDirection, TradeStatus
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.portfolio.portfolio_bot import PortfolioBot
from bots.portfolio.store import JsonPortfolioStore
from bots.strategy.models import StrategyProposal
from hokage.memory.resolver import PathResolver
from integrations.brokers.base_venue import BaseVenue
from integrations.brokers.models import (
    AccountBalance,
    ConnectionState,
    ConnectionStatus,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    VenueCapabilities,
    VenuePosition,
    VenueHolding,
    utc_now,
    ExecutionMode,
    ExecutionContext,
)
from integrations.data.factory import ProviderFactory
from integrations.data.interfaces import MarketDataProvider
from integrations.data.models import AssetClass, Exchange, Instrument
from integrations.tax.mock_provider import SimulatedTaxProvider
from integrations.tax.store import JsonTaxLedger


class PaperVenue(BaseVenue):
    """Paper trading execution venue wrapping ExecutionBot, PaperEngine, and local stores.
    
    Conforms to the BaseVenue abstract interface.
    """

    def __init__(
        self,
        venue_id: str = "paper_main",
        account_id: str = "paper",
        brain_root: Path | None = None,
        price_source: MarketDataProvider | None = None,
        context: ExecutionContext | None = None,
        friction_model: ExecutionFrictionModel | None = None,
    ) -> None:
        """Initialize the PaperVenue.

        Args:
            venue_id: Unique registration identifier (e.g. 'paper_main').
            account_id: Account ID to update (e.g. 'paper').
            brain_root: Optional custom path to brain root.
            price_source: Optional injected market price provider.
            context: Optional ExecutionContext guiding execution limits and modes.
        """
        self._venue_id = venue_id
        self._account_id = account_id
        
        if context is None:
            self._context = ExecutionContext(
                execution_mode=ExecutionMode.PAPER,
                active_venue_id=venue_id,
                brain_id="primary_brain",
                authority_level="elder",
            )
        else:
            self._context = context
        
        # Connection state initialization
        self._connection_state = ConnectionState.DISCONNECTED

        # Capabilities declaration
        self._capabilities = VenueCapabilities(
            market_orders=True,
            limit_orders=True,
            stop_orders=True,
            websocket_streaming=False,
            historical_data=True,
            margin_trading=True,
            options_trading=False,
            futures_trading=False,
            fractional_shares=True
        )

        # Dynamic path resolution
        self._resolver = PathResolver(brain_root)
        trades_dir = self._resolver.resolve_trades_dir()
        portfolio_dir = self._resolver.resolve_portfolio_dir()
        tax_dir = self._resolver.resolve_tax_dir()

        # Database and ledger stores (isolated by venue ID if not paper_main)
        if self._venue_id == "paper_main":
            self._trade_store = JsonTradeStore(trades_dir)
            self._portfolio_store = JsonPortfolioStore(portfolio_dir)
            self._tax_ledger = JsonTaxLedger(tax_dir)
        else:
            self._trade_store = JsonTradeStore(trades_dir / self._venue_id)
            self._portfolio_store = JsonPortfolioStore(portfolio_dir / self._venue_id)
            self._tax_ledger = JsonTaxLedger(tax_dir / self._venue_id)
        self._tax_provider = SimulatedTaxProvider()

        # Engine & Bot wiring
        self._price_source = price_source or ProviderFactory.create_market_data_provider()
        self._engine = PaperEngine(price_source=self._price_source, friction_model=friction_model)
        self._execution_bot = ExecutionBot(engine=self._engine, store=self._trade_store)

    @property
    def venue_id(self) -> str:
        """Unique registration identifier."""
        return self._venue_id

    @property
    def capabilities(self) -> VenueCapabilities:
        """Capabilities supported by this venue."""
        return self._capabilities

    def connect(self) -> ConnectionStatus:
        """Establish session connection and return status."""
        self._connection_state = ConnectionState.CONNECTED
        return ConnectionStatus(
            state=ConnectionState.CONNECTED,
            last_checked=utc_now(),
            latency_ms=1.5,
            message="Connected to paper trading simulation engine."
        )

    def disconnect(self) -> ConnectionStatus:
        """Cleanly close session connection."""
        self._connection_state = ConnectionState.DISCONNECTED
        return ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            last_checked=utc_now(),
            latency_ms=0.0,
            message="Disconnected from paper trading simulation engine."
        )

    def get_status(self) -> ConnectionStatus:
        """Perform diagnostics checks and return current connection state."""
        return ConnectionStatus(
            state=self._connection_state,
            last_checked=utc_now()
        )

    def place_order(self, request: OrderRequest) -> OrderResponse:
        """Route order request to the paper execution pipeline."""
        if self._context.execution_mode not in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
            raise RuntimeError("Paper trading is not active in the current execution mode.")
        if self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")

        # 1. Map OrderRequest to StrategyProposal
        proposal = StrategyProposal(
            name=request.strategy_id or "DirectOrder",
            description=request.execution_reason or "Order placed via PaperVenue",
            market=request.instrument.symbol,
            entry_rule="short" if request.side == OrderSide.SELL else "long",
            exit_rule="none",
            stop_loss_rule="none",
            take_profit_rule="none",
            timeframe="1m",
            confidence_score=1.0,
            sources_cited=(),
            playbook_id=request.playbook_id,
            volatility_regime=request.volatility_regime,
        )

        # 2. Execution Bot + Trade Store fill persistence (passing quantity explicitly to avoid state mutation)
        limit_price = request.price if request.order_type == OrderType.LIMIT else None
        trade = self._execution_bot.execute(
            proposal,
            persist=True,
            quantity=request.quantity,
            limit_price=limit_price,
        )

        # 5. Load Account first
        account = self._portfolio_store.load_account(self._account_id)

        # 4. Tax event generation and ledger recording
        tax_event = self._tax_provider.to_tax_event(trade, account)
        self._tax_ledger.record_event(tax_event)

        portfolio_bot = PortfolioBot(account)
        portfolio_bot.apply_trade(trade)
        self._portfolio_store.save_account(account)

        # 6. Map results to standard OrderResponse
        return OrderResponse(
            venue_order_id=trade.trade_id,
            venue_id=self._venue_id,
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.FILLED,
            quantity=trade.quantity,
            filled_quantity=trade.quantity,
            average_price=trade.entry_price,
            metadata={"trade_record": trade.to_dict(), "tax_event_total": tax_event.total_tax}
        )

    def cancel_order(self, venue_order_id: str) -> bool:
        """Request order cancellation. 
        
        Since paper trades fill instantly, returns False if the order was already executed.
        """
        if self._context.execution_mode not in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
            raise RuntimeError("Paper trading is not active in the current execution mode.")
        if self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")

        # Verify order exists
        trades = self._trade_store.load_all()
        for t in trades:
            if t.trade_id == venue_order_id:
                # Filled instantly, cannot cancel
                return False
        return False

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        """Retrieve latest details for a specific order."""
        if self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")

        trades = self._trade_store.load_all()
        for t in trades:
            if t.trade_id == venue_order_id:
                # Reconstruct instrument
                inst = Instrument(
                    symbol=t.market,
                    asset_class=AssetClass.INDIAN_EQUITY,
                    exchange=Exchange.NSE
                )
                side = OrderSide.BUY if t.direction == TradeDirection.LONG else OrderSide.SELL
                return OrderResponse(
                    venue_order_id=t.trade_id,
                    venue_id=self._venue_id,
                    instrument=inst,
                    side=side,
                    status=OrderStatus.FILLED,
                    quantity=t.quantity,
                    filled_quantity=t.quantity,
                    average_price=t.entry_price,
                    metadata={"trade_record": t.to_dict()}
                )
        raise KeyError(f"Order '{venue_order_id}' not found.")

    def get_account_balance(self) -> AccountBalance:
        """Query account capital and margins."""
        if self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")

        account = self._portfolio_store.load_account(self._account_id)
        return AccountBalance(
            venue_id=self._venue_id,
            total_equity=account.equity,
            cash=account.cash,
            margin_available=account.cash,
            margin_used=0.0,
            currency=account.currency
        )

    def get_positions(self) -> list[VenuePosition]:
        """Query currently active open positions."""
        if self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")

        account = self._portfolio_store.load_account(self._account_id)
        positions = []
        for pos in account.positions.values():
            if pos.status != TradeStatus.OPEN:
                continue

            inst = Instrument(
                symbol=pos.market,
                asset_class=AssetClass.INDIAN_EQUITY,
                exchange=Exchange.NSE
            )
            side = OrderSide.BUY if pos.direction == TradeDirection.LONG else OrderSide.SELL

            positions.append(
                VenuePosition(
                    instrument=inst,
                    side=side,
                    quantity=pos.quantity,
                    average_price=pos.entry_price,
                    current_price=pos.current_price or pos.entry_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    venue_id=self._venue_id,
                    metadata={"position_id": pos.position_id}
                )
            )
        return positions

    def get_holdings(self) -> list[VenueHolding]:
        """Query currently active holdings (returns empty for paper venue)."""
        if self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")
        return []

