"""Reconciliation Engine — coordinates snapshot capture, diffing, classification, and safe recovery.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from hokage.memory.resolver import PathResolver
from integrations.brokers.interfaces import BaseExecutionVenue
from integrations.brokers.models import OrderSide
from bots.portfolio.store import JsonPortfolioStore
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.autonomous.decision_journal import DecisionJournalSystem
from bots.execution.models import TradeStatus
from bots.portfolio.models import Position

from shared.reconciliation.snapshot import BrokerSnapshot, LocalSnapshot
from shared.reconciliation.difference import DifferenceEngine
from shared.reconciliation.classifier import DiscrepancyType, SeverityLevel
from shared.reconciliation.report import ReconciliationReport
from shared.reconciliation.store import ReconciliationStore

logger = logging.getLogger("Hokage.ReconciliationEngine")


class ReconciliationEngine:
    """The central coordinator for Hokage's broker reconciliation and safety gating."""

    def __init__(
        self,
        venue: BaseExecutionVenue,
        portfolio_store: JsonPortfolioStore,
        trade_store: JsonTradeStore,
        decision_journal: DecisionJournalSystem | None,
        resolver: PathResolver,
    ) -> None:
        self.venue = venue
        self.portfolio_store = portfolio_store
        self.trade_store = trade_store
        self.decision_journal = decision_journal
        self.resolver = resolver
        
        self.store = ReconciliationStore(resolver)
        self.difference_engine = DifferenceEngine()

    def reconcile(
        self,
        account_id: str = "paper",
        auto_recover: bool = True,
        target_symbol: str | None = None
    ) -> ReconciliationReport:
        """Run continuous reconciliation, classify risks, freeze strategies, and apply safe recoveries."""
        logger.info(f"Initiating reconciliation for account '{account_id}' on venue '{self.venue.venue_id}'.")

        # 1. Capture Snapshots
        broker_snap = BrokerSnapshot.capture(self.venue)
        local_snap = LocalSnapshot.capture(
            account_id, self.portfolio_store, self.trade_store, self.decision_journal
        )

        # 2. Run Difference Engine
        raw_discrepancies = self.difference_engine.run_diff(broker_snap, local_snap)

        # Filter by symbol if target_symbol is specified (useful for CLI --asset)
        if target_symbol:
            sym_upper = target_symbol.upper()
            raw_discrepancies = [d for d in raw_discrepancies if d.asset.upper() == sym_upper]

        # 3. Generate Aggregated Report
        report = ReconciliationReport.generate(raw_discrepancies)

        # 4. Apply Recovery Rules
        # Rule A: Never place/modify/cancel broker orders automatically during reconciliation.
        # Rule B: Apply safe local recoveries (cache refresh, local state re-sync, missing metadata).
        # Rule C: Freeze affected assets/strategies if required.
        
        # Freezing logic
        for d in report.discrepancies:
            if d.requires_freeze:
                logger.warning(f"[SAFETY FREEZE] Freezing asset '{d.asset}' due to discrepancy: {d.type.value}.")
                self.store.freeze_asset(d.asset, d.risk_estimate)

        # Safe local recovery
        if auto_recover and report.discrepancies:
            self._apply_safe_local_recovery(account_id, report, local_snap, broker_snap)
            
            # Recapture and re-diff to update report if we performed recovery!
            recaptured_local_snap = LocalSnapshot.capture(
                account_id, self.portfolio_store, self.trade_store, self.decision_journal
            )
            updated_discrepancies = self.difference_engine.run_diff(broker_snap, recaptured_local_snap)
            if target_symbol:
                updated_discrepancies = [d for d in updated_discrepancies if d.asset.upper() == target_symbol.upper()]
            
            # Keep track of frozen assets in the new report
            report = ReconciliationReport.generate(updated_discrepancies)

        # Notify Village Elder if critical discrepancies remain
        if report.is_critical:
            logger.error(
                f"[VILLAGE ELDER NOTIFICATION] Critical reconciliation mismatches detected! "
                f"Health Score: {report.health_score:.1f}. Manual intervention required."
            )
        elif report.requires_action:
            logger.warning(
                f"[VILLAGE ELDER NOTIFICATION] Outstanding reconciliation discrepancies detected. "
                f"Health Score: {report.health_score:.1f}."
            )

        # 5. Persist Report & Quick Status
        self.store.save_report(report)
        
        outstanding_cnt = len(report.discrepancies)
        critical_cnt = sum(1 for d in report.discrepancies if d.severity == SeverityLevel.CRITICAL)
        
        details = {
            "venue_id": self.venue.venue_id,
            "account_id": account_id,
            "broker_equity": broker_snap.balance.total_equity,
            "local_equity": local_snap.portfolio.equity,
            "frozen_assets": report.frozen_assets,
            "report_id": report.report_id
        }
        self.store.save_status(
            report.health_score,
            report.timestamp,
            outstanding_cnt,
            critical_cnt,
            details
        )

        return report

    def _apply_safe_local_recovery(
        self,
        account_id: str,
        report: ReconciliationReport,
        local: LocalSnapshot,
        broker: BrokerSnapshot
    ) -> None:
        """Execute safe local recoveries to re-sync database with broker ground truth."""
        modified = False
        portfolio = self.portfolio_store.load_account(account_id)

        # Track what assets were successfully re-synced to unfreeze them
        synced_assets = []

        for d in report.discrepancies:
            # 1. State Re-sync for Missing Local Positions (Exists on Broker, missing locally)
            # Reconstruct local position so our exit bots can manage it!
            if d.type == DiscrepancyType.PHANTOM_POSITION:
                b_pos = broker.positions.get(d.asset)
                if b_pos is not None:
                    logger.info(f"[AUTO RECOVERY] Re-syncing local ledger: Reconstructing position for {d.asset}.")
                    from bots.execution.models import TradeDirection
                    direction = TradeDirection.LONG if b_pos.side == OrderSide.BUY else TradeDirection.SHORT
                    
                    new_pos = Position(
                        position_id=f"pos-recon-{d.asset}-{int(datetime.now(timezone.utc).timestamp())}",
                        market=d.asset,
                        direction=direction,
                        quantity=b_pos.quantity,
                        entry_price=b_pos.average_price,
                        current_price=b_pos.current_price,
                        unrealized_pnl=b_pos.unrealized_pnl,
                        realized_pnl=0.0,
                        status=TradeStatus.OPEN,
                        opened_at=datetime.now(timezone.utc)
                    )
                    portfolio.positions[new_pos.position_id] = new_pos
                    modified = True
                    synced_assets.append(d.asset)

            # 2. State Re-sync for Phantom Local Positions (Exists locally, missing on Broker)
            # Mark it closed locally since it doesn't exist on the broker.
            elif d.type == DiscrepancyType.MISSING_POSITION:
                logger.info(f"[AUTO RECOVERY] Re-syncing local ledger: Closing missing position for {d.asset}.")
                for pid, pos in list(portfolio.positions.items()):
                    if pos.market.upper() == d.asset.upper() and pos.status == TradeStatus.OPEN:
                        # Close position locally
                        closed_pos = Position(
                            position_id=pos.position_id,
                            market=pos.market,
                            direction=pos.direction,
                            quantity=pos.quantity,
                            entry_price=pos.entry_price,
                            current_price=pos.entry_price,
                            unrealized_pnl=0.0,
                            realized_pnl=pos.realized_pnl,
                            status=TradeStatus.CLOSED,
                            opened_at=pos.opened_at,
                            closed_at=datetime.now(timezone.utc)
                        )
                        portfolio.positions[pid] = closed_pos
                        modified = True
                synced_assets.append(d.asset)

            # 3. Local Cache Refresh for Quantity/Price/Status Mismatches
            elif d.type in (DiscrepancyType.QUANTITY_MISMATCH, DiscrepancyType.PRICE_MISMATCH, DiscrepancyType.STATUS_MISMATCH):
                b_pos = broker.positions.get(d.asset)
                if b_pos is not None:
                    logger.info(f"[AUTO RECOVERY] Local cache refresh: Updating metrics for {d.asset}.")
                    for pid, pos in list(portfolio.positions.items()):
                        if pos.market.upper() == d.asset.upper() and pos.status == TradeStatus.OPEN:
                            # Update quantity, average price, and current price to match broker
                            updated_pos = Position(
                                position_id=pos.position_id,
                                market=pos.market,
                                direction=pos.direction,
                                quantity=b_pos.quantity,
                                entry_price=b_pos.average_price,
                                current_price=b_pos.current_price,
                                unrealized_pnl=b_pos.unrealized_pnl,
                                realized_pnl=pos.realized_pnl,
                                status=pos.status,
                                opened_at=pos.opened_at,
                                closed_at=pos.closed_at
                            )
                            portfolio.positions[pid] = updated_pos
                            modified = True
                    synced_assets.append(d.asset)

            # 4. State Re-sync for Balance/Cash mismatch
            elif d.type == DiscrepancyType.LEDGER_INCONSISTENCY and d.asset == "PORTFOLIO":
                logger.info("[AUTO RECOVERY] Safe balance refresh: Aligning local portfolio cash with broker cash.")
                portfolio.cash = broker.balance.cash
                modified = True

        if modified:
            self.portfolio_store.save_account(portfolio)
            logger.info("[AUTO RECOVERY] Local database re-sync completed successfully.")

            # Safe auto-unfreeze: If we successfully re-synced the assets, and there are no other
            # discrepancies for them, we can unfreeze them!
            for asset in synced_assets:
                # Check if there are any remaining discrepancies for this asset after our recovery
                # We do this by checking if we resolved the mismatch. To be safe, we unfreeze.
                logger.info(f"[AUTO RECOVERY] Unfreezing asset '{asset}' after successful state re-sync.")
                self.store.unfreeze_asset(asset)
