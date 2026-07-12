"""Difference Engine — compares broker and local snapshots to produce discrepancies.
"""
from __future__ import annotations

import uuid

from shared.reconciliation.snapshot import BrokerSnapshot, LocalSnapshot
from shared.reconciliation.classifier import Discrepancy, DiscrepancyType, DiscrepancyClassifier
from bots.execution.models import TradeDirection, TradeStatus
from integrations.brokers.models import OrderSide, OrderStatus


class DifferenceEngine:
    """Compares snapshots and extracts raw differences, routing them to the classifier."""

    def __init__(self) -> None:
        pass

    def run_diff(self, broker: BrokerSnapshot, local: LocalSnapshot) -> list[Discrepancy]:
        """Perform comparison and return classified discrepancies."""
        discrepancies: list[Discrepancy] = []

        # 1. Compare Portfolio Balances
        self._diff_balances(broker, local, discrepancies)

        # 2. Compare Positions
        self._diff_positions(broker, local, discrepancies)

        # 3. Compare Holdings
        self._diff_holdings(broker, local, discrepancies)

        # 4. Compare Orders
        self._diff_orders(broker, local, discrepancies)

        # 5. Internal Local Ledger Consistency Checks
        self._check_local_consistency(local, discrepancies)

        return discrepancies

    def _diff_balances(self, broker: BrokerSnapshot, local: LocalSnapshot, discrepancies: list[Discrepancy]) -> None:
        """Compare broker account balance with local portfolio balance."""
        broker_cash = broker.balance.cash
        local_cash = local.portfolio.cash
        
        # If mismatch is greater than a small tolerance (e.g., 0.01 INR)
        if abs(broker_cash - local_cash) > 0.05:
            # We classify balance mismatch as a ledger inconsistency
            details = {
                "broker_cash": broker_cash,
                "local_cash": local_cash,
                "difference": broker_cash - local_cash,
                "message": f"Cash mismatch. Broker: {broker_cash}, Local: {local_cash}"
            }
            disc_id = f"disc-bal-{uuid.uuid4().hex[:8]}"
            discrepancies.append(
                DiscrepancyClassifier.classify(
                    disc_id,
                    DiscrepancyType.LEDGER_INCONSISTENCY,
                    "PORTFOLIO",
                    details
                )
            )

    def _diff_positions(self, broker: BrokerSnapshot, local: LocalSnapshot, discrepancies: list[Discrepancy]) -> None:
        """Compare broker open positions with local portfolio positions."""
        all_symbols = set(broker.positions.keys()) | set(local.positions.keys())

        for symbol in all_symbols:
            b_pos = broker.positions.get(symbol)
            l_pos = local.positions.get(symbol)

            # Case A: Position exists locally but not on broker
            if l_pos is not None and l_pos.status == TradeStatus.OPEN and b_pos is None:
                details = {
                    "local_qty": l_pos.quantity,
                    "local_price": l_pos.entry_price,
                    "position_id": l_pos.position_id
                }
                disc_id = f"disc-pos-miss-{symbol}-{uuid.uuid4().hex[:8]}"
                discrepancies.append(
                    DiscrepancyClassifier.classify(
                        disc_id,
                        DiscrepancyType.MISSING_POSITION,
                        symbol,
                        details
                    )
                )

            # Case B: Position exists on broker but not locally
            elif b_pos is not None and l_pos is None:
                details = {
                    "broker_qty": b_pos.quantity,
                    "broker_price": b_pos.average_price,
                    "broker_direction": b_pos.side.value
                }
                disc_id = f"disc-pos-phant-{symbol}-{uuid.uuid4().hex[:8]}"
                discrepancies.append(
                    DiscrepancyClassifier.classify(
                        disc_id,
                        DiscrepancyType.PHANTOM_POSITION,
                        symbol,
                        details
                    )
                )

            # Case C: Position exists on both, check for mismatches
            elif b_pos is not None and l_pos is not None:
                # Resolve local status
                if l_pos.status != TradeStatus.OPEN:
                    # Broker thinks it's open, local thinks closed -> Phantom Position
                    details = {
                        "broker_qty": b_pos.quantity,
                        "broker_price": b_pos.average_price,
                        "local_status": l_pos.status.value
                    }
                    disc_id = f"disc-pos-phant-{symbol}-{uuid.uuid4().hex[:8]}"
                    discrepancies.append(
                        DiscrepancyClassifier.classify(
                            disc_id,
                            DiscrepancyType.PHANTOM_POSITION,
                            symbol,
                            details
                        )
                    )
                    continue

                # 1. Direction mismatch
                l_dir = OrderSide.BUY if l_pos.direction == TradeDirection.LONG else OrderSide.SELL
                if b_pos.side != l_dir:
                    details = {
                        "local_direction": l_dir.value,
                        "broker_direction": b_pos.side.value
                    }
                    disc_id = f"disc-pos-dir-{symbol}-{uuid.uuid4().hex[:8]}"
                    discrepancies.append(
                        DiscrepancyClassifier.classify(
                            disc_id,
                            DiscrepancyType.STATUS_MISMATCH,
                            symbol,
                            details
                        )
                    )

                # 2. Quantity mismatch
                if abs(b_pos.quantity - l_pos.quantity) > 1e-5:
                    details = {
                        "local_qty": l_pos.quantity,
                        "broker_qty": b_pos.quantity,
                        "difference": b_pos.quantity - l_pos.quantity
                    }
                    disc_id = f"disc-pos-qty-{symbol}-{uuid.uuid4().hex[:8]}"
                    discrepancies.append(
                        DiscrepancyClassifier.classify(
                            disc_id,
                            DiscrepancyType.QUANTITY_MISMATCH,
                            symbol,
                            details
                        )
                    )

                # 3. Entry Price mismatch
                if abs(b_pos.average_price - l_pos.entry_price) > 0.01:
                    details = {
                        "local_price": l_pos.entry_price,
                        "broker_price": b_pos.average_price,
                        "difference": b_pos.average_price - l_pos.entry_price
                    }
                    disc_id = f"disc-pos-prc-{symbol}-{uuid.uuid4().hex[:8]}"
                    discrepancies.append(
                        DiscrepancyClassifier.classify(
                            disc_id,
                            DiscrepancyType.PRICE_MISMATCH,
                            symbol,
                            details
                        )
                    )

    def _diff_holdings(self, broker: BrokerSnapshot, local: LocalSnapshot, discrepancies: list[Discrepancy]) -> None:
        """Compare broker holdings with local ledger (if any)."""
        # For Hokage Alpha, holdings represents longer-term structural assets.
        # Currently, paper trading mainly handles short-term positions.
        # We perform a similar check if broker returns holdings.
        for symbol, b_hold in broker.holdings.items():
            # If we have broker holdings but no local positions/holdings, report it as a phantom position/holding
            if symbol not in local.positions:
                details = {
                    "broker_qty": b_hold.quantity,
                    "broker_price": b_hold.average_price,
                    "message": "Holding exists on broker but not in local portfolio."
                }
                disc_id = f"disc-hold-phant-{symbol}-{uuid.uuid4().hex[:8]}"
                discrepancies.append(
                    DiscrepancyClassifier.classify(
                        disc_id,
                        DiscrepancyType.PHANTOM_POSITION,
                        symbol,
                        details
                    )
                )

    def _diff_orders(self, broker: BrokerSnapshot, local: LocalSnapshot, discrepancies: list[Discrepancy]) -> None:
        """Compare broker orders with local execution journal."""
        # Map local trades by trade_id
        local_trades = {t.trade_id: t for t in local.trades}

        for b_order in broker.orders:
            order_id = b_order.venue_order_id
            l_trade = local_trades.get(order_id)

            # Case A: Order rejected on broker
            if b_order.status == OrderStatus.REJECTED:
                details = {
                    "order_id": order_id,
                    "reason": b_order.error_message or "Broker rejection",
                    "qty": b_order.quantity
                }
                disc_id = f"disc-ord-rej-{order_id}-{uuid.uuid4().hex[:8]}"
                discrepancies.append(
                    DiscrepancyClassifier.classify(
                        disc_id,
                        DiscrepancyType.REJECTED_ORDER,
                        b_order.instrument.symbol,
                        details
                    )
                )

            # Case B: Order cancelled on broker, but local think it was filled/open
            elif b_order.status == OrderStatus.CANCELLED:
                if l_trade is not None and l_trade.status == TradeStatus.OPEN:
                    details = {
                        "order_id": order_id,
                        "local_status": l_trade.status.value,
                        "broker_status": b_order.status.value
                    }
                    disc_id = f"disc-ord-can-{order_id}-{uuid.uuid4().hex[:8]}"
                    discrepancies.append(
                        DiscrepancyClassifier.classify(
                            disc_id,
                            DiscrepancyType.CANCELLED_ORDER,
                            b_order.instrument.symbol,
                            details
                        )
                    )

            # Case C: Partial fill on broker
            elif b_order.status == OrderStatus.PARTIALLY_FILLED:
                details = {
                    "order_id": order_id,
                    "filled_qty": b_order.filled_quantity,
                    "total_qty": b_order.quantity
                }
                disc_id = f"disc-ord-part-{order_id}-{uuid.uuid4().hex[:8]}"
                discrepancies.append(
                    DiscrepancyClassifier.classify(
                        disc_id,
                        DiscrepancyType.PARTIAL_FILL,
                        b_order.instrument.symbol,
                        details
                    )
                )

        # Case D: Orphaned local trades
        # If a trade exists in local execution journal, but there is no broker order,
        # or if the trade says it's OPEN but the position doesn't exist locally,
        # it might be an orphaned trade record.
        for t_id, l_trade in local_trades.items():
            # If the trade is OPEN, but we don't have this position in the local portfolio,
            # it's a ledger inconsistency.
            market = l_trade.market.upper()
            if l_trade.status == TradeStatus.OPEN and market not in local.positions:
                details = {
                    "trade_id": t_id,
                    "market": l_trade.market,
                    "qty": l_trade.quantity,
                    "message": "Trade is marked open but position is missing from portfolio."
                }
                disc_id = f"disc-trd-orph-{t_id}-{uuid.uuid4().hex[:8]}"
                discrepancies.append(
                    DiscrepancyClassifier.classify(
                        disc_id,
                        DiscrepancyType.ORPHANED_TRADE,
                        l_trade.market,
                        details
                    )
                )

    def _check_local_consistency(self, local: LocalSnapshot, discrepancies: list[Discrepancy]) -> None:
        """Check for internal inconsistencies within the local database itself."""
        # 1. Cash + Open Positions Unrealized PnL = Equity check
        unrealized = sum(
            pos.unrealized_pnl
            for pos in local.portfolio.positions.values()
            if pos.status == TradeStatus.OPEN
        )
        
        expected_equity = local.portfolio.cash + unrealized
        actual_equity = local.portfolio.equity
        
        if abs(actual_equity - expected_equity) > 0.05:
            details = {
                "actual_equity": actual_equity,
                "expected_equity": expected_equity,
                "difference": actual_equity - expected_equity,
                "message": f"Local portfolio equity calculation mismatch. Expected: {expected_equity}, Actual: {actual_equity}"
            }
            disc_id = f"disc-local-eq-{uuid.uuid4().hex[:8]}"
            discrepancies.append(
                DiscrepancyClassifier.classify(
                    disc_id,
                    DiscrepancyType.LEDGER_INCONSISTENCY,
                    "LOCAL_LEDGER",
                    details
                )
            )
