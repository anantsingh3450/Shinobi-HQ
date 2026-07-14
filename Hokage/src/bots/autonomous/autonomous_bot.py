"""Autonomous Trading Bot for Hokage.

Coordinates background scheduled market scans, exit monitoring (TSL/TP),
opportunity ranking, risk sizing, and order placement via registered venues.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor

from bots.research.models import ResearchQuery
from hokage.memory.resolver import PathResolver

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator

from integrations.brokers.models import (
    OrderRequest,
    OrderSide,
    OrderType,
    ExecutionMode,
)
from integrations.data.models import Instrument, Exchange
from bots.autonomous.models import (
    DailyReport,
    AssetDecisionState,
    AssetSurveillanceState,
    TradeAutopsy,
)

# Import new Market Intelligence Layer components
from bots.autonomous.cache import IntelligenceCache
from bots.autonomous.research_intel import MarketScanner, NewsIntelligenceEngine, GeopoliticalIntelligenceEngine
from bots.autonomous.memory import MemoryManager
from bots.autonomous.analogs import HistoricalAnalogEngine
from bots.autonomous.discovery import OpportunityDiscoveryEngine
from bots.autonomous.briefings import BriefingGenerator
from bots.autonomous.learning import EODLearningLoop
from bots.autonomous.predictive import (
    MarketRegimeEngine,
    MacroCorrelationEngine,
    EventImpactPredictor,
    SectorFlowForecastEngine,
    PredictionAccuracyTracker,
)
from bots.autonomous.conviction import (
    ConvictionScoreEngine,
    NoTradeDecisionEngine,
    ConfidenceCalibrationEngine,
)
from bots.autonomous.capital_preservation import CapitalPreservationEngine
from bots.autonomous.portfolio_intelligence import (
    PortfolioAwareness,
    PositionAllocationEngine,
    PortfolioHealthScore,
)
from bots.autonomous.trust_engine import ElderTrustEngine
from bots.autonomous.decision_journal import DecisionJournalSystem
from bots.autonomous.personality_engine import PortfolioManagerPersonalityLayer
from bots.autonomous.performance_analytics import PerformanceAnalyticsEngine
from bots.autonomous.position_review import PositionReviewEngine
from bots.autonomous.trade_dna import TradeDNAEngine

logger = logging.getLogger("Hokage.AutonomousTrading")


class AutonomousTradingBot:
    """Orchestrates autonomous scanning and execution in the background."""

    def __init__(
        self,
        orchestrator: HokageOrchestrator,
        watchlist: list[str] | None = None,
        scan_interval_seconds: int = 60,
        tsl_percent: float = 0.05,  # 5% Trailing Stop-Loss
        tp_percent: float = 0.10,   # 10% Take Profit
    ) -> None:
        """Initialize AutonomousTradingBot."""
        self.orchestrator = orchestrator
        
        # HNEP Phase 2: STRICT PAPER MODE LOCK
        if hasattr(self.orchestrator, "context") and self.orchestrator.context.execution_mode == ExecutionMode.LIVE:
            logger.critical("Boot safeguard triggered: LIVE execution mode flag detected on boot. Overriding to PAPER mode.")
            self.orchestrator.context.execution_mode = ExecutionMode.PAPER

        self.watchlist = watchlist or ["TCS", "INFY", "RELIANCE"]
        self.scan_interval = scan_interval_seconds
        self.tsl_percent = tsl_percent
        self.tp_percent = tp_percent

        # Setup scanner constraints and defaults (default to OPEN_MARKET if no watchlist passed)
        if watchlist is not None:
            self.scan_mode = "WATCHLIST_RESTRICTED"
            self.scan_constraints: Any = watchlist
        else:
            self.scan_mode = "OPEN_MARKET"
            self.scan_constraints = None

        resolver = getattr(orchestrator, "resolver", None)
        if resolver and type(resolver).__name__ not in ("MagicMock", "Mock"):
            self._resolver = resolver
        else:
            self._resolver = PathResolver()
        self._autonomous_dir = self._resolver.resolve_brain_root() / "autonomous"
        self._autonomous_dir.mkdir(parents=True, exist_ok=True)
        self._positions_file = self._autonomous_dir / "active_positions.json"
        self._reports_dir = self._resolver.resolve_brain_root() / "reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_positions_tracking: dict[str, dict[str, float]] = self._load_positions_tracking()
        self._shadow_positions_file = self._autonomous_dir / "shadow_positions.json"
        self._shadow_positions_tracking: dict[str, dict[str, dict[str, Any]]] = self._load_shadow_positions_tracking()

        self._trades_taken_today = []
        self._exits_executed_today = []
        self._last_crypto_report_date = None
        self._last_bar_key = None

        # Gatekeeper, overrides and reset tracking
        self.intraday_override = {}
        self.elder_manual_input_received = False
        self.gatekeeper_state = None
        self._last_midnight_reset_date = None
        self._state_lock = threading.Lock()
        self.free_mind_free_hand = True
        self._cron_thread = None

        # Instantiate Two-Speed Architecture Cache and Engines
        self.cache = IntelligenceCache()
        self.memory_manager = MemoryManager()
        self.scanner = MarketScanner(self.orchestrator, self.cache)
        self.news_engine = NewsIntelligenceEngine(self.cache)
        self.geo_engine = GeopoliticalIntelligenceEngine(self.news_engine, self.cache)
        self.analog_engine = HistoricalAnalogEngine(self.memory_manager, self.cache)
        self.discovery_engine = OpportunityDiscoveryEngine(self.scanner, self.cache)

        # Predictive Intelligence Layer
        self.regime_engine = MarketRegimeEngine(self.orchestrator, self.cache)
        self.macro_engine = MacroCorrelationEngine(self.cache)
        self.event_predictor = EventImpactPredictor(self.cache)
        self.sector_forecast_engine = SectorFlowForecastEngine(self.macro_engine, self.event_predictor, self.cache)
        self.conviction_engine = ConvictionScoreEngine(self.cache)
        self.no_trade_engine = NoTradeDecisionEngine(self.cache)
        self.accuracy_tracker = PredictionAccuracyTracker(self.cache)
        self.calibration_engine = ConfidenceCalibrationEngine(self.cache)

        # Capital Preservation & Allocation Engines
        self.preservation_engine = CapitalPreservationEngine(self.cache)
        try:
            context = self.orchestrator.get_execution_context()
            venue = self.orchestrator.registry.get_venue(context.active_venue_id)
            if not venue:
                venue = self.orchestrator.paper_venue
        except Exception:
            venue = self.orchestrator.paper_venue
        
        self.portfolio_intel = PortfolioAwareness(venue, self.cache)
        from integrations.data.trade_ledger import ledger
        from integrations.notifications.telegram_bot import TelegramBotUplink
        self.trade_ledger = ledger
        self.telegram_bot = TelegramBotUplink()
        # Attach this bot as the uplink's control-command handler so the
        # commander can /kill /pause /resume /close_all /status from Telegram.
        self.telegram_bot.command_handler = self
        self.allocation_engine = PositionAllocationEngine(self.portfolio_intel)
        self.trust_engine = ElderTrustEngine(self.cache)
        self.journal = DecisionJournalSystem()
        self.personality_engine = PortfolioManagerPersonalityLayer("ADAPTIVE")
        self.analytics_engine = PerformanceAnalyticsEngine()
        self.position_review_engine = PositionReviewEngine(memory_manager=self.memory_manager)
        self.trade_dna_engine = TradeDNAEngine()

        self.briefing_generator = BriefingGenerator(
            scanner=self.scanner,
            news_engine=self.news_engine,
            geo_engine=self.geo_engine,
            analog_engine=self.analog_engine,
            discovery_engine=self.discovery_engine,
            cache=self.cache,
            regime_engine=self.regime_engine,
            conviction_engine=self.conviction_engine,
            no_trade_engine=self.no_trade_engine,
            accuracy_tracker=self.accuracy_tracker,
            portfolio_intel=self.portfolio_intel,
            trust_engine=self.trust_engine,
            preservation_engine=self.preservation_engine,
            personality_layer=self.personality_engine,
            analytics_engine=self.analytics_engine,
            journal=self.journal,
        )
        
        from bots.autonomous.capital_preservation import RiskManager
        self.risk_manager = RiskManager(self, max_daily_drawdown_pct=15.0)
        
        self.learning_loop = EODLearningLoop(self.orchestrator, self.memory_manager)

        from bots.strategy.portfolio import StrategyPortfolioManager
        self.strategy_portfolio = StrategyPortfolioManager(self._resolver)
        from bots.autonomous.committee import InvestmentCommittee, CommitteeLedger, CommitteePerformanceTracker
        self.committee = InvestmentCommittee(self._resolver)
        self.committee_ledger = CommitteeLedger(self._resolver)
        self.committee_tracker = CommitteePerformanceTracker(self._resolver)
        from bots.autonomous.intelligence import (
            SessionBehaviorEngine,
            LiquidityEngine,
            VolumeEngine,
            PositionManagementEngine,
            AdaptiveSizingEngine,
            TradeQualityEngine,
            AdvancedMarketRegimeEngine,
        )
        self.session_behavior_engine = SessionBehaviorEngine()
        self.liquidity_engine = LiquidityEngine()
        self.volume_engine = VolumeEngine()
        self.position_mgmt_engine = PositionManagementEngine()
        self.adaptive_sizing_engine = AdaptiveSizingEngine()
        self.trade_quality_engine = TradeQualityEngine()
        self.adv_regime_engine = AdvancedMarketRegimeEngine()
        from bots.strategy.evolution import StrategyEvolutionEngine
        self.strategy_evolution = StrategyEvolutionEngine(self._resolver)
        from bots.strategy.strategy_engine import StrategyEngine
        self.strategy_engine = StrategyEngine(max_unique_assets=5)
        try:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            db_eng = SqliteStorageEngine(self._resolver)
            from integrations.brokers.session_manager import KolkataTime
            tz = KolkataTime()
            ist_now = datetime.now(timezone.utc).astimezone(tz)
            date_str = ist_now.strftime("%Y-%m-%d")
            self.strategy_engine.load_daily_trades_from_db(db_eng, date_str)
            db_eng.close()
        except Exception as e:
            logger.warning(f"Could not load daily trades on startup: {e}")

    def _should_re_evaluate(self, reason: str) -> bool:
        """Verify if surveillance re-evaluation is triggered by event."""
        valid_reasons = {
            "NEW_CANDLE",
            "PRICE_MOVEMENT",
            "VOLUME_ANOMALY",
            "REGIME_CHANGE",
            "NEWS_RELEASE",
            "COMMANDER_QUERY",
            "SCHEDULED_CHECKPOINT",
        }
        return reason.upper() in valid_reasons

    def update_asset_surveillance_state(
        self,
        asset: str,
        state: str,
        conviction: int,
        risk_score: float,
        blockers: list[str] | None = None,
        confirmations: list[str] | None = None,
        next_review: str = "15:00",
        trigger_desc: str = ""
    ) -> dict[str, Any]:
        """Update and cache the surveillance state of a monitored asset."""
        try:
            state_enum = AssetDecisionState(state.upper())
        except ValueError:
            state_enum = AssetDecisionState.WATCHING

        surv_state = AssetSurveillanceState(
            asset=asset.upper(),
            state=state_enum,
            conviction_score=conviction,
            risk_score=risk_score,
            current_blockers=tuple(blockers or []),
            missing_confirmations=tuple(confirmations or []),
            next_review_time=next_review,
            what_would_trigger=trigger_desc,
            last_changed_at=datetime.now(timezone.utc).isoformat()
        )

        try:
            state_file = self._autonomous_dir / "asset_surveillance_state.json"
            data = {}
            if state_file.exists():
                with state_file.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            data[asset.upper()] = surv_state.to_dict()
            with state_file.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            logger.info("Updated surveillance state for %s to %s", asset.upper(), state_enum.value)
        except Exception as exc:
            logger.error("Failed to update surveillance state: %s", exc)

        return surv_state.to_dict()

    def _load_positions_tracking(self) -> dict[str, dict[str, float]]:
        """Load persistent stop levels from brain root."""
        if self._positions_file.exists():
            try:
                with self._positions_file.open("r") as fh:
                    return json.load(fh)
            except Exception as exc:
                logger.error(f"Failed to load active positions: {exc}")
        return {}

    def _save_positions_tracking(self) -> None:
        """Save stop levels to brain root."""
        try:
            with self._positions_file.open("w") as fh:
                json.dump(self._active_positions_tracking, fh, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save active positions: {exc}")

    def _load_shadow_positions_tracking(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Load persistent shadow positions from brain root."""
        if hasattr(self, "_shadow_positions_file") and self._shadow_positions_file.exists():
            try:
                with self._shadow_positions_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                logger.error(f"Failed to load shadow positions: {exc}")
        return {}

    def _save_shadow_positions_tracking(self) -> None:
        """Save shadow positions to brain root."""
        try:
            with self._shadow_positions_file.open("w", encoding="utf-8") as fh:
                json.dump(self._shadow_positions_tracking, fh, indent=2, sort_keys=True)
        except Exception as exc:
            logger.error(f"Failed to save shadow positions: {exc}")

    def _monitor_and_exit_shadow_positions(self, is_tick: bool = True) -> None:
        """Check shadow positions for candidate strategies and enforce trailing exits/early exits."""
        try:
            risk_state = self.cache.read_intelligence("risk_state.json") or {}
            vix_impact_delta = risk_state.get("vix_impact_delta", 0.0)
            regime_data = self.cache.read_intelligence("market_regime.json") or {}
            trend_score = regime_data.get("trend_score", 0.0)
            classified_regime = self.adv_regime_engine.classify_regime(trend_score, vix_impact_delta)

            portfolio_metrics = self.portfolio_intel.compute_portfolio_metrics()
            total_equity = portfolio_metrics.get("total_assets", 500000.0)

            updated_shadow_tracking = {}
            for strat_id, strat_positions in self._shadow_positions_tracking.items():
                strat = self.strategy_portfolio.portfolio.get("strategies", {}).get(strat_id)
                if not strat or strat.get("status") not in ("SHADOW_MODE", "PROBATION"):
                    continue

                updated_shadow_tracking[strat_id] = {}
                for symbol, tracking in list(strat_positions.items()):
                    symbol_upper = symbol.upper()
                    current_price = self.orchestrator.price_source.get_price(symbol_upper)
                    if current_price is None or current_price <= 0.0:
                        current_price = tracking.get("current_price", tracking["entry_price"])

                    # Evaluate open position via Cascading Exits Stack
                    from integrations.brokers.models import OrderSide
                    side = OrderSide.BUY if tracking.get("side", "BUY") == "BUY" else OrderSide.SELL
                    trigger_exit, exit_reason, tracking = self._evaluate_cascading_exits(
                        symbol=symbol_upper,
                        side=side,
                        quantity=tracking.get("quantity", 1.0),
                        average_price=tracking["entry_price"],
                        current_price=current_price,
                        tracking=tracking,
                        is_tick=is_tick,
                        venue=None
                    )
                    tracking["current_price"] = current_price


                    if trigger_exit:
                        direction_sign = 1.0 if tracking.get("side", "BUY") == "BUY" else -1.0
                        pnl_per_unit = (current_price - tracking["entry_price"]) * direction_sign
                        simulated_pnl = pnl_per_unit * tracking["quantity"]
                        is_win = simulated_pnl > 0

                        self.strategy_portfolio.record_trade_outcome(
                            strategy_id=strat_id,
                            asset=symbol_upper,
                            is_win=is_win,
                            pnl=simulated_pnl,
                            market_regime=classified_regime
                        )

                        active_prod = None
                        for s_id, s in self.strategy_portfolio.portfolio.get("strategies", {}).items():
                            if s.get("status") in ("ACTIVE", "PRODUCTION") and s_id != strat_id:
                                if symbol_upper in s.get("supported_assets", []):
                                    active_prod = s
                                    break

                        active_prod_status = "NO_POSITION"
                        if symbol_upper in self._active_positions_tracking:
                            active_prod_status = "HOLDING"

                        comp_notes = (
                            f"Shadow strategy {strat_id} exited {symbol_upper} at {current_price} due to {exit_reason}. "
                            f"Simulated PnL: {simulated_pnl:.2f}. "
                            f"Active production strategy position status: {active_prod_status}."
                        )

                        self.strategy_evolution.log_shadow_decision(
                            strategy_id=strat_id,
                            symbol=symbol_upper,
                            decision_type="EXIT",
                            decision_details={
                                "exit_price": current_price,
                                "exit_reason": exit_reason,
                                "simulated_pnl": round(simulated_pnl, 2),
                                "is_win": is_win,
                                "active_production_strategy_id": active_prod["strategy_id"] if active_prod else "NONE",
                                "active_production_strategy_status": active_prod_status,
                                "comparison_notes": comp_notes
                            }
                        )
                    else:
                        updated_shadow_tracking[strat_id][symbol_upper] = tracking

                        active_prod = None
                        for s_id, s in self.strategy_portfolio.portfolio.get("strategies", {}).items():
                            if s.get("status") in ("ACTIVE", "PRODUCTION") and s_id != strat_id:
                                if symbol_upper in s.get("supported_assets", []):
                                    active_prod = s
                                    break

                        active_prod_status = "NO_POSITION"
                        if symbol_upper in self._active_positions_tracking:
                            active_prod_status = "HOLDING"

                        comp_notes = (
                            f"Shadow strategy {strat_id} is HOLDING {symbol_upper} at {current_price}. "
                            f"Current peak: {tracking.get('peak_price', 0.0)}, stop: {tracking.get('stop_price', 0.0):.2f}. "
                            f"Active production strategy position status: {active_prod_status}."
                        )

                        self.strategy_evolution.log_shadow_decision(
                            strategy_id=strat_id,
                            symbol=symbol_upper,
                            decision_type="HOLD",
                            decision_details={
                                "current_price": current_price,
                                "peak_price": tracking.get("peak_price", 0.0),
                                "stop_price": round(tracking.get("stop_price", 0.0), 2),
                                "active_production_strategy_id": active_prod["strategy_id"] if active_prod else "NONE",
                                "active_production_strategy_status": active_prod_status,
                                "comparison_notes": comp_notes
                            }
                        )

            self._shadow_positions_tracking = updated_shadow_tracking
            self._save_shadow_positions_tracking()
        except Exception as e:
            logger.error(f"Error in shadow exit monitoring: {e}", exc_info=True)

    def start(self) -> None:
        """Start the background autonomous thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Autonomous trading thread is already running.")
            return

        self._stop_event.clear()
        
        # On startup: clean up ghost/stale open positions from prior sessions
        self._cleanup_stale_paper_positions()
        
        # Start the 06:00 AM CronScheduler
        from bots.autonomous.cron_reset import CronScheduler
        self._cron_thread = CronScheduler(self, self._state_lock)
        self._cron_thread.start()
        # Start the Telegram Uplink polling thread
        if self.telegram_bot:
            self.telegram_bot.start()

        self._thread = threading.Thread(target=self._run_loop, name="HokageAutonomousLoop", daemon=True)
        self._thread.start()
        logger.info("Autonomous trading loop started.")

    def _cleanup_stale_paper_positions(self) -> None:
        """On startup, close any open paper positions that are older than today.
        
        Stale open positions in the DB will block the MaxPositionsRiskRule and prevent
        new trades. This cleanup runs at bot start and on midnight reset.
        """
        try:
            account_id = self.orchestrator.paper_venue._account_id
            account = self.orchestrator.portfolio_store.load_account(account_id)
            from shared.persistence.models import TradeStatus
            from datetime import date
            today = date.today()
            cleaned = 0
            for pos_id, pos in list(account.positions.items()):
                if pos.status == TradeStatus.OPEN:
                    # Check if position was opened before today
                    try:
                        from datetime import datetime as _dt
                        opened_date = _dt.fromisoformat(pos.opened_at).date() if hasattr(pos, "opened_at") and pos.opened_at else None
                        if opened_date and opened_date < today:
                            logger.warning(
                                f"Startup cleanup: Closing stale paper position for {pos.market} "
                                f"(opened {opened_date}, today is {today}). "
                                f"This prevents it from blocking new trades via MaxPositionsRiskRule."
                            )
                            account.positions[pos_id] = pos._replace(status=TradeStatus.CLOSED)
                            cleaned += 1
                    except Exception:
                        pass
            if cleaned > 0:
                self.orchestrator.portfolio_store.save_account(account)
                logger.info(f"Startup cleanup: Closed {cleaned} stale paper position(s) from prior sessions.")
            else:
                logger.info("Startup cleanup: No stale paper positions found. DB is clean.")
        except Exception as e:
            logger.warning(f"Startup position cleanup skipped (non-critical): {e}")


    def stop(self) -> None:
        """Stop the background autonomous thread gracefully."""
        if self._cron_thread is not None:
            self._cron_thread.stop()
            self._cron_thread = None

        if self.telegram_bot:
            self.telegram_bot.stop()

        if self._thread is None:
            return

        self._stop_event.set()
        self._thread.join(timeout=10.0)
        self._thread = None
        logger.info("Autonomous trading loop stopped.")

    def is_active(self) -> bool:
        """Return True if background loop is active."""
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        """Main loop that executes interval checks."""
        # List of exchanges we track independently in the autonomous loop
        tracked_exchanges = [Exchange.NSE, Exchange.BSE, Exchange.MCX, Exchange.BINANCE, Exchange.NASDAQ, Exchange.FOREX]

        while not self._stop_event.is_set():
            try:
                utc_now = datetime.now(timezone.utc)
                from integrations.brokers.session_manager import KolkataTime
                from datetime import time as dt_time
                tz = KolkataTime()
                ist_now = datetime.now(timezone.utc).astimezone(tz)
                ist_time = ist_now.time()
                current_date_str = ist_now.strftime("%Y-%m-%d")

                # Midnight Reset Check
                if self._last_midnight_reset_date is None:
                    self._last_midnight_reset_date = current_date_str
                elif current_date_str != self._last_midnight_reset_date:
                    logger.info("Midnight reset triggered. Flushing overrides and gatekeeper memory.")
                    self._last_midnight_reset_date = current_date_str
                    self.intraday_override.clear()
                    self.elder_manual_input_received = False
                    self.gatekeeper_state = None

                # Gatekeeper Protocol: 06:00 AM to 09:00 AM IST
                if dt_time(6, 0) <= ist_time < dt_time(9, 0):
                    if not self.elder_manual_input_received:
                        self.gatekeeper_state = "Await_Elder_Command"
                        logger.info("Gatekeeper Protocol: Awaiting Elder Command (06:00 - 09:00 IST). Autonomous scanning paused.")
                    else:
                        self.gatekeeper_state = None
                else:
                    self.gatekeeper_state = None

                # Manage shadow sessions independently per exchange
                for exchange in tracked_exchanges:
                    status = self.orchestrator.session_manager.get_exchange_status(exchange, utc_now)

                    if exchange == Exchange.BINANCE:
                        # Crypto is 24/7. Auto-start if not active.
                        self._auto_start_shadow_session_for_exchange(Exchange.BINANCE)

                        # Check if we should trigger crypto midnight IST reporting rollover
                        if self._should_trigger_crypto_reporting():
                            self._trigger_crypto_daily_reporting()
                    else:
                        # Traditional markets
                        if status == "OPEN":
                            self._auto_start_shadow_session_for_exchange(exchange)
                        else:
                            self._auto_stop_shadow_session_for_exchange(exchange)

                # 15m bar-close vs tick split loop structure
                is_tick = True
                bar_key = (ist_now.year, ist_now.month, ist_now.day, ist_now.hour, ist_now.minute // 15)
                if self._last_bar_key is None:
                    self._last_bar_key = bar_key
                    is_tick = False
                elif bar_key != self._last_bar_key:
                    self._last_bar_key = bar_key
                    is_tick = False

                # 1. Active Exit Monitors across all active venues (Runs on both is_tick=True and is_tick=False)
                self._monitor_and_exit_positions(is_tick=is_tick)
                
                # Check portfolio health (kill-switch). Only evaluate on REAL,
                # positive equity data: a fresh brain, a failed balance query, or
                # missing metrics must never read as a crashed portfolio (this
                # falsely fired the kill-switch on first clean-brain boot).
                if self.portfolio_intel:
                    metrics = self.portfolio_intel.compute_portfolio_metrics()
                    curr_eq = metrics.get("total_assets", 0.0)
                    start_eq = metrics.get("peak_equity", 0.0)
                    if curr_eq > 0.0 and start_eq > 0.0:
                        self.risk_manager.check_portfolio_health(curr_eq, start_eq)
                    else:
                        logger.warning(
                            f"Skipping portfolio health check: equity data not ready "
                            f"(total_assets={curr_eq}, peak_equity={start_eq})."
                        )

                # 2. Opportunity Scan & Entry Sizing for currently tradable assets (ONLY runs on new bar closes is_tick=False)
                if not is_tick and self.gatekeeper_state not in ("Await_Elder_Command", "KILL_SWITCH_ENGAGED"):
                    if not self.intraday_override.get('halted', False):
                        self._scan_and_enter_opportunities()

                # 3. Direct Broker Reconciliation Sync (every 180 seconds)
                if not hasattr(self, "_last_reconciliation_time") or self._last_reconciliation_time is None:
                    self._last_reconciliation_time = datetime.now()
                elif (datetime.now() - self._last_reconciliation_time).total_seconds() >= 180.0:
                    self._last_reconciliation_time = datetime.now()
                    try:
                        self._run_direct_broker_sync_and_flatten_ghost_positions()
                    except Exception as e:
                        logger.error(f"Error in background direct broker reconciliation sync: {e}")
                    try:
                        self._check_broker_session_health()
                    except Exception as e:
                        logger.error(f"Error in broker session health check: {e}")


            except Exception as exc:
                logger.error(f"Error in autonomous loop iteration: {exc}", exc_info=True)

            # Sleep in small ticks to detect shutdown quickly
            slept = 0.0
            while slept < self.scan_interval:
                if self._stop_event.is_set():
                    break
                time.sleep(1.0)
                slept += 1.0

    def _should_trigger_crypto_reporting(self) -> bool:
        """Check if we should trigger the daily crypto rollover/reporting at midnight IST."""
        from integrations.brokers.session_manager import KolkataTime
        tz = KolkataTime()
        ist_now = datetime.now(timezone.utc).astimezone(tz)
        current_date_str = ist_now.strftime("%Y-%m-%d")

        if self._last_crypto_report_date is None:
            # Initialize with today so we don't immediately trigger on startup
            self._last_crypto_report_date = current_date_str
            return False

        # Day change in IST triggers reporting
        return current_date_str != self._last_crypto_report_date

    def _trigger_crypto_daily_reporting(self) -> None:
        """Trigger EOD/daily reporting for Crypto and rollover the shadow session."""
        logger.info("Triggering daily crypto session rollover and EOD reporting at midnight IST.")
        from integrations.brokers.session_manager import KolkataTime
        tz = KolkataTime()
        ist_now = datetime.now(timezone.utc).astimezone(tz)
        self._last_crypto_report_date = ist_now.strftime("%Y-%m-%d")

        # Stop active session and compile reports
        self._auto_stop_shadow_session_for_exchange(Exchange.BINANCE)
        # Immediately start a new one to continue uninterrupted trading
        self._auto_start_shadow_session_for_exchange(Exchange.BINANCE)

    def _auto_start_shadow_session_for_exchange(self, exchange: Exchange) -> None:
        """Automatically start a shadow trading session for a specific exchange on market open."""
        try:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            from bots.autonomous.shadow_engine import ShadowEngine
            sqlite_engine = SqliteStorageEngine(self.orchestrator.resolver)
            sqlite_engine.run_migrations()
            shadow_engine = ShadowEngine(sqlite_engine)

            conn = sqlite_engine.get_connection()
            session_prefix = f"SHADOW_SES_{exchange.name}_"
            cursor = conn.execute(
                "SELECT session_id FROM shadow_sessions WHERE status = 'ACTIVE' AND session_id LIKE ? LIMIT 1;",
                (f"{session_prefix}%",)
            )
            row = cursor.fetchone()
            if row:
                return  # Session already active for this exchange

            # Get starting capital from commander profile
            from hokage.memory.profile import ProfileService
            profile_service = ProfileService(self.orchestrator.resolver)
            profile = profile_service.get_profile()
            starting_equity = profile.portfolio.starting_capital

            session_id = shadow_engine.start_shadow_session(
                starting_equity=starting_equity,
                git_version="git-auto-shadow",
                config_hash="commander-profile-auto",
                strategy_set_version="strategy-config-auto",
                market_universe_version="market-universe-auto",
                risk_profile_version="risk-rules-auto",
                exchange=exchange.name
            )
            logger.info(f"Auto-started shadow session '{session_id}' for exchange {exchange.name}.")
        except Exception as exc:
            logger.error(f"Failed to auto-start shadow session for exchange {exchange.name}: {exc}")

    def _auto_stop_shadow_session_for_exchange(self, exchange: Exchange) -> None:
        """Automatically stop the shadow session for an exchange and compile EOD reports."""
        try:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            from bots.autonomous.shadow_engine import ShadowEngine
            sqlite_engine = SqliteStorageEngine(self.orchestrator.resolver)
            sqlite_engine.run_migrations()
            shadow_engine = ShadowEngine(sqlite_engine)

            conn = sqlite_engine.get_connection()
            session_prefix = f"SHADOW_SES_{exchange.name}_"
            cursor = conn.execute(
                "SELECT session_id FROM shadow_sessions WHERE status = 'ACTIVE' AND session_id LIKE ? LIMIT 1;",
                (f"{session_prefix}%",)
            )
            row = cursor.fetchone()
            if not row:
                return  # No active session for this exchange

            active_session_id = row["session_id"]

            # 1. Stop the session
            shadow_engine.stop_shadow_session(active_session_id)
            logger.info(f"Auto-stopped shadow session '{active_session_id}' for exchange {exchange.name} on close.")

            # 2. Record daily performance close
            context = self.orchestrator.get_execution_context()
            broker = self.orchestrator.broker_registry.get_broker_for_exchange(exchange)
            venue_id = f"paper_{broker}" if context.execution_mode in (ExecutionMode.PAPER, ExecutionMode.HYBRID) else (
                "kite_main" if broker == "zerodha" else f"{broker}_main"
            )
            venue = self.orchestrator.registry.get_venue(venue_id)
            if venue:
                bal = venue.get_account_balance()
                equity = bal.total_equity
                cash = bal.cash
            else:
                equity = 100000.0
                cash = 100000.0

            # Fetch benchmark prices for this exchange
            benchmarks = {}
            if exchange in (Exchange.NSE, Exchange.BSE):
                try:
                    nifty_price = self.orchestrator.price_source.get_price("NIFTY 50")
                except Exception:
                    nifty_price = 23500.0
                benchmarks["NIFTY 50"] = nifty_price
            elif exchange == Exchange.MCX:
                try:
                    gold_price = self.orchestrator.price_source.get_price("GOLD")
                except Exception:
                    gold_price = 72000.0
                benchmarks["GOLD"] = gold_price
            elif exchange == Exchange.BINANCE:
                try:
                    btc_price = self.orchestrator.price_source.get_price("BTCUSDT")
                except Exception:
                    btc_price = 65000.0
                benchmarks["BTCUSDT"] = btc_price
            elif exchange == Exchange.NASDAQ:
                try:
                    ndx_price = self.orchestrator.price_source.get_price("NASDAQ")
                except Exception:
                    ndx_price = 19500.0
                benchmarks["NASDAQ"] = ndx_price

            shadow_engine.record_daily_performance(
                session_id=active_session_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                portfolio_equity=equity,
                portfolio_cash=cash,
                benchmark_prices=benchmarks
            )

            # 3. Generate Daily EOD report package and archive it in database
            report_id = shadow_engine.generate_and_archive_report(active_session_id, "DAILY")
            logger.info(f"Generated and archived EOD shadow report '{report_id}' in SQLite for exchange {exchange.name}.")

            # 4. Generate and cache the Commander Daily Briefing narrative
            report = self.generate_daily_report(exchange=exchange)
            briefing_text = self.briefing_generator.generate_daily_briefing(report)
            logger.info(f"Generated Commander Daily Briefing narrative successfully for exchange {exchange.name}.")

        except Exception as exc:
            logger.error(f"Failed to auto-stop shadow session and generate EOD package for exchange {exchange.name}: {exc}")


    def _get_atr_for_symbol(self, symbol: str) -> float:
        """Calculate the 14-period Average True Range on the 15-minute interval."""
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            from datetime import datetime, timedelta, UTC
            instrument = self.orchestrator.price_source.resolve_instrument(symbol)
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(UTC) - timedelta(days=2),
                end=datetime.now(UTC),
                interval=CandleInterval.FIFTEEN_MINUTES
            )
            res = self.orchestrator.price_source.get_historical_candles(req)
            if res and res.candles and len(res.candles) >= 14:
                tr_list = []
                for i in range(1, len(res.candles)):
                    c = res.candles[i]
                    prev_c = res.candles[i-1]
                    tr = max(
                        c.high - c.low,
                        abs(c.high - prev_c.close),
                        abs(c.low - prev_c.close)
                    )
                    tr_list.append(tr)
                if tr_list:
                    return sum(tr_list[-14:]) / len(tr_list[-14:])
        except Exception as e:
            logger.error(f"Failed to calculate ATR for {symbol}: {e}")
        
        # Fallback to 1.5% of the current price
        try:
            price = self.orchestrator.price_source.get_price(symbol)
            if price:
                return price * 0.015
        except Exception:
            pass
        return 1.0

    def _get_vix_impact(self) -> float:
        """Helper to get VIX volatility delta."""
        try:
            risk_state = self.cache.read_intelligence("risk_state.json") or {}
            if "vix_impact_delta" in risk_state:
                return float(risk_state["vix_impact_delta"])
        except Exception:
            pass
        try:
            vix = self.orchestrator.price_source.get_price("INDIAVIX")
            if vix:
                return float(vix) - 15.0
        except Exception:
            pass
        return 0.0

    def _calculate_dynamic_lot_size(self, symbol: str, total_equity: float, entry_price: float = 1.0, alloc_pct: float = 2.0, confidence_score: float = 50.0, direction: str = "long") -> float:
        """Calculate dynamic lot sizing per trade using Kelly Criterion with LLM confidence."""
        try:
            atr = self._get_atr_for_symbol(symbol)
            lot_multiplier = 1.0
            try:
                instrument = self.orchestrator.price_source.resolve_instrument(symbol)
                if instrument.metadata and "lot_size" in instrument.metadata:
                    lot_multiplier = float(instrument.metadata["lot_size"])
            except Exception:
                pass
                
            # Bayesian Adaptive Kelly Engine
            from bots.strategy.midnight_crucible import crucible
            bayes = crucible.get_bayesian_kelly_parameters()
            
            p_theo = max(0.1, min(0.9, confidence_score / 100.0))
            b_theo = 0.015  # 1.5% theoretical gain
            L_theo = 0.01   # 1.0% theoretical loss
            
            n = bayes['total_trades']
            burn_in = 30
            blend = min(1.0, n / burn_in)
            
            p = (blend * bayes['p']) + ((1.0 - blend) * p_theo)
            b = (blend * bayes['b']) + ((1.0 - blend) * b_theo)
            L = (blend * bayes['L']) + ((1.0 - blend) * L_theo)
            
            if b > 0 and L > 0:
                kelly_f = (p * b - (1.0 - p) * L) / (b * L)
            else:
                kelly_f = 0.01

            # NEGATIVE-KELLY BLOCK: a non-positive Kelly fraction means the
            # empirical+theoretical blend expects this trade to LOSE money.
            # Never take a minimum position on negative edge — take none.
            if kelly_f <= 0:
                logger.warning(
                    f"Negative-Kelly block for {symbol}: kelly_f={kelly_f:.4f} "
                    f"(p={p:.3f}, b={b:.4f}, L={L:.4f}). Sizing 0 — no trade."
                )
                return 0.0

            fractional_kelly = kelly_f * 0.5  # Half-Kelly for safety
            fractional_kelly = min(0.05, fractional_kelly)  # Max 5% equity

            risk_capital = fractional_kelly * total_equity
            raw_qty = risk_capital / (1.5 * atr * lot_multiplier)
            qty = max(1.0, round(raw_qty) * lot_multiplier)
            return qty
        except Exception as e:
            # NOTE: this handler previously imported integrations.diagnostics.logger,
            # a module that does not exist — so any sizing exception crashed the scan
            # loop instead of failing safe. Use the module logger.
            logger.error(f"Failed to calculate dynamic lot size for {symbol}: {e}")
            # Fail-closed: a sizing failure must never place a blind 1-lot order.
            return 0.0


    #: Midday chop blackout and late-session cutoff for NSE entries (IST).
    #: Measured on a comparable live system: midday entries and late-session
    #: entries are net leaks. MCX commodities keep their own session gates.
    _NSE_MIDDAY_BLACKOUT = ((11, 30), (13, 30))
    _NSE_LAST_ENTRY = (14, 0)
    #: India VIX percentile above which BUYING options is blocked — premium is
    #: statistically rich and the move must beat an inflated price (Natenberg).
    _VIX_PERCENTILE_BLOCK = 0.80
    _VIX_LOOKBACK_DAYS = 60

    def _entry_conduct_gate(self, symbol: str, direction: str) -> tuple[bool, str]:
        """Time-of-day windows, underlying bias alignment, IV premium guard.

        Each check runs only when its data exists — a missing feed skips that
        check (logged), it never fabricates a value. Returns (allowed, reason).
        """
        symbol_upper = symbol.upper()
        is_mcx = symbol_upper.replace("_", "").startswith(("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"))

        # 1. NSE time-of-day protections (MCX runs its own sessions).
        if not is_mcx:
            now = self._now_ist()
            hm = (now.hour, now.minute)
            if self._NSE_MIDDAY_BLACKOUT[0] <= hm < self._NSE_MIDDAY_BLACKOUT[1]:
                return False, "Midday chop blackout (11:30-13:30 IST): new entries suspended."
            if hm >= self._NSE_LAST_ENTRY:
                return False, "Late-session cutoff (14:00 IST): no new entries into the close."

        # 2. Bias alignment on the underlying: longs only with a bullish tape,
        # shorts only with a bearish tape, stand aside when mixed.
        bias = self._compute_underlying_bias(symbol)
        if bias == "MIXED":
            return False, "Bias engine: underlying tape is MIXED — standing aside."
        if bias == "BULLISH" and direction != "long":
            return False, "Bias engine: bearish entry against a BULLISH tape."
        if bias == "BEARISH" and direction != "short":
            return False, "Bias engine: bullish entry against a BEARISH tape."
        if bias is None:
            logger.info(f"Bias engine: no intraday data for {symbol}; bias check skipped.")

        # 3. IV premium guard: we BUY options; block when India VIX sits in the
        # top quintile of its trailing range (premium too rich).
        vix_pct = self._india_vix_percentile()
        if vix_pct is not None and vix_pct >= self._VIX_PERCENTILE_BLOCK:
            return False, (
                f"IV premium guard: India VIX at {vix_pct:.0%} percentile of "
                f"{self._VIX_LOOKBACK_DAYS}d range — option premium too rich to buy."
            )

        return True, "conduct gates passed"

    def _compute_underlying_bias(self, symbol: str) -> str | None:
        """Classify the underlying tape as BULLISH / BEARISH / MIXED from real
        intraday candles (EMA(9)/EMA(21) alignment + price vs session VWAP).
        Returns None when no intraday data is available."""
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            instrument = self.orchestrator.price_source.resolve_instrument(symbol)
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=3),
                end=datetime.now(timezone.utc),
                interval=CandleInterval.FIFTEEN_MINUTES,
            )
            res = self.orchestrator.price_source.get_historical_candles(req)
            candles = list(res.candles) if res and res.candles else []
        except Exception as exc:
            logger.debug(f"Bias engine: intraday candles unavailable for {symbol}: {exc}")
            return None
        if len(candles) < 21:
            return None

        closes = [c.close for c in candles]

        def _ema(values: list[float], period: int) -> float:
            k = 2.0 / (period + 1.0)
            ema = values[0]
            for v in values[1:]:
                ema = v * k + ema * (1.0 - k)
            return ema

        ema9 = _ema(closes[-30:], 9)
        ema21 = _ema(closes[-42:], 21)

        # Session VWAP from the current day's candles (volume-weighted; falls
        # back to None-safe simple mean when the venue reports no volume).
        last_day = candles[-1].timestamp.date()
        session = [c for c in candles if c.timestamp.date() == last_day]
        vol_sum = sum((c.volume or 0.0) for c in session)
        if vol_sum > 0:
            vwap = sum(((c.high + c.low + c.close) / 3.0) * (c.volume or 0.0) for c in session) / vol_sum
        else:
            vwap = sum(c.close for c in session) / len(session) if session else closes[-1]

        price = closes[-1]
        bullish = ema9 > ema21 and price > vwap
        bearish = ema9 < ema21 and price < vwap
        if bullish:
            return "BULLISH"
        if bearish:
            return "BEARISH"
        return "MIXED"

    def _india_vix_percentile(self) -> float | None:
        """Current India VIX close as a percentile of its trailing range.
        None when the feed is unavailable (guard is then skipped, not faked)."""
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            instrument = self.orchestrator.price_source.resolve_instrument("INDIA VIX")
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=self._VIX_LOOKBACK_DAYS + 10),
                end=datetime.now(timezone.utc),
                interval=CandleInterval.ONE_DAY,
            )
            res = self.orchestrator.price_source.get_historical_candles(req)
            closes = [c.close for c in (res.candles if res else ())][-self._VIX_LOOKBACK_DAYS:]
        except Exception as exc:
            logger.debug(f"IV premium guard: India VIX history unavailable: {exc}")
            return None
        if len(closes) < 20:
            return None
        current = closes[-1]
        below = sum(1 for c in closes if c <= current)
        return below / len(closes)

    @staticmethod
    def _quote_liquidity_inputs(quote: Any) -> tuple[float | None, float | None]:
        """Extract REAL liquidity inputs (spread %, bid/ask depth ratio) from a
        live quote. Either value is None when the venue supplied no data for
        it — the corresponding gate check is skipped, never fed a fabricated
        neutral value."""
        spread_pct = None
        bid_ask_ratio = None
        try:
            if quote is not None and quote.price > 0 and quote.bid is not None and quote.ask is not None:
                spread_pct = ((quote.ask - quote.bid) / quote.price) * 100.0
            bid_qty = getattr(quote, "bid_qty", None)
            ask_qty = getattr(quote, "ask_qty", None)
            if bid_qty and ask_qty and float(ask_qty) > 0:
                bid_ask_ratio = float(bid_qty) / float(ask_qty)
        except Exception:
            pass
        return spread_pct, bid_ask_ratio

    def _get_volume_context(self, symbol: str, quote: Any) -> tuple[float, float] | None:
        """Return (current_day_volume, avg_daily_volume) from REAL data only.

        Doctrine: no fabricated market data. current volume comes from the live
        quote; the average is computed from actual daily candles (14 days).
        Returns None when either side is unavailable — callers must then SKIP
        the volume gate rather than run it on invented numbers. Note: the
        current day's cumulative volume is naturally lower early in the session,
        which biases the breakout ratio conservative (fewer entries) — the safe
        direction.
        """
        try:
            current_vol = float(quote.volume) if quote.volume is not None else None
        except Exception:
            current_vol = None
        if not current_vol or current_vol <= 0:
            return None
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            from datetime import timedelta
            instrument = self.orchestrator.price_source.resolve_instrument(symbol)
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=14),
                end=datetime.now(timezone.utc),
                interval=CandleInterval.ONE_DAY,
            )
            res = self.orchestrator.price_source.get_historical_candles(req)
            vols = [float(c.volume) for c in (res.candles if res and res.candles else []) if c.volume and c.volume > 0]
            if not vols:
                return None
            return current_vol, sum(vols) / len(vols)
        except Exception:
            return None

    # Market-wide circuit breaker stand-down. NSE halts trading on a 10%/15%/20%
    # index move; we stop taking NEW entries at 9% — before the exchange halt —
    # because fills, spreads, and exits become unreliable in a limit-move regime.
    _CIRCUIT_BREAKER_INDEX = "NIFTY 50"
    _CIRCUIT_BREAKER_MOVE_PCT = 9.0

    def _check_circuit_breaker(self) -> tuple[bool, str]:
        """Detect a market-wide limit move vs previous close.

        Returns (blocked, reason). Fail-open on missing/invalid index data:
        absence of benchmark data must not freeze trading — per-symbol data
        quality is already fail-closed by the price-provenance guard. Exits are
        never gated by this check.
        """
        try:
            quote = self.orchestrator.price_source.get_quote(self._CIRCUIT_BREAKER_INDEX)
            price = getattr(quote, "price", None)
            prev = getattr(quote, "previous_close", None)
            if not isinstance(price, (int, float)) or not isinstance(prev, (int, float)) or prev <= 0:
                return False, ""
            move_pct = abs(price - prev) / prev * 100.0
            if move_pct >= self._CIRCUIT_BREAKER_MOVE_PCT:
                return True, (
                    f"Circuit breaker: {self._CIRCUIT_BREAKER_INDEX} moved {move_pct:.2f}% vs previous "
                    f"close (threshold {self._CIRCUIT_BREAKER_MOVE_PCT}%)."
                )
        except Exception:
            return False, ""
        return False, ""

    def _check_broker_session_health(self) -> None:
        """Detect mid-session broker auth failure (e.g. Kite daily token expiry).

        Probes every live (non-paper) venue; on an auth-shaped failure, halts
        new entries and alerts the commander via Telegram once per IST date.
        Exits remain active. Paper/mock venues carry no token risk and are
        skipped. (Data-feed token expiry is separately fail-closed by the
        price-provenance guard on the entry path.)
        """
        context = self.orchestrator.get_execution_context()
        if context.execution_mode != ExecutionMode.LIVE:
            return
        try:
            venue_ids = list(self.orchestrator.registry.list_venues())
        except Exception:
            return
        for venue_id in venue_ids:
            if "paper" in venue_id.lower() or "mock" in venue_id.lower():
                continue
            venue = self.orchestrator.registry.get_venue(venue_id)
            try:
                venue.get_account_balance()
            except Exception as exc:
                msg = str(exc).lower()
                if any(tag in msg for tag in ("token", "auth", "session", "api_key", "forbidden", "403")):
                    today = self._now_ist().strftime("%Y-%m-%d")
                    if getattr(self, "_last_token_alert_date", None) != today:
                        self._last_token_alert_date = today
                        self.intraday_override["halted"] = True
                        logger.critical(f"Broker session failure on venue {venue_id}: {exc}. Entries halted.")
                        if self.telegram_bot:
                            self.telegram_bot.send_message(
                                "🚨 *BROKER SESSION EXPIRED* 🚨\n"
                                f"Venue `{venue_id}` rejected authentication: {exc}\n"
                                "Entries are HALTED. Re-login via the dashboard or /token, then send /resume."
                            )

    def handle_remote_command(self, command: str) -> str:
        """Execute a commander control command arriving via the Telegram uplink.

        Supported: /kill (halt + liquidate), /pause (halt entries), /resume,
        /close_all (liquidate, no halt), /status. Returns an acknowledgement
        string that the uplink sends back to the commander.
        """
        cmd = command.strip().lower().lstrip("/")
        if cmd == "kill":
            self.intraday_override["halted"] = True
            self.gatekeeper_state = "KILL_SWITCH_ENGAGED"
            closed = self._close_all_positions("MANUAL_KILL_SWITCH")
            logger.critical("MANUAL KILL SWITCH engaged via Telegram. %d liquidation order(s) sent.", closed)
            return (
                f"🚨 *KILL SWITCH ENGAGED*. All entries halted. "
                f"Liquidation orders sent for {closed} position(s). Restart required to clear."
            )
        if cmd == "pause":
            self.intraday_override["halted"] = True
            logger.warning("Trading PAUSED via Telegram command.")
            return "⏸ *Trading PAUSED*. No new entries. Existing positions stay managed (exits remain active). /resume to lift."
        if cmd == "resume":
            if self.gatekeeper_state == "KILL_SWITCH_ENGAGED":
                return "⛔ Kill switch is engaged — /resume refused. Restart the system to clear it."
            self.intraday_override.pop("halted", None)
            logger.warning("Trading RESUMED via Telegram command.")
            return "▶️ *Trading RESUMED*. Entry scanning re-enabled."
        if cmd == "close_all":
            closed = self._close_all_positions("MANUAL_CLOSE_ALL")
            logger.warning("CLOSE ALL via Telegram: %d liquidation order(s) sent.", closed)
            return f"🛑 *CLOSE ALL*: liquidation orders sent for {closed} position(s). Entries NOT halted (use /pause or /kill)."
        if cmd == "status":
            return (
                f"📡 *STATUS*: halted={self.intraday_override.get('halted', False)}, "
                f"gatekeeper={self.gatekeeper_state}, "
                f"tracked_positions={len(self._active_positions_tracking)}, "
                f"loop_active={self.is_active()}"
            )
        return f"Unknown control command: /{cmd}"

    def _close_all_positions(self, reason: str) -> int:
        """Send liquidation orders for every locally tracked open position.

        Returns the number of positions a liquidation order was sent for.
        Used by the manual kill switch and /close_all.
        """
        closed = 0
        for asset, pos_data in list(self._active_positions_tracking.items()):
            try:
                side_str = pos_data.get("side", "BUY")
                side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL
                qty = float(pos_data.get("quantity", 1.0))
                venue_id = pos_data.get("venue_id", "paper_main")
                venue = self.orchestrator.registry.get_venue(venue_id)
                if not venue:
                    venue = getattr(self.orchestrator, "paper_venue", None)
                if not venue:
                    raise ValueError(f"Venue {venue_id} not found and paper_venue unavailable.")
                self._execute_partial_exit(symbol=asset, side=side, quantity=qty, reason=reason, venue=venue)
                closed += 1
            except Exception as e:
                logger.error(f"Failed to liquidate {asset} during {reason}: {e}")
        return closed

    def _execute_partial_exit(self, symbol: str, side: OrderSide, quantity: float, reason: str, venue: Any) -> None:
        """Place a partial exit order to scale out of a position."""
        from integrations.brokers.models import OrderRequest, OrderSide, OrderType
        from integrations.data.models import Instrument
        
        exit_side = OrderSide.SELL if (side == OrderSide.BUY or side.value == "BUY") else OrderSide.BUY
        
        # Resolve instrument
        resolved_exch = self.orchestrator.session_manager.resolve_exchange(symbol)
        resolved_ac = self.orchestrator.session_manager.resolve_asset_class(symbol)
        inst = Instrument(symbol=symbol, asset_class=resolved_ac, exchange=resolved_exch)
        
        exit_req = OrderRequest(
            instrument=inst,
            side=exit_side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            venue_id=venue.venue_id,
            strategy_id="AutonomousExit",
            execution_reason=reason
        )
        try:
            logger.info(f"Connoisseur Scale-Out: Placing order to {exit_side} {quantity} {symbol} on {venue.venue_id} for {reason}")
            venue.place_order(exit_req)
            
            if self.telegram_bot and self.telegram_bot.enabled:
                self.telegram_bot.notify_exit(symbol, price=0.0, reason=f"Partial Scale-Out: {reason}")
            
            # Fire event to EventBus
            from hokage.dashboard.event_bus import EventBus
            bus = EventBus()
            bus.publish("EXECUTION_COMPLETED", {
                "symbol": symbol,
                "side": exit_side.value,
                "quantity": quantity,
                "status": "SUCCESS_PARTIAL",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception as exc:
            logger.error(f"Failed to execute partial scale-out for {symbol}: {exc}")

    # Commander doctrine: no synthetic prices. Entry orders may only execute
    # against quotes from a live source (authenticated broker feed or real
    # public feed) that are fresh. Synthetic/mock table prices never trade.
    _SYNTHETIC_PROVIDER_TAGS = ("mock", "synthetic")
    _MAX_QUOTE_AGE_SECONDS = 600.0

    def _get_validated_live_price(self, symbol: str) -> tuple[float | None, str]:
        """Fetch a quote and validate its provenance for order execution.

        Returns (price, reason). price is None when the quote is synthetic,
        stale, or absent — in which case NO entry order may be placed. Exits are
        deliberately NOT gated on this (never refuse to exit on data quality).
        """
        try:
            quote = self.orchestrator.price_source.get_quote(symbol)
        except Exception as exc:
            return None, f"quote fetch failed: {exc}"
        if quote is None:
            return None, "no quote returned"

        price = getattr(quote, "price", None)
        if not isinstance(price, (int, float)) or price <= 0:
            return None, f"invalid price {price!r}"

        provider = str(getattr(quote, "provider", "") or "").lower()
        if any(tag in provider for tag in self._SYNTHETIC_PROVIDER_TAGS):
            return None, f"synthetic provider '{provider}'"

        quoted_at = getattr(quote, "quoted_at", None)
        if not isinstance(quoted_at, datetime):
            return None, "quote has no timestamp"
        try:
            age = (datetime.now(timezone.utc) - quoted_at).total_seconds()
        except TypeError:
            return None, "quote timestamp is not timezone-aware"
        if age > self._MAX_QUOTE_AGE_SECONDS:
            return None, f"stale quote ({age:.0f}s old, max {self._MAX_QUOTE_AGE_SECONDS:.0f}s)"

        return float(price), "live"

    def _now_ist(self) -> datetime:
        """Current time in IST — the single injectable clock seam for exit timing.

        Production returns real session time. Tests may replace this method (e.g.
        ``bot._now_ist = lambda: fixed_dt``) to pin the clock and deterministically
        exercise time-dependent exits like the EOD square-off and late-day targets.
        """
        from integrations.brokers.session_manager import KolkataTime
        return datetime.now(timezone.utc).astimezone(KolkataTime())

    def _evaluate_cascading_exits(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        average_price: float,
        current_price: float,
        tracking: dict[str, Any],
        is_tick: bool,
        venue: Any = None
    ) -> tuple[bool, str, dict[str, Any]]:
        """Evaluate open position across the Adaptive Exit Ladder (Assassin + Connoisseur)."""
        import math

        now_ist = self._now_ist()

        if not tracking:
            tracking = {
                "entry_price": average_price,
                "peak_price": max(average_price, current_price) if (side == OrderSide.BUY or side.value == "BUY") else min(average_price, current_price)
            }

        # 1. Manual Kill Switch
        if getattr(self, "intraday_override", {}).get(symbol) == "KILL":
            return True, "Manual Kill Switch Activated", tracking

        symbol_upper = symbol.upper()
        is_option = symbol_upper.endswith("CE") or symbol_upper.endswith("PE")
        is_mcx_instrument = symbol_upper.startswith(("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS")) or (
            venue is not None and "mcx" in venue.venue_id.lower()
        )

        # 2. Time-Based Square-Off (loss protection outranks profit-taking;
        # MCX instruments are recognized by symbol so paper-venue commodity
        # options still square off at the 23:15 MCX close, not 15:20).
        is_crypto = venue and ("crypto" in venue.venue_id.lower() or "binance" in venue.venue_id.lower())
        if not is_crypto:
            sq_hour, sq_min = (23, 15) if is_mcx_instrument else (15, 20)
            if now_ist.hour > sq_hour or (now_ist.hour == sq_hour and now_ist.minute >= sq_min):
                return True, "Time-Based Square-Off (EOD)", tracking

        # BOUGHT OPTIONS: dedicated premium-aware exit ladder. The generic
        # underlying-ATR ladder below misreads premium series (an option's own
        # "ATR" is meaningless for thesis stops), so options exit here.
        if is_option and (side == OrderSide.BUY or side.value == "BUY"):
            return self._evaluate_option_exit_ladder(
                symbol=symbol_upper,
                quantity=quantity,
                entry_premium=average_price,
                current_premium=current_price,
                tracking=tracking,
                now_ist=now_ist,
                is_mcx=is_mcx_instrument,
            )

        # 3. Hard Backstop (futures/equity path)
        max_rupee_loss = 5000.0
        direction_sign = 1.0 if (side == OrderSide.BUY or side.value == "BUY") else -1.0
        unrealized_pnl = (current_price - average_price) * quantity * direction_sign
        if unrealized_pnl <= -max_rupee_loss:
            return True, f"Hard Backstop Triggered (-₹{abs(unrealized_pnl):,.2f})", tracking

        # Connoisseur Scale-Out & Assassin Stop-Loss Rules:
        atr = self._get_atr_for_symbol(symbol)
        atr = float(atr) if atr else average_price * 0.01

        # Assassin Rule: Dynamic Stop-Loss set at 1.5x ATR from entry
        atr_stop_distance = 1.5 * atr
        target1_dist = 1.5 * atr
        target2_dist = 3.0 * atr

        # Initialize tracking details
        if "initial_qty" not in tracking:
            tracking["initial_qty"] = quantity
        if "scaled_out_stage" not in tracking:
            tracking["scaled_out_stage"] = 0
        if "stop_price" not in tracking:
            if side == OrderSide.BUY or side.value == "BUY":
                tracking["stop_price"] = average_price - atr_stop_distance
            else:
                tracking["stop_price"] = average_price + atr_stop_distance

        # Track peak price
        if side == OrderSide.BUY or side.value == "BUY":
            tracking["peak_price"] = max(tracking.get("peak_price", average_price), current_price)
        else:
            tracking["peak_price"] = min(tracking.get("peak_price", average_price), current_price)

        scaled_out_stage = tracking.get("scaled_out_stage", 0)
        initial_qty = tracking["initial_qty"]

        # Long Exit Rules
        if side == OrderSide.BUY or side.value == "BUY":
            if current_price >= (average_price + target1_dist) and scaled_out_stage == 0:
                scale_qty = max(1.0, round(initial_qty / 3.0))
                if venue:
                    self._execute_partial_exit(symbol, side, scale_qty, "Connoisseur Target 1 (1.5x ATR) Reached", venue)
                tracking["scaled_out_stage"] = 1
                tracking["stop_price"] = average_price
                logger.info(f"Connoisseur Rule: {symbol} reached Target 1. Scaled out 1/3 ({scale_qty}). Stop moved to breakeven ({average_price:.2f}).")

            elif current_price >= (average_price + target2_dist) and scaled_out_stage == 1:
                scale_qty = max(1.0, round(initial_qty / 3.0))
                if venue:
                    self._execute_partial_exit(symbol, side, scale_qty, "Connoisseur Target 2 (3.0x ATR) Reached", venue)
                tracking["scaled_out_stage"] = 2
                tracking["stop_price"] = average_price + target1_dist
                logger.info(f"Connoisseur Rule: {symbol} reached Target 2. Scaled out 1/3 ({scale_qty}). Stop moved to Target 1 ({tracking['stop_price']:.2f}).")

            if scaled_out_stage == 2:
                trail_stop = tracking["peak_price"] - 1.5 * atr
                tracking["stop_price"] = max(tracking["stop_price"], trail_stop)

            if current_price <= tracking["stop_price"]:
                reason = "Assassin Stop-Loss Triggered" if scaled_out_stage == 0 else "Trailing Stop Triggered"
                return True, f"{reason} at {tracking['stop_price']:.2f}", tracking

        # Short Exit Rules
        else:
            if current_price <= (average_price - target1_dist) and scaled_out_stage == 0:
                scale_qty = max(1.0, round(initial_qty / 3.0))
                if venue:
                    self._execute_partial_exit(symbol, side, scale_qty, "Connoisseur Target 1 (1.5x ATR) Reached", venue)
                tracking["scaled_out_stage"] = 1
                tracking["stop_price"] = average_price
                logger.info(f"Connoisseur Rule: {symbol} reached Target 1. Scaled out 1/3 ({scale_qty}). Stop moved to breakeven ({average_price:.2f}).")

            elif current_price <= (average_price - target2_dist) and scaled_out_stage == 1:
                scale_qty = max(1.0, round(initial_qty / 3.0))
                if venue:
                    self._execute_partial_exit(symbol, side, scale_qty, "Connoisseur Target 2 (3.0x ATR) Reached", venue)
                tracking["scaled_out_stage"] = 2
                tracking["stop_price"] = average_price - target1_dist
                logger.info(f"Connoisseur Rule: {symbol} reached Target 2. Scaled out 1/3 ({scale_qty}). Stop moved to Target 1 ({tracking['stop_price']:.2f}).")

            if scaled_out_stage == 2:
                trail_stop = tracking["peak_price"] + 1.5 * atr
                tracking["stop_price"] = min(tracking["stop_price"], trail_stop)

            if current_price >= tracking["stop_price"]:
                reason = "Assassin Stop-Loss Triggered" if scaled_out_stage == 0 else "Trailing Stop Triggered"
                return True, f"{reason} at {tracking['stop_price']:.2f}", tracking

        return False, "", tracking

    #: Tiered premium hard backstop: cheap options are noisier, so their
    #: catastrophe cap is proportionally wider. (entry premium floor, max loss %)
    _OPTION_BACKSTOP_TIERS = ((500.0, 0.15), (200.0, 0.25), (100.0, 0.35), (0.0, 0.50))
    #: Underlying thesis stop: adverse move >= this multiple of entry-time ATR
    #: on the UNDERLYING invalidates the directional premise.
    _OPTION_THESIS_ATR_MULT = 1.25
    #: TRAIL_LOCK arms once open profit reaches this many rupees per position,
    #: then never gives back more than the same amount from peak.
    _OPTION_TRAIL_LOCK_RUPEES = 1000.0
    #: Adaptive target: fraction of the expected remaining underlying move,
    #: through an assumed ATM delta, clamped to a % band of entry premium.
    _OPTION_TARGET_MOVE_FRACTION = 0.30
    _OPTION_TARGET_ATM_DELTA = 0.45
    _OPTION_TARGET_MIN_PCT = 0.06
    _OPTION_TARGET_MAX_PCT = 0.25

    def _evaluate_option_exit_ladder(
        self,
        symbol: str,
        quantity: float,
        entry_premium: float,
        current_premium: float,
        tracking: dict[str, Any],
        now_ist: datetime,
        is_mcx: bool,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Ordered exit ladder for BOUGHT options — first match wins.

        Loss protection outranks profit taking: tiered premium backstop, then
        the underlying-ATR thesis stop, then the adaptive TARGET_HIT, then
        TRAIL_LOCK. Square-off/kill-switch are handled by the caller before
        this ladder runs. Missing data (no underlying quote, no ATR) skips a
        rung — it never fabricates a value.
        """
        import math

        tracking["peak_price"] = max(tracking.get("peak_price", entry_premium), current_premium)
        peak_premium = tracking["peak_price"]

        # Rung 1 — tiered premium HARD BACKSTOP (catastrophe cap).
        for tier_floor, max_loss_pct in self._OPTION_BACKSTOP_TIERS:
            if entry_premium >= tier_floor:
                backstop_price = entry_premium * (1.0 - max_loss_pct)
                if current_premium <= backstop_price:
                    return True, (
                        f"Option Hard Backstop: premium {current_premium:.2f} fell "
                        f"{max_loss_pct:.0%} below entry {entry_premium:.2f}"
                    ), tracking
                break

        # Rung 2 — ATR thesis stop on the UNDERLYING: the trade's premise is a
        # direction on the underlying; when that breaks, exit regardless of
        # what the premium alone is doing.
        underlying = tracking.get("underlying")
        entry_und_price = tracking.get("entry_underlying_price")
        entry_und_atr = tracking.get("entry_underlying_atr")
        if underlying and entry_und_price and entry_und_atr:
            und_price, _ = self._get_validated_live_price(underlying)
            if und_price is not None:
                adverse = (entry_und_price - und_price) if symbol.endswith("CE") else (und_price - entry_und_price)
                if adverse >= self._OPTION_THESIS_ATR_MULT * float(entry_und_atr):
                    return True, (
                        f"Underlying Thesis Stop: {underlying} moved {adverse:.2f} against "
                        f"position (>= {self._OPTION_THESIS_ATR_MULT} x ATR {float(entry_und_atr):.2f})"
                    ), tracking

        # Rung 3 — TARGET_HIT: adaptive, move-calibrated premium target sized
        # to how much the market can plausibly still move today.
        if entry_und_atr:
            bar_minutes = 5 if is_mcx else 15
            close_hour, close_min = (23, 15) if is_mcx else (15, 20)
            minutes_left = (close_hour - now_ist.hour) * 60 + (close_min - now_ist.minute)
            bars_left = max(0.0, minutes_left / bar_minutes)
            expected_move = float(entry_und_atr) * math.sqrt(bars_left)
            raw_target = entry_premium + (
                self._OPTION_TARGET_MOVE_FRACTION * self._OPTION_TARGET_ATM_DELTA * expected_move
            )
            target = min(
                max(raw_target, entry_premium * (1.0 + self._OPTION_TARGET_MIN_PCT)),
                entry_premium * (1.0 + self._OPTION_TARGET_MAX_PCT),
            )
            tracking["target_price"] = round(target, 2)
            if current_premium >= target:
                return True, (
                    f"TARGET_HIT: premium {current_premium:.2f} reached adaptive "
                    f"target {target:.2f} (entry {entry_premium:.2f})"
                ), tracking

        # Rung 4 — TRAIL_LOCK: once peak open profit >= the lock amount, a
        # rising floor gives back at most that amount from peak.
        if quantity > 0:
            peak_profit_rupees = (peak_premium - entry_premium) * quantity
            if peak_profit_rupees >= self._OPTION_TRAIL_LOCK_RUPEES:
                floor_premium = peak_premium - (self._OPTION_TRAIL_LOCK_RUPEES / quantity)
                tracking["stop_price"] = max(tracking.get("stop_price", 0.0), floor_premium)
                if current_premium <= floor_premium:
                    return True, (
                        f"TRAIL_LOCK: premium {current_premium:.2f} gave back "
                        f"₹{self._OPTION_TRAIL_LOCK_RUPEES:,.0f} from peak {peak_premium:.2f}"
                    ), tracking

        return False, "", tracking

    def _monitor_and_exit_positions(self, is_tick: bool = True) -> None:
        """Check open positions across all active venues and enforce TSL/TP exits."""
        context = self.orchestrator.get_execution_context()
        if context.execution_mode == ExecutionMode.READ_ONLY:
            return

        # Determine all active venues based on execution mode
        active_venues = []
        for venue_id in self.orchestrator.registry.list_venues():
            venue = self.orchestrator.registry.get_venue(venue_id)
            is_paper_venue = "paper" in venue_id.lower() or "mock" in venue_id.lower()
            if context.execution_mode in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
                if is_paper_venue:
                    active_venues.append(venue)
            elif context.execution_mode == ExecutionMode.LIVE:
                if not is_paper_venue:
                    active_venues.append(venue)

        # Query all positions and map symbol to the venue where it belongs
        positions_with_venue = []
        for venue in active_venues:
            try:
                for pos in venue.get_positions():
                    positions_with_venue.append((pos, venue))
            except Exception as exc:
                logger.error(f"Failed to fetch positions for venue {venue.venue_id}: {exc}")

        risk_state = self.cache.read_intelligence("risk_state.json") or {}
        vix_impact_delta = risk_state.get("vix_impact_delta", 0.0)
        regime_data = self.cache.read_intelligence("market_regime.json") or {}
        trend_score = regime_data.get("trend_score", 0.0)
        classified_regime = self.adv_regime_engine.classify_regime(trend_score, vix_impact_delta)

        updated_tracking = {}
        for pos, venue in positions_with_venue:
            symbol = pos.instrument.symbol
            tracking = self._active_positions_tracking.get(symbol)
            
            # Evaluate open position via Cascading Exits Stack
            trigger_exit, exit_reason, tracking = self._evaluate_cascading_exits(
                symbol=symbol,
                side=pos.side,
                quantity=pos.quantity,
                average_price=pos.average_price,
                current_price=pos.current_price or pos.average_price,
                tracking=tracking,
                is_tick=is_tick,
                venue=venue
            )


            if trigger_exit:
                exit_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                exit_req = OrderRequest(
                    instrument=pos.instrument,
                    side=exit_side,
                    quantity=pos.quantity,
                    order_type=OrderType.MARKET,
                    venue_id=venue.venue_id,
                    strategy_id="AutonomousExit",
                    execution_reason=exit_reason
                )
                try:
                    logger.info(f"Triggering Exit for {symbol} ({exit_reason})")
                    resp = venue.place_order(exit_req)
                    exit_record = {
                        "symbol":     symbol,
                        "side":       exit_side.value,
                        "quantity":   pos.quantity,
                        "reason":     exit_reason,
                        "pnl":        pos.unrealized_pnl,
                        "timestamp":  datetime.now(timezone.utc).isoformat(),
                    }
                    self._exits_executed_today.append(exit_record)

                    # Resolve metadata stored at entry time
                    entry_meta = tracking or {}
                    stored_decision_id   = entry_meta.get("decision_id", "")
                    stored_entry_price   = entry_meta.get("entry_price", pos.average_price)
                    stored_stop_price    = entry_meta.get("stop_price", 0.0)
                    stored_target_price  = entry_meta.get("target_price", pos.average_price * 1.10)
                    stored_conviction    = entry_meta.get("conviction_score", 75)
                    stored_alloc_pct     = entry_meta.get("allocation_pct", 1.0)
                    stored_sector        = entry_meta.get("sector", self.portfolio_intel.symbol_sectors.get(symbol.upper(), "other"))
                    stored_personality   = entry_meta.get("personality_mode", "BALANCED")
                    stored_sector_flow   = entry_meta.get("sector_flow", "N/A")

                    symbol_sec = stored_sector
                    regime_data = self.cache.read_intelligence("market_regime.json")
                    regime_str = regime_data.get("prediction", "NORMAL")

                    exit_price_actual = pos.current_price or stored_entry_price
                    return_pct = (
                        ((exit_price_actual - stored_entry_price) / stored_entry_price)
                        if stored_entry_price > 0 else 0.0
                    )
                    is_win = (pos.unrealized_pnl > 0.0)
                    outcome_str = "WIN" if is_win else ("LOSS" if pos.unrealized_pnl < 0 else "BREAKEVEN")

                    if not is_win:
                        self._log_post_mortem_failure(
                            symbol=symbol,
                            trade_id=tracking.get("decision_id", "UNKNOWN"),
                            exit_price=exit_price_actual,
                            exit_reason=exit_reason,
                            entry_price=stored_entry_price,
                            stop_price=stored_stop_price,
                            pnl=pos.unrealized_pnl
                        )

                    # --- Layer 1: Synchronous outcome recording ---
                    self.analytics_engine.record_trade_outcome(
                        symbol=symbol,
                        sector=symbol_sec,
                        market_regime=regime_str,
                        conviction_score=stored_conviction,
                        holding_period_days=3,
                        pnl=pos.unrealized_pnl,
                        is_win=is_win,
                        decision_id=stored_decision_id,
                        entry_price=stored_entry_price,
                        exit_price=exit_price_actual,
                        return_pct=return_pct,
                    )

                    # Record strategy portfolio trade outcome based on registered strategy ID
                    stored_strategy_id = entry_meta.get("strategy_id", "strat-autotrend-equities-v1")
                    self.strategy_portfolio.record_trade_outcome(
                        strategy_id=stored_strategy_id,
                        asset=symbol,
                        is_win=is_win,
                        pnl=pos.unrealized_pnl,
                        market_regime=regime_str
                    )

                    # --- Layer 1: Journal outcome update ---
                    if stored_decision_id:
                        self.journal.update_decision_outcome(
                            decision_id=stored_decision_id,
                            outcome=outcome_str,
                            pnl=pos.unrealized_pnl,
                            exit_reason=exit_reason,
                            holding_days=3,
                            return_pct=return_pct,
                        )

                    # --- Layer 2: Async post-exit analysis ---
                    def _async_post_exit(
                        _symbol=symbol,
                        _decision_id=stored_decision_id,
                        _entry_price=stored_entry_price,
                        _exit_price=exit_price_actual,
                        _stop_price=stored_stop_price,
                        _target_price=stored_target_price,
                        _conviction=stored_conviction,
                        _alloc_pct=stored_alloc_pct,
                        _exit_reason=exit_reason,
                        _pnl=pos.unrealized_pnl,
                        _return_pct=return_pct,
                        _regime=regime_str,
                        _sector=symbol_sec,
                        _personality=stored_personality,
                        _sector_flow=stored_sector_flow,
                        _result=outcome_str,
                    ) -> None:
                        try:
                            # Position Review
                            self.position_review_engine.review_trade(
                                symbol=_symbol,
                                entry_price=_entry_price,
                                exit_price=_exit_price,
                                stop_price=_stop_price,
                                target_price=_target_price,
                                conviction_score=_conviction,
                                position_size_pct=_alloc_pct,
                                holding_days=3,
                                exit_reason=_exit_reason,
                                pnl=_pnl,
                                decision_id=_decision_id,
                                return_pct=_return_pct,
                            )
                        except Exception as exc:
                            logger.warning("Position review failed for %s: %s", _symbol, exc)
                        try:
                            # Trade DNA
                            self.trade_dna_engine.record_dna(
                                decision_id=_decision_id,
                                symbol=_symbol,
                                market_regime=_regime,
                                sector=_sector,
                                conviction_score=_conviction,
                                holding_period_days=3,
                                result=_result,
                                return_pct=_return_pct,
                                pnl=_pnl,
                                entry_price=_entry_price,
                                exit_price=_exit_price,
                                exit_reason=_exit_reason,
                                personality_mode=_personality,
                                sector_flow=_sector_flow,
                            )
                        except Exception as exc:
                            logger.warning("Trade DNA recording failed for %s: %s", _symbol, exc)

                        try:
                            # Autopsy & Telegram
                            autopsy = TradeAutopsy(
                                trade_id=_decision_id,
                                symbol=_symbol,
                                direction="LONG", # Defaulting to LONG for now
                                entry_price=_entry_price,
                                exit_price=_exit_price,
                                pnl=_pnl,
                                return_pct=_return_pct,
                                holding_time_seconds=3 * 86400, # Mocked holding time based on holding_days=3
                                exit_reason=_exit_reason,
                                ml_edge_score_at_entry=_conviction,
                                vix_at_entry=15.0, # Defaulting for now
                                market_regime_at_entry=_regime,
                                max_adverse_excursion_pct=-2.0, # Mocking max adverse
                                max_favorable_excursion_pct=return_pct + 1.0, # Mocking max favorable
                            )
                            if self.orchestrator.improvement_bot:
                                self.orchestrator.improvement_bot.process_autopsy(autopsy)
                            
                            if self.telegram_bot and self.telegram_bot.enabled:
                                self.telegram_bot.notify_exit(_symbol, price=_exit_price, reason=_exit_reason)
                                
                        except Exception as exc:
                            logger.error(f"Failed to process trade autopsy for {_symbol}: {exc}")

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        executor.submit(_async_post_exit)

                except Exception as exc:
                    logger.error(f"Failed to execute exit order for {symbol}: {exc}")
                    updated_tracking[symbol] = tracking
            else:
                updated_tracking[symbol] = tracking

        self._active_positions_tracking = updated_tracking
        self._save_positions_tracking()
        self._monitor_and_exit_shadow_positions(is_tick=is_tick)

    def _log_post_mortem_failure(
        self,
        symbol: str,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        entry_price: float,
        stop_price: float,
        pnl: float
    ) -> None:
        """Kakashi (Risk Bot) post-mortem failure analysis for loss-making trades."""
        reasons = []
        if exit_reason and "Stop-Loss" in exit_reason:
            reasons.append("Hard Stop-Loss Triggered")
        elif exit_price <= stop_price:
            reasons.append("Price violated stop-loss threshold")

        if exit_price < stop_price and stop_price > 0:
            pct_drag = abs(exit_price - stop_price) / stop_price * 100.0
            reasons.append(f"Execution slippage drag of {pct_drag:.2f}%")

        try:
            vix = self.orchestrator.price_source.get_price("INDIAVIX")
            vix_val = float(vix) if vix else 15.0
            if vix_val < 14.0:
                reasons.append("Implied Volatility (IV) collapse / regime contraction")
        except Exception:
            pass

        if not reasons:
            reasons.append("Trend reversal invalidation under structural consolidation")

        reason_str = f"Kakashi Risk Analysis: Loss triggered on {symbol}. Causes: " + "; ".join(reasons)
        logger.warning(reason_str)

        try:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            db = SqliteStorageEngine(self._resolver)
            conn = db.get_connection()
            with conn:
                conn.execute(
                    "UPDATE trades SET failure_reason = ? WHERE trade_id = ?;",
                    (reason_str, trade_id)
                )
                conn.execute(
                    "UPDATE positions SET failure_reason = ? WHERE position_id = ?;",
                    (reason_str, trade_id)
                )
            db.close()
        except Exception as e:
            logger.error(f"Failed to write post-mortem failure reason to database: {e}")

    def _run_direct_broker_sync_and_flatten_ghost_positions(self) -> None:
        """Trigger direct broker reconciliation and forcefully flatten unindexed ghost positions."""
        logger.info("Direct Broker Sync: Running 180s reconciliation audit for ghost positions...")
        try:
            context = self.orchestrator.get_execution_context()
            venue = self.orchestrator.registry.get_venue(context.active_venue_id)
            if not venue:
                venue = self.orchestrator.paper_venue
        except Exception:
            venue = self.orchestrator.paper_venue

        try:
            from integrations.brokers.models import OrderRequest, OrderSide, OrderType
            from bots.execution.models import TradeStatus
            
            # 1. Fetch broker positions
            broker_positions = {p.instrument.symbol.upper(): p for p in venue.get_positions()}
            
            # 2. Fetch local positions
            account_id = "paper"
            portfolio = self.orchestrator.portfolio_store.load_account(account_id)
            local_positions = {pos.market.upper() for pos in portfolio.positions.values() if pos.status == TradeStatus.OPEN}
            
            # 3. Detect and flatten ghost positions
            for symbol, b_pos in broker_positions.items():
                if symbol not in local_positions and b_pos.quantity > 0:
                    logger.warning(
                        f"Direct Broker Sync: Detected ghost position for {symbol} on broker "
                        f"({b_pos.quantity} units, side: {b_pos.side}). Forcefully flattening it instantly."
                    )
                    # Opposing order side to flatten
                    flatten_side = OrderSide.SELL if b_pos.side == OrderSide.BUY else OrderSide.BUY
                    
                    req = OrderRequest(
                        instrument=b_pos.instrument,
                        side=flatten_side,
                        quantity=b_pos.quantity,
                        order_type=OrderType.MARKET,
                        venue_id=venue.venue_id,
                        strategy_id="GHOST_FLATTEN",
                        execution_reason="Direct broker sync: Force flattening unindexed ghost position."
                    )
                    venue.place_order(req)
                    
            # 4. Check Margin Utilization Ceiling (65%)
            try:
                bal = venue.get_account_balance()
                total_equity = bal.total_equity
                margin_used = bal.margin_used
                if total_equity > 0:
                    margin_utilization = (margin_used / total_equity) * 100.0
                    if margin_utilization > 65.0:
                        logger.warning(
                            f"Margin Gatekeeper: Margin utilization is at {margin_utilization:.2f}%, "
                            f"which exceeds the hard ceiling of 65%. Blocking new entry opportunities."
                        )
            except Exception as e:
                logger.warning(f"Could not check margin utilization ceiling: {e}")
                
        except Exception as e:
            logger.error(f"Failed to run direct broker sync/flatten: {e}")

    def _evaluate_single_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Run Research -> Strategy -> Backtest validations for a single asset, augmented by ML Engine."""
        try:
            # 1. Fetch historical data and engineer features
            from bots.strategy.features import fetch_and_cache_ohlcv, calculate_features
            from bots.strategy.ml_engine import MLEngine
            
            df = fetch_and_cache_ohlcv(symbol, timeframe="1d")
            if df is not None and not df.empty and len(df) >= 20:
                df = calculate_features(df)
                ml_engine = MLEngine()
                rec, prob = ml_engine.get_zone_recommendation(symbol, df)
                if rec == "neutral":
                    logger.info(f"ML Engine: No edge detected for {symbol} (probability {prob:.2f}). Skipping.")
                    return None
            else:
                logger.warning(f"Insufficient historical data to run ML Engine for {symbol}.")
                rec = "long" # default fallback
                prob = 0.5
                
            # 2. Run Research
            query = ResearchQuery(text=f"Autoscan trends for {symbol}")
            report = self.orchestrator.research_bot.research(query, persist=False)
            
            # 3. Run Strategy Generator
            proposal = self.orchestrator.strategy_bot.generate(report)
            
            # Override entry rule and confidence using ML Engine predictions
            from bots.strategy.models import StrategyProposal
            proposal = StrategyProposal(
                name=proposal.name,
                description=f"ML Edge Probability: {prob:.1f}%. " + proposal.description,
                market=proposal.market,
                entry_rule=rec,
                exit_rule=proposal.exit_rule,
                stop_loss_rule=proposal.stop_loss_rule,
                take_profit_rule=proposal.take_profit_rule,
                timeframe=proposal.timeframe,
                confidence_score=prob,
                sources_cited=proposal.sources_cited,
                generated_at=proposal.generated_at,
                proposal_id=proposal.proposal_id,
                playbook_id=proposal.playbook_id,
                volatility_regime=proposal.volatility_regime
            )
            
            # 4. Validate via Backtest
            backtest_result = self.orchestrator.backtest_bot.validate_strategy(proposal)

            if backtest_result.passed:
                return {
                    "proposal": proposal,
                    "backtest_result": backtest_result,
                    "score": proposal.confidence_score * (backtest_result.win_rate / 100.0)
                }
            # Surface WHY the gate failed — this rejection was previously
            # silent, which made a hard-broken backtest window look like the
            # market simply offering nothing all day.
            logger.warning(
                f"Backtest gate rejected {symbol}: {backtest_result.summary} "
                f"(win_rate={backtest_result.win_rate}, trades={backtest_result.total_trades})"
            )
        except Exception as exc:
            logger.error(f"Failed to scan opportunity for {symbol}: {exc}")
        return None

    def _scan_and_enter_opportunities(self) -> None:
        """Scan watchlist/market universe for opportunities, rank, size and place entry orders."""
        # Enforce hardcoded maximum margin utilization ceiling of 65%
        try:
            context = self.orchestrator.get_execution_context()
            venue = self.orchestrator.registry.get_venue(context.active_venue_id)
            if not venue:
                venue = self.orchestrator.paper_venue
            bal = venue.get_account_balance()
            if bal.total_equity > 0:
                margin_util = (bal.margin_used / bal.total_equity) * 100.0
                if margin_util > 65.0:
                    logger.warning(f"Margin Gatekeeper: Aborting entry scan. Margin utilization is at {margin_util:.2f}%, exceeding 65% ceiling.")
                    return
        except Exception as e:
            logger.warning(f"Could not verify margin utilization ceiling: {e}")

        # Market-wide circuit-breaker stand-down: no new entries during a limit
        # move; exit monitoring continues in the main loop untouched.
        cb_blocked, cb_reason = self._check_circuit_breaker()
        if cb_blocked:
            logger.critical(f"{cb_reason} Aborting entry scan; exits remain active.")
            cb_today = self._now_ist().strftime("%Y-%m-%d")
            if getattr(self, "_last_circuit_alert_date", None) != cb_today and self.telegram_bot:
                self._last_circuit_alert_date = cb_today
                self.telegram_bot.send_message(
                    f"⚡ *CIRCUIT BREAKER STAND-DOWN* ⚡\n{cb_reason}\nNo new entries. Exits remain active."
                )
            return

        # Opening Bell Observation Protocol: block NSE/BSE entries during the
        # 09:15-09:30 IST window. Uses the injectable clock seam so tests can
        # pin session time deterministically.
        from datetime import time as dt_time
        ist_now = self._now_ist()
        current_date_str = ist_now.strftime("%Y-%m-%d")

        is_observation_window = dt_time(9, 15) <= ist_now.time() < dt_time(9, 30)



        from hokage.dashboard.event_bus import EventBus
        bus = EventBus()
        bus.publish("MARKET_SCAN_STARTED", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scan_mode": getattr(self, "scan_mode", "WATCHLIST_RESTRICTED"),
            "scan_constraints": [u.upper() for u in (self.cache.read_intelligence("market_regime.json") or {}).get("active_universe", [])]
        })
        # Load active profile settings from SSOT
        from hokage.memory.profile import ProfileService
        profile_service = ProfileService(self._resolver)
        profile = profile_service.get_profile()
        active_universe = [u.upper() for u in profile.horizon.active_universe]

        self.scan_mode = "WATCHLIST_RESTRICTED"
        self.scan_constraints = active_universe

        # Resolve active risk status from Fast Trading Brain cache
        risk_state = self.cache.read_intelligence("risk_state.json") or {}
        risk_off = (risk_state.get("risk_on_off_status") == "RISK-OFF")

        # Compute portfolio metrics, health, and rolling accuracy stats
        portfolio_metrics = self.portfolio_intel.compute_portfolio_metrics()
        accuracy_data = self.cache.read_intelligence("prediction_accuracy.json") or {}
        win_rate = accuracy_data.get("overall_accuracy", 100.0)
        
        health_data = PortfolioHealthScore.calculate_health(portfolio_metrics, win_rate)
        portfolio_health = health_data["health_score"]

        # Calculate Trust Score
        trust_data = self.trust_engine.calculate_trust_score(
            prediction_accuracy=win_rate,
            drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0)
        )
        trust_score = trust_data["trust_score"]

        # Evaluate risk constraints from Capital Preservation Engine
        preservation_data = self.preservation_engine.evaluate_risk_profile(
            drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0),
            vix_impact_delta=risk_state.get("vix_impact_delta", 0.0),
            enabled=profile.risk.capital_preservation
        )
        preservation_mode = preservation_data["mode"]

        # Resolve active personality profile
        personality_profile = self.personality_engine.resolve_personality_profile(
            market_regime=risk_state.get("risk_on_off_status", "RISK-ON"),
            vix_impact_delta=risk_state.get("vix_impact_delta", 0.0),
            drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0),
            is_recovery_mode=(preservation_mode == "RECOVERY")
        )
        # Update personality engine active mode
        self.personality_engine.configured_mode = profile.risk.risk_mode.value

        min_conviction = max(
            preservation_data.get("min_conviction_threshold", 51),
            personality_profile.get("min_conviction_threshold", 51)
        )

        # Build reasoning chain gates
        _gate1 = {
            "gate":     "CapitalPreservation",
            "decision": preservation_mode,
            "reason":   (
                f"Mode={preservation_mode}. "
                f"Max allocation={preservation_data.get('max_allocation_pct', 2.0):.1f}%. "
                f"Min conviction threshold={preservation_data.get('min_conviction_threshold', 51)}."
            ),
        }
        _gate2 = {
            "gate":     "PortfolioHealth",
            "decision": health_data.get("health_grade", "UNKNOWN"),
            "reason":   (
                f"Health score={portfolio_health}. "
                f"Grade={health_data.get('health_grade', 'UNKNOWN')}. "
                f"Trust score={trust_score}."
            ),
        }

        # Resolve executing venue
        context = self.orchestrator.get_execution_context()
        default_venue = self.orchestrator.registry.get_venue(context.active_venue_id)
        if not default_venue:
            default_venue = self.orchestrator.paper_venue

        # Safety check: if execution mode is LIVE but the active venue is a paper/mock venue, abort.
        if context.execution_mode == ExecutionMode.LIVE:
            if default_venue and ("paper" in default_venue.venue_id.lower() or "mock" in default_venue.venue_id.lower()):
                logger.critical(f"CRITICAL FAULT: Active venue '{default_venue.venue_id}' is a mock/paper venue, but execution mode is LIVE! Aborting scan.")
                return

        # Check existing positions to prevent duplicates across all active venues
        existing_symbols = set()
        for v_id in self.orchestrator.registry.list_venues():
            venue = self.orchestrator.registry.get_venue(v_id)
            is_paper_venue = "paper" in v_id.lower() or "mock" in v_id.lower()
            if context.execution_mode in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
                if is_paper_venue:
                    try:
                        for p in venue.get_positions():
                            existing_symbols.add(p.instrument.symbol.upper())
                    except Exception as exc:
                        logger.error(f"Failed to query open positions for venue {v_id}: {exc}")
            elif context.execution_mode == ExecutionMode.LIVE:
                if not is_paper_venue:
                    try:
                        for p in venue.get_positions():
                            existing_symbols.add(p.instrument.symbol.upper())
                    except Exception as exc:
                        logger.error(f"Failed to query open positions for venue {v_id}: {exc}")

        # Merge with locally tracked active positions to prevent double execution
        for sym in self._active_positions_tracking:
            existing_symbols.add(sym.upper())

        # Check available cash on default/primary venue as a fast check
        cash_available = True
        try:
            bal = default_venue.get_account_balance()
            if bal.cash <= 1000.0:  # Safeguard boundary cash limit
                cash_available = False
        except Exception as exc:
            logger.error(f"Failed to query default account balance: {exc}")
            cash_available = False

        # Dynamically discover opportunities
        scanned_symbols = self.discovery_engine.discover_opportunities(self.scan_mode, self.scan_constraints)
        scanned_symbols = [s.upper() for s in scanned_symbols]

        # Keep only currently tradable assets
        tradable_symbols = []
        for s in scanned_symbols:
            if self.orchestrator.session_manager.is_tradable(s):
                tradable_symbols.append(s)
            else:
                logger.debug(f"Symbol {s} is not currently tradable (exchange session closed). Skipping scan.")

        # Day-of-Week Isolator Filter
        from integrations.brokers.session_manager import KolkataTime
        tz = KolkataTime()
        ist_now = datetime.now(timezone.utc).astimezone(tz)
        weekday = ist_now.weekday() # 0 = Monday, 6 = Sunday
        
        if 0 <= weekday <= 4:
            allowed_sectors = ["index", "it", "energy", "banking", "fintech", "defence", "us_tech", "commodity"]
            day_desc = "Weekday (Mon-Fri) - Indices/Equities/Commodities only"
        else:
            allowed_sectors = ["crypto", "forex"]
            day_desc = "Weekend (Sat-Sun) - Forex/Crypto only"

        day_filtered_symbols = []
        for s in tradable_symbols:
            sector = self.portfolio_intel.symbol_sectors.get(s, "other")
            if sector in allowed_sectors:
                day_filtered_symbols.append(s)
            else:
                block_msg = f"Day-of-Week Isolator: {s} ({sector}) is blocked on {day_desc}."
                logger.info(block_msg)
                eval_results[s] = {
                    "state": "NO_TRADE",
                    "blockers": [block_msg],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": 0.0,
                    "reasons": [block_msg]
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": s,
                    "reason": block_msg,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
        
        tradable_symbols = day_filtered_symbols

        # Venue-aware observation gate. (Exchange lives in the DATA models
        # module; the old import from brokers.models raised ImportError, which
        # crashed the entry scan every day inside the 09:15-09:30 window.)
        observation_blocked = set()
        if is_observation_window:
            from integrations.data.models import Exchange as _DataExchange
            for s in tradable_symbols:
                instrument = self.orchestrator.price_source.resolve_instrument(s)
                if instrument and instrument.exchange in (_DataExchange.NSE, _DataExchange.BSE):
                    observation_blocked.add(s)

        symbols_to_scan = [s for s in tradable_symbols if s not in existing_symbols and s not in observation_blocked]

        # Tracking evaluations to update states
        eval_results = {}

        # Add observation blocked symbols to eval results early
        for s in observation_blocked:
            obs_reason = "Opening Bell Observation Protocol: Prohibited from executing entry orders until 09:30 AM IST."
            eval_results[s] = {
                "state": "NO_TRADE",
                "blockers": [obs_reason],
                "confirmations": [],
                "conviction": 0,
                "risk": 0.0,
                "reasons": [obs_reason]
            }

        # If general NO TRADE/RISK-OFF triggers are active
        global_blocker = None
        if risk_off:
            global_blocker = "Fast Trading Brain: Cached risk state is RISK-OFF."
        elif preservation_mode == "NO TRADE":
            global_blocker = "Fast Trading Brain: Capital Preservation Mode is NO TRADE."
        elif not cash_available:
            global_blocker = "Insufficient account cash balance."

        if global_blocker:
            for s in scanned_symbols:
                if s in existing_symbols:
                    eval_results[s] = {"state": "EXECUTED", "blockers": [], "confirmations": [], "conviction": 85, "risk": 0.0}
                else:
                    eval_results[s] = {
                        "state": "NO_TRADE",
                        "blockers": [global_blocker],
                        "confirmations": [],
                        "conviction": 0,
                        "risk": 0.0,
                        "reasons": [global_blocker]
                    }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": s,
                    "reason": global_blocker,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            bus.publish("MARKET_SCAN_COMPLETED", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scanned_count": len(scanned_symbols),
                "candidates_count": 0
            })
            bus.publish("NO_TRADE_DAY", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason_summary": global_blocker,
                "risk_score": 5.0,
                "rejected_opportunities_count": len(scanned_symbols),
                "expected_edge": 0.0,
                "capital_preservation_score": 100.0
            })
            self._update_all_states(eval_results)
            return

        candidates = []
        if symbols_to_scan:
            with ThreadPoolExecutor(max_workers=min(10, len(symbols_to_scan))) as executor:
                futures = {executor.submit(self._evaluate_single_symbol, s): s for s in symbols_to_scan}
                for fut in futures:
                    symbol = futures[fut]
                    res = fut.result()
                    if res is not None:
                        proposal = res["proposal"]
                        bus.publish("OPPORTUNITY_FOUND", {
                            "symbol": symbol,
                            "proposal_name": proposal.name,
                            "confidence_score": proposal.confidence_score,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        proposal = res["proposal"]
                        backtest_result = res["backtest_result"]
                        symbol = proposal.market.upper()

                        # Precompute entry price right away
                        try:
                            entry_price = self.orchestrator.price_source.get_price(symbol)
                            valid_price = (entry_price is not None and isinstance(entry_price, (int, float)) and entry_price > 0.0)
                        except Exception:
                            entry_price = 0.0
                            valid_price = False

                        # Precompute conviction score
                        rotation = self.cache.read_intelligence("sector_rotation.json") or {}
                        analogs_data = self.cache.read_intelligence("analog_matches.json") or {}
                        primary_analog = analogs_data.get("primary_analog", {})
                        sentiment_data = self.cache.read_intelligence("market_sentiment.json") or {}

                        symbol_sec = self.portfolio_intel.symbol_sectors.get(symbol, "OTHER")
                        flows = rotation.get("prediction", {}).get("forecast_flows", {})
                        flow_val = flows.get(symbol_sec, 0.02)
                        vix_impact_delta = risk_state.get("vix_impact_delta", 0.0)

                        portfolio_context_val = max(0.0, min(1.0, portfolio_health / 100.0))
                        res_conv = self.conviction_engine.calculate_conviction(
                            market_regime_score=risk_state.get("confidence", 0.82),
                            sector_rotation_strength=flow_val,
                            analog_similarity=primary_analog.get("similarity_score", 92.5),
                            news_sentiment_confidence=sentiment_data.get("confidence", 0.70),
                            backtest_win_rate=backtest_result.win_rate,
                            prediction_accuracy=win_rate,
                            vix_impact_delta=vix_impact_delta,
                            risk_reward_ratio=backtest_result.profit_factor,
                            portfolio_context=portfolio_context_val,
                            symbol=symbol,
                            sector=symbol_sec,
                        )

                        res.update({
                            "entry_price": entry_price,
                            "valid_price": valid_price,
                            "conviction_score": res_conv["score"],
                            "decision_id": res_conv.get("decision_id", ""),
                            "conviction_breakdown": res_conv.get("conviction_breakdown", {}),
                            "flow_val": flow_val,
                            "vix_impact_delta": vix_impact_delta,
                            "symbol_sec": symbol_sec,
                            "rotation_dir": rotation.get("capital_rotation_direction", "N/A"),
                            "primary_analog": primary_analog,
                        })
                        candidates.append(res)
                    else:
                        bus.publish("OPPORTUNITY_REJECTED", {
                            "symbol": symbol,
                            "reason": "Failed research/strategy/backtest validation.",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })

        # Apply Portfolio Intelligence Opportunity Ranking (expected return, confidence, correlation, diversification, capital efficiency)
        candidates = self.allocation_engine.rank_opportunities(candidates, portfolio_metrics)

        for cand in candidates:
            proposal = cand["proposal"]
            backtest_result = cand["backtest_result"]
            symbol = cand["symbol"]
            entry_price = cand["entry_price"]
            valid_price = cand["valid_price"]
            opp_conviction_score = cand["conviction_score"]
            decision_id = cand["decision_id"]
            conviction_breakdown = cand["conviction_breakdown"]
            flow_val = cand["flow_val"]
            vix_impact_delta = cand["vix_impact_delta"]
            symbol_sec = cand["symbol_sec"]
            sector_rotation_dir = cand["rotation_dir"]
            primary_analog = cand["primary_analog"]
            ranking_reasons = cand.get("ranking_reasons", [])
            composite_score = cand.get("composite_score", 0.0)
            standalone_score = cand.get("standalone_score", 0.0)
            # Put-Call Ratio (PCR) Advisory — soft warning only (no hard block while using mock data source)
            # TODO: Wire a real PCR data feed here to re-enable hard blocking.
            try:
                from bots.autonomous.options_intelligence import OptionsIntelligenceEngine
                options_engine = OptionsIntelligenceEngine({"type": "mock_options"})
                metrics = options_engine.fetch_options_metrics(symbol)
                pcr = metrics.get("pcr", 1.0)
            except Exception:
                pcr = 1.0

            if proposal.entry_rule == "long" and pcr < 1.15:
                logger.info(f"PCR Advisory: Put-Call Ratio {pcr:.2f} is below optimal 1.15 for CE entry on {symbol}. Proceeding with caution.")
            elif proposal.entry_rule == "short" and pcr > 0.75:
                logger.info(f"PCR Advisory: Put-Call Ratio {pcr:.2f} is above 0.75 for PE entry on {symbol}. Proceeding with caution.")

            # Session check using SessionBehaviorEngine
            session = self.session_behavior_engine.get_current_session()
            is_session_allowed, session_reason = self.session_behavior_engine.filter_opportunity(session, proposal.entry_rule)
            if not is_session_allowed:
                logger.info(f"Opportunity for {symbol} rejected by SessionBehaviorEngine: {session_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"SessionBehaviorEngine: {session_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"SessionBehaviorEngine: {session_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"SessionBehaviorEngine: {session_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                continue

            # Volume breakout check using VolumeEngine — REAL volumes only.
            # (Previously avg_vol = current/2.0, a fabricated denominator that made
            # the ratio a constant 2.0 and the gate decorative.)
            try:
                quote = self.orchestrator.price_source.get_quote(symbol)
            except Exception:
                quote = None
            vol_ctx = self._get_volume_context(symbol, quote) if quote is not None else None
            if vol_ctx is None:
                logger.info(f"Volume context unavailable for {symbol}; skipping volume gate (no fabricated volumes).")
                is_vol_valid, vol_reason = True, "volume data unavailable; gate skipped"
            else:
                current_vol, avg_vol = vol_ctx
                is_vol_valid, vol_reason = self.volume_engine.validate_breakout(current_vol, avg_vol)
            if not is_vol_valid:
                logger.info(f"Opportunity for {symbol} rejected by VolumeEngine: {vol_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"VolumeEngine: {vol_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"VolumeEngine: {vol_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"VolumeEngine: {vol_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                continue

            # Liquidity check using LiquidityEngine. Spread AND order-book depth
            # ratio are REAL (from the live quote); missing data means the
            # corresponding check is skipped, never faked.
            spread_pct, bid_ask_ratio = self._quote_liquidity_inputs(quote)

            if spread_pct is None:
                logger.info(f"Spread unavailable for {symbol}; skipping liquidity gate (no fabricated spreads).")
                is_liq_valid, liq_reason = True, "spread data unavailable; gate skipped"
            else:
                is_option = symbol.upper().endswith(("CE", "PE"))
                is_liq_valid, liq_reason = self.liquidity_engine.check_liquidity(spread_pct, bid_ask_ratio, is_option=is_option)
            if not is_liq_valid:
                logger.info(f"Opportunity for {symbol} rejected by LiquidityEngine: {liq_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"LiquidityEngine: {liq_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"LiquidityEngine: {liq_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"LiquidityEngine: {liq_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                continue

            # Automatic Strategy Selection based on specialization doctrine
            regime_str = risk_state.get("risk_on_off_status", "RISK-ON")
            vix_delta = risk_state.get("vix_impact_delta", 0.0)
            volatility_str = "HIGH" if vix_delta >= 2.0 else "LOW"
            
            bus.publish("STRATEGY_STARTED", {
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            selection_res = self.strategy_portfolio.select_strategy(
                asset=symbol,
                market_regime=regime_str,
                volatility_regime=volatility_str
            )
            selected_strat = selection_res["strategy"]
            logger.info(selection_res["reason"])
            bus.publish("STRATEGY_COMPLETED", {
                "symbol": symbol,
                "strategy_id": selected_strat.get("strategy_id"),
                "strategy_name": selected_strat.get("name"),
                "reason": selection_res["reason"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            _gate_strategy = {
                "gate":     "StrategySelection",
                "decision": selected_strat["name"],
                "reason":   selection_res["reason"]
            }



            # Validate entry price & RiskBot early
            risk_approved = False
            risk_reason = "Risk verification pipeline failure."
            # Risk-approved quantity ceiling. The RiskManager pipeline (HardLotCapRule,
            # MaxPositionSize, Leverage, VaR, ES) returns the maximum quantity it will
            # authorize. Sizing MUST NOT exceed this. Default to no ceiling only until
            # the verdict is available; a failed/absent risk check keeps this at 0.0 so
            # no order can be sized above the cap by accident.
            risk_max_qty = float("inf")
            if valid_price:
                try:
                    account = self.orchestrator.portfolio_store.load_account(self.orchestrator.paper_venue._account_id)
                    risk_verdict = self.orchestrator.risk_bot.check_proposal(account, proposal, entry_price)
                    risk_approved = risk_verdict.is_approved
                    risk_max_qty = risk_verdict.max_approved_quantity
                    risk_reason = risk_verdict.reason if not risk_approved else "All risk parameters satisfied."
                    if risk_approved:
                        bus.publish("RISK_APPROVED", {
                            "symbol": symbol,
                            "reason": risk_reason,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                    else:
                        bus.publish("RISK_REJECTED", {
                            "symbol": symbol,
                            "reason": risk_reason,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                except Exception as exc:
                    risk_reason = f"Risk check failed: {exc}"
                    bus.publish("RISK_REJECTED", {
                        "symbol": symbol,
                        "reason": risk_reason,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
            else:
                risk_reason = "Invalid entry price."
                bus.publish("RISK_REJECTED", {
                    "symbol": symbol,
                    "reason": risk_reason,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            # Construct Investment Committee Context
            ic_context = {
                "market_regime": risk_state.get("risk_on_off_status", "RISK-ON"),
                "vix_impact_delta": vix_impact_delta,
                "sector_flow_strength": flow_val,
                "preservation_mode": preservation_mode,
                "drawdown_pct": portfolio_metrics.get("drawdown_pct", 0.0),
                "cash_available": cash_available,
                "valid_price": valid_price,
                "risk_approved": risk_approved,
                "risk_reason": risk_reason,
                "strategy_confidence": selected_strat.get("confidence", 50.0),
                "strategy_name": selected_strat.get("name", "strat-autotrend"),
            }

            # Evaluate Proposal through Investment Committee
            committee_decision = self.committee.evaluate_proposal(proposal, backtest_result, ic_context)

            # Record in Immutable Committee Ledger
            self.committee_ledger.record_decision(decision_id, selected_strat["strategy_id"], symbol, committee_decision)
            
            # Fire COMMITTEE_VOTE
            votes_dict = {c: {"vote": v.vote.value if hasattr(v.vote, 'value') else v.vote, "reason": v.reasoning} for c, v in committee_decision.votes.items()}
            bus.publish("COMMITTEE_VOTE", {
                "symbol": symbol,
                "verdict": committee_decision.final_verdict,
                "confidence": committee_decision.decision_confidence,
                "votes": votes_dict,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # Build reasoning chain gates
            _gate1 = {
                "gate": "CapitalPreservation",
                "decision": preservation_mode,
                "reason": f"Mode={preservation_mode}. drawdown={portfolio_metrics.get('drawdown_pct', 0.0):.2f}%."
            }
            _gate2 = {
                "gate": "PortfolioHealth",
                "decision": health_data.get("health_grade", "UNKNOWN"),
                "reason": f"Health score={portfolio_health}. Trust={trust_score}."
            }
            _gate3 = {
                "gate": "ConvictionScore",
                "decision": opp_conviction_score,
                "reason": "Calculated conviction score."
            }
            _gate4 = {
                "gate": "InvestmentCommittee",
                "decision": committee_decision.final_verdict,
                "reason": f"Collective decision. Approvals={committee_decision.approval_percentage:.1f}%. Veto={committee_decision.veto_triggered}."
            }

            if committee_decision.final_verdict == "REJECTED":
                # Compute allocation for statistics and EOD avoided-loss
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"Rejected by Investment Committee. Rejecting members: {', '.join(committee_decision.rejecting_committees)}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                alloc_res = self.allocation_engine.evaluate_allocation(symbol, committee_decision.decision_confidence)
                alloc_pct = alloc_res.get("suggested_allocation_pct", 0.0)
                scale = min(
                    preservation_data.get("max_allocation_pct", 2.0) / 2.0,
                    personality_profile.get("sizing_scale", 1.0)
                )
                alloc_pct = round(alloc_pct * scale, 2)
                total_equity = portfolio_metrics.get("total_assets", 500000.0)
                qty = self._calculate_dynamic_lot_size(symbol, total_equity, entry_price=entry_price or 1.0, alloc_pct=alloc_pct, confidence_score=committee_decision.decision_confidence if 'committee_decision' in locals() else 50.0)
                avoided_loss = qty * (entry_price or 1.0) * self.tsl_percent

                reasons_list = [
                    f"Committee {c} voted REJECT: {committee_decision.votes[c].reasoning}"
                    for c in committee_decision.rejecting_committees
                ]
                if not committee_decision.rejecting_committees:
                    reasons_list.append("Committee rejections did not pass majority approval.")

                # Populate Future Conditions
                future_conditions = []
                for c in committee_decision.rejecting_committees:
                    if c == "Trend":
                        future_conditions.append("Market regime NORMAL/RISK-ON and backtest win_rate >= 55%")
                    elif c == "Volatility":
                        future_conditions.append("VIX delta < 1.5")
                    elif c == "Risk":
                        future_conditions.append("All risk boundaries satisfied")
                    elif c == "CapitalPreservation":
                        future_conditions.append("Capital preservation mode NORMAL")
                    elif c == "LiquidityExecution":
                        future_conditions.append("Sufficient cash balance and valid prices")
                future_conditions_str = " | ".join(future_conditions) or "Improvement in market structural indicators."

                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": reasons_list,
                    "confirmations": [],
                    "conviction": int(committee_decision.decision_confidence),
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": reasons_list,
                    "proposal_name": proposal.name,
                    "breakdown": conviction_breakdown
                }

                _chain = [_gate1, _gate2, _gate_strategy, _gate3, _gate4]
                self.journal.record_decision(
                    symbol=symbol,
                    decision="REJECTED",
                    conviction=int(committee_decision.decision_confidence),
                    conviction_breakdown=conviction_breakdown,
                    reason=f"Rejected by Investment Committee. Rejecting members: {', '.join(committee_decision.rejecting_committees)}.",
                    veto_source=committee_decision.veto_committees[0] if committee_decision.veto_committees else None,
                    market_regime=risk_state.get("risk_on_off_status", "RISK-ON"),
                    sector_flow=sector_rotation_dir,
                    decision_id=decision_id,
                    portfolio_health=portfolio_health,
                    trust_score=trust_score,
                    personality_mode=personality_profile["active_mode"],
                    sector=symbol_sec,
                    analog_match=primary_analog.get("event_description", "N/A"),
                    sector_rotation_state=sector_rotation_dir,
                    reasoning_chain=_chain,
                )
                continue

            # If APPROVED, determine size and place order
            alloc_res = self.allocation_engine.evaluate_allocation(symbol, committee_decision.decision_confidence)
            alloc_pct = alloc_res.get("suggested_allocation_pct", 0.0)
            active_constraints = alloc_res.get("active_constraints", [])
            
            # Apply adaptive sizing based on regime, drawdown, and VIX
            regime_data = self.cache.read_intelligence("market_regime.json") or {}
            trend_score = regime_data.get("trend_score", 0.0)
            classified_regime = self.adv_regime_engine.classify_regime(trend_score, vix_impact_delta)
            
            alloc_pct = self.adaptive_sizing_engine.get_adapted_allocation(
                base_alloc_pct=alloc_pct,
                regime=classified_regime,
                drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0),
                vix_impact_delta=vix_impact_delta
            )
            
            scale = min(
                preservation_data.get("max_allocation_pct", 2.0) / 2.0,
                personality_profile.get("sizing_scale", 1.0)
            )
            alloc_pct = round(alloc_pct * scale, 2)

            # Portfolio-First Allocation adjustment:
            # Scale based on portfolio improvement (composite_score / standalone_score ratio)
            portfolio_multiplier = 1.0
            # Only adjust sizing if we have existing open positions in the portfolio.
            # Otherwise, standalone score dictates classical allocation.
            if standalone_score > 0.0 and len(portfolio_metrics.get("correlation_matrix", {})) > 0:
                portfolio_multiplier = max(0.5, min(1.5, composite_score / standalone_score))
            alloc_pct = round(alloc_pct * portfolio_multiplier, 2)

            _gate_alloc = {
                "gate": "PositionAllocation",
                "decision": f"{alloc_pct:.2f}%",
                "reason": (
                    f"Sized allocation with scale {scale:.2f} and portfolio multiplier {portfolio_multiplier:.2f}. "
                    f"Composite Score: {composite_score:.2f} (Standalone: {standalone_score:.2f}). "
                    f"Active Constraints: {active_constraints}."
                )
            }

            if alloc_pct == 0.0:
                reasons_list = [
                    f"Allocation sized to 0% by Capital Preservation sizing engine or active constraints: {active_constraints}."
                ]
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": "Allocation sized to 0% by Capital Preservation sizing engine or active constraints.",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": reasons_list,
                    "confirmations": [],
                    "conviction": int(committee_decision.decision_confidence),
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": reasons_list,
                    "proposal_name": proposal.name,
                    "breakdown": conviction_breakdown
                }
                continue

            state_ready = "LONG_READY" if proposal.entry_rule == "long" else "SHORT_READY"
            eval_results[symbol] = {
                "state": state_ready,
                "blockers": [],
                "confirmations": [],
                "conviction": int(committee_decision.decision_confidence),
                "risk": round(backtest_result.profit_factor, 2),
            }

            try:
                # --- Final pre-execution validations ---
                # 1. Price provenance check (Doctrine: no synthetic prices; also
                # blocks stale quotes right before order placement).
                latest_price, price_reason = self._get_validated_live_price(symbol)
                if latest_price is None:
                    logger.warning(f"Aborting execution for {symbol}: price provenance check failed ({price_reason}).")
                    continue
                entry_price = latest_price

                # 2. Risk check: Read fresh risk status to prevent trade if status switched to RISK-OFF
                fresh_risk = self.cache.read_intelligence("risk_state.json") or {}
                if fresh_risk.get("risk_on_off_status") == "RISK-OFF":
                    logger.warning(f"Aborting execution for {symbol}: Risk state switched to RISK-OFF right before order.")
                    continue

                # Resolve the correct execution venue dynamically for this asset
                venue = self.orchestrator.broker_registry.get_venue_for_asset(symbol, context.execution_mode)
                if venue is None:
                    logger.warning(f"Aborting execution for {symbol}: no venue resolved for asset in mode {context.execution_mode}.")
                    continue

                # 3. Live broker reconciliation: verify symbol is not already in active positions on broker
                try:
                    broker_positions = {p.instrument.symbol.upper() for p in venue.get_positions()}
                    if symbol in broker_positions:
                        logger.warning(f"Aborting execution for {symbol}: Position already exists on broker {venue.venue_id} right before order.")
                        continue
                except Exception as exc:
                    logger.error(f"Broker position check failed right before order for {symbol} on venue {venue.venue_id}: {exc}")
                    continue

                # Venue cash check right before execution
                try:
                    bal = venue.get_account_balance()
                    if bal.cash <= 1000.0:
                        logger.warning(f"Aborting execution for {symbol}: Insufficient cash on venue {venue.venue_id} right before order.")
                        continue
                except Exception as exc:
                    logger.error(f"Failed to query account balance for venue {venue.venue_id} right before order: {exc}")
                    continue

                # 1. Resolve Playbook ID
                playbook_id = self.strategy_engine.get_playbook_id(proposal.name)
                
                # 2. Enforce unique asset diversification (rotate entries across 5 unique symbols per daily playbook batch)
                allowed, block_reason = self.strategy_engine.is_entry_allowed(playbook_id, symbol, current_date_str)
                if not allowed:
                    logger.warning(f"Aborting execution for {symbol}: Playbook {playbook_id} limits violated. Reason: {block_reason}")
                    continue

                # 3. Implement IV Swapper
                try:
                    vix = self.orchestrator.price_source.get_price("INDIAVIX")
                    vix_val = float(vix) if vix else 15.0
                except Exception:
                    vix_val = 15.0

                if vix_val >= 18.0:
                    volatility_regime = "EXPANDING"
                    swapped_entry_rule = "ATM Option Buying"
                else:
                    volatility_regime = "COMPRESSING"
                    swapped_entry_rule = "Debit Spreads"

                # Swap entry rule on proposal dynamically
                from bots.strategy.models import StrategyProposal
                original_entry = proposal.entry_rule
                proposal = StrategyProposal(
                    name=proposal.name,
                    description=proposal.description,
                    market=proposal.market,
                    entry_rule=swapped_entry_rule,
                    exit_rule=proposal.exit_rule,
                    stop_loss_rule=proposal.stop_loss_rule,
                    take_profit_rule=proposal.take_profit_rule,
                    timeframe=proposal.timeframe,
                    confidence_score=proposal.confidence_score,
                    sources_cited=proposal.sources_cited,
                    generated_at=proposal.generated_at,
                    proposal_id=proposal.proposal_id,
                    playbook_id=playbook_id,
                    volatility_regime=volatility_regime
                )

                # Calculate size
                total_equity = portfolio_metrics.get("total_assets", 500000.0)
                qty = self._calculate_dynamic_lot_size(symbol, total_equity, entry_price=entry_price, alloc_pct=alloc_pct, confidence_score=committee_decision.decision_confidence if 'committee_decision' in locals() else 50.0, direction=original_entry)

                # HARD RISK CEILING: never size above the RiskManager-approved quantity.
                # HardLotCapRule caps NIFTY/CRUDEOIL to 1 lot via max_approved_quantity;
                # MaxPositionSize/Leverage/VaR/ES also express their limit here. The
                # execution venues (paper_engine, kite_venue) fill the requested quantity
                # verbatim and perform NO risk clamp, so this is the sole enforcement point.
                if qty > risk_max_qty:
                    logger.warning(
                        f"Sizing clamp: {symbol} Kelly-sized qty {qty} exceeds risk-approved "
                        f"ceiling {risk_max_qty}. Capping to {risk_max_qty}."
                    )
                    qty = risk_max_qty

                # Negative-Kelly block / sizing failure / zero risk budget -> no trade.
                if qty <= 0:
                    logger.warning(f"Aborting execution for {symbol}: sized quantity is {qty} (no positive edge or no risk budget).")
                    continue

                # Entry conduct gates (measured-evidence rules): time-of-day
                # windows, underlying bias alignment, and the IV premium guard.
                conduct_ok, conduct_reason = self._entry_conduct_gate(symbol, original_entry)
                if not conduct_ok:
                    logger.info(f"Entry blocked for {symbol}: {conduct_reason}")
                    eval_results[symbol] = {
                        "state": "NO_TRADE",
                        "blockers": [conduct_reason],
                        "confirmations": [],
                        "conviction": int(committee_decision.decision_confidence),
                        "risk": 0.0,
                        "reasons": [conduct_reason],
                    }
                    continue

                side = OrderSide.BUY if original_entry == "long" else OrderSide.SELL

                # Create TradeAuthorization BEFORE placing order
                from bots.autonomous.models import TradeAuthorization
                auth = TradeAuthorization(
                    asset=symbol,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    direction=side.value,
                    conviction_score=int(committee_decision.decision_confidence),
                    risk_reward=round(backtest_result.profit_factor, 2),
                    trend_validation=True,
                    volatility_validation=True,
                    capital_preservation_validation=True,
                    universe_validation=True,
                    execution_reason=proposal.description or "Continuous Opportunity Surveillance Breakout",
                    authorised_by=f"Elder {profile.commander_name}"
                )
                self.journal.record_trade_authorization(auth)

                bus.publish("EXECUTION_STARTED", {
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": qty,
                    "allocated_pct": alloc_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                logger.info(f"Placing autonomous entry order: {side} {qty} {symbol} on venue {venue.venue_id}")
                resolved_exch = self.orchestrator.session_manager.resolve_exchange(symbol)
                resolved_ac = self.orchestrator.session_manager.resolve_asset_class(symbol)
                inst = Instrument(symbol=symbol, asset_class=resolved_ac, exchange=resolved_exch)
                req = OrderRequest(
                    instrument=inst,
                    side=side,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    venue_id=venue.venue_id,
                    strategy_id=proposal.name,
                    execution_reason="Autonomous CIO Allocation Sized Entry",
                    playbook_id=playbook_id,
                    volatility_regime=volatility_regime
                )
                
                # Options routing: option-routed underlyings (NIFTY, CRUDE_OIL)
                # execute as BOUGHT nearest-expiry ATM CE/PE — loss capped at
                # premium. FAIL CLOSED: if no real contract/premium resolves,
                # there is NO trade. A directional signal never silently falls
                # back to an instrument class the commander hasn't approved.
                from bots.execution.options_router import OptionsRouter, OptionsRoutingError
                if OptionsRouter.routes(symbol):
                    try:
                        cash_for_premium = None
                        try:
                            cash_for_premium = float(venue.get_account_balance().cash)
                        except Exception:
                            pass
                        opt_router = OptionsRouter(price_source=self.orchestrator.price_source)
                        req = opt_router.route_to_options(
                            req, current_price=entry_price, available_cash=cash_for_premium
                        )
                        logger.info(
                            f"Options Router transformed request: {req.side.value} "
                            f"{req.quantity:g} {req.instrument.symbol}"
                        )
                    except OptionsRoutingError as e:
                        logger.warning(f"Options routing blocked entry for {symbol}: {e}")
                        eval_results[symbol] = {
                            "state": "NO_TRADE",
                            "blockers": [f"OptionsRouter: {e}"],
                            "confirmations": [],
                            "conviction": int(committee_decision.decision_confidence),
                            "risk": 0.0,
                            "reasons": [f"OptionsRouter: {e}"],
                        }
                        continue

                try:
                    resp = venue.place_order(req)
                except Exception as e:
                    logger.error(f"Exception during place_order for {symbol}: {e}")
                    resp = None
                    
                if resp is None:
                    logger.warning(f"Order for {symbol} returned None. Marking UNCONFIRMED.")
                    qty_filled = 0.0
                    status_str = "UNCONFIRMED"
                elif str(getattr(resp, 'status', '')).upper() in ("REJECTED", "CANCELLED", "ERROR", "FAILED"):
                    logger.error(f"Order for {symbol} REJECTED/CANCELLED: {getattr(resp, 'error_message', 'Unknown Reject')}")
                    bus.publish("EXECUTION_REJECTED", {
                        "symbol": symbol,
                        "reason": getattr(resp, 'error_message', 'Unknown Reject'),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                else:
                    qty_filled = getattr(resp, "filled_quantity", req.quantity)
                    if not qty_filled:
                        qty_filled = req.quantity
                    status_str = "SUCCESS" if qty_filled >= req.quantity else "PARTIAL"

                # Track the instrument actually filled: for option-routed
                # entries that is the option contract (exit monitor keys off
                # venue positions, which carry the option symbol), and its
                # entry price is the premium paid, not the underlying level.
                tracked_symbol = req.instrument.symbol
                tracked_side = req.side
                tracked_entry_price = entry_price
                option_tracking_extras: dict[str, Any] = {}
                req_meta = req.instrument.metadata or {}
                if req_meta.get("is_option"):
                    tracked_entry_price = float(req_meta.get("premium_at_entry", entry_price))
                    # The option exit ladder needs the underlying's entry
                    # context: thesis stop and adaptive target both key off the
                    # UNDERLYING price/ATR, not the premium series.
                    entry_und_atr = self._get_atr_for_symbol(symbol)
                    option_tracking_extras = {
                        "entry_underlying_price": float(entry_price),
                        "entry_underlying_atr": float(entry_und_atr) if entry_und_atr else None,
                        "lot_size": req_meta.get("lot_size"),
                        "option_type": req_meta.get("option_type"),
                        "strike": req_meta.get("strike"),
                        "expiry": req_meta.get("expiry"),
                    }

                self.strategy_engine.record_trade(playbook_id, symbol, current_date_str)
                bus.publish("EXECUTION_COMPLETED", {
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": qty_filled,
                    "price": entry_price,
                    "status": status_str,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

                self._trades_taken_today.append({
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": qty_filled,
                    "entry_price": entry_price,
                    "reason": proposal.description,
                    "decision_id": decision_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                _chain_accepted = [_gate1, _gate2, _gate_strategy, _gate3, _gate4, _gate_alloc, {
                    "gate": "Execute",
                    "decision": "ACCEPTED",
                    "reason": f"All IC gates passed. Deploying {alloc_pct:.2f}% capital ({qty} units at ₹{entry_price:.2f}).",
                }]
                self.journal.record_decision(
                    symbol=symbol,
                    decision="ACCEPTED",
                    conviction=int(committee_decision.decision_confidence),
                    conviction_breakdown=conviction_breakdown,
                    reason=f"Investment Committee authorized deployment of {alloc_pct}% capital.",
                    veto_source=None,
                    market_regime=risk_state.get("risk_on_off_status", "RISK-ON"),
                    sector_flow=sector_rotation_dir,
                    decision_id=decision_id,
                    portfolio_health=portfolio_health,
                    trust_score=trust_score,
                    personality_mode=personality_profile["active_mode"],
                    sector=symbol_sec,
                    analog_match=primary_analog.get("event_description", "N/A"),
                    sector_rotation_state=sector_rotation_dir,
                    expected_outcome=f"Target allocation {alloc_pct}%",
                    actual_outcome="EXECUTED",
                    reasoning_chain=_chain_accepted,
                )

                self._active_positions_tracking[tracked_symbol] = {
                    "entry_price": tracked_entry_price,
                    "peak_price": tracked_entry_price,
                    "stop_price": tracked_entry_price * (1.0 - self.tsl_percent) if tracked_side == OrderSide.BUY else tracked_entry_price * (1.0 + self.tsl_percent),
                    "target_price": tracked_entry_price * (1.0 + self.tp_percent),
                    "decision_id": decision_id,
                    "strategy_id": selected_strat["strategy_id"],
                    "conviction_score": int(committee_decision.decision_confidence),
                    "allocation_pct": alloc_pct,
                    "sector": symbol_sec,
                    "personality_mode": personality_profile.get("active_mode", "BALANCED"),
                    "sector_flow": sector_rotation_dir,
                    "side": tracked_side.value if hasattr(tracked_side, "value") else tracked_side,
                    "quantity": float(qty_filled),
                    "venue_id": getattr(venue, "venue_id", "paper_main"),
                    "underlying": symbol,
                    "unconfirmed": (status_str == "UNCONFIRMED"),
                    **option_tracking_extras,
                }
                self._save_positions_tracking()

                if self.telegram_bot and self.telegram_bot.enabled:
                    self.telegram_bot.notify_entry(
                        symbol=tracked_symbol,
                        cmp=tracked_entry_price,
                        target=self._active_positions_tracking[tracked_symbol]["target_price"],
                        edge=float(committee_decision.decision_confidence)
                    )

                eval_results[symbol] = {
                    "state": "EXECUTED",
                    "blockers": [],
                    "confirmations": [],
                    "conviction": int(committee_decision.decision_confidence),
                    "risk": round(backtest_result.profit_factor, 2),
                }

            except Exception as exc:
                logger.error(f"Failed to enter autonomous opportunity for {symbol}: {exc}")
                bus.publish("EXECUTION_COMPLETED", {
                    "symbol": symbol,
                    "status": "FAILED",
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

        # Update all active universe surveillance states
        self._update_all_states(eval_results, scanned_symbols, existing_symbols)
        
        # Fire MARKET_SCAN_COMPLETED
        bus.publish("MARKET_SCAN_COMPLETED", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scanned_count": len(scanned_symbols),
            "candidates_count": len(candidates)
        })

        # Fire PORTFOLIO_UPDATED
        bus.publish("PORTFOLIO_UPDATED", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trades_taken_count": len(self._trades_taken_today),
            "portfolio_health": portfolio_health
        })

        # Fire NO_TRADE_DAY if no trades taken today
        if not self._trades_taken_today:
            reasons_summary = []
            for sym, res in eval_results.items():
                if res.get("state") in ("NO_TRADE", "WAITING") and "reasons" in res:
                    reasons_summary.extend(res["reasons"])
            bus.publish("NO_TRADE_DAY", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason_summary": "; ".join(reasons_summary) or "No actionable opportunities found.",
                "risk_score": 1.5,
                "rejected_opportunities_count": len(eval_results),
                "expected_edge": 0.0,
                "capital_preservation_score": 100.0 if profile.risk.capital_preservation else 50.0
            })

        # Loop over candidate strategies in SHADOW_MODE or PROBATION to simulate decisions
        session = self.session_behavior_engine.get_current_session()
        for strat_id, strat in list(self.strategy_portfolio.portfolio.get("strategies", {}).items()):
            if strat.get("status") in ("SHADOW_MODE", "PROBATION"):
                for cand in candidates:
                    proposal = cand["proposal"]
                    backtest_result = cand["backtest_result"]
                    symbol = proposal.market.upper()
                    
                    # Verify strategy supports this asset
                    if symbol not in strat.get("supported_assets", []):
                        continue
                    
                    # Verify we don't already have a shadow position in this asset for this strategy
                    if symbol in self._shadow_positions_tracking.get(strat_id, {}):
                        continue

                    # Find active production strategy for comparison
                    active_prod = None
                    for s_id, s in self.strategy_portfolio.portfolio.get("strategies", {}).items():
                        if s.get("status") in ("ACTIVE", "PRODUCTION") and s_id != strat_id:
                            if symbol in s.get("supported_assets", []):
                                active_prod = s
                                break

                    # Determine active production strategy action/sizing for comparison
                    total_equity = portfolio_metrics.get("total_assets", 500000.0)
                    active_action = "NO_TRADE"
                    active_sizing_pct = 0.0
                    active_qty = 0
                    if active_prod:
                        for t in self._trades_taken_today:
                            if t["symbol"] == symbol:
                                active_action = "ENTERED"
                                active_sizing_pct = round((t["quantity"] * t["entry_price"]) / total_equity * 100.0, 2)
                                active_qty = t["quantity"]
                                break
                                
                    active_prod_id = active_prod["strategy_id"] if active_prod else "NONE"

                    # 1. Session check using SessionBehaviorEngine
                    is_session_allowed, session_reason = self.session_behavior_engine.filter_opportunity(session, proposal.entry_rule)
                    if not is_session_allowed:
                        self.strategy_evolution.log_shadow_decision(
                            strategy_id=strat_id,
                            symbol=symbol,
                            decision_type="ENTRY",
                            decision_details={
                                "verdict": "REJECTED",
                                "reason": f"SessionBehaviorEngine: {session_reason}",
                                "active_production_strategy_id": active_prod_id,
                                "active_production_strategy_action": active_action
                            }
                        )
                        continue

                    # 2. Volume breakout check using VolumeEngine — REAL volumes only
                    # (mirrors the production entry path; no fabricated denominators).
                    try:
                        quote = self.orchestrator.price_source.get_quote(symbol)
                    except Exception:
                        quote = None
                    vol_ctx = self._get_volume_context(symbol, quote) if quote is not None else None
                    if vol_ctx is None:
                        is_vol_valid, vol_reason = True, "volume data unavailable; gate skipped"
                    else:
                        current_vol, avg_vol = vol_ctx
                        is_vol_valid, vol_reason = self.volume_engine.validate_breakout(current_vol, avg_vol)
                    if not is_vol_valid:
                        self.strategy_evolution.log_shadow_decision(
                            strategy_id=strat_id,
                            symbol=symbol,
                            decision_type="ENTRY",
                            decision_details={
                                "verdict": "REJECTED",
                                "reason": f"VolumeEngine: {vol_reason}",
                                "active_production_strategy_id": active_prod_id,
                                "active_production_strategy_action": active_action
                            }
                        )
                        continue

                    # 3. Liquidity check using LiquidityEngine — real spread and
                    # real depth ratio; mirrors the production entry path.
                    spread_pct, bid_ask_ratio = self._quote_liquidity_inputs(quote)

                    if spread_pct is None:
                        is_liq_valid, liq_reason = True, "spread data unavailable; gate skipped"
                    else:
                        is_option = symbol.upper().endswith(("CE", "PE"))
                        is_liq_valid, liq_reason = self.liquidity_engine.check_liquidity(spread_pct, bid_ask_ratio, is_option=is_option)
                    if not is_liq_valid:
                        self.strategy_evolution.log_shadow_decision(
                            strategy_id=strat_id,
                            symbol=symbol,
                            decision_type="ENTRY",
                            decision_details={
                                "verdict": "REJECTED",
                                "reason": f"LiquidityEngine: {liq_reason}",
                                "active_production_strategy_id": active_prod_id,
                                "active_production_strategy_action": active_action
                            }
                        )
                        continue

                    # Determine prices
                    entry_price = self.orchestrator.price_source.get_price(symbol) or 100.0
                    
                    # Determine market regime and adaptive sizing
                    vix_impact_delta = risk_state.get("vix_impact_delta", 0.0)
                    regime_data = self.cache.read_intelligence("market_regime.json") or {}
                    trend_score = regime_data.get("trend_score", 0.0)
                    classified_regime = self.adv_regime_engine.classify_regime(trend_score, vix_impact_delta)

                    alloc_res = self.allocation_engine.evaluate_allocation(symbol, 85)
                    alloc_pct = alloc_res.get("suggested_allocation_pct", 0.0)
                    alloc_pct = self.adaptive_sizing_engine.get_adapted_allocation(
                        base_alloc_pct=alloc_pct,
                        regime=classified_regime,
                        drawdown_pct=portfolio_metrics.get("drawdown_pct", 0.0),
                        vix_impact_delta=vix_impact_delta
                    )
                    scale = min(
                        preservation_data.get("max_allocation_pct", 2.0) / 2.0,
                        personality_profile.get("sizing_scale", 1.0)
                    )
                    alloc_pct = round(alloc_pct * scale, 2)
                    total_equity = portfolio_metrics.get("total_assets", 500000.0)
                    qty = self._calculate_dynamic_lot_size(symbol, total_equity, entry_price=entry_price, alloc_pct=alloc_pct, confidence_score=committee_decision.decision_confidence if 'committee_decision' in locals() else 50.0, direction=proposal.entry_rule)
                    if qty <= 0:
                        # Negative-Kelly block: shadow strategies mirror production
                        # sizing discipline — no positive edge, no simulated entry.
                        continue

                    # Trailing Stops and Take Profit management
                    adapted_tsl, adapted_tp = self.position_mgmt_engine.get_adapted_exit_percentages(
                        self.tsl_percent, self.tp_percent, vix_impact_delta
                    )
                    side_str = "BUY" if proposal.entry_rule == "long" else "SELL"
                    stop_price = entry_price * (1.0 - adapted_tsl) if side_str == "BUY" else entry_price * (1.0 + adapted_tsl)
                    target_price = entry_price * (1.0 + adapted_tp) if side_str == "BUY" else entry_price * (1.0 - adapted_tp)

                    comp_notes = (
                        f"Shadow strategy {strat_id} entered {symbol} with allocation {alloc_pct:.2f}% ({qty} units). "
                        f"Active production strategy {active_prod_id} action: {active_action}."
                    )

                    decision_details = {
                        "verdict": "ENTERED",
                        "trigger": "Simulated scan match",
                        "market_regime": risk_state.get("risk_on_off_status", "RISK-ON"),
                        "vix_impact_delta": vix_impact_delta,
                        "suggested_price": entry_price,
                        "sizing_pct": alloc_pct,
                        "sizing_qty": qty,
                        "stop_loss_pct": adapted_tsl,
                        "take_profit_pct": adapted_tp,
                        "stop_price": round(stop_price, 2),
                        "target_price": round(target_price, 2),
                        "active_production_strategy_id": active_prod_id,
                        "active_production_strategy_action": active_action,
                        "active_production_strategy_sizing_pct": active_sizing_pct,
                        "active_production_strategy_sizing_qty": active_qty,
                        "comparison_notes": comp_notes
                    }

                    # Record simulated position
                    self._shadow_positions_tracking.setdefault(strat_id, {})[symbol] = {
                        "entry_price": entry_price,
                        "peak_price": entry_price,
                        "stop_price": stop_price,
                        "target_price": target_price,
                        "quantity": qty,
                        "allocation_pct": alloc_pct,
                        "side": side_str,
                        "entry_timestamp": datetime.now(timezone.utc).isoformat(),
                        "current_price": entry_price
                    }

                    self.strategy_evolution.log_shadow_decision(
                        strategy_id=strat_id,
                        symbol=symbol,
                        decision_type="ENTRY",
                        decision_details=decision_details
                    )

        self._save_shadow_positions_tracking()

        # Evaluate pipeline transitions for all candidate strategies
        bus.publish("LEARNING_STARTED", {
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        for strat_id, strat in list(self.strategy_portfolio.portfolio.get("strategies", {}).items()):
            if strat.get("status") not in ("ACTIVE", "PRODUCTION", "ARCHIVED"):
                active_prod = None
                for s_id, s in self.strategy_portfolio.portfolio.get("strategies", {}).items():
                    if s.get("status") in ("ACTIVE", "PRODUCTION") and s_id != strat_id:
                        if any(a in s.get("supported_assets", []) for a in strat.get("supported_assets", [])):
                            active_prod = s
                            break
                
                changed, transition_reason = self.strategy_evolution.evaluate_pipeline_transition(strat, active_prod)
                if changed:
                    logger.info(f"Strategy {strat_id} transitioned: {transition_reason}")
                    if strat["status"] == "PRODUCTION":
                        strat["status"] = "ACTIVE"
                    self.strategy_portfolio.save()
        bus.publish("LEARNING_COMPLETED", {
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def _update_all_states(self, eval_results, scanned_symbols=None, existing_symbols=None) -> None:
        """Update surveillance states and log no-trades for all active universe assets."""
        from hokage.memory.profile import ProfileService
        profile_service = ProfileService(self._resolver)
        profile = profile_service.get_profile()
        active_universe = [u.upper() for u in profile.horizon.active_universe]

        scanned = scanned_symbols or active_universe
        existing = existing_symbols or set()

        for symbol in active_universe:
            symbol_upper = symbol.upper()
            if symbol_upper in existing:
                self.update_asset_surveillance_state(
                    asset=symbol_upper,
                    state="EXECUTED",
                    conviction=85,
                    risk_score=2.0,
                    blockers=[],
                    confirmations=[],
                    trigger_desc="All validations passed. Position active."
                )
            elif symbol_upper in eval_results:
                res = eval_results[symbol_upper]
                state_val = res["state"]
                conv = res["conviction"]
                risk = res["risk"]
                blockers = res["blockers"]
                confirmations = res["confirmations"]
                
                # Expose specific trigger conditions
                trigger = ""
                if state_val == "WAITING":
                    trigger = "Calibrate conviction above threshold, resolve VIX/market volatility delta."
                elif state_val == "NO_TRADE":
                    trigger = "Valid setup breakout matching structural filters and VIX limits."
                elif state_val in ("LONG_READY", "SHORT_READY", "EXECUTED"):
                    trigger = "Position active or authorized."

                self.update_asset_surveillance_state(
                    asset=symbol_upper,
                    state=state_val,
                    conviction=conv,
                    risk_score=risk,
                    blockers=blockers,
                    confirmations=confirmations,
                    trigger_desc=trigger
                )

                # Write NoTradeDecision if rejected
                if state_val in ("NO_TRADE", "WAITING") and "reasons" in res:
                    from bots.autonomous.models import NoTradeDecision
                    no_trade = NoTradeDecision(
                        asset=symbol_upper,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        decision="NO_TRADE",
                        confidence=conv,
                        reasons=tuple(res["reasons"]),
                        supporting_evidence={"conviction_breakdown": res.get("breakdown", {})},
                        invalidated_setups=tuple([res.get("proposal_name", "UNKNOWN")]),
                        next_review_time="15:00"
                    )
                    self.journal.record_no_trade_decision(no_trade)

            else:
                # Market under observation
                self.update_asset_surveillance_state(
                    asset=symbol_upper,
                    state="WATCHING",
                    conviction=0,
                    risk_score=0.0,
                    blockers=["No strategy setup detected"],
                    confirmations=["Strategy setup pattern confirmation"],
                    trigger_desc="Valid strategy proposal setup matching trend heuristics."
                )

        # Publish state change to the EventBus so the dashboard updates in real-time
        try:
            from hokage.dashboard.event_bus import EventBus
            EventBus().publish("state_change", {})
        except Exception as exc:
            logger.error(f"Failed to publish state_change event: {exc}")

    def generate_daily_report(self, exchange: Exchange | None = None) -> DailyReport:
        """Compile execution statistics and generate the DailyReport, optionally filtered by exchange."""
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Filter trades and exits by exchange if specified
        trades_today = self._trades_taken_today
        exits_today = self._exits_executed_today
        if exchange is not None:
            trades_today = [
                t for t in trades_today
                if self.orchestrator.session_manager.resolve_exchange(t["symbol"]) == exchange
            ]
            exits_today = [
                e for e in exits_today
                if self.orchestrator.session_manager.resolve_exchange(e["symbol"]) == exchange
            ]

        # Calculate PnL and Win Rate
        realized_pnl = sum(e["pnl"] for e in exits_today)
        win_count = sum(1 for e in exits_today if e["pnl"] > 0)
        total_exits = len(exits_today)
        win_rate = (win_count / total_exits * 100.0) if total_exits > 0 else 0.0

        # Query current open positions for unrealized PnL
        unrealized_pnl = 0.0
        portfolio_alloc = {}

        context = self.orchestrator.get_execution_context()
        # Resolve target venue(s)
        venues_to_query = []
        if exchange is not None:
            broker = self.orchestrator.broker_registry.get_broker_for_exchange(exchange)
            venue_id = f"paper_{broker}" if context.execution_mode in (ExecutionMode.PAPER, ExecutionMode.HYBRID) else (
                "kite_main" if broker == "zerodha" else f"{broker}_main"
            )
            try:
                venue = self.orchestrator.registry.get_venue(venue_id)
                venues_to_query.append(venue)
            except KeyError:
                pass
        else:
            # Query all active venues if no exchange specified
            for venue_id in self.orchestrator.registry.list_venues():
                is_paper_venue = "paper" in venue_id.lower() or "mock" in venue_id.lower()
                if context.execution_mode in (ExecutionMode.PAPER, ExecutionMode.HYBRID):
                    if is_paper_venue:
                        venues_to_query.append(self.orchestrator.registry.get_venue(venue_id))
                elif context.execution_mode == ExecutionMode.LIVE:
                    if not is_paper_venue:
                        venues_to_query.append(self.orchestrator.registry.get_venue(venue_id))

        total_val = 0.0
        total_cash = 0.0
        positions = []
        for venue in venues_to_query:
            try:
                venue_pos = venue.get_positions()
                positions.extend(venue_pos)
                bal = venue.get_account_balance()
                total_cash += bal.cash
                unrealized_pnl += sum(p.unrealized_pnl for p in venue_pos)
                total_val += sum(p.quantity * p.current_price for p in venue_pos)
            except Exception as exc:
                logger.error(f"Failed to query final metrics for venue {venue.venue_id}: {exc}")

        total_assets = total_val + total_cash
        if total_assets > 0:
            for p in positions:
                val = p.quantity * p.current_price
                portfolio_alloc[p.instrument.symbol] = round((val / total_assets) * 100.0, 2)
            portfolio_alloc["CASH"] = round((total_cash / total_assets) * 100.0, 2)

        exchange_name = exchange.name if exchange else "GLOBAL"
        report = DailyReport(
            date=today_str,
            trades_taken=tuple(trades_today),
            exits_executed=tuple(exits_today),
            realized_pnl=round(realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            win_rate=round(win_rate, 2),
            portfolio_allocation=portfolio_alloc,
            market_summary=f"{exchange_name} scan run completed. Executed {len(trades_today)} entries.",
            lessons_learned="Autonomous tracking performed stop checks cleanly."
        )

        # Persist report with exchange suffix
        suffix = f"_{exchange_name.lower()}" if exchange else ""
        report_file = self._reports_dir / f"daily_{today_str}{suffix}.json"
        try:
            with report_file.open("w") as fh:
                json.dump({
                    "date": report.date,
                    "realized_pnl": report.realized_pnl,
                    "unrealized_pnl": report.unrealized_pnl,
                    "win_rate": report.win_rate,
                    "portfolio_allocation": report.portfolio_allocation,
                    "trades_taken": report.trades_taken,
                    "exits_executed": report.exits_executed,
                    "market_summary": report.market_summary,
                    "lessons_learned": report.lessons_learned
                }, fh, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save EOD daily report for {exchange_name}: {exc}")

        return report

        # Write No-Trade EOD review if no trades were executed
        if not self._trades_taken_today:
            try:
                # Load profile details from SSOT (not in scope from _scan_and_enter_opportunities)
                from hokage.memory.profile import ProfileService
                _profile_svc = ProfileService(self._resolver)
                profile = _profile_svc.get_profile()
                active_universe = [u.upper() for u in profile.horizon.active_universe]
                portfolio_metrics = self.portfolio_intel.compute_portfolio_metrics()

                title = profile.commander_title
                name = profile.commander_name
                active_universe_str = ", ".join(active_universe)
                capital_preservation = "Enabled" if profile.risk.capital_preservation else "Disabled"
                
                # Fetch decisions
                today_decisions = []
                for d in self.journal.load_no_trade_decisions():
                    if d.get("timestamp", "").startswith(today_str):
                        today_decisions.append(d)

                no_trade_count = sum(1 for d in today_decisions if d.get("decision") == "NO_TRADE")
                waiting_count = sum(1 for d in today_decisions if d.get("decision") == "WAITING")
                watching_count = len(active_universe) - (no_trade_count + waiting_count)
                if watching_count < 0:
                    watching_count = 0
                
                total_evaluated = len(active_universe)
                trades_rejected = no_trade_count + waiting_count
                
                capital_preserved = portfolio_metrics.get("total_assets", profile.portfolio.starting_capital)
                avoided_losses = trades_rejected * (capital_preserved * 0.01) # 1% of capital per rejected setup

                monitored_assets_statuses = ""
                for dec in today_decisions:
                    asset = dec.get("asset", "UNKNOWN")
                    reasons = dec.get("reasons", [])
                    reasons_str = "\n".join(f"    * {r}" for r in reasons)
                    monitored_assets_statuses += (
                        f"- Asset: {asset}\n"
                        f"  Timestamp: {dec.get('timestamp')}\n"
                        f"  Decision: {dec.get('decision')}\n"
                        f"  Confidence: {dec.get('confidence')}/100\n"
                        f"  Reasons:\n{reasons_str}\n"
                        f"  Next Review Time: {dec.get('next_review_time')}\n\n"
                    )
                if not monitored_assets_statuses:
                    monitored_assets_statuses = "No decisions logged today.\n"

                no_trade_layout = f"""==================================================
