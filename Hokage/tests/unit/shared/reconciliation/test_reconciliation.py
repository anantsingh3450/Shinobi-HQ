"""Comprehensive verification tests for the Broker Reconciliation Engine and Safety Gating."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from hokage.memory.resolver import PathResolver
from hokage.memory.bootstrap import BrainBootstrapper
from integrations.brokers.interfaces import BaseExecutionVenue
from integrations.brokers.models import (
    AccountBalance,
    ConnectionState,
    ConnectionStatus,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    VenueCapabilities,
    VenuePosition,
    VenueHolding,
)
from integrations.data.models import Instrument, AssetClass, Exchange
from bots.portfolio.models import Account, Position
from bots.execution.models import TradeRecord, TradeDirection, TradeStatus
from bots.strategy.models import StrategyProposal
from bots.portfolio.store import JsonPortfolioStore
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.autonomous.decision_journal import DecisionJournalSystem
from bots.risk.rules import CompositeRiskManager, ReconciliationFreezeRiskRule
from bots.risk.risk_bot import RiskBot

from shared.reconciliation.snapshot import BrokerSnapshot, LocalSnapshot
from shared.reconciliation.classifier import DiscrepancyType, SeverityLevel, Discrepancy
from shared.reconciliation.difference import DifferenceEngine
from shared.reconciliation.report import ReconciliationReport
from shared.reconciliation.store import ReconciliationStore
from shared.reconciliation.engine import ReconciliationEngine


class MockVenue(BaseExecutionVenue):
    """Controllable mock execution venue for testing reconciliation scenarios."""

    def __init__(self, venue_id: str = "mock_broker") -> None:
        self._venue_id = venue_id
        self.balance = AccountBalance(
            venue_id=venue_id, total_equity=100000.0, cash=100000.0, margin_available=100000.0, margin_used=0.0
        )
        self.positions: list[VenuePosition] = []
        self.holdings: list[VenueHolding] = []
        self.orders: list[OrderResponse] = []
        self.raise_error = False

    @property
    def venue_id(self) -> str:
        return self._venue_id

    @property
    def capabilities(self) -> VenueCapabilities:
        return VenueCapabilities(
            market_orders=True, limit_orders=True, stop_orders=True, websocket_streaming=False,
            historical_data=False, margin_trading=True, options_trading=False, futures_trading=False, fractional_shares=False
        )

    def connect(self) -> ConnectionStatus:
        return ConnectionStatus(state=ConnectionState.CONNECTED, last_checked=datetime.now(timezone.utc))

    def disconnect(self) -> ConnectionStatus:
        return ConnectionStatus(state=ConnectionState.DISCONNECTED, last_checked=datetime.now(timezone.utc))

    def get_status(self) -> ConnectionStatus:
        return ConnectionStatus(state=ConnectionState.CONNECTED, last_checked=datetime.now(timezone.utc))

    def place_order(self, request: OrderRequest) -> OrderResponse:
        raise NotImplementedError()

    def cancel_order(self, venue_order_id: str) -> bool:
        return True

    def get_order_status(self, venue_order_id: str) -> OrderResponse:
        raise NotImplementedError()

    def get_account_balance(self) -> AccountBalance:
        if self.raise_error:
            raise RuntimeError("Broker connection timeout")
        return self.balance

    def get_positions(self) -> list[VenuePosition]:
        if self.raise_error:
            raise RuntimeError("Broker connection timeout")
        return self.positions

    def get_holdings(self) -> list[VenueHolding]:
        if self.raise_error:
            raise RuntimeError("Broker connection timeout")
        return self.holdings

    def get_orders(self) -> list[OrderResponse]:
        if self.raise_error:
            raise RuntimeError("Broker connection timeout")
        return self.orders


@pytest.fixture
def temp_resolver(tmp_path: Path) -> PathResolver:
    """Provides an isolated PathResolver with bootstrapped brain directories."""
    resolver = PathResolver(tmp_path)
    BrainBootstrapper(resolver).bootstrap()
    return resolver


def test_perfect_alignment(temp_resolver: PathResolver) -> None:
    """Verify health score is 100 when broker and local are perfectly matched."""
    venue = MockVenue()
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())
    
    # Save matching account locally
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    portfolio_store.save_account(account)

    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    report = engine.reconcile(auto_recover=False)

    assert report.health_score == 100.0
    assert len(report.discrepancies) == 0
    assert report.is_critical is False
    assert report.requires_action is False


def test_phantom_position_detection_and_recovery(temp_resolver: PathResolver) -> None:
    """Verify detection of phantom positions and automated metadata reconstruction."""
    venue = MockVenue()
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    # Create empty account locally
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    portfolio_store.save_account(account)

    # Setup phantom position on the broker
    inst = Instrument(symbol="INFY", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    venue.positions.append(
        VenuePosition(
            instrument=inst, side=OrderSide.BUY, quantity=50.0, average_price=1500.0,
            current_price=1510.0, unrealized_pnl=500.0, venue_id=venue.venue_id
        )
    )

    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    
    # Run with recovery disabled first to check detection
    report = engine.reconcile(auto_recover=False)
    assert len(report.discrepancies) == 1
    d = report.discrepancies[0]
    assert d.type == DiscrepancyType.PHANTOM_POSITION
    assert d.severity == SeverityLevel.CRITICAL
    assert d.requires_freeze is True
    assert engine.store.is_asset_frozen("INFY") is True

    # Now run with recovery enabled to trigger local state reconstruction
    report_recovered = engine.reconcile(auto_recover=True)
    
    # Verification: Local position should now exist, discrepancies resolved, and asset unfrozen
    assert len(report_recovered.discrepancies) == 0
    assert report_recovered.health_score == 100.0
    
    local_acc = portfolio_store.load_account("paper")
    open_positions = [p for p in local_acc.positions.values() if p.status == TradeStatus.OPEN]
    assert len(open_positions) == 1
    recovered_pos = open_positions[0]
    assert recovered_pos.market == "INFY"
    assert recovered_pos.quantity == 50.0
    assert recovered_pos.entry_price == 1500.0
    
    # Asset should be unfrozen automatically
    assert engine.store.is_asset_frozen("INFY") is False


def test_missing_position_detection_and_recovery(temp_resolver: PathResolver) -> None:
    """Verify detection of missing broker positions and automated local state netting."""
    venue = MockVenue()
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    # Create local open position
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    pos = Position(
        position_id="pos-1", market="TCS", direction=TradeDirection.LONG, quantity=10.0,
        entry_price=3400.0, current_price=3400.0, unrealized_pnl=0.0, realized_pnl=0.0,
        status=TradeStatus.OPEN, opened_at=datetime.now(timezone.utc)
    )
    account.positions[pos.position_id] = pos
    portfolio_store.save_account(account)

    # Broker has zero positions (meaning the position is missing/was closed externally)
    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    
    # Check detection
    report = engine.reconcile(auto_recover=False)
    assert len(report.discrepancies) == 1
    d = report.discrepancies[0]
    assert d.type == DiscrepancyType.MISSING_POSITION
    assert d.severity == SeverityLevel.HIGH
    assert d.requires_freeze is True
    assert engine.store.is_asset_frozen("TCS") is True

    # Run recovery to sync local ledger to matches broker (marks local position CLOSED)
    report_recovered = engine.reconcile(auto_recover=True)
    assert len(report_recovered.discrepancies) == 0
    
    local_acc = portfolio_store.load_account("paper")
    assert local_acc.positions["pos-1"].status == TradeStatus.CLOSED
    assert engine.store.is_asset_frozen("TCS") is False


def test_quantity_mismatch_severities_and_recovery(temp_resolver: PathResolver) -> None:
    """Verify that quantity mismatches are flagged correctly and recovered."""
    venue = MockVenue()
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    # Local position: 10 units of RELIANCE
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    pos = Position(
        position_id="pos-2", market="RELIANCE", direction=TradeDirection.LONG, quantity=10.0,
        entry_price=2400.0, current_price=2400.0, unrealized_pnl=0.0, realized_pnl=0.0,
        status=TradeStatus.OPEN, opened_at=datetime.now(timezone.utc)
    )
    account.positions[pos.position_id] = pos
    portfolio_store.save_account(account)

    # Broker position: 15 units (Broker > Local = CRITICAL risk)
    inst = Instrument(symbol="RELIANCE", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    venue.positions.append(
        VenuePosition(
            instrument=inst, side=OrderSide.BUY, quantity=15.0, average_price=2400.0,
            current_price=2400.0, unrealized_pnl=0.0, venue_id=venue.venue_id
        )
    )

    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    
    # Check CRITICAL classification for broker > local
    report = engine.reconcile(auto_recover=False)
    assert len(report.discrepancies) == 1
    assert report.discrepancies[0].type == DiscrepancyType.QUANTITY_MISMATCH
    assert report.discrepancies[0].severity == SeverityLevel.CRITICAL
    assert report.discrepancies[0].requires_freeze is True

    # Run recovery (syncs local to matches 15 units)
    report_recovered = engine.reconcile(auto_recover=True)
    assert len(report_recovered.discrepancies) == 0
    
    local_acc = portfolio_store.load_account("paper")
    assert local_acc.positions["pos-2"].quantity == 15.0


def test_price_mismatch_thresholds(temp_resolver: PathResolver) -> None:
    """Verify that average entry price mismatches are classified by deviation thresholds."""
    venue = MockVenue()
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    # Local position: entry price 100.0
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    pos = Position(
        position_id="pos-3", market="SBIN", direction=TradeDirection.LONG, quantity=100.0,
        entry_price=100.0, current_price=100.0, unrealized_pnl=0.0, realized_pnl=0.0,
        status=TradeStatus.OPEN, opened_at=datetime.now(timezone.utc)
    )
    account.positions[pos.position_id] = pos
    portfolio_store.save_account(account)

    # Broker position: entry price 108.0 (8% mismatch -> HIGH severity + Freeze)
    inst = Instrument(symbol="SBIN", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    venue.positions.append(
        VenuePosition(
            instrument=inst, side=OrderSide.BUY, quantity=100.0, average_price=108.0,
            current_price=100.0, unrealized_pnl=0.0, venue_id=venue.venue_id
        )
    )

    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    report = engine.reconcile(auto_recover=False)
    assert len(report.discrepancies) == 1
    assert report.discrepancies[0].type == DiscrepancyType.PRICE_MISMATCH
    assert report.discrepancies[0].severity == SeverityLevel.HIGH
    assert report.discrepancies[0].requires_freeze is True


def test_stale_local_cache_balance_resync(temp_resolver: PathResolver) -> None:
    """Verify that a cash balance discrepancy triggers automated cache alignment."""
    venue = MockVenue()
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    # Local cash: 100,000 INR
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    portfolio_store.save_account(account)

    # Broker cash: 98,500 INR (due to some unrecorded charges/fees)
    venue.balance = AccountBalance(
        venue_id=venue.venue_id, total_equity=98500.0, cash=98500.0, margin_available=98500.0, margin_used=0.0
    )

    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    
    # Check detection
    report = engine.reconcile(auto_recover=False)
    assert len(report.discrepancies) == 1
    assert report.discrepancies[0].type == DiscrepancyType.LEDGER_INCONSISTENCY

    # Check recovery re-syncs cash
    report_recovered = engine.reconcile(auto_recover=True)
    assert len(report_recovered.discrepancies) == 0
    
    local_acc = portfolio_store.load_account("paper")
    assert local_acc.cash == 98500.0


def test_reconciliation_freeze_risk_rule(temp_resolver: PathResolver) -> None:
    """Verify that if an asset is frozen, risk gating blocks new strategy proposals."""
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    
    # Setup account and frozen asset in store
    account = Account(account_id="paper", initial_balance=100000.0, cash=100000.0)
    portfolio_store.save_account(account)

    store = ReconciliationStore(temp_resolver)
    store.freeze_asset("WIPRO", "Simulated critical discrepancies")

    # Construct the Risk Bot with ReconciliationFreezeRiskRule
    risk_bot = RiskBot(
        manager=CompositeRiskManager([
            ReconciliationFreezeRiskRule(resolver=temp_resolver)
        ])
    )

    # Create a trade proposal for WIPRO
    proposal = StrategyProposal(
        name="WIPRO Momentum", description="trade", market="WIPRO", entry_rule="long",
        exit_rule="none", stop_loss_rule="none", take_profit_rule="none", timeframe="1m",
        confidence_score=1.0, sources_cited=()
    )

    # Evaluate proposal through risk bot — must be rejected!
    verdict = risk_bot.check_proposal(account, proposal, 500.0)
    assert verdict.is_approved is False
    assert "blocked by active safety freeze" in verdict.reason

    # Create a proposal for a non-frozen asset (e.g. TCS) — must be approved
    proposal_ok = StrategyProposal(
        name="TCS Momentum", description="trade", market="TCS", entry_rule="long",
        exit_rule="none", stop_loss_rule="none", take_profit_rule="none", timeframe="1m",
        confidence_score=1.0, sources_cited=()
    )
    verdict_ok = risk_bot.check_proposal(account, proposal_ok, 3000.0)
    assert verdict_ok.is_approved is True


def test_network_interruption_graceful_handling(temp_resolver: PathResolver) -> None:
    """Verify that network disconnects do not crash the engine and are classified correctly."""
    venue = MockVenue()
    venue.raise_error = True  # Simulates broker connection timeout/disconnect

    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    
    # Run reconciliation — must handle gracefully and flag connection issues
    report = engine.reconcile(auto_recover=False)
    assert report.health_score < 100.0
    assert len(report.discrepancies) > 0
    assert any(d.type == DiscrepancyType.LEDGER_INCONSISTENCY for d in report.discrepancies)


def test_recovery_after_restart_persistence(temp_resolver: PathResolver) -> None:
    """Verify that frozen asset states persist across system restarts."""
    store1 = ReconciliationStore(temp_resolver)
    store1.freeze_asset("HDFC", "Mismatched execution logs")

    # Simulate restart by instantiating a brand new store
    store2 = ReconciliationStore(temp_resolver)
    assert store2.is_asset_frozen("HDFC") is True
    assert "asset:HDFC" in store2.list_freezes()

    # Unfreeze and verify it is removed
    store2.unfreeze_asset("HDFC")
    assert store2.is_asset_frozen("HDFC") is False


def test_race_conditions_concurrency(temp_resolver: PathResolver) -> None:
    """Verify thread safety of the reconciliation persistence store."""
    store = ReconciliationStore(temp_resolver)
    errors = []

    def worker(tid: int):
        try:
            for i in range(20):
                asset = f"ASSET-{tid}-{i}"
                store.freeze_asset(asset, f"Thread {tid} write")
                assert store.is_asset_frozen(asset) is True
                store.unfreeze_asset(asset)
                assert store.is_asset_frozen(asset) is False
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrency errors: {errors}"


def test_stress_test_large_portfolio(temp_resolver: PathResolver) -> None:
    """Verify performance and scaling efficiency with a large volume of assets and records."""
    venue = MockVenue()
    venue.balance = AccountBalance(
        venue_id=venue.venue_id, total_equity=500000.0, cash=500000.0, margin_available=500000.0, margin_used=0.0
    )
    portfolio_store = JsonPortfolioStore(temp_resolver.resolve_portfolio_dir())
    trade_store = JsonTradeStore(temp_resolver.resolve_trades_dir())

    # Create large local portfolio with 150 active positions
    account = Account(account_id="paper", initial_balance=1000000.0, cash=500000.0)
    
    for i in range(150):
        symbol = f"SYM{i}"
        pos = Position(
            position_id=f"pos-{i}", market=symbol, direction=TradeDirection.LONG, quantity=10.0,
            entry_price=100.0 + i, current_price=100.0 + i, unrealized_pnl=0.0, realized_pnl=0.0,
            status=TradeStatus.OPEN, opened_at=datetime.now(timezone.utc)
        )
        account.positions[pos.position_id] = pos

        # Create matching broker position
        inst = Instrument(symbol=symbol, asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
        venue.positions.append(
            VenuePosition(
                instrument=inst, side=OrderSide.BUY, quantity=10.0, average_price=100.0 + i,
                current_price=100.0 + i, unrealized_pnl=0.0, venue_id=venue.venue_id
            )
        )

    portfolio_store.save_account(account)

    # Perform reconciliation and measure execution duration
    engine = ReconciliationEngine(venue, portfolio_store, trade_store, None, temp_resolver)
    
    start_time = time.perf_counter()
    report = engine.reconcile(auto_recover=False)
    end_time = time.perf_counter()
    
    duration_ms = (end_time - start_time) * 1000.0
    print(f"Reconciled large portfolio (150 positions) in {duration_ms:.2f} ms.")

    assert report.health_score == 100.0
    assert len(report.discrepancies) == 0
    # Must reconcile a large portfolio efficiently (e.g. under 200ms)
    assert duration_ms < 200.0
