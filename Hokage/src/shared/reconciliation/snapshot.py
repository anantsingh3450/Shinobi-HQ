"""Reconciliation Snapshots — represents states of the broker and local database.

Captures all necessary details to perform diffing and discrepancy classification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from integrations.brokers.interfaces import BaseExecutionVenue
from integrations.brokers.models import AccountBalance, VenuePosition, VenueHolding, OrderResponse
from bots.portfolio.models import Account, Position
from bots.execution.models import TradeRecord
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.portfolio.store import JsonPortfolioStore
from bots.autonomous.decision_journal import DecisionJournalSystem


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    """Ground truth state captured from the execution venue."""

    venue_id: str
    balance: AccountBalance
    positions: dict[str, VenuePosition]  # Map of symbol -> VenuePosition
    holdings: dict[str, VenueHolding]    # Map of symbol -> VenueHolding
    orders: list[OrderResponse]          # List of recent order responses
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def capture(cls, venue: BaseExecutionVenue) -> BrokerSnapshot:
        """Query the venue to capture the current broker state."""
        # 1. Fetch balance
        try:
            balance = venue.get_account_balance()
        except Exception as exc:
            # Create a safe fallback zero-balance if venue is disconnected/unresponsive
            balance = AccountBalance(
                venue_id=venue.venue_id,
                total_equity=0.0,
                cash=0.0,
                margin_available=0.0,
                margin_used=0.0,
                currency="INR",
                metadata={"error": str(exc)}
            )

        # 2. Fetch positions
        try:
            raw_positions = venue.get_positions()
            positions = {pos.instrument.symbol.upper(): pos for pos in raw_positions}
        except Exception:
            positions = {}

        # 3. Fetch holdings
        try:
            raw_holdings = venue.get_holdings()
            holdings = {h.instrument.symbol.upper(): h for h in raw_holdings}
        except Exception:
            holdings = {}

        # 4. Fetch orders (try custom method if exists, otherwise fallback to empty list)
        orders = []
        if hasattr(venue, "get_orders") and callable(getattr(venue, "get_orders")):
            try:
                orders = venue.get_orders()
            except Exception:
                pass
        else:
            # Fallback: if we have a trade store, we can treat its entries as completed orders
            # since the paper venue completes orders instantly and matches them 1:1.
            # Otherwise we leave orders empty.
            if hasattr(venue, "_trade_store") and venue._trade_store is not None:
                try:
                    trades = venue._trade_store.load_all()
                    from integrations.brokers.models import OrderSide, OrderStatus
                    from integrations.data.models import Instrument, AssetClass, Exchange
                    for t in trades:
                        inst = Instrument(symbol=t.market, asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
                        side = OrderSide.BUY if t.direction == "LONG" else OrderSide.SELL
                        orders.append(
                            OrderResponse(
                                venue_order_id=t.trade_id,
                                venue_id=venue.venue_id,
                                instrument=inst,
                                side=side,
                                status=OrderStatus.FILLED,
                                quantity=t.quantity,
                                filled_quantity=t.quantity,
                                average_price=t.entry_price,
                                updated_at=t.executed_at
                            )
                        )
                except Exception:
                    pass

        return cls(
            venue_id=venue.venue_id,
            balance=balance,
            positions=positions,
            holdings=holdings,
            orders=orders,
        )


@dataclass(frozen=True, slots=True)
class LocalSnapshot:
    """Internal database state captured from local stores."""

    account_id: str
    portfolio: Account
    positions: dict[str, Position]        # Map of market -> Position
    trades: list[TradeRecord]             # Execution journal trades
    decisions: list[dict[str, Any]]       # Decision journal entries
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def capture(
        cls,
        account_id: str,
        portfolio_store: JsonPortfolioStore,
        trade_store: JsonTradeStore,
        decision_journal: DecisionJournalSystem | None = None,
    ) -> LocalSnapshot:
        """Capture the local portfolio, positions, and execution ledger."""
        # 1. Load account and positions
        try:
            portfolio = portfolio_store.load_account(account_id)
            positions = {pos.market.upper(): pos for pos in portfolio.positions.values()}
        except Exception:
            portfolio = Account(account_id=account_id, initial_balance=0.0, cash=0.0)
            positions = {}

        # 2. Load execution journal
        try:
            trades = list(trade_store.load_all())
        except Exception:
            trades = []

        # 3. Load decisions
        decisions = []
        if decision_journal is not None:
            try:
                decisions = decision_journal.load_journal_entries()
            except Exception:
                pass

        return cls(
            account_id=account_id,
            portfolio=portfolio,
            positions=positions,
            trades=trades,
            decisions=decisions,
        )