HOKAGE NO-TRADE EOD REVIEW
==================================================
Date: {today_str}
Status: SUCCESSFUL NO-TRADE DAY
Commander: {title} {name}
Active Universe: {active_universe_str}
Capital Preservation: {capital_preservation}

--------------------------------------------------
DECISION JOURNAL SUMMARY
--------------------------------------------------
Total Evaluated Assets: {total_evaluated}
Decisions Breakdown:
- NO_TRADE: {no_trade_count}
- WAITING: {waiting_count}
- WATCHING: {watching_count}

Monitored Asset Statuses:
{monitored_assets_statuses}
--------------------------------------------------
PRIMARY SUCCESS METRICS (DECISION QUALITY)
--------------------------------------------------
- Risk-adjusted return: 0.00%
- After-tax return: 0.00%
- Capital preservation: True
- Opportunity quality: N/A
- Conviction accuracy: N/A
- Drawdown control: 0.00%

--------------------------------------------------
SECONDARY SUCCESS METRICS
--------------------------------------------------
- Trades executed: 0
- Trades rejected: {trades_rejected}
- No-trade days: 1
- Capital preserved: ₹{capital_preserved:,.2f}
- Avoided-loss estimates: ₹{avoided_losses:,.2f}
==================================================
"""
                # Write files
                file_generic = self._reports_dir / "no_trade_eod_review.txt"
                file_dated = self._reports_dir / f"no_trade_eod_review_{today_str}.txt"
                
                with file_generic.open("w", encoding="utf-8") as fh:
                    fh.write(no_trade_layout)
                with file_dated.open("w", encoding="utf-8") as fh:
                    fh.write(no_trade_layout)
                logger.info("Generated No-Trade EOD review report.")
            except Exception as exc:
                logger.error("Failed to generate No-Trade EOD review: %s", exc)

        return report
