"""Hokage Orchestrator — drives the bot pipeline.

Wires all bots together and exposes named pipeline methods that the
CommandRouter calls. No business logic lives here.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

from bots.backtest.backtest_bot import BacktestBot
from bots.backtest.engine.historical_backtest_engine import HistoricalBacktestEngine
from bots.execution.engine.paper_engine import PaperEngine
from bots.execution.execution_bot import ExecutionBot
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.execution.friction import ProfiledFrictionModel, resolve_active_friction_profile
from bots.portfolio.portfolio_bot import PortfolioBot
from bots.portfolio.store import JsonPortfolioStore
from bots.research.models import ResearchQuery
from bots.research.research_bot import ResearchBot
from bots.risk.risk_bot import RiskBot
from bots.risk.rules import (
    CompositeRiskManager,
    MaxDrawdownRiskRule,
    MaxPositionSizeRiskRule,
    MaxPositionsRiskRule,
    UniverseConstraintRiskRule,
    ReconciliationFreezeRiskRule,
    SectorConcentrationRiskRule,
    PortfolioBetaRiskRule,
    DynamicVaRSizingRule,
    ExpectedShortfallRiskRule,
    HardLotCapRule,
)
from bots.strategy.generators import HeuristicStrategyGenerator
from bots.strategy.strategy_bot import StrategyBot
from bots.autonomous.autonomous_bot import AutonomousTradingBot
from bots.improvement.improvement_bot import ImprovementBot
from integrations.data.dummy_source import DummyResearchSource
from integrations.data.factory import ProviderFactory
from integrations.tax.mock_provider import SimulatedTaxProvider
from integrations.tax.store import JsonTaxLedger
from hokage.ledger.prediction_ledger import JsonPredictionLedger, PredictionRecord
from hokage.memory.resolver import PathResolver
from hokage.memory.bootstrap import BrainBootstrapper

from integrations.brokers.interfaces import ExecutionVenueRegistry
from integrations.brokers.paper_venue import PaperVenue
from integrations.brokers.kite_venue import KiteVenue
from integrations.brokers.groww_venue import GrowwVenue
from integrations.brokers.coindcx_venue import CoinDcxVenue
from integrations.brokers.institutional_venue import InstitutionalVenue
from integrations.brokers.secrets import SecretManager
from integrations.brokers.kite_connection import KiteConnectionManager
from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
from integrations.brokers.models import ConnectionState, ExecutionMode, ExecutionContext
from integrations.brokers.session_manager import TradingSessionManager
from integrations.brokers.broker_registry import BrokerRegistry

# Initialise default path resolver and bootstrap default brain
_resolver = PathResolver()
BrainBootstrapper(_resolver).bootstrap()

import sys

def _check_legacy_data_dirs() -> None:
    legacy_paths = [
        Path("data/paper_trades"),
        Path("data/portfolio"),
        Path("data/predictions"),
        Path("data/tax"),
    ]
    if any(p.exists() for p in legacy_paths):
        print("Legacy data directory detected. Portable Brain is now the canonical storage location.", file=sys.stderr)

_check_legacy_data_dirs()

_PAPER_TRADES_DIR = _resolver.resolve_trades_dir()
_PORTFOLIO_DIR = _resolver.resolve_portfolio_dir()
_PREDICTION_LEDGER_DIR = _resolver.resolve_predictions_dir()
_TAX_LEDGER_DIR = _resolver.resolve_tax_dir()
_PAPER_ACCOUNT_ID = "paper"


class HokageOrchestrator:
    """Core workflow engine that drives the bot pipeline."""

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize orchestrator with all configured bots."""
        self.resolver = PathResolver(brain_root)
        BrainBootstrapper(self.resolver).bootstrap()

        # Run SQLite migrations on startup to ensure transactional storage is active
        # Only run if not under pytest, or if we are explicitly running the persistence tests.
        import sys
        is_persistence_test = any("test_sqlite_persistence" in arg or "test_component4" in arg for arg in sys.argv)
        if "pytest" not in sys.modules or is_persistence_test:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            self.sqlite_engine = SqliteStorageEngine(self.resolver)
            self.sqlite_engine.run_migrations()

        # Support fallback to monkeypatched module variables if brain_root is not provided
        trades_dir = self.resolver.resolve_trades_dir() if brain_root is not None else _PAPER_TRADES_DIR
        portfolio_dir = self.resolver.resolve_portfolio_dir() if brain_root is not None else _PORTFOLIO_DIR
        predictions_dir = self.resolver.resolve_predictions_dir() if brain_root is not None else _PREDICTION_LEDGER_DIR
        tax_dir = self.resolver.resolve_tax_dir() if brain_root is not None else _TAX_LEDGER_DIR

        # Initialize default ExecutionContext (toggles capabilities dynamically)
        self.context = ExecutionContext(
            execution_mode=ExecutionMode.READ_ONLY,
            active_venue_id="kite_main",
            brain_id="primary_brain",
            authority_level="elder",
        )

        # SecretManager loads from user-local platform specific APPDATA path
        self.secrets_manager = SecretManager()
        self.kite_connection = KiteConnectionManager(self.secrets_manager)
        self.kite_provider = KiteMarketDataProvider(self.kite_connection)

        # Determine price source based on environment config
        from integrations.data.models import ProviderConfig, MarketDataMode
        config = ProviderConfig.from_env()
        if config.market_data_mode is MarketDataMode.KITE:
            self.price_source = self.kite_provider
        else:
            self.price_source = ProviderFactory.create_market_data_provider(config)

        # Research phase
        self.research_bot = ResearchBot(sources=[DummyResearchSource()])

        # Strategy phase — generator injected via DI
        self.strategy_bot = StrategyBot(generator=HeuristicStrategyGenerator())

        # Backtest phase — engine injected via DI
        self.backtest_bot = BacktestBot(
            engine=HistoricalBacktestEngine(market_data_provider=self.price_source)
        )

        # Risk phase — manager injected via DI
        self.risk_bot = RiskBot(
            manager=CompositeRiskManager(
                [
                    MaxDrawdownRiskRule(),
                    MaxPositionSizeRiskRule(),
                    MaxPositionsRiskRule(resolver=self.resolver),
                    UniverseConstraintRiskRule(resolver=self.resolver),
                    ReconciliationFreezeRiskRule(resolver=self.resolver),
                    # Phase 6.6C — Portfolio Risk Hardening
                    SectorConcentrationRiskRule(),
                    PortfolioBetaRiskRule(),
                    DynamicVaRSizingRule(),
                    ExpectedShortfallRiskRule(),
                    HardLotCapRule(resolver=self.resolver),
                ]
            )
        )

        # Resolve active execution realism friction profile
        self.friction_profile = resolve_active_friction_profile(self.resolver)
        self.friction_model = ProfiledFrictionModel(self.friction_profile)

        # Execution phase — engine and store injected via DI
        self.trade_store = JsonTradeStore(trades_dir)
        self.execution_bot = ExecutionBot(
            engine=PaperEngine(price_source=self.price_source, friction_model=self.friction_model),
            store=self.trade_store,
        )

        # Portfolio persistence
        self.portfolio_store = JsonPortfolioStore(portfolio_dir)
        self.prediction_ledger = JsonPredictionLedger(predictions_dir)
        self.tax_provider = SimulatedTaxProvider()
        self.tax_ledger = JsonTaxLedger(tax_dir)

        # Registry and venue setups
        self.registry = ExecutionVenueRegistry()
        self.session_manager = TradingSessionManager()

        # Config-driven broker registry — resolve paths relative to the project root
        _project_root = Path(__file__).resolve().parents[3]
        self.broker_registry = BrokerRegistry(
            self.registry,
            self.session_manager,
            config_path=_project_root / "config" / "broker_registry.json",
            brokers_dir=_project_root / "config" / "brokers",
        )
        
        self.paper_venue = PaperVenue(
            venue_id="paper_main",
            brain_root=brain_root,
            price_source=self.price_source,
            context=self.context,
            friction_model=self.friction_model
        )
        self.registry.register_venue(self.paper_venue)

        # Broker-specific paper venues — driven by the registry config so adding a
        # new broker in broker_registry.json automatically creates its paper venue.
        self.paper_venues = {}
        for broker in self.broker_registry.list_brokers():
            profile = self.broker_registry.get_capability_profile(broker)
            paper_venue_id = profile.paper_venue_id if profile else f"paper_{broker}"
            p_venue = PaperVenue(
                venue_id=paper_venue_id,
                brain_root=brain_root,
                price_source=self.price_source,
                context=self.context,
                friction_model=self.friction_model
            )
            self.registry.register_venue(p_venue)
            self.paper_venues[broker] = p_venue
        
        self.kite_venue = KiteVenue(
            venue_id="kite_main",
            connection_manager=self.kite_connection,
            context=self.context
        )
        self.registry.register_venue(self.kite_venue)

        self.groww_venue = GrowwVenue(
            venue_id="groww_main",
            context=self.context
        )
        self.registry.register_venue(self.groww_venue)

        self.coindcx_venue = CoinDcxVenue(
            venue_id="coindcx_main",
            context=self.context
        )
        self.registry.register_venue(self.coindcx_venue)

        self.institutional_venue = InstitutionalVenue(
            venue_id="oanda_main",
            context=self.context
        )
        self.registry.register_venue(self.institutional_venue)

        self.autonomous_bot = AutonomousTradingBot(self)
        self.improvement_bot = ImprovementBot(
            portfolio_manager=self.autonomous_bot.strategy_portfolio,
            resolver=self.resolver,
            prediction_ledger=self.prediction_ledger,
            trade_store=self.trade_store
        )

        # Watchdog & Heartbeat System
        from shared.watchdog import Watchdog
        self.watchdog = Watchdog(self.resolver, self)

        # Bot health metrics initialization
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        self.bot_health_metrics = {
            "research_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.5, "memory": 45.0, "latency": 0.05, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.05},
            "strategy_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.8, "memory": 55.0, "latency": 0.08, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.08},
            "risk_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.4, "memory": 35.0, "latency": 0.03, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.03},
            "execution_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.6, "memory": 40.0, "latency": 0.06, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.06},
            "portfolio_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.3, "memory": 30.0, "latency": 0.02, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.02},
            "improvement_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.2, "memory": 25.0, "latency": 0.04, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.04},
            "shadow_bot": {"health_score": 100, "heartbeat": now_str, "cpu": 0.5, "memory": 50.0, "latency": 0.07, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.07},
            "market_intelligence": {"health_score": 100, "heartbeat": now_str, "cpu": 0.7, "memory": 60.0, "latency": 0.12, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.12},
            "voice_commander": {"health_score": 100, "heartbeat": now_str, "cpu": 0.2, "memory": 20.0, "latency": 0.01, "queue_size": 0, "last_execution": now_str, "current_task": "IDLE", "failure_count": 0, "recovery_count": 0, "average_runtime": 0.01}
        }

        # Command Queue Integration
        from hokage.orchestrator.command_queue import CommandQueue
        self.command_queue = CommandQueue(self)
        self.command_queue.start_worker()

    def get_execution_context(self) -> ExecutionContext:
        """Return the active ExecutionContext, dynamically synchronized with brain.json / commander profile."""
        try:
            # First check if brain.json has an override execution_mode
            brain_json_path = self.resolver.resolve_brain_root() / "brain.json"
            brain_mode = None
            if brain_json_path.exists():
                try:
                    with open(brain_json_path, "r", encoding="utf-8") as f:
                        brain_data = json.load(f)
                    brain_mode = brain_data.get("execution_mode")
                except Exception:
                    pass

            from hokage.memory.profile import ProfileService
            profile_service = ProfileService(self.resolver)
            profile = profile_service.get_profile()
            
            # Map execution mode string/enum from brain or profile
            profile_mode = brain_mode if brain_mode else profile.environment.mode
            from integrations.brokers.models import ExecutionMode
            if isinstance(profile_mode, str):
                try:
                    mode_enum = ExecutionMode(profile_mode.upper())
                except ValueError:
                    mode_enum = ExecutionMode.READ_ONLY
            else:
                mode_enum = profile_mode
                
            if mode_enum in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
                new_active_venue_id = "paper_zerodha"
            else:
                new_active_venue_id = "kite_main"
                
            self.context = ExecutionContext(
                execution_mode=mode_enum,
                active_venue_id=new_active_venue_id,
                brain_id=self.context.brain_id,
                authority_level=self.context.authority_level,
            )
            # Sync to all venues in registry
            for venue_id in self.registry.list_venues():
                try:
                    venue = self.registry.get_venue(venue_id)
                    if hasattr(venue, "_context"):
                        venue._context = self.context
                except Exception:
                    pass
        except Exception:
            pass
        return self.context

    # ------------------------------------------------------------------
    # Watchdog & Heartbeat Operations
    # ------------------------------------------------------------------

    def run_watchdog_check(self) -> dict[str, Any]:
        """Run system-wide diagnostic checks and return watchdog status."""
        self.watchdog.check_system_health()
        return self.watchdog.get_watchdog_status()

    def get_watchdog_status(self) -> dict[str, Any]:
        """Get the latest watchdog status summary."""
        return self.watchdog.get_watchdog_status()

    def publish_heartbeat(self, subsystem: str, status: str = "HEALTHY", latency: float = 0.0) -> dict[str, Any]:
        """Publish a heartbeat for a subsystem."""
        hb = self.watchdog.publish_heartbeat(subsystem, status, execution_latency=latency)
        return hb.to_dict()

    def get_watchdog_incidents(self) -> list[dict[str, Any]]:
        """Load all recorded incidents."""
        return [i.to_dict() for i in self.watchdog.store.load_incidents()]

    def acknowledge_watchdog_incident(self, incident_id: str) -> bool:
        """Acknowledge a specific incident."""
        return self.watchdog.store.acknowledge_incident(incident_id)

    def trigger_watchdog_restart(self, subsystem: str) -> bool:
        """Manually trigger a safe background restart for a subsystem."""
        return self.watchdog.execute_restart(subsystem)


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
        tax_event = self.tax_provider.to_tax_event(trade)
        self.tax_ledger.record_event(tax_event)

        # 4. Portfolio update (keeps account_paper.json in sync with trades.jsonl)
        account = self.portfolio_store.load_account(_PAPER_ACCOUNT_ID)
        portfolio_bot = PortfolioBot(account)
        portfolio_bot.apply_trade(trade)
        self.portfolio_store.save_account(account)

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
            "simulated_tax": tax_event.total_tax,
            "tax_jurisdiction": tax_event.jurisdiction.value,
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
        print("\n========== HOKAGE BACKTEST ==========")
        print(f"Strategy: {proposal.name}")
        print(f"Market: {proposal.market}")
        print(f"Confidence: {proposal.confidence_score}")
        print(f"Passed: {backtest_result.passed}")
        print(f"Win Rate: {backtest_result.win_rate}")
        print(f"Profit Factor: {backtest_result.profit_factor}")
        print(f"Net Profit: {backtest_result.net_profit}")
        print(f"After Tax Profit: {backtest_result.after_tax_net_profit}")
        print(f"Max Drawdown: {backtest_result.max_drawdown}")
        print("=====================================\n")
        self.prediction_ledger.record(
            PredictionRecord.from_pipeline(proposal, backtest_result)
        )
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

        # 5. Guard rails (same discipline as the autonomous entry path):
        #    - never execute a placeholder/unresolved symbol ("MARKET"/"UNKNOWN"
        #      once created a ghost paper position at a default price),
        #    - never execute without a real positive price,
        #    - never exceed the risk-approved quantity (HardLotCapRule etc.
        #      express their limit via max_approved_quantity).
        symbol_upper = (proposal.market or "").upper()
        exec_qty = min(1.0, risk_verdict.max_approved_quantity)
        if symbol_upper in ("", "MARKET", "UNKNOWN") or not entry_price or entry_price <= 0 or exec_qty <= 0:
            raise ValueError(
                f"Execution blocked: unresolved symbol '{proposal.market}', "
                f"price={entry_price!r}, risk-approved qty={exec_qty}. "
                "Evaluation completed but no order was placed."
            )

        # 6. Paper execution + persistence
        trade = self.execution_bot.execute(proposal, persist=True, quantity=exec_qty)

        # 6. Tax simulation
        tax_event = self.tax_provider.to_tax_event(trade)
        self.tax_ledger.record_event(tax_event)

        # 7. Portfolio update
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
            "after_tax_net_profit": backtest_result.after_tax_net_profit,
            "tax_estimate": backtest_result.tax_estimate,
            "backtest_provider": backtest_result.provider,
            "backtest_summary": backtest_result.summary,
            "risk_approved": risk_verdict.is_approved,
            "risk_reason": risk_verdict.reason,
            "simulated_tax": tax_event.total_tax,
            "tax_jurisdiction": tax_event.jurisdiction.value,
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

    # ------------------------------------------------------------------
    # Query: Portfolio state
    # ------------------------------------------------------------------

    def query_portfolio(self) -> dict:
        """Return a summary of the current paper account state.

        Unrealized PnL is explicitly labelled as unavailable because no live
        price feed is active in this phase. All other fields are read from the
        persisted account JSON.

        Returns:
            Dictionary of account summary fields for CLI display.
        """
        account = self.portfolio_store.load_account(_PAPER_ACCOUNT_ID)
        open_count = sum(
            1
            for pos in account.positions.values()
            if pos.status.name == "OPEN"
        )
        return {
            "account_id": account.account_id,
            "initial_balance": account.initial_balance,
            "cash": account.cash,
            "currency": account.currency,
            "realized_pnl": account.realized_pnl,
            "open_positions": open_count,
            "unrealized_pnl": "N/A (live price feed inactive)",
        }

    # ------------------------------------------------------------------
    # Query: Open positions
    # ------------------------------------------------------------------

    def query_positions(self) -> list[dict]:
        """Return all currently open positions in the paper account.

        Filters to status == OPEN only. Closed positions are excluded.

        Returns:
            List of dicts, one per open position, sorted by opened_at.
            Empty list if no positions are open or account does not exist.
        """
        account = self.portfolio_store.load_account(_PAPER_ACCOUNT_ID)
        result = []
        for pos in account.positions.values():
            if pos.status.name != "OPEN":
                continue
            result.append({
                "market": pos.market,
                "direction": pos.direction.value,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "opened_at": pos.opened_at.isoformat(),
            })
        result.sort(key=lambda p: p["opened_at"])
        return result

    # ------------------------------------------------------------------
    # Query: Prediction ledger summary
    # ------------------------------------------------------------------

    def query_predictions(self) -> dict:
        """Return a summary of all strategy predictions recorded in the ledger.

        Returns:
            Dictionary with total count, pass/fail split, and average win rate.
            Returns zero-valued dict if no predictions have been recorded.
        """
        records = self.prediction_ledger.load_all()
        total = len(records)
        if total == 0:
            return {
                "total_predictions": 0,
                "passed": 0,
                "failed": 0,
                "average_win_rate": "N/A",
            }
        passed = sum(1 for r in records if r.backtest_passed)
        failed = total - passed
        avg_win_rate = round(sum(r.win_rate for r in records) / total, 2)
        return {
            "total_predictions": total,
            "passed": passed,
            "failed": failed,
            "average_win_rate": avg_win_rate,
        }

    # ------------------------------------------------------------------
    # Query: Tax ledger summary
    # ------------------------------------------------------------------

    def query_tax(self) -> dict:
        """Return a summary of all recorded tax events.

        Aggregates total tax across all events and breaks down totals by
        TaxComponentType. Returns zero-valued dict if no events recorded.

        Returns:
            Dictionary with event count, total tax, and per-component breakdown.
        """
        events = self.tax_ledger.load_events()
        total_events = len(events)
        if total_events == 0:
            return {
                "total_events": 0,
                "total_tax": 0.0,
                "by_component": {},
            }
        total_tax = round(sum(e.total_tax for e in events), 6)
        by_component: dict[str, float] = {}
        for event in events:
            for component in event.components:
                key = component.component_type.value
                by_component[key] = round(by_component.get(key, 0.0) + component.amount, 6)
        return {
            "total_events": total_events,
            "total_tax": total_tax,
            "by_component": by_component,
        }

    # ------------------------------------------------------------------
    # Zerodha Read-Only Queries
    # ------------------------------------------------------------------

    def _ensure_zerodha_connected(self) -> None:
        """Helper to ensure Zerodha session is connected before making queries."""
        if self.kite_venue.get_status().state != ConnectionState.CONNECTED:
            self.kite_venue.connect()

    def query_zerodha_funds(self) -> dict:
        """Fetch and return Zerodha funds/margins summary."""
        self._ensure_zerodha_connected()
        bal = self.kite_venue.get_account_balance()
        return {
            "venue_id": bal.venue_id,
            "total_equity": bal.total_equity,
            "cash": bal.cash,
            "margin_available": bal.margin_available,
            "margin_used": bal.margin_used,
            "currency": bal.currency
        }

    def query_zerodha_holdings(self) -> list[dict]:
        """Fetch and return Zerodha holdings list."""
        self._ensure_zerodha_connected()
        holdings = self.kite_venue.get_holdings()
        return [
            {
                "symbol": h.instrument.symbol,
                "quantity": h.quantity,
                "average_price": h.average_price,
                "current_price": h.current_price,
                "unrealized_pnl": h.unrealized_pnl
            }
            for h in holdings
        ]

    def query_zerodha_positions(self) -> list[dict]:
        """Fetch and return Zerodha positions list."""
        self._ensure_zerodha_connected()
        positions = self.kite_venue.get_positions()
        return [
            {
                "symbol": p.instrument.symbol,
                "side": p.side.value,
                "quantity": p.quantity,
                "average_price": p.average_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl
            }
            for p in positions
        ]

    def query_zerodha_pnl(self) -> dict:
        """Fetch today's P&L (net unrealized PnL sum across open positions)."""
        self._ensure_zerodha_connected()
        positions = self.kite_venue.get_positions()
        total_pnl = sum(p.unrealized_pnl for p in positions)
        return {
            "total_pnl": round(total_pnl, 2),
            "currency": "INR",
            "position_count": len(positions)
        }

    def query_live_price(self, symbol: str) -> float:
        """Fetch live last traded price for symbol using Kite market data provider."""
        self._ensure_zerodha_connected()
        return self.kite_provider.get_price(symbol)

    def query_account_profile(self) -> dict:
        """Fetch and return Zerodha account profile."""
        self._ensure_zerodha_connected()
        return self.kite_connection.get_kite_client().profile()

    def get_kite_profile(self) -> dict:
        """Fetch and return structured account profile."""
        profile = self.query_account_profile()
        return {
            "user_name": profile.get("user_name", "N/A"),
            "user_id": profile.get("user_id", "N/A"),
            "broker": profile.get("broker", "ZERODHA"),
            "account_type": profile.get("user_type", "individual")
        }

    def get_kite_funds(self) -> dict:
        """Fetch and return structured funds and margin availability."""
        self._ensure_zerodha_connected()
        bal = self.kite_venue.get_account_balance()
        return {
            "available_cash": bal.cash,
            "utilized_margin": bal.margin_used,
            "available_margin": bal.margin_available
        }

    def get_kite_holdings(self) -> list[dict]:
        """Fetch and return structured delivery holdings list."""
        self._ensure_zerodha_connected()
        holdings = self.kite_venue.get_holdings()
        return [
            {
                "symbol": h.instrument.symbol,
                "quantity": h.quantity,
                "average_cost": h.average_price,
                "current_value": round(h.quantity * h.current_price, 2),
                "unrealized_pnl": h.unrealized_pnl
            }
            for h in holdings
        ]

    def get_kite_positions(self) -> list[dict]:
        """Fetch and return structured net open positions list."""
        self._ensure_zerodha_connected()
        positions = self.kite_venue.get_positions()
        return [
            {
                "symbol": p.instrument.symbol,
                "quantity": p.quantity,
                "side": p.side.value,
                "pnl": p.unrealized_pnl
            }
            for p in positions
        ]

    def get_kite_quote(self, symbol: str) -> dict:
        """Fetch latest quote with net change calculations."""
        self._ensure_zerodha_connected()
        client = self.kite_connection.get_kite_client()
        from integrations.data.models import Exchange
        inst = self.kite_provider.resolve_instrument(symbol)
        exchange_str = "NSE" if inst.exchange == Exchange.NSE else "BSE"
        kite_symbol = f"{exchange_str}:{inst.symbol}"
        
        quotes = client.quote([kite_symbol])
        data = quotes.get(kite_symbol, {})
        last_price = float(data.get("last_price", 0.0))
        ohlc = data.get("ohlc", {})
        close = float(ohlc.get("close", 0.0))
        
        change = round(last_price - close, 2) if close > 0 else 0.0
        pct_change = round((change / close) * 100, 2) if close > 0 else 0.0
        
        return {
            "symbol": symbol.upper(),
            "last_traded_price": last_price,
            "change": change,
            "percentage_change": pct_change
        }

    def get_market_status(self) -> dict:
        """Determine if Indian stock market (NSE/BSE) is open based on IST timezone."""
        from integrations.data.models import Exchange
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now + timedelta(hours=5, minutes=30)

        nse_status = self.session_manager.get_exchange_status(Exchange.NSE, utc_now)
        is_open = nse_status == "OPEN"
        reason = "Active trading hours" if is_open else "Outside trading hours"

        exchanges = [Exchange.NSE, Exchange.BSE, Exchange.MCX, Exchange.BINANCE, Exchange.NASDAQ, Exchange.FOREX]
        status_map = {}
        for ex in exchanges:
            status_map[ex.value] = self.session_manager.get_exchange_status(ex, utc_now)

        return {
            "market": "NSE/BSE",
            "status": nse_status,
            "is_open": is_open,
            "time_ist": ist_now.strftime("%Y-%m-%d %H:%M:%S"),
            "exchanges": status_map,
            "reason": reason
        }

    def get_kite_watchlist(self) -> list[str]:
        """Fetch the watchlist symbol list."""
        return self.kite_provider.get_watchlist()

    def start_autonomous_trading(self) -> str:
        """Start background autonomous loop."""
        self.autonomous_bot.start()
        return "Autonomous trading loop started."

    def stop_autonomous_trading(self) -> str:
        """Stop background autonomous loop."""
        self.autonomous_bot.stop()
        return "Autonomous trading loop stopped."

    def get_autonomous_trading_status(self) -> dict:
        """Return execution mode and loop active status."""
        return {
            "is_active": self.autonomous_bot.is_active(),
            "execution_mode": self.context.execution_mode.value,
            "active_venue_id": self.context.active_venue_id,
            "watchlist": self.autonomous_bot.watchlist,
            "scan_interval": self.autonomous_bot.scan_interval,
            "scan_mode": self.autonomous_bot.scan_mode,
        }

    def get_daily_summary_report(self) -> dict:
        """Generate EOD daily summary briefing."""
        report = self.autonomous_bot.generate_daily_report()
        return {
            "date": report.date,
            "realized_pnl": report.realized_pnl,
            "unrealized_pnl": report.unrealized_pnl,
            "win_rate": report.win_rate,
            "portfolio_allocation": report.portfolio_allocation,
            "trades_taken": list(report.trades_taken),
            "exits_executed": list(report.exits_executed),
            "market_summary": report.market_summary,
            "lessons_learned": report.lessons_learned,
        }

    def get_morning_briefing(self) -> str:
        """Generate pre-market morning intelligence briefing, refreshing Layer 2 caches first."""
        self.run_layer2_intelligence_cycle()
        return self.autonomous_bot.briefing_generator.generate_morning_briefing(
            self.autonomous_bot.scan_mode, self.autonomous_bot.scan_constraints
        )

    def get_daily_briefing_report(self) -> str:
        """Generate formatted EOD briefing markdown report."""
        report = self.autonomous_bot.generate_daily_report()
        return self.autonomous_bot.briefing_generator.generate_daily_briefing(report)

    def run_eod_learning(self) -> dict:
        """Run close of day learning analyzer."""
        return self.autonomous_bot.learning_loop.run_close_of_day_learning()

    def set_autonomous_mode(self, mode: str, constraints: Any = None) -> str:
        """Set autonomous scan constraint mode dynamically."""
        self.autonomous_bot.scan_mode = mode.upper()
        self.autonomous_bot.scan_constraints = constraints
        return f"Autonomous scan mode changed to {mode.upper()}."

    def run_layer2_intelligence_cycle(self) -> str:
        """Execute Layer 2 Deep Intelligence calculations (RSS news, geopolitics, sector rotation, analogs, predictive models)."""
        # 1. Scanner indices
        self.autonomous_bot.scanner.scan_indices()
        # 2. News feeds
        news_events = self.autonomous_bot.news_engine.fetch_news_events()
        # 3. Geopolitical impacts
        self.autonomous_bot.geo_engine.assess_geopolitical_impact()
        # 4. Sector rotation
        from bots.autonomous.sector_rotation import SectorRotationEngine
        s_rot = SectorRotationEngine(self, self.autonomous_bot.cache)
        s_rot.compute_rotation()
        # 5. Analogs
        risk = self.autonomous_bot.cache.read_intelligence("risk_state.json")
        primary_event = risk.get("active_geopolitical_assessments", [{}])[0]
        self.autonomous_bot.analog_engine.find_analogs(
            event_category=primary_event.get("category", "MACRO"),
            sentiment_score=primary_event.get("sentiment_score", 0.0),
            vix_impact_delta=primary_event.get("vix_impact_delta", 0.0)
        )
        # 6. Run new Predictive Intelligence Layer models
        regime_data = self.autonomous_bot.regime_engine.classify_regime()
        event_impacts = self.autonomous_bot.event_predictor.predict_event_impact(news_events)
        flow_forecast = self.autonomous_bot.sector_forecast_engine.forecast_flows(regime_data, event_impacts)
        
        # 7. Portfolio metrics, health, trust score, and capital preservation evaluations
        portfolio_metrics = self.autonomous_bot.portfolio_intel.compute_portfolio_metrics()
        accuracy_data = self.autonomous_bot.cache.read_intelligence("prediction_accuracy.json")
        win_rate = accuracy_data.get("overall_accuracy", 100.0)
        
        # Trust score
        self.autonomous_bot.trust_engine.calculate_trust_score(
            prediction_accuracy=win_rate,
            drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0)
        )
        
        # Preservation
        vix_delta = risk.get("vix_impact_delta", 0.0)
        preservation_data = self.autonomous_bot.preservation_engine.evaluate_risk_profile(
            drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0),
            vix_impact_delta=vix_delta
        )
        
        # 8. Conviction and No-Trade decision precomputations
        # Use a default conviction calculation for general status
        primary_event_sentiment = primary_event.get("sentiment_score", 0.0)
        analog_sim = primary_event_sentiment * 100.0 if primary_event_sentiment >= 0 else (1.0 + primary_event_sentiment) * 100.0
        
        conv_res = self.autonomous_bot.conviction_engine.calculate_conviction(
            market_regime_score=regime_data.get("confidence", 0.82),
            sector_rotation_strength=0.05,
            analog_similarity=analog_sim,
            news_sentiment_confidence=event_impacts.get("confidence", 0.70),
            backtest_win_rate=60.0,
            prediction_accuracy=win_rate,
            vix_impact_delta=vix_delta
        )
        
        self.autonomous_bot.no_trade_engine.evaluate_no_trade(
            conviction_score=conv_res["score"],
            analog_similarity=analog_sim,
            vix_impact_delta=vix_delta,
            history_accuracy=win_rate
        )

        # 9. Force opportunity discovery rankings precomputations
        self.autonomous_bot.discovery_engine.discover_opportunities(
            self.autonomous_bot.scan_mode, self.autonomous_bot.scan_constraints
        )
        
        return "Layer 2 intelligence precomputations complete."

    def run_performance_improvement_cycle(self) -> list[dict]:
        """Run EOD performance drift analysis and generate advisory proposals."""
        proposals = self.improvement_bot.generate_improvement_proposals()
        return [p for p in proposals]

    def get_improvement_proposals(self) -> list[dict]:
        """Load all improvement proposals from the ledger."""
        return self.improvement_bot.load_proposals()

    def apply_improvement_proposal(self, proposal_id: str) -> bool:
        """Apply a specific improvement proposal. Uses the Commander name from profile."""
        from hokage.memory.profile import ProfileService
        profile_service = ProfileService(self.resolver)
        profile = profile_service.get_profile()
        commander_name = f"{profile.commander_title} {profile.commander_name}"
        return self.improvement_bot.apply_improvement_proposal(proposal_id, commander_name)

    def analyze_strategy_drift(self, strategy_id: str, asset: str) -> dict:
        """Run drift analysis on a strategy-asset pair."""
        return self.improvement_bot.analyze_performance_drift(strategy_id, asset)

    def run_reconciliation(self, account_id: str = "paper", auto_recover: bool = True, target_symbol: str | None = None) -> dict:
        """Execute the reconciliation engine and return the report summary."""
        # Retrieve active venue based on context
        active_venue_id = self.context.active_venue_id
        try:
            venue = self.registry.get_venue(active_venue_id)
        except Exception:
            venue = self.paper_venue  # fallback

        from shared.reconciliation.engine import ReconciliationEngine
        from bots.autonomous.decision_journal import DecisionJournalSystem
        decision_journal = DecisionJournalSystem(self.resolver)

        engine = ReconciliationEngine(
            venue=venue,
            portfolio_store=self.portfolio_store,
            trade_store=self.trade_store,
            decision_journal=decision_journal,
            resolver=self.resolver
        )
        report = engine.reconcile(account_id=account_id, auto_recover=auto_recover, target_symbol=target_symbol)
        return report.to_dict()


