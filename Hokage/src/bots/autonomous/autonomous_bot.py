"""Autonomous Trading Bot for Hokage.

Coordinates background scheduled market scans, exit monitoring (TSL/TP),
opportunity ranking, risk sizing, and order placement via registered venues.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone, date as dt_date
from typing import Any, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor

from bots.research.models import ResearchQuery
from hokage.memory.resolver import PathResolver

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator

from integrations.brokers.models import (
    OrderRequest,
    OrderSide,
    OrderStatus,
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
from bots.autonomous import bias_rules, capital_regime
from bots.autonomous.cache import IntelligenceCache
from shared import power
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

from shared.watchdog.deadman import DeadMansSwitch

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

        self._trades_taken_today = []
        self._exits_executed_today = []
        self._last_crypto_report_date = None
        self._last_bar_key = None
        # Guards the once-a-day automatic plain-language EOD report send.
        self._eod_report_sent_date = None
        # Post-exit re-entry cooldown per UNDERLYING (UTC exit timestamps).
        # Same-day re-entries are allowed (evolution needs repetition), but an
        # immediate re-entry after an exit is usually the same thesis being
        # revenge-traded into the same tape. In-memory only: a restart clears
        # it, which at worst permits one earlier re-entry.
        self._underlying_exit_cooldowns: dict[str, datetime] = {}
        # Commander-requested instant exits (hard sell). Holds tracked-position
        # symbols the commander wants closed NOW, regardless of the ladder's
        # target/stop. The monitor's exit path honors these first, so a forced
        # exit gets the same full bookkeeping (journal outcome, strategy stats,
        # cooldown, tracking removal) as any other exit.
        self._forced_exits: set[str] = set()
        # Reason label for the current forced-exit sweep (kill switch vs
        # commander hard-sell) so the journal records WHY it closed.
        self._forced_exit_label: str | None = None
        # Post-win re-entry watermarks per underlying: after a TARGET_HIT
        # exit, same-direction re-entry needs the index PAST the exit level.
        # In-memory (a restart clears it — worst case one earlier re-entry).
        self._target_exit_watermarks: dict[str, dict[str, Any]] = {}

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
        # Honour the orchestrator's brain root. Constructing the journal with no
        # root silently fell back to HOKAGE_BRAIN_ROOT/CWD, so a bot running
        # under an explicitly-rooted orchestrator (portable deployment, test
        # sandbox) wrote its decisions into a DIFFERENT brain than the one that
        # reads them — the split that lets pytest reach the production journal.
        _brain_root = None
        try:
            _brain_root = self.orchestrator.resolver.resolve_brain_root()
        except AttributeError:
            pass  # No resolver (test double): fall back to the env/CWD default.
        self.journal = DecisionJournalSystem(_brain_root)
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

        # MCX Commodity Arena (commander-approved 2026-07-18): a fully
        # separate league — own file, own seed lineup, own 100,000/strategy
        # war chest — so its ledger can never mix with the index Dojo's.
        from bots.strategy.mcx_portfolio import (
            generate_mcx_seed_portfolio,
            MCX_STRATEGY_STARTING_CAPITAL,
        )
        self.mcx_strategy_portfolio = StrategyPortfolioManager(
            self._resolver,
            file_name="mcx_strategy_portfolio.json",
            starting_capital=MCX_STRATEGY_STARTING_CAPITAL,
            seed_generator=generate_mcx_seed_portfolio,
        )
        # Guards the once-a-day automatic MCX plain-language EOD report send.
        self._mcx_eod_report_sent_date = None

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
        """Load persistent stop levels from brain root.

        A FILE THAT WILL NOT PARSE IS NOT AN EMPTY BOOK. The empty dict this
        returns on failure is indistinguishable from "flat overnight", and it
        means every position still open starts the session with no stop and no
        target - the same loss as the critical-battery sleep that suspended
        Hokage for 7.5 hours mid-session, but arriving silently at boot.

        So the failure is CRITICAL rather than one ERROR among thousands, and
        the unreadable bytes are KEPT rather than overwritten by the first save
        of the new session. They are usually most of a valid file, and the
        stops are recoverable by hand from them.
        """
        if self._positions_file.exists():
            try:
                with self._positions_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                kept = self._positions_file.with_name(
                    f"{self._positions_file.stem}.unreadable-"
                    f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
                )
                try:
                    os.replace(self._positions_file, kept)
                except Exception:
                    kept = self._positions_file
                logger.critical(
                    "ACTIVE POSITIONS UNREADABLE (%s). Every position still open "
                    "is starting this session with NO stop and NO target. The "
                    "bytes are kept at %s - recover the levels from there before "
                    "trusting the exit path.", exc, kept,
                )
        return {}

    def _save_positions_tracking(self) -> None:
        """Save stop levels to brain root, atomically.

        THE OLD VERSION COULD DESTROY THIS FILE BY TRYING TO WRITE IT.
        json.dump streams into a handle already opened "w" - the truncate
        happens FIRST - so any value it cannot serialize leaves the real file
        cut off mid-key and unparseable. On 2026-10-28 a datetime reached
        "_archived_at" and did exactly that, 168 times across two days, while
        positions were open: active_positions.json ended at byte 639 and the
        only surviving copy of those stops and targets was process memory.

        Two defences, because one was clearly not enough:
          * the write lands in a temp file and is renamed over the real one,
            so a failure costs the NEW copy and never the old one
          * default=str, so an unserializable value becomes a string in the
            file rather than costing every stop in it
        """
        tmp = self._positions_file.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._active_positions_tracking, fh, indent=2, default=str)
            os.replace(tmp, self._positions_file)
        except Exception as exc:
            logger.error(f"Failed to save active positions: {exc}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _entry_family_of(self, strategy_name: str | None) -> str:
        """Volume-gate entry family for the strategy that is ACTUALLY trading.

        "breakout" carries the surge demand (BREAKOUT_MIN_RATIO); every other
        family is held only to the thin-tape floor (TREND_MIN_RATIO), because a
        pullback or mean-reversion entry happens on quiet retracement tape by
        design.

        THIS USED TO TAKE A SYMBOL and answer with
        `strategy_portfolio.select_strategy(symbol)` — the strategy the
        PORTFOLIO would pick, asked before the league had run. The league then
        reassigns selected_strat from its own winner, so the strategy whose
        family chose the threshold was frequently not the strategy that would
        have traded. 260 of 278 volume rejections in Hokage's history were made
        on the breakout bar, and 242 of those would have passed the trend bar.
        MeanReversion was being starved by MacroBreakout's threshold on symbols
        MacroBreakout might not even win.

        Takes the winner's NAME now, so the question is asked of the module
        whose signal is about to become a position.
        """
        return "breakout" if "breakout" in (strategy_name or "").lower() else "trend"

    def strategy_deployed_capital(self) -> dict[str, float]:
        """Capital locked in open positions per strategy_id.

        One league: every position is a real paper-venue position tagged with
        the strategy that entered it. Cost basis = entry price * quantity (for
        options the entry price is the premium paid, so the lock equals the
        real premium outlay).
        """
        deployed: dict[str, float] = {}
        for tracking in self._active_positions_tracking.values():
            strat_id = tracking.get("strategy_id")
            if not strat_id:
                continue
            cost = float(tracking.get("entry_price", 0.0)) * float(tracking.get("quantity", 0.0))
            deployed[strat_id] = deployed.get(strat_id, 0.0) + cost
        return deployed

    @staticmethod
    def _strategy_supports(strat: dict[str, Any], symbol: str) -> bool:
        """Whether this strategy is allowed to compete for this symbol.

        Edge is measured PER ASSET and it does not travel. Measured 2026-08-11
        with tools/research/entry_module_lab.py, the same module is a winner on
        one commodity and a loser on another:

            SessionShift  GOLDM t=+3.17 / SILVERM t=+2.71  but NATURALGAS t=-2.14
            RangeFade     NATURALGAS t=+2.33               but GOLDM/SILVERM negative

        They are near mirror images, so a league where every strategy judges
        every asset must run each of them on ground where it measurably loses.
        `supported_assets` already existed on every strategy record but the
        entry scan never read it — it appeared once, in an unrelated similarity
        check. This is the seam that makes it mean something.

        FAILS OPEN. A missing or empty list means "no restriction recorded", so
        a strategy is never silently muted by an absent field; only a list that
        exists and excludes the symbol keeps a strategy out. Every strategy
        today lists its full universe, so enforcing this changes nothing until
        a scope is deliberately narrowed.
        """
        assets = strat.get("supported_assets")
        if not assets:
            return True
        return symbol.upper() in {str(a).upper() for a in assets}

    @staticmethod
    def _no_verdict_reason(
        symbol: str, scoped_count: int, out_of_scope: list[str]
    ) -> str:
        """Why nothing judged this symbol, when nothing judged this symbol.

        A SCOPE IS CONFIGURATION, NOT A VERDICT, so the scan loops no longer
        journal "{name}: not scoped to {symbol}." every pass. That can leave
        the verdict list empty, and a no-trade carrying no reason at all reads
        as "nothing was even considered" - indistinguishable from a scan that
        crashed before it started.

        The two causes are different problems and must not share a message:
        nothing is scoped to this asset (a coverage gap - it cannot be traded
        at all, and that is the failure the boot audit exists to catch), or
        strategies are scoped but none has an entry module registered (a
        wiring fault). Named, with the out-of-scope strategies listed, so the
        gap is readable without the portfolio JSON in hand.

        The wording keeps "scoped to" so gate_analytics tallies it as
        STRATEGY_SCOPE/COVERAGE rather than UNCLASSIFIED.
        """
        if scoped_count == 0:
            listed = ", ".join(out_of_scope) if out_of_scope else "none live"
            return (
                f"StrategyScope: no live strategy is scoped to {symbol} "
                f"(out of scope: {listed}). This asset cannot be traded."
            )
        return (
            f"StrategyScope: {scoped_count} strategies are scoped to {symbol} "
            f"but none has an entry module registered."
        )

    def _is_counter_trend_strategy(self, strategy_id: str | None) -> bool:
        """True when this strategy's entry module bets AGAINST the prevailing
        move, and must therefore skip the trend-alignment gate."""
        if not strategy_id:
            return False
        try:
            from bots.strategy.components.entries import ENTRY_MODULES
            from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES
        except Exception:
            return False
        module = ENTRY_MODULES.get(strategy_id) or MCX_ENTRY_MODULES.get(strategy_id)
        return bool(getattr(module, "COUNTER_TREND", False))

    def _resolve_strategy_id(
        self, record: Any, strategies: dict | None
    ) -> str | None:
        """The id a strategy record is filed under: its own field, or failing
        that the key it lives at.

        A record is the VALUE in a dict keyed by its own id, so carrying that
        id inside itself looks redundant — and `strat-eiareaction-mcx-v1` did
        not carry it. See `audit_strategy_records`, which now names any record
        thinner than its peers at boot.

        WHY THIS EXISTS RATHER THAN A `.get()` AT EACH SITE. The MCX entry
        path reads `selected_strat["strategy_id"]` by subscript in four
        places and the index path in six, so a thin record that clears the
        gates raises KeyError in the middle of a scan. Reading it leniently
        instead is worse: `_strategy_available_capital` does not raise on an
        unknown id, it falls through to STRATEGY_STARTING_CAPITAL and hands
        the strategy a FULL FRESH CHEST in place of its real remaining
        balance. Unresolvable must therefore mean "stand aside", loudly —
        never a default, never a crash.

        THE COUNTER-TREND GATES READ THIS TOO, since 2026-10-30, on the
        commander's word. `_is_counter_trend_strategy` looks the id up in
        ENTRY_MODULES / MCX_ENTRY_MODULES, which are keyed by exactly these
        ids, so a record that could not name itself was silently "not
        counter-trend" — and `EIAReactionEntry.COUNTER_TREND = True`, added
        in a68de90 on 2026-10-23 for precisely this gate, could never fire.
        It held the shipped exemption shut for a week.

        The blast radius is one strategy. Every other record in both leagues
        carries its own id and was already resolving correctly, so RangeFade,
        FadeRange and MeanReversion are unaffected: only EIAReaction changes,
        and only to the behaviour already approved for it.
        """
        if not isinstance(record, dict):
            return None
        stored = record.get("strategy_id")
        if stored:
            return str(stored)
        # Identity, not equality: two strategies can hold equal dicts, and the
        # question here is which key THIS object is filed under.
        for sid, candidate in (strategies or {}).items():
            if candidate is record:
                return str(sid)
        return None

    @staticmethod
    def _holding_seconds(entry_meta: dict | None) -> float:
        """How long the position was actually held, from its own entry stamp.

        Every exit-path consumer used to be handed a hardcoded 3 days, so
        GOLDM26NOV141000PE (71 minutes) and SILVERM26NOV184000PE (6 minutes)
        were both recorded as three-day holds on 2026-10-30, their generated
        lessons said "3d hold", and the calibration engine compared a constant
        3 against an expected 3 and reported perfect agreement about a number
        nobody had measured.

        0.0 means UNREADABLE, and it is the honest answer here: it cannot be
        mistaken for a real hold, where the 3 days it replaces looked exactly
        like one.
        """
        stamp = (entry_meta or {}).get("entry_timestamp")
        if not stamp:
            return 0.0
        try:
            started = datetime.fromisoformat(str(stamp))
        except (TypeError, ValueError):
            return 0.0
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())

    def _strategy_display_name(self, strategy_id: str | None) -> str | None:
        """Human name for a strategy id, e.g. 'TrendPullback'.

        Four strategies share one account, so an alert that says a trade
        happened without saying WHO made it hides the only thing the tournament
        exists to measure. Looks in both leagues; falls back to the raw id
        rather than inventing a name, and returns None when there is nothing to
        attribute (manual commander trades carry their own label).
        """
        if not strategy_id:
            return None
        for manager in (
            getattr(self, "strategy_portfolio", None),
            getattr(self, "mcx_strategy_portfolio", None),
        ):
            if manager is None:
                continue
            try:
                strat = manager.portfolio.get("strategies", {}).get(strategy_id)
            except Exception:
                continue
            if strat and strat.get("name"):
                return str(strat["name"])
        if strategy_id.startswith("COMMANDER_MANUAL"):
            return "Commander (manual)"
        return strategy_id

    def _portfolio_manager_for_strategy(self, strategy_id: str):
        """Route a strategy_id to its OWNING league (index Dojo vs MCX Arena).

        Two StrategyPortfolioManager instances exist so their ledgers can
        never mix. Any strategy_id not registered in the MCX portfolio falls
        back to the index portfolio — the original, unchanged behavior for
        every index strategy and for legacy/manual strategy_ids.
        """
        mcx_pf = getattr(self, "mcx_strategy_portfolio", None)
        if mcx_pf is not None and strategy_id in mcx_pf.portfolio.get("strategies", {}):
            return mcx_pf
        return self.strategy_portfolio

    def _strategy_available_capital(self, strategy_id: str) -> float:
        """Remaining war chest for one strategy (starting + realized - deployed)."""
        deployed = self.strategy_deployed_capital()
        portfolio_mgr = self._portfolio_manager_for_strategy(strategy_id)
        for row in portfolio_mgr.get_capital_report(deployed):
            if row["strategy_id"] == strategy_id:
                return float(row["available"])
        from bots.strategy.portfolio import STRATEGY_STARTING_CAPITAL
        return STRATEGY_STARTING_CAPITAL

    def _strategy_chest_size(self, strategy_id: str) -> float | None:
        """Full war chest for one strategy (starting + realized), or None.

        The denominator the premium cap is written in: MAX_PREMIUM_CHEST_FRACTION
        caps a single position at 33% of THIS number.
        `_strategy_available_capital` returns what is LEFT after open positions,
        which is a moving target — the same trade would score differently
        depending on what else happened to be open at the time.

        None, never a default. `_strategy_available_capital` falls through to
        STRATEGY_STARTING_CAPITAL for an id it does not recognise, which is the
        fallback that hands an unresolvable strategy a full fresh chest; a
        post-trade GRADE must say "unknown" rather than inherit that.
        """
        if not strategy_id:
            return None
        try:
            deployed = self.strategy_deployed_capital()
            portfolio_mgr = self._portfolio_manager_for_strategy(str(strategy_id))
            for row in portfolio_mgr.get_capital_report(deployed):
                if row["strategy_id"] == strategy_id:
                    chest = float(row["starting_capital"]) + float(row["realized_pnl"])
                    return chest if chest > 0 else None
        except Exception as exc:
            logger.debug(
                "Could not resolve the war chest for %s: %s", strategy_id, exc
            )
        return None

    def _chest_fraction_pct(
        self,
        strategy_id: str,
        entry_price: float,
        quantity: float,
    ) -> float | None:
        """Premium committed at entry as a percentage of the strategy's chest.

        Frozen into the entry record because it is only knowable AT entry: the
        chest moves with every realized exit, so asking this question after the
        fact answers a different question. Stamped by all three entry paths —
        index, MCX Arena and manual — so the sizing grade means one thing.
        """
        chest = self._strategy_chest_size(strategy_id)
        if not chest or chest <= 0:
            return None
        try:
            cost = float(entry_price) * float(quantity)
        except (TypeError, ValueError):
            return None
        if cost <= 0:
            return None
        return round(cost / chest * 100.0, 4)


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

        # THE WATCH THAT DOES NOT LIVE ON THIS MACHINE. Started last, so a
        # heartbeat is only sent once the loop it reports on is actually
        # running. See shared.watchdog.deadman: between 2026-09-23 and
        # 2026-10-08 Hokage was gone for eleven market sessions and the
        # on-machine liveness probe went down with him.
        self._deadman = DeadMansSwitch(status_fn=self._deadman_status)
        self._deadman.start()

        self._thread = threading.Thread(target=self._run_loop, name="HokageAutonomousLoop", daemon=True)
        self._thread.start()
        logger.info("Autonomous trading loop started.")

        # WHICH CODE IS THIS. Hokage ran 44 hours on 2026-11-07's build while
        # three restarts reported success, and nothing could report the gap:
        # every panel asks the running process how it is, and a stale process
        # is perfectly healthy. The commit on disk at boot IS the commit this
        # process runs, because boot is when the files were read.
        try:
            from shared.ops import code_version

            # publish=True: this process IS the bot, so it may claim the
            # shared record that other processes - the 06:30 brief above all -
            # read to say whether a restart is pending.
            code_version.record_boot(publish=True)
            logger.info("Code version: %s", code_version.describe())
        except Exception as exc:
            logger.debug("Could not read the code version: %s", exc)

        # WHAT DAY IS IT. Six gates in this system decide what to do from the
        # weekday, and on 2026-11-08 every one of them was wrong. One line at
        # boot makes the day's actual hours readable without a log dive, and
        # names a session the archive has seen that the table has not.
        try:
            from hokage.memory import trading_calendar

            logger.info("Session calendar: %s", self._describe_today())
            unlisted = trading_calendar.unlisted_sessions_from_archive()
            if unlisted:
                logger.warning(
                    "Session calendar: the archive has candles for %s, which "
                    "this calendar calls closed - a special session is "
                    "missing from the table and every calendar-gated sender "
                    "will go silent through it",
                    ", ".join(str(d) for d in unlisted))
        except Exception as exc:
            logger.debug("Could not describe today's session: %s", exc)

    def _cleanup_stale_paper_positions(self) -> None:
        """On startup, close any open paper positions that are older than today.
        
        Stale open positions in the DB will block the MaxPositionsRiskRule and prevent
        new trades. This cleanup runs at bot start and on midnight reset.
        """
        try:
            account_id = self.orchestrator.paper_venue._account_id
            account = self.orchestrator.portfolio_store.load_account(account_id)
            from bots.execution.models import TradeStatus
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


    def _deadman_status(self) -> str:
        """The one line that rides along with each heartbeat.

        Convenience, not signal: the heartbeat's presence is what the switch
        measures. Nothing here may be sensitive — it is displayed by an
        outside service — so it carries no account, no credential and no
        instrument-level detail.
        """
        # IN-MEMORY STATE ONLY. This runs on the heartbeat thread, whose one
        # job is to prove the process is alive; reaching into the database
        # for a nicer status line would put a lock between that proof and
        # the thing it proves.
        bits = []
        try:
            mode = self.orchestrator.context.execution_mode
            bits.append(getattr(mode, "value", str(mode)))
        except Exception:
            bits.append("mode unknown")
        probe_ok = getattr(self, "_feed_probe_ok", None)
        bits.append("feed ok" if probe_ok is True else
                    ("feed down" if probe_ok is False else "feed unknown"))
        reason = getattr(self, "_feed_probe_reason", "") or ""
        if probe_ok is False and reason:
            bits.append(str(reason)[:80])
        return " | ".join(bits)

    def stop(self) -> None:
        """Stop the background autonomous thread gracefully."""
        # FIRST, so the final /fail carries a reason even if something below
        # throws. An alert that says "stopped cleanly" is a different message
        # from one that says nothing at all.
        deadman = getattr(self, "_deadman", None)
        if deadman is not None:
            deadman.stop("clean shutdown")
            self._deadman = None

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

        # Hand the host's power management back. An unclean exit gets the same
        # result for free — the request dies with the process — so this is
        # tidiness, not a load-bearing guarantee.
        try:
            power.release_system_awake()
        except Exception as exc:
            logger.debug(f"Releasing the host sleep guard failed: {exc}")
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

                # Auto-send the plain-language end-of-day report once, shortly
                # after the NSE close (square-off is 15:20 IST). Non-trader
                # friendly recap of every trade — pushed to Telegram.
                if dt_time(15, 35) <= ist_time < dt_time(16, 30):
                    if self._eod_report_sent_date != current_date_str:
                        self._eod_report_sent_date = current_date_str
                        if self._segment_shut_today("NSE"):
                            # NOT A `continue`. Everything below in this tick -
                            # the MCX report, the per-exchange shadow sessions -
                            # still has to run, and the loop's own sleep is at
                            # the bottom, so a continue here would busy-spin.
                            logger.info(
                                "Skipping the equity end-of-day report - %s",
                                self._describe_today())
                        else:
                            try:
                                report = self.build_eod_plain_report()
                                if self.telegram_bot and self.telegram_bot.enabled:
                                    self.telegram_bot.send_message(report)
                                logger.info("Sent plain-language end-of-day report.")
                            except Exception as exc:
                                logger.error(f"Failed to send EOD plain report: {exc}")

                # MCX Arena's own evening plain-language report, sent once
                # shortly after its 23:15 square-off (commander-approved
                # 2026-07-18 plan: a second report for the commodity league).
                if dt_time(23, 35) <= ist_time < dt_time(23, 59, 59):
                    if self._mcx_eod_report_sent_date != current_date_str:
                        self._mcx_eod_report_sent_date = current_date_str
                        if self._segment_shut_today("MCX"):
                            logger.info(
                                "Skipping the MCX end-of-day report - %s",
                                self._describe_today())
                        else:
                            try:
                                mcx_report = self.build_eod_plain_report(
                                    account_id="paper_mcx", venue_id="paper_mcx",
                                    title=f"MCX Arena — {ist_now.strftime('%A, %d %b %Y')}",
                                )
                                if self.telegram_bot and self.telegram_bot.enabled:
                                    self.telegram_bot.send_message(mcx_report)
                                logger.info("Sent MCX Arena plain-language end-of-day report.")
                            except Exception as exc:
                                logger.error(f"Failed to send MCX EOD plain report: {exc}")

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

                # 0a. Did we just wake from a coma? A sleeping laptop takes the
                # whole risk engine with it: on 2026-07-30 Windows slept the
                # machine at 10:28 on a critical battery and it stayed down till
                # 18:03, so an open BANKNIFTY put sat 7.5 hours with no stop, no
                # trail and no thesis-stop, then squared off after the close for
                # -4,248 — two thirds of the day's loss. Nothing announced it and
                # health read 100/100 the second it woke. Say it out loud.
                try:
                    self._check_for_unconscious_gap()
                except Exception as exc:
                    logger.error(f"Wake-gap check failed: {exc}")

                # 0a-bis. Do not merely REPORT the coma — prevent it. Both of
                # 2026-08-12's gaps were the Windows idle timer firing on
                # schedule (uptime 5h08m and 5h02m against an 18000s setting),
                # because a headless Hokage looks exactly like an unused
                # laptop. Re-asserted every iteration on purpose: the request
                # is per-thread and dies with the thread that set it.
                try:
                    power.hold_system_awake(announce=True)
                except Exception as exc:
                    logger.error(f"Host sleep guard failed: {exc}")

                # 0a-ter. Can every strategy that will compete today actually
                # afford to fill? Once per boot; see audit_strategy_chests.
                try:
                    self._announce_broke_strategies()
                except Exception as exc:
                    logger.error(f"Strategy chest audit failed: {exc}")

                # 0a-quater. And can every asset actually be traded by someone?
                # A broke strategy fails loudly at the router; an orphaned asset
                # fails silently forever. See audit_asset_coverage.
                try:
                    self._announce_orphaned_assets()
                except Exception as exc:
                    logger.error(f"Asset coverage audit failed: {exc}")

                # 0a-quinquies. And is every competitor's RECORD complete? A
                # broke strategy fails at the router and an orphaned asset
                # never trades; a record missing one field changes how the
                # gates judge it and says nothing at all. See
                # audit_strategy_records.
                try:
                    self._announce_incomplete_strategy_records()
                except Exception as exc:
                    logger.error(f"Strategy record audit failed: {exc}")

                # 0b. A critical-battery sleep is not a surprise — it is a
                # countdown. Warn while there is still time to plug in. The
                # guard above does NOT cover this: ES_SYSTEM_REQUIRED stops the
                # idle timer, not a machine running out of power.
                try:
                    self._check_battery_runway()
                except Exception as exc:
                    logger.error(f"Battery runway check failed: {exc}")

                # 0. Is the market data feed even answering? This runs FIRST and
                # in its own guard: a dead feed is exactly the condition that
                # makes the steps below throw, and when they threw, the shared
                # except swallowed the iteration and the blind-system alarm
                # further down never ran at all.
                try:
                    self._check_data_feed_session()
                except Exception as exc:
                    logger.error(f"Data feed health check failed: {exc}")

                # 0b. Is the candle archive missing a session? The nightly sync
                # runs at 23:40 so the MCX session is complete, and needs a live
                # broker token to write anything. The commander logs in in the
                # MORNING, and Kite expires a token daily — so the 23:40 run
                # found the session UNREACHABLE on 11-01, 11-04, 11-05, 11-07
                # and 11-08, and refused to write rather than record a short
                # day as a real one. Correct, and it still left Sunday's
                # Muhurat tape missing until it was pulled by hand.
                #
                # Nothing is lost by a single skip — `sync` re-fetches a 90-day
                # window, so a later success repairs the nights before it. What
                # is lost is the guarantee, because a contract that rolls
                # between the skip and the next success takes its tape with it.
                # So: a catch-up from inside Hokage, when the token is freshest.
                try:
                    self._catch_up_candle_archive()
                except Exception as exc:
                    logger.error(f"Candle archive catch-up failed: {exc}")

                # 0c. What can this account size actually TRADE? Runs after the
                # feed check on purpose — it needs real quotes, and it stays
                # silent until it gets them. Announcing "you can trade nothing"
                # off a dead feed would be a false alarm of exactly the kind
                # the blind-system work existed to kill. Once per boot.
                try:
                    self._announce_capital_regime()
                except Exception as exc:
                    logger.error(f"Capital regime check failed: {exc}")

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
                        try:
                            self._scan_and_enter_mcx_opportunities()
                        except Exception as exc:
                            logger.error(f"MCX Arena scan failed (index league unaffected): {exc}")

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

                # Reached only when the whole iteration completed without
                # raising, so this heartbeat means "the scan loop is doing its
                # job" rather than "a timer thread is still alive". A loop that
                # throws every cycle now goes stale and shows up in the health
                # score, which is exactly what did NOT happen while Hokage spent
                # seven days failing every scan at 100.0/100 health.
                try:
                    self.orchestrator.publish_heartbeat("strategy_engine", "HEALTHY")
                except Exception as exc:
                    logger.debug(f"Could not publish strategy_engine heartbeat: {exc}")

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


    def _get_atr_for_symbol(self, symbol: str) -> float | None:
        """14-period ATR on the 15-minute interval, or None when unknowable.

        RETURNS None RATHER THAN INVENTING A NUMBER (2026-08-25). It used to
        fall back to 1.5% of price, and then to a literal 1.0. On 2026-08-25 a
        Kite rate limit made GOLDM's calculation fail twice, and the fallback
        handed back:

            GOLDM price 160,907  ->  fabricated ATR 2,413.6
            thesis stop = 1.25 x ATR = 3,017 points
            real GOLDM ATR that week was 345.29 and 246.64
            -> a stop SEVEN TIMES too wide

        A fabricated risk number is worse than a missing one, because every
        rung downstream treats it as measured. The two GOLDM trades the week
        before stopped out after 563 and 321 points; a 3,017-point stop would
        never have fired at all, and the position would have looked protected
        the whole time.

        This is the doctrine the rest of the ladder already follows — the
        volume gate skips when its context is unavailable, the liquidity check
        falls back and SAYS SO, excursions record None rather than 0.0. ATR was
        the one place still guessing.
        """
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            from datetime import datetime, timedelta, UTC
            instrument = self.orchestrator.price_source.resolve_instrument(symbol)
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(UTC) - timedelta(days=self._INTRADAY_LOOKBACK_DAYS),
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
        
        # No fallback. An unknown ATR is unknown; callers must decide whether
        # they can proceed without it, and the entry path refuses to.
        logger.warning(
            f"ATR unavailable for {symbol}; returning None rather than a "
            f"fabricated value. Any rung or entry that needs it must stand down."
        )
        return None

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
            if not atr or atr <= 0:
                # Sizing divides by ATR. Without it there is no risk-based
                # quantity to compute, and guessing one would size a position
                # off an invented number — the exact failure this returns None
                # to prevent. Zero means "no trade", which every caller already
                # treats as a stand-aside.
                logger.warning(
                    f"Cannot size {symbol}: ATR unavailable, so risk-based "
                    f"quantity is undefined. Standing aside."
                )
                return 0.0
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
    #: Commander-approved 2026-07-16: widened from 14:00. EOD square-off is
    #: 15:20 IST, so a 15:00 entry still has a 20-minute runway; Malfoy keeps
    #: its own 14:00 cutoff as a module trait.
    _NSE_LAST_ENTRY = (15, 0)
    #: Minutes an underlying stands down after an exit before it may be
    #: re-entered the same day (blocks revenge re-entry into the same tape).
    #: Commander-approved 2026-07-16: 30 -> 15.
    _REENTRY_COOLDOWN_MINUTES = 15
    #: India VIX percentile above which BUYING options is blocked — premium is
    #: statistically rich and the move must beat an inflated price (Natenberg).
    #: Calendar days of 15-minute history to request for ATR, the bias engine
    #: and MarketContext.
    #:
    #: CALENDAR DAYS ARE NOT TRADING DAYS, and that was the bug. ATR asked for
    #: 2 days and needed 14 bars; the bias engine and MarketContext asked for 3
    #: and needed 21. On a MONDAY, "now - 2 days" reaches back to Saturday, the
    #: market was shut, and the window holds only Monday's own bars. The 14th
    #: fifteen-minute bar does not exist until three and a half hours after the
    #: open.
    #:
    #: Measured 2026-10-12, a Monday: ATR was unavailable for all seven assets
    #: from 10:00 to 12:15, and NIFTY reached the SIZING stage three times in
    #: that window and stood down -- "Cannot size NIFTY: ATR unavailable" at
    #: 10:31, 10:45 and 11:00. Three entries that had already passed every gate
    #: were lost to a lookback, not to a judgement.
    #:
    #: Ten days always contains several trading sessions, even across a long
    #: weekend or a Diwali-length holiday cluster. One prior session alone
    #: supplies 25 bars on NSE and 58 on MCX, so this is generous on purpose:
    #: the cost is a slightly larger history fetch, and the alternative is
    #: Hokage being structurally unable to size a trade every Monday morning.
    _INTRADAY_LOOKBACK_DAYS = 10

    _VIX_PERCENTILE_BLOCK = 0.80
    _VIX_LOOKBACK_DAYS = 60

    def _entry_conduct_gate(
        self, symbol: str, direction: str, counter_trend: bool = False
    ) -> tuple[bool, str]:
        """Time-of-day windows, underlying bias alignment, IV premium guard.

        Each check runs only when its data exists — a missing feed skips that
        check (logged), it never fabricates a value. Returns (allowed, reason).

        `counter_trend` skips ONLY the bias-alignment check, for strategies
        whose thesis is to bet against the prevailing move. That check permits
        longs on a BULLISH tape and shorts on a BEARISH one, so a fade — which
        fires exactly when price is stretched from VWAP — can never satisfy it.
        Measured over six weeks of real NIFTY/BANKNIFTY bars: MeanReversion
        produced 16 valid signals and the gate allowed 0. RangeFade had the same
        disease and had also never traded. Every other gate still applies: time
        windows, IV premium, volume, correlation cluster and the chest cap.
        """
        symbol_upper = symbol.upper()
        is_mcx = symbol_upper.replace("_", "").startswith(("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"))

        # 1. NSE time-of-day protections (MCX runs its own sessions).
        # Commander-approved 2026-07-16: the GLOBAL midday blackout is gone.
        # It was cloned from the Malfoy benchmark's conduct rules and blocked
        # EVERY strategy 11:30-13:30 — two hours of tape nobody could trade,
        # starving the league of the very data evolution needs. The blackout
        # survives as Malfoy's personal trait inside its own entry module
        # (that is its identity); other strategies judge midday on merit.
        if not is_mcx:
            now = self._now_ist()
            hm = (now.hour, now.minute)
            if hm >= self._NSE_LAST_ENTRY:
                return False, "Late-session cutoff (15:00 IST): no new entries into the close."

        # 2. Bias alignment on the underlying: longs only with a bullish tape,
        # shorts only with a bearish tape, stand aside when mixed. Skipped for
        # counter-trend strategies, which carry their own (inverted) trend guard
        # and would otherwise be refused every single time.
        bias = None if counter_trend else self._compute_underlying_bias(symbol)
        if counter_trend:
            logger.info(
                f"Bias alignment skipped for {symbol}: counter-trend entry judged by its "
                f"own trend guard."
            )
        if bias == "MIXED":
            return False, "Bias engine: underlying tape is MIXED — standing aside."
        if bias == "BULLISH" and direction != "long":
            return False, "Bias engine: bearish entry against a BULLISH tape."
        if bias == "BEARISH" and direction != "short":
            return False, "Bias engine: bullish entry against a BEARISH tape."
        if bias is None and not counter_trend and symbol.upper() not in bias_rules.VETO_DISABLED_SYMBOLS:
            # Only say "no data" when that is actually why. A symbol whose veto
            # has been measured down also returns None, and it logs its own
            # reason inside _compute_underlying_bias; claiming a data outage
            # here would send anyone reading the log hunting a feed fault that
            # does not exist.
            logger.info(f"Bias engine: no intraday data for {symbol}; bias check skipped.")

        # 3. IV premium guard: we BUY options; block when India VIX sits in the
        # top quintile of its trailing range (premium too rich).
        #
        # NSE INDEX OPTIONS ONLY. Commander-approved 2026-10-19.
        #
        # India VIX is the implied volatility of NIFTY options. Using it to
        # refuse a GOLDM option purchase is a category error: it is a
        # statement about the price of index premium and says nothing about
        # the price of gold premium. That argument stands on its own, and the
        # measurement agrees with it.
        #
        # iv_lab, 2026-10-19, SessionShift — the only ACTIVE strategy, and
        # GOLDM/SILVERM the only two cells it can trade. Realised edge in ATR
        # units, audit geometry:
        #
        #     GOLDM   hold    passed n=88  +0.470   blocked n=19  +0.659
        #     SILVERM train   passed n=179 -0.006   blocked n=98  +0.047
        #     SILVERM hold    passed n=234 +0.173   blocked n=55  +0.247
        #
        # Three measurable halves, and in every one the signals this guard
        # threw away did BETTER than the ones it passed. None of it is
        # significant — blocked reads t+1.50, +0.29, +1.28 — so this is NOT
        # evidence that blocking helps. It is the absence of any evidence
        # that the guard filters, with a consistent direction across three
        # independent halves, on top of the category error.
        #
        # WHAT THIS COSTS, recorded because it is real. On the modules that
        # are archived or parked, the same guard measured as genuine
        # protection:
        #
        #     RangeFade  / GOLDM   train  passed +0.648 t+3.37  blocked -0.141
        #     RangeFade  / SILVERM hold   passed -0.073         blocked -0.632 t-4.83
        #     EventRider / GOLDM   train  passed -0.031         blocked -0.516 t-2.01
        #
        # Those modules do not trade today. IF ONE OF THEM IS EVER UN-PARKED
        # ON AN MCX SYMBOL, THIS EXEMPTION MUST BE REVISITED FIRST — the
        # protection it removes was measured, and on RangeFade/SILVERM it was
        # measured at t-4.83. test_iv_guard_is_nse_only.py fails if that
        # happens.
        #
        # The threshold itself is untouched: _VIX_PERCENTILE_BLOCK is still
        # 0.80 and still applies in full to NIFTY, BANKNIFTY and SENSEX.
        if not is_mcx:
            vix_pct = self._india_vix_percentile()
            if vix_pct is not None and vix_pct >= self._VIX_PERCENTILE_BLOCK:
                return False, (
                    f"IV premium guard: India VIX at {vix_pct:.0%} percentile of "
                    f"{self._VIX_LOOKBACK_DAYS}d range — option premium too rich to buy."
                )

        return True, "conduct gates passed"

    #: NIFTY/BANKNIFTY/SENSEX move ~90% together — simultaneous same-direction
    #: entries across them are ONE macro bet taken multiple times. On
    #: 2026-07-17 three 12:15 CE entries lost together (-6.3k in 100 minutes).
    #: Cap same-direction exposure across the family (commander-approved).
    _INDEX_FAMILY = {"NIFTY", "BANKNIFTY", "SENSEX", "BANKEX", "FINNIFTY", "MIDCPNIFTY"}
    _MAX_FAMILY_SAME_DIRECTION = 2

    @staticmethod
    def _position_direction(pos: dict[str, Any]) -> str:
        """Directional sense of a tracked position: long or short.

        Bought options carry the bet in the CONTRACT TYPE (CE = long the
        index, PE = short the index) while side stays BUY; non-options carry
        it in the side.
        """
        opt_type = str(pos.get("option_type") or "").upper()
        if opt_type.startswith("C"):
            return "long"
        if opt_type.startswith("P"):
            return "short"
        return "long" if str(pos.get("side", "BUY")).upper() == "BUY" else "short"

    def _journal_no_trade(self, symbol: str, reasons: list[str]) -> None:
        """Record an MCX refusal the way the index league already records its own.

        2026-09-02: the commander asked Hokage on Telegram "Why no trades so
        far?" and got "I have no trade recorded to explain yet." Chasing that
        found this: `no_trade_decisions` held 75 rows for the day and EVERY ONE
        was an index asset. The MCX league logged its stand-asides to the log
        file, published them on the bus, and journaled NOTHING.

        So the gate tally, the daily briefing and any answer about why nothing
        traded were all structurally blind to the entire commodity arena — the
        league holding most of the capital, and the one carrying the assets the
        commander wants mastered. A refusal that is only ever printed is a
        refusal nobody can count.

        Never fatal: a journal write must not be able to stop a scan.
        """
        try:
            from bots.autonomous.models import NoTradeDecision

            journal = getattr(self, "journal", None)
            if journal is None:
                return
            journal.record_no_trade_decision(NoTradeDecision(
                asset=str(symbol).upper(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                decision="NO_TRADE",
                confidence=0.0,
                reasons=tuple(reasons),
                supporting_evidence={"league": "MCX"},
                invalidated_setups=(),
                next_review_time="",
            ))
        except Exception as exc:
            logger.debug(f"Could not journal the MCX no-trade for {symbol}: {exc}")

    def _entry_cluster_gate(
        self,
        symbol: str,
        direction: str,
        underlying_price: float | None,
        family: set[str] | None = None,
        max_same_direction: int | None = None,
        family_label: str = "index-family",
        counter_trend: bool = False,
    ) -> tuple[bool, str]:
        """Portfolio-level entry checks the per-trade gates cannot see.

        1. Correlation cap: at most `max_same_direction` open positions
           betting the same way across `family`. Defaults to the index
           family/cap; the MCX Arena calls this with its own ENERGY/PRECIOUS
           family sets (2026-07-18) — same discipline, different universe.
        1b. No opposing bet: the family may not be bet both ways at once.
           Hokage buys premium only, so opposing legs on correlated underlyings
           cancel the edge and keep both theta bills (2026-07-30).
        2. Re-entry watermark: after a TARGET_HIT win, the same direction on
           that underlying is only allowed if the index has pushed PAST the
           level where we took profit — never buying the dip of our own
           winner (the 13:03 re-entry mistake, -1,774).
        """
        symbol_upper = symbol.upper()
        direction = "short" if str(direction).lower().startswith("s") else "long"
        family = family if family is not None else self._INDEX_FAMILY
        cap = max_same_direction if max_same_direction is not None else self._MAX_FAMILY_SAME_DIRECTION

        # --- 1. correlation cap across the family --------------------------
        if symbol_upper in family:
            same_dir = 0
            opposing: list[str] = []
            for pos in self._active_positions_tracking.values():
                und = str(pos.get("underlying") or "").upper()
                if und not in family:
                    continue
                if self._position_direction(pos) == direction:
                    same_dir += 1
                else:
                    opposing.append(und)
            if same_dir >= cap:
                return False, (
                    f"CorrelationCap: already {same_dir} same-direction ({direction}) {family_label} "
                    f"positions open — one shared bet, not several."
                )
            # --- 1b. no opposing bet inside a correlated family ------------
            # The cap stopped the same bet being taken three times, but nothing
            # stopped the family being bet BOTH ways at once: on 2026-07-30
            # Hokage held NIFTY calls, SENSEX calls and BANKNIFTY puts together.
            # Hokage only ever BUYS premium, so that is not a hedge — on indices
            # that move ~90% together the directional edge largely cancels while
            # both legs keep paying theta and a spread. If the tape has genuinely
            # turned, the correct response is for the open position to EXIT via
            # the ladder, not to be offset by a second premium purchase.
            if opposing:
                counter = "short" if direction == "long" else "long"
                return False, (
                    f"OpposingFamilyBet: already {counter} on "
                    f"{', '.join(sorted(set(opposing)))} while this is a {direction} bet on the same "
                    f"{family_label}. Buying both sides of one correlated move pays two premiums "
                    f"for a net-flat book — if the thesis flipped, the open position should exit."
                )

        # --- 2. post-win re-entry watermark --------------------------------
        # TREND-FOLLOWING MODULES ONLY, since 2026-08-27.
        #
        # The rule says "not buying the dip of our own winner", which is sound
        # for a module whose thesis is that the move continues. Applied to a
        # COUNTER-TREND module it is exactly inverted: RangeFade exists to buy
        # a price stretched BELOW VWAP, so a lower price is a BETTER entry, not
        # a stale one. The gate was per-symbol and could not see which module
        # had won the auction.
        #
        # WHAT IT COST, on the one asset with a confirmed edge:
        #
        #     2026-08-27  RangeFade won the NATURALGAS auction   17 times
        #                 blocked by this watermark              16
        #                 actually traded                         1  (+2,000)
        #
        # MEASURED before changing, train vs hold-out, full geometry — is the
        # Nth signal of a day worse than the first?
        #
        #     1st of the day   TRAIN n=5  +1.907 t=+1.10 | HOLD n=20 -0.059 t=-0.21
        #     2nd onward       TRAIN n=11 +1.946 t=+2.15 | HOLD n=71 +0.225 t=+1.28
        #     3rd onward       TRAIN n=7  +2.148 t=+2.93 | HOLD n=51 +0.267 t=+1.38
        #
        # The repeats measure BETTER than the first on both halves, and the
        # hold-out puts the first signal of the day slightly NEGATIVE. The
        # watermark was keeping the worst signal and discarding the best.
        #
        # Neither bucket clears t>=2 on both halves and the ordinal split is a
        # proxy (the watermark only triggers after a PROFITABLE exit), so this
        # is not a confirmed edge — it is the removal of a rule the evidence
        # does not support, from the one module whose thesis it contradicts.
        # Commander-approved 2026-08-27. Trend modules keep it in full force.
        if counter_trend:
            return True, "cluster gates passed (watermark n/a: counter-trend module)"

        wm = getattr(self, "_target_exit_watermarks", {}).get(symbol_upper)
        if wm and wm.get("direction") == direction and isinstance(underlying_price, (int, float)):
            level = float(wm.get("level") or 0.0)
            if level > 0:
                stale = (direction == "long" and underlying_price <= level) or (
                    direction == "short" and underlying_price >= level
                )
                if stale:
                    return False, (
                        f"ReentryWatermark: took {direction} profit on {symbol_upper} at index level "
                        f"{level:.2f}; now {underlying_price:.2f} — not buying the dip of our own winner. "
                        f"Re-entry unlocks past {level:.2f}."
                    )

        return True, "cluster gates passed"

    #: The veto's thresholds and per-asset rule table now live as module-level
    #: values in `bots.autonomous.bias_rules`, so `tools/research/veto_lab.py`
    #: can score the exact branch production executes instead of a copy that
    #: drifts. These aliases preserve the historical class-attribute names for
    #: every existing caller and test — read the module for the measurements
    #: behind each entry.
    _BIAS_MIN_SESSION_BARS = bias_rules.MIN_SESSION_BARS
    _BIAS_VWAP_ATR_FRACTION = bias_rules.VWAP_ATR_FRACTION
    _BIAS_RULE_BY_SYMBOL = bias_rules.RULE_BY_SYMBOL
    _BIAS_REVERSION_ATR = bias_rules.REVERSION_ATR
    _BIAS_PULLBACK_ATR = bias_rules.PULLBACK_ATR

    def _compute_underlying_bias(self, symbol: str) -> str | None:
        """Classify the underlying tape as BULLISH / BEARISH / MIXED from real
        intraday candles, using the per-asset rule in `bias_rules`.

        Returns None when the veto has no opinion — either because no intraday
        data is available, or because the veto has been MEASURED to subtract
        from the entry module it gates on this symbol.
        """
        if symbol.upper() in bias_rules.VETO_DISABLED_SYMBOLS:
            # Not a bypass: a measured verdict. veto_lab.py scored the entry
            # module with and without this gate on real candles and the gate
            # made it worse, so direction is left to the component that was
            # measured choosing it. See bias_rules.VETO_DISABLED_SYMBOLS.
            logger.info(
                f"Bias engine: veto stood down on {symbol} — measured to subtract "
                f"from the entry module here; direction left to the module."
            )
            return None
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            instrument = self.orchestrator.price_source.resolve_instrument(symbol)
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=self._INTRADAY_LOOKBACK_DAYS),
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

        last_day = candles[-1].timestamp.date()
        session = [c for c in candles if c.timestamp.date() == last_day]
        price = closes[-1]

        # Session VWAP. Genuinely volume-weighted on MCX futures, which carry
        # real traded volume — and the MCX rules below lean on it heavily
        # (vwap_reversion measured t=+5.14 on CRUDEOIL). On NSE index SPOT the
        # feed reports volume 0, so this degrades to a plain mean of closes and
        # carries no information; that is exactly why the index rule below is
        # the one branch that never touches it.
        vol_sum = sum((c.volume or 0.0) for c in session)
        if vol_sum > 0:
            vwap = sum(((c.high + c.low + c.close) / 3.0) * (c.volume or 0.0)
                       for c in session) / vol_sum
        else:
            vwap = sum(c.close for c in session) / len(session) if session else price

        trs: list[float] = []
        for prev, cur in zip(candles[-15:-1], candles[-14:]):
            trs.append(max(cur.high - cur.low,
                           abs(cur.high - prev.close),
                           abs(cur.low - prev.close)))
        atr = (sum(trs) / len(trs)) if trs else 0.0

        # The verdict itself is `bias_rules.classify_tape` — the same function
        # tools/research/veto_lab.py scores. Everything above this line is
        # fetching and deriving; everything below it is reporting. Keeping the
        # decision in one pure, importable place is what makes the veto
        # measurable at all, and an unmeasured veto is how a module with
        # t=+3.17 came to be blocked 15 times in one session.
        verdict, reason = bias_rules.classify_tape(
            symbol=symbol,
            price=price,
            vwap=vwap,
            atr=atr,
            ema9=ema9,
            ema21=ema21,
            recent_closes=closes[-4:],
            session_bar_count=len(session),
        )
        if verdict == "MIXED":
            logger.info(f"Bias engine: {reason}")
        return verdict

    #: How many consecutive context failures on one asset before the arena
    #: stops treating it as bad luck. Scans run about every 15 minutes, so
    #: four is roughly an hour of an asset being untradeable - long enough
    #: not to fire on a transient quote hiccup, short enough that a session
    #: is not lost before anyone hears about it. Ten hours were lost to this
    #: across 2026-10-26 and 10-27 with no alarm at all.
    _CTX_FAILURES_BEFORE_ALARM = 4

    #: After this many, clear the provider's futures-symbol cache ONCE and
    #: say so. A bounded, logged hypothesis - not a silent retry loop.
    _CTX_FAILURES_BEFORE_RESET = 8

    @property
    def _ctx_failure(self) -> dict:
        """Why each symbol's context last failed. Created lazily so the
        hundreds of places that build a bare bot in tests keep working."""
        if not hasattr(self, "_ctx_failure_reasons"):
            self._ctx_failure_reasons: dict[str, str] = {}
        return self._ctx_failure_reasons

    @property
    def _ctx_misses(self) -> dict:
        """Consecutive context failures per symbol."""
        if not hasattr(self, "_ctx_miss_counts"):
            self._ctx_miss_counts: dict[str, int] = {}
        return self._ctx_miss_counts

    def _note_context_miss(self, symbol: str) -> str:
        """Count a context failure, escalate if it is becoming a blackout.

        Returns the sentence the caller should log, which always carries the
        REASON - the thing whose absence made this invisible for two days.
        """
        misses = self._ctx_misses.get(symbol, 0) + 1
        self._ctx_misses[symbol] = misses
        why = self._ctx_failure.get(symbol) or "no reason recorded"
        line = (f"MCX Arena: no live market context for {symbol}; standing "
                f"aside. ({why}; miss {misses})")

        if misses == self._CTX_FAILURES_BEFORE_ALARM:
            alarm = (f"{symbol} has had no market context for "
                     f"{misses} consecutive scans — it is untradeable and the "
                     f"rest of the arena is unaffected. Last reason: {why}")
            logger.critical(f"ARENA BLACKOUT — {alarm}")
            if self.telegram_bot:
                try:
                    self.telegram_bot.send_message(f"ARENA BLACKOUT\n\n{alarm}")
                except Exception as exc:
                    logger.debug(f"Could not send the blackout alert: {exc}")

        if misses == self._CTX_FAILURES_BEFORE_RESET:
            # ONE bounded attempt, with its result readable in the next scan.
            try:
                source = getattr(self.orchestrator, "price_source", None)
                cache = getattr(source, "_futures_symbol_cache", None)
                if isinstance(cache, dict) and cache:
                    cache.clear()
                    logger.warning(
                        f"{symbol}: clearing the futures-symbol cache once after "
                        f"{misses} failed scans. If the next scan succeeds, a "
                        f"stale contract resolution was the cause.")
            except Exception as exc:
                logger.debug(f"Could not clear the futures cache: {exc}")
        return line

    def _clear_context_miss(self, symbol: str) -> None:
        """A context that built is the end of the streak."""
        if self._ctx_misses.pop(symbol, None):
            logger.info(f"MCX Arena: market context for {symbol} is back.")
        self._ctx_failure.pop(symbol, None)

    def _build_market_context(self, symbol: str, cache: dict[str, Any] | None = None) -> Any:
        """Build the live tape snapshot every entry module reads.

        Built ONCE per symbol per scan (via `cache`) and shared by all
        competitors, so the tournament judges every strategy on byte-identical
        data — a strategy must not win because it got a fresher quote.

        Returns None when the venue cannot supply enough real candles; callers
        must then stand aside rather than evaluate on a fabricated tape.
        """
        from bots.strategy.components.models import MarketContext

        if cache is not None and symbol in cache:
            return cache[symbol]

        ctx = None
        try:
            from integrations.data.models import HistoricalDataRequest, CandleInterval
            instrument = self.orchestrator.price_source.resolve_instrument(symbol)
            req = HistoricalDataRequest(
                instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=self._INTRADAY_LOOKBACK_DAYS),
                end=datetime.now(timezone.utc),
                interval=CandleInterval.FIFTEEN_MINUTES,
            )
            res = self.orchestrator.price_source.get_historical_candles(req)
            candles = list(res.candles) if res and res.candles else []
        except Exception as exc:
            # KEPT, NOT DROPPED. This line used to be the only record of why
            # an asset was untradeable, and it was at DEBUG - so the MCX arena
            # went dark for two full sessions (2026-10-26, 2026-10-27) with
            # nothing in the log but "no live market context" sixty times.
            self._ctx_failure[symbol] = f"{type(exc).__name__}: {str(exc)[:160]}"
            logger.debug(f"MarketContext: intraday candles unavailable for {symbol}: {exc}")
            candles = []

        if candles and len(candles) < 21:
            # NOT AN ERROR, AND STILL A REASON. A short series is a different
            # fault from a failed fetch and the two were indistinguishable.
            self._ctx_failure[symbol] = (
                f"only {len(candles)} candles, need 21")
        if len(candles) >= 21:
            self._ctx_failure.pop(symbol, None)
            closes = [c.close for c in candles]
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]

            def _ema(values: list[float], period: int) -> float:
                k = 2.0 / (period + 1.0)
                ema = values[0]
                for v in values[1:]:
                    ema = v * k + ema * (1.0 - k)
                return ema

            last_day = candles[-1].timestamp.date()
            session = [c for c in candles if c.timestamp.date() == last_day]
            vol_sum = sum((c.volume or 0.0) for c in session)
            if vol_sum > 0:
                vwap = sum(((c.high + c.low + c.close) / 3.0) * (c.volume or 0.0) for c in session) / vol_sum
            else:
                vwap = sum(c.close for c in session) / len(session) if session else closes[-1]

            minutes_in = None
            if session:
                open_ts = session[0].timestamp
                minutes_in = int((candles[-1].timestamp - open_ts).total_seconds() // 60)

            try:
                atr = self._get_atr_for_symbol(symbol)
            except Exception:
                atr = None

            regime_data = self.cache.read_intelligence("market_regime.json") or {}
            ctx = MarketContext(
                symbol=symbol,
                price=closes[-1],
                ema9=_ema(closes[-30:], 9),
                ema21=_ema(closes[-42:], 21),
                vwap=vwap,
                closes=tuple(closes),
                highs=tuple(highs),
                lows=tuple(lows),
                atr=atr,
                regime=regime_data.get("prediction", "UNKNOWN"),
                vix_percentile=self._india_vix_percentile(),
                minutes_into_session=minutes_in,
                #: Off the candle, never datetime.now(). The session being
                #: traded is whatever the tape says it is; a wall-clock read
                #: would disagree with it on any replay and would be a
                #: fabricated value in exactly the way ATR used to be.
                session_date=last_day,
                #: Same source, same reason. See MarketContext.minute_of_day.
                minute_of_day=(candles[-1].timestamp.hour * 60
                               + candles[-1].timestamp.minute),
            )

        if cache is not None:
            cache[symbol] = ctx
        return ctx

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
            candles = list(res.candles if res else ())
            self._archive_vix(candles)
            closes = [c.close for c in candles][-self._VIX_LOOKBACK_DAYS:]
        except Exception as exc:
            logger.debug(f"IV premium guard: India VIX history unavailable: {exc}")
            return None
        if len(closes) < 20:
            return None
        current = closes[-1]
        below = sum(1 for c in closes if c <= current)
        return below / len(closes)

    @staticmethod
    def _archive_vix(candles) -> None:
        """Keep the VIX history this guard just fetched, forever.

        VIX is the ONLY input to the gate that can switch Hokage off entirely,
        and until 2026-10-16 it was archived nowhere — every lab that wanted to
        ask a volatility question had to borrow a live Zerodha session, so the
        answer existed only while a token did. The guard already pulls 70 daily
        bars whenever it runs, so writing them down costs no extra broker call
        and happens on exactly the days a session exists.

        It can never affect the guard: a failure here is logged at debug and
        the percentile is computed from the candles regardless. The archive
        itself refuses to store the session in progress.
        """
        try:
            from hokage.memory import vix_archive

            vix_archive.remember(candles)
        except Exception as exc:
            logger.debug(f"VIX archive write skipped: {exc}")

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

    #: Prior sessions required before a time-of-day volume baseline is trusted.
    #: Fewer than this and the "typical" curve is one or two days of noise, so
    #: the gate is skipped rather than run against a baseline we cannot stand
    #: behind.
    _VOLUME_MIN_PRIOR_SESSIONS = 3
    _VOLUME_PROFILE_LOOKBACK_DAYS = 14

    def _get_volume_context(self, symbol: str, quote: Any) -> tuple[float, float] | None:
        """Return (today_cumulative_volume, typical_cumulative_volume_at_this_time).

        Both sides are REAL and measured at the SAME point in the session.

        The previous version divided today's *partial* cumulative volume by the
        average *complete* 14-day session. That ratio rises from ~0 to ~1 purely
        as the day ages, so it measured the clock, not the tape: on 2026-07-15
        NIFTY it ran 0.20x at 09:15 to 0.87x at 15:15 and never once reached the
        1.20x breakout bar — the breakout family could not fire at any hour of
        any day, and CRUDE_OIL's evening "THIN_TAPE 0.35x" was simply 18:15.

        Comparing today's cumulative volume at time T against the average
        cumulative volume at the same T on prior sessions removes the intraday
        volume curve from the measurement. 1.0x then means "normal for this time
        of day" and the family thresholds recover the meaning they were written
        with. Same-day NIFTY re-measured this way: 1.31x at 09:15 — a real surge
        the old denominator scored as 0.20x.

        The live quote is deliberately not the source for today's side: its
        cumulative volume may span different session boundaries than the candle
        series the baseline is built from, and comparing two differently-bounded
        numbers is the bug this method exists to fix. ``quote`` is retained only
        as the caller's liveness check.

        Returns None when the data cannot support an honest comparison (no
        candles, too few prior sessions, no matching time-of-day bucket) — the
        caller must then SKIP the gate rather than run it on invented numbers.
        """
        try:
            from datetime import timedelta

            from integrations.data.models import CandleInterval, HistoricalDataRequest

            start = datetime.now(timezone.utc) - timedelta(days=self._VOLUME_PROFILE_LOOKBACK_DAYS)
            end = datetime.now(timezone.utc)

            # An INDEX HAS NO VOLUME OF ITS OWN, so ask for the futures series
            # whose volume represents it. NIFTY and BANKNIFTY got this by
            # accident — they resolve to NFO futures — while SENSEX resolved to
            # BSE:SENSEX, the index, whose volume is None. Today's volume then
            # came back 0, this method returned None, and the caller SKIPPED the
            # gate: across 200 volume rejections not one was SENSEX.
            #
            # Volume only. Price, ATR, bias and strike selection still read the
            # index, because a futures basis would skew all four.
            candles: list[Any] = []
            _volume_candles = getattr(
                self.orchestrator.price_source, "get_volume_candles", None
            )
            if callable(_volume_candles):
                candles = list(
                    _volume_candles(symbol, start, end, CandleInterval.FIFTEEN_MINUTES)
                    or []
                )

            if not candles:
                # No volume series known, or a provider without one (mock, or a
                # non-Kite feed). Fall back to the instrument's own candles; if
                # those carry no volume either, the checks below return None and
                # the caller skips the gate rather than inventing a ratio.
                instrument = self.orchestrator.price_source.resolve_instrument(symbol)
                if instrument is None:
                    return None
                res = self.orchestrator.price_source.get_historical_candles(
                    HistoricalDataRequest(
                        instrument=instrument,
                        start=start,
                        end=end,
                        interval=CandleInterval.FIFTEEN_MINUTES,
                    )
                )
                candles = list(res.candles) if res and res.candles else []
            if not candles:
                return None

            by_day: dict[Any, list[Any]] = {}
            for c in candles:
                by_day.setdefault(c.timestamp.date(), []).append(c)

            days = sorted(by_day)
            today, prior_days = days[-1], days[:-1]
            if len(prior_days) < self._VOLUME_MIN_PRIOR_SESSIONS:
                return None

            # Today's cumulative volume, and the session clock we compare at.
            today_bars = sorted(by_day[today], key=lambda c: c.timestamp)
            current_vol = sum(float(c.volume or 0) for c in today_bars)
            if current_vol <= 0:
                return None
            marker = today_bars[-1].timestamp.strftime("%H:%M")

            # Average cumulative volume reached by this same clock time on prior
            # sessions. A day that had not yet traded to this point contributes
            # nothing — a half-session must not be averaged in as if complete.
            peers: list[float] = []
            for day in prior_days:
                run = 0.0
                reached = False
                for c in sorted(by_day[day], key=lambda c: c.timestamp):
                    run += float(c.volume or 0)
                    if c.timestamp.strftime("%H:%M") == marker:
                        reached = True
                        break
                if reached and run > 0:
                    peers.append(run)

            if len(peers) < self._VOLUME_MIN_PRIOR_SESSIONS:
                return None
            return current_vol, sum(peers) / len(peers)
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

    # An auth-shaped failure means the token is dead; a network-shaped one means
    # the feed is merely unreachable. Both blind Hokage, but only the first is
    # fixed by logging in again — and sending the commander to a login page over
    # a DNS blip wastes his time, so the two are never conflated.
    _AUTH_ERROR_TAGS = ("token", "auth", "session", "api_key", "forbidden", "403")
    _NETWORK_ERROR_TAGS = (
        "getaddrinfo", "resolve", "timed out", "timeout", "unreachable",
        "max retries", "connection refused", "connection aborted", "connection reset",
        # Zerodha's own servers failing is THEIR outage, not a dead token.
        # On 2026-08-05 17:51 Kite returned a 502 Bad Gateway; none of the tags
        # above matched, the fallback below blamed auth, and the commander was
        # told to log in while his session was perfectly valid. Sending him to
        # a login page during a broker outage is the exact misdirection this
        # classifier exists to prevent.
        "502", "503", "504", "bad gateway", "service unavailable", "gateway time",
        "text/html",  # an HTML body from a JSON API is a proxy/error page
    )

    def _diagnose_feed_failure(self, reason: str) -> str:
        """Classify a dead feed as 'auth', 'network', or 'unknown'.

        The provider wraps a rejected token as the maddeningly generic "Venue is
        not connected.", which matches neither tag set. When the message settles
        nothing, ask Kite directly — one round trip, and only ever on a feed
        that is already down.
        """
        low = reason.lower()
        if any(tag in low for tag in self._AUTH_ERROR_TAGS):
            return "auth"
        if any(tag in low for tag in self._NETWORK_ERROR_TAGS):
            return "network"
        try:
            from integrations.brokers.secrets import SecretManager
            from kiteconnect import KiteConnect
            mgr = SecretManager()
            api_key = mgr.get_secret("api_key", broker="zerodha")
            access_token = mgr.get_secret("access_token", broker="zerodha")
            if not api_key or not access_token:
                return "auth"
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            kite.profile()
            # Credentials are live, so the token is not what broke the feed.
            return "unknown"
        except Exception as exc:
            probe = str(exc).lower()
            if any(tag in probe for tag in self._NETWORK_ERROR_TAGS):
                return "network"
            if any(tag in probe for tag in self._AUTH_ERROR_TAGS):
                return "auth"
            # Do NOT default to blaming the token. An unrecognised failure is
            # unknown, and saying so beats sending the commander to re-login
            # for something a login cannot fix.
            return "unknown"

    #: Don't hammer Kite's auth endpoint while an outage persists. One attempt
    #: a minute recovers a mid-session login well inside a single scan cycle.
    _RECONNECT_MIN_INTERVAL_SECONDS = 60.0

    #: Consecutive NETWORK failures before the broker client is rebuilt.
    #:
    #: Three, because the feed is probed roughly once a minute: a real internet
    #: blip clears well inside that (2026-09-02's 08:58 outage healed in ~90
    #: seconds untouched), while the 13:53 one ran 47 minutes because nothing
    #: ever rebuilt the client. Below three this would churn the connection on
    #: every transient; far above it, the dead pool keeps costing trading hours.
    _NETWORK_REBUILD_AFTER = 3

    def _try_broker_reconnect(self) -> bool:
        """Re-authenticate the broker session in place, at most once a minute.

        The access token is read once at boot, so a login that happens later
        never reaches the running process. This is the seam that lets it.
        """
        import time as _time
        now = _time.monotonic()
        last = getattr(self, "_last_reconnect_attempt", None)
        if last is not None and (now - last) < self._RECONNECT_MIN_INTERVAL_SECONDS:
            return False
        self._last_reconnect_attempt = now

        manager = getattr(self.orchestrator, "kite_connection", None)
        if manager is None or not hasattr(manager, "try_reconnect"):
            return False
        if not manager.try_reconnect():
            return False

        # A live session is not the same as a live feed — prove it with the
        # quote that failed, so we never announce a recovery we cannot see.
        try:
            self.orchestrator.price_source.get_price("NIFTY 50")
        except Exception as exc:
            logger.warning(f"Broker session refreshed but the feed is still down: {exc}")
            return False
        return True

    @staticmethod
    def _chest_of(strat: dict[str, Any]) -> float:
        """What this strategy can actually put at risk: seed plus realized P&L.

        One definition, shared by the chest audit and the coverage audit. They
        disagreeing about what "can afford to trade" means is how an asset ends
        up reported as covered by a strategy that cannot fill.
        """
        capital = strat.get("capital") or {}
        try:
            return float(capital.get("starting", 0.0)) + float(capital.get("realized_pnl", 0.0))
        except (TypeError, ValueError):
            return 0.0

    #: Assets deliberately NOT traded, with the reason. An asset in here is a
    #: decision; an asset missing a strategy WITHOUT being in here is a bug.
    #: The coverage audit reports the two differently so a standing choice
    #: cannot desensitise the commander to a real orphan.
    #:
    #: CRUDEOIL parked 2026-08-26 after six sweeps, every one train vs hold-out
    #: on the cleaned corpus, every one failing out of sample:
    #:
    #:   stretch threshold, 6 bands      hold-out -0.33 .. -1.07, best +0.53
    #:   trend guard, 6 settings + off   hold-out -0.11 .. -1.28, ALL negative
    #:   evening window 17:00-22:30      hold-out -0.02 .. -1.27
    #:   horizon 30m..240m (no stop)     +2.06 at 240m — but see below
    #:   horizon x stop, 12 combos       hold-out -1.63 .. +0.82, none clears
    #:   direction inverted (follow)     train -7.72 / hold +1.49, mirror fail
    #:
    #: The 240-minute +2.06 was measured WITHOUT a stop. Adding the stop that
    #: production always has collapses it to +0.82 — the same full-geometry
    #: lesson SILVERM taught on 2026-08-15.
    #:
    #: Crude fails as a fade AND as a follow, so the signal carries no
    #: information there; this is not a tuning problem. It comes back when a
    #: crude-specific idea is built and measured, not before. NATURALGAS on the
    #: identical signal measures +3.37 out of sample.
    PARKED_ASSETS: dict[str, str] = {
        "CRUDEOIL": ("no measured edge in any configuration — 7 sweeps, all "
                     "failing out of sample; awaiting a crude-specific module"),
        # NATURALGAS UN-PARKED 2026-10-21, commander-approved, with the
        # measurement against it stated rather than hidden.
        #
        # It was parked because the fade went negative out of sample. That is
        # still true. Measured over the whole archive on 2026-10-21, three
        # horizons, every MCX module:
        #
        #     RangeFade      +0.225 t+1.65  +0.407 t+1.80  +0.065 t+0.22
        #     SessionShift   +0.051 t+0.39  +0.065 t+0.38  +0.035 t+0.16
        #     TrendRider     -0.029 t-0.29  -0.047 t-0.40  -0.315 t-2.03
        #     EventRider     -0.082 t-0.41  -0.325 t-1.08  -0.449 t-1.25
        #
        # Nothing clears t=2. Split train/hold, RangeFade is a textbook
        # overfit: +0.595 t+3.11 in sample against -0.239 t-1.91 out of it.
        #
        # THE REASON TO TRADE IT ANYWAY IS DATA, NOT EDGE. The old gas
        # evidence was destroyed by a futures roll before the candle archive
        # existed (see candle_archive); the archive now keeps every bar, so
        # from here a gas verdict compounds instead of evaporating. This is
        # paper money buying a measurable record.
        #
        # NATURALGAS: PARKED on 09-22, un-parked 10-21, re-parked briefly on
        # 2026-11-09 on cost, and UN-PARKED AGAIN the same day by commander
        # directive. It trades.
        #
        # THE MEASUREMENT AGAINST IT STANDS AND IS KEPT HERE RATHER THAN
        # DELETED. Priced live on 2026-11-09: a round trip costs 0.73-0.75% of
        # premium - the dearest book in the universe - against a best measured
        # edge of 0.22%. On those numbers every gas round trip loses on
        # arrival, and no sample size repairs that.
        #
        # THE REASON TO TRADE IT ANYWAY IS THE 10-21 REASON, RESTATED: a
        # record, not an edge. Paper money buying a measurable history on an
        # archive that now survives the futures roll. Noted plainly so that a
        # losing gas column is read as the price of that record rather than as
        # a surprise - and so that whoever reads this next can see the trade-
        # off was made with the numbers in hand, not in ignorance of them.
        #
        # UNPARKED IS NOT FUNDED. Gas is not in hokage.research.funded_cells,
        # so its cells answer to the full family's bar (3.22), not the
        # three-cell bar. Nothing here lowers the evidence required to ship a
        # gas change.
        #
        # PARKED 2026-11-09 on cost.
        "BANKNIFTY": ("round trip 0.69-0.75% against a measured edge of "
                      "0.65% - the margin is negative before theta"),
        "SILVERM": ("round trip 0.69-0.70% against a measured edge of 0.24%"),
    }

    #: The three cells the commander funded on 2026-11-09, and the ONLY assets
    #: left unparked. Kept here as the readable counterpart to PARKED_ASSETS:
    #: the enforcement is the parked list, and this is what it leaves standing.
    #: See hokage.research.funded_cells for the reasoning and the arithmetic.
    FUNDED_ASSETS: tuple[str, ...] = ("NIFTY", "SENSEX", "GOLDM")

    def is_parked(self, symbol: str) -> bool:
        """Whether this asset is a standing DECISION not to trade.

        Parked assets are skipped by the scan loop entirely. They were being
        evaluated every cycle and refused every cycle: on 2026-10-12, 108 of
        294 journal entries were "SessionShift: not scoped to CRUDEOIL" and
        "... to NATURALGAS", 37% of the day's record spent restating a choice
        already made. That buried the 16 IV-guard refusals and the 7 volume
        refusals, which were the only decisions that carried information.

        THIS DOES NOT MAKE THEM INVISIBLE, which is the thing that would make
        it dangerous. audit_asset_coverage still names each one at EVERY boot
        with its full reason, and the weekly audit's parked_watch still scores
        them from the candle archive, which keeps syncing them (they are in
        candle_archive.ASSETS and weekly_audit.UNIVERSE). The route back to
        trading them is measurement, and that route is untouched — only the
        per-cycle repetition is gone.
        """
        return symbol.upper() in self.PARKED_ASSETS

    def audit_asset_coverage(self) -> list[str]:
        """Name every asset in the universe that no live strategy can trade.

        THE FAILURE THIS EXISTS TO CATCH, found 2026-08-18 and six days late:
        TrendRider was archived on 2026-08-12 for measuring negative, and its
        200,000 chest was released to SessionShift. Both decisions were right.
        But TrendRider was the ONLY strategy scoped to CRUDEOIL, and
        SessionShift is scoped to GOLDM and SILVERM. CRUDEOIL quietly stopped
        being tradable and stayed that way for six sessions.

        Nothing alarmed, because nothing failed. Hokage competed, stood aside,
        and logged "not scoped to CRUDEOIL" twice a cycle — which at a glance
        is indistinguishable from a quiet tape. A dead asset and a patient one
        produce the same silence.

        `evolution.py` Rail 2 already refuses to autonomously archive a
        strategy when that would orphan an asset. But that rail guards the NEXT
        archive; it never inspected the lineup it inherited. A rule enforced
        only on new decisions is blind to the hole that predates it.

        COVERAGE HERE MEANS LIVE *AND* SOLVENT. A broke owner is not an owner:
        it wins the auction and converts the win into a stand-aside, which is
        precisely how an asset goes dark while the arena looks healthy.
        """
        from bots.strategy.mcx_portfolio import MCX_UNIVERSE

        findings: list[str] = []
        leagues = (
            ("Index Dojo", getattr(self, "strategy_portfolio", None),
             ["NIFTY", "BANKNIFTY", "SENSEX"]),
            ("MCX Arena", getattr(self, "mcx_strategy_portfolio", None),
             list(MCX_UNIVERSE)),
        )
        for league, manager, universe in leagues:
            portfolio = getattr(manager, "portfolio", None) or {}
            strategies = list((portfolio.get("strategies") or {}).values())
            if not strategies:
                # An unloaded league is a different fault with its own alarms.
                # Reporting every asset orphaned here would bury the real one.
                continue
            for asset in universe:
                # PARKED IS DECIDED FIRST, because coverage is irrelevant to an
                # asset the scan loop skips. Checking it last meant a parked
                # asset with strategies scoped to it counted as COVERED and its
                # parked status was never printed: on 2026-11-09, five live
                # strategies were scoped to NATURALGAS, so the audit announced
                # "every asset has a live strategy that can trade it" about an
                # asset that will not be scanned at all. A true sentence about
                # the book and a false one about the day.
                if asset.upper() in self.PARKED_ASSETS:
                    # A standing decision, not a fault. Reported so it stays
                    # visible, but never as an alarm - an alarm that fires every
                    # boot for a choice already made teaches the commander to
                    # ignore the one that matters.
                    logger.info(
                        f"{league}: {asset} is PARKED - "
                        f"{self.PARKED_ASSETS[asset.upper()]}"
                    )
                    continue
                solvent: list[str] = []
                broke: list[str] = []
                for strat in strategies:
                    if strat.get("status") in (None, "ARCHIVED"):
                        continue
                    if not self._strategy_supports(strat, asset):
                        continue
                    name = strat.get("name", strat.get("strategy_id", "?"))
                    if self._chest_of(strat) > 0:
                        solvent.append(name)
                    else:
                        broke.append(name)
                if solvent:
                    continue
                if broke:
                    findings.append(
                        f"{league}: {asset} has no strategy that can trade it. "
                        f"{', '.join(sorted(broke))} is scoped to it but holds no "
                        f"chest, so it will win the auction and fill nothing."
                    )
                else:
                    findings.append(
                        f"{league}: {asset} has NO live strategy scoped to it at "
                        f"all. It cannot trade today or any day until something is "
                        f"scoped onto it, or it is parked deliberately."
                    )
        return findings

    def audit_strategy_chests(self) -> list[str]:
        """Name every strategy that can compete but cannot afford to fill.

        THE FAILURE THIS EXISTS TO CATCH (2026-08-12): SessionShift was
        re-scoped to GOLDM/SILVERM on measured edge but its `capital.starting`
        was left at 0 from an earlier consolidation, leaving a chest of -1,280.
        It then won SIXTEEN auctions in one session and filled NONE — the
        router rejected every one with "Risk budget -422 affords 0 lots". From
        the outside the arena looked healthy: a strategy was competing, and
        winning. Nothing anywhere said the money was missing.

        A broke strategy is worse than an archived one. It still enters the
        tournament, still beats live rivals on confidence, and then converts
        its win into a stand-aside — so it does not merely fail itself, it
        denies the asset to whichever strategy would have traded it.

        Returns the human-readable findings so callers can announce them.
        """
        findings: list[str] = []
        leagues = (
            ("Index Dojo", getattr(self, "strategy_portfolio", None)),
            ("MCX Arena", getattr(self, "mcx_strategy_portfolio", None)),
        )
        for league, manager in leagues:
            portfolio = getattr(manager, "portfolio", None) or {}
            for strat in (portfolio.get("strategies") or {}).values():
                if strat.get("status") == "ARCHIVED":
                    continue  # cannot trade by design; an idle chest is fine
                chest = self._chest_of(strat)
                if chest > 0:
                    continue
                scope = ", ".join(strat.get("supported_assets") or []) or "all assets"
                findings.append(
                    f"{league}: {strat.get('name', strat.get('strategy_id', '?'))} "
                    f"({strat.get('status')}) has a chest of {chest:,.0f} and is scoped to "
                    f"{scope}. It will win auctions and fill nothing."
                )
        return findings

    #: Fields whose absence from a strategy record is not cosmetic, and what
    #: it costs. A record is the VALUE in a dict keyed by its own id, so
    #: storing that id inside itself looks redundant - right up until
    #: something asks the record what it is called.
    _LOAD_BEARING_STRATEGY_FIELDS = {
        "strategy_id": "the counter-trend exemption, the chest lookup and fill "
                       "attribution all read it from the record",
        "win_rate": "the tournament cannot score it",
        "expectancy": "the tournament cannot score it",
        "trade_count": "the tournament cannot score it",
        "sharpe_ratio": "the tournament cannot score it",
        "created_at": "the retirement clock has no start",
    }

    def audit_strategy_records(self) -> list[str]:
        """Name every competing strategy whose record is missing fields its
        peers have.

        THE FAILURE THIS EXISTS TO CATCH (2026-10-29): EIAReaction fired for
        only the second time in its life, won the auction, and was refused by
        the bias engine for being "too extended to join the trend" - the gate
        that a fade module is explicitly exempt from. It carries
        COUNTER_TREND = True, and commit a68de90 added that flag a week
        earlier for exactly this reason.

        The exemption never applied, because it is looked up by strategy id
        and EIAReaction's record was a stub: seven fields where every peer had
        eighteen, "strategy_id" among the missing. The lookup returned None,
        the exemption evaluated False, and a shipped fix sat inert for a week
        while the module it was written for kept being blocked.

        Nothing failed. No exception, no rejected order, no missing data - the
        record was simply thinner than its neighbours, and the one field that
        mattered reads as "not counter-trend" when it is absent.

        CONSERVATIVE ON PURPOSE: only fields that EVERY other competitor in
        that league carries are reported, so one unusual record cannot
        manufacture findings about the rest.

        Returns the human-readable findings so callers can announce them.
        """
        findings: list[str] = []
        leagues = (
            ("Index Dojo", getattr(self, "strategy_portfolio", None)),
            ("MCX Arena", getattr(self, "mcx_strategy_portfolio", None)),
        )
        for league, manager in leagues:
            portfolio = getattr(manager, "portfolio", None) or {}
            records = {
                sid: st for sid, st in (portfolio.get("strategies") or {}).items()
                if isinstance(st, dict) and st.get("status") != "ARCHIVED"
            }
            if len(records) < 2:
                continue            # nothing to compare a record against
            for sid, strat in records.items():
                peers = [set(other) for other_sid, other in records.items() if other_sid != sid]
                missing = sorted(set.intersection(*peers) - set(strat))
                if not missing:
                    continue
                line = (
                    f"{league}: {strat.get('name', sid)} ({sid}) is missing "
                    f"{len(missing)} field(s) that every other competitor has: "
                    f"{', '.join(missing)}."
                )
                for field in missing:
                    cost = self._LOAD_BEARING_STRATEGY_FIELDS.get(field)
                    if cost:
                        line += f" Without {field}, {cost}."
                findings.append(line)
        return findings

    def _announce_incomplete_strategy_records(self) -> None:
        """Run the record audit once per boot and say so loudly if it bites."""
        if getattr(self, "_record_audit_done", False):
            return
        self._record_audit_done = True
        try:
            findings = self.audit_strategy_records()
        except Exception as exc:
            logger.error(f"Strategy record audit failed: {exc}")
            return
        if not findings:
            logger.info("Strategy record audit: every competitor carries the same fields.")
            return
        for line in findings:
            logger.critical(f"INCOMPLETE STRATEGY RECORD - {line}")
        if not self.telegram_bot:
            return
        try:
            self.telegram_bot.send_message(
                "STRATEGY RECORD IS INCOMPLETE\n\n"
                + "\n\n".join(findings)
                + "\n\nThis throws no error. The strategy competes normally and "
                  "whatever reads the missing field quietly gets a default."
            )
        except Exception as exc:
            logger.debug(f"Could not send the record audit alert: {exc}")

    def _trade_context(
        self,
        symbol: str,
        tracking: dict[str, Any] | None,
        *,
        side: str,
        premium: float | None = None,
        target: float | None = None,
        edge: float | None = None,
        exit_price: float | None = None,
        exit_reason: str | None = None,
        pnl: float | None = None,
        strategy_reason: str | None = None,
    ) -> Any:
        """Assemble the facts needed to explain one trade in either register.

        Returns None on any failure. An explanation is a nicety; losing the
        alert that a real trade happened is not acceptable, so nothing here is
        allowed to propagate.
        """
        try:
            from bots.autonomous.trade_explainer import TradeContext

            track = tracking or {}
            strategy_id = track.get("strategy_id")
            underlying = track.get("underlying") or ""
            return TradeContext(
                tradingsymbol=symbol,
                side=side,
                strategy=self._strategy_display_name(strategy_id),
                strategy_reason=strategy_reason,
                premium=premium if premium is not None else track.get("entry_price"),
                lot_size=track.get("lot_size"),
                target=target if target is not None else track.get("target_price"),
                underlying_price=track.get("entry_underlying_price"),
                underlying_atr=track.get("entry_underlying_atr"),
                stop_atr_mult=self._thesis_atr_mult_for(strategy_id, underlying),
                edge_score=edge,
                exit_price=exit_price,
                exit_reason=exit_reason,
                pnl=pnl,
            )
        except Exception as exc:
            logger.debug(f"Could not build a trade context for {symbol}: {exc}")
            return None

    def price_universe_lots(self, symbols: list[str]) -> dict[str, float]:
        """Rupee cost of ONE lot of the ATM call for each symbol.

        Only symbols that actually quote are returned. An asset we could not
        PRICE is not the same as an asset we cannot AFFORD, and conflating them
        would turn a feed hiccup into a "you can trade nothing" alarm — exactly
        the class of false alarm the blind-system work existed to kill.
        """
        costs: dict[str, float] = {}
        source = getattr(self.orchestrator, "price_source", None)
        resolver = getattr(source, "resolve_option_contract", None)
        if resolver is None:
            return costs
        for symbol in symbols:
            try:
                spot = source.get_price(symbol)
                contract = resolver(symbol, "CE", spot)
                if not contract or float(contract.get("lot_size", 0)) <= 0:
                    continue
                premium = float(source.get_quote(contract["tradingsymbol"]).price)
                if premium <= 0:
                    continue
                costs[symbol.upper()] = premium * float(contract["lot_size"])
            except Exception as exc:
                logger.debug(f"Could not price a lot of {symbol}: {exc}")
        return costs

    def _announce_capital_regime(self) -> None:
        """Say, once per boot, what this account size can actually trade.

        PHASE 0 — REPORTING ONLY. Nothing here refuses an order; the router
        still enforces the cap. The point is that Hokage should KNOW he is
        priced out of an asset and say so at 08:45, instead of discovering it
        one rejected trade at a time.

        Measured 2026-08-15: a 20,000 account cannot hold a single lot of
        anything in this universe. The cheapest, NATURALGAS at 7,688, needs
        23,295 to sit inside the 33% cap.
        """
        if getattr(self, "_capital_regime_announced", False):
            return

        from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION
        from bots.strategy.mcx_portfolio import MCX_UNIVERSE

        index_universe = ["NIFTY", "BANKNIFTY", "SENSEX"]
        costs = self.price_universe_lots(index_universe + list(MCX_UNIVERSE))
        if not costs:
            # No quotes at all means the feed is not up yet, NOT that the
            # account is broke. Stay silent and retry on a later iteration.
            logger.debug("Capital regime: no lot could be priced yet; will retry.")
            return

        # WHAT DID NOT PRICE. price_universe_lots returns only the symbols
        # that quoted, which is correct — but a caller that reads the result
        # as "the universe" turns a feed gap into a confident, wrong answer.
        # On 2026-10-22 NATURALGAS simply vanished from this line, and the
        # line latched for the whole day off a read taken while the venue was
        # unauthenticated.
        wanted = {s.upper() for s in index_universe + list(MCX_UNIVERSE)}
        unpriced = wanted - set(costs)

        # A PARTIAL READ DOES NOT LATCH. Once-per-boot is right for a complete
        # picture and wrong for a half one, so the flag waits until every
        # symbol in scope has a price.
        complete = not unpriced
        if complete:
            self._capital_regime_announced = True

        lines: list[str] = []
        starved: list[str] = []

        for league, account_id, universe in (
            ("Index Dojo", "paper", index_universe),
            ("MCX Arena", "paper_mcx", list(MCX_UNIVERSE)),
        ):
            equity = self._account_equity(account_id)
            if equity is None:
                continue
            profile = capital_regime.profile_for(equity)
            in_scope = {u.upper() for u in universe}
            scoped = {s: c for s, c in costs.items() if s in in_scope}
            missing = sorted(in_scope - set(scoped))
            affordable, priced_out = capital_regime.affordable_assets(
                equity, scoped, MAX_PREMIUM_CHEST_FRACTION
            )
            head = f"{league}: {equity:,.0f} -> {profile.name} regime"
            if affordable:
                head += f" | can trade {', '.join(affordable)}"
            if priced_out:
                head += f" | PRICED OUT of {', '.join(priced_out)}"
            if missing:
                # UNKNOWN, stated. Never an omission the reader has to notice.
                head += f" | COULD NOT PRICE {', '.join(missing)}"
            lines.append(head)
            # Starvation is only a claim worth making about a complete scope.
            if not affordable and scoped and not missing:
                starved.append(league)

        if not lines:
            return

        # Say the first partial out loud, then stay quiet until the picture
        # changes or completes. Repeating an incomplete line every minute of
        # the session would bury the corrected one.
        previous = getattr(self, "_capital_regime_unpriced", None)
        if not complete and previous == unpriced:
            return
        self._capital_regime_unpriced = unpriced

        for line in lines:
            logger.info(f"Capital regime — {line}")
        if not complete:
            logger.info(
                f"Capital regime — {len(unpriced)} of {len(wanted)} symbols "
                f"did not quote ({', '.join(sorted(unpriced))}); this reading "
                f"is INCOMPLETE and will be taken again."
            )

        if starved:
            cheapest = min(costs.items(), key=lambda kv: kv[1])
            needed = capital_regime.minimum_account_for(
                cheapest[1], MAX_PREMIUM_CHEST_FRACTION
            )
            alarm = (
                f"{' and '.join(starved)} cannot afford ONE lot of anything in "
                f"scope. Cheapest is {cheapest[0]} at {cheapest[1]:,.0f}, which "
                f"needs {needed:,.0f} to sit inside the "
                f"{MAX_PREMIUM_CHEST_FRACTION:.0%} cap. Every entry will be "
                f"refused at the router."
            )
            logger.critical(f"CAPITAL STARVED — {alarm}")
            if self.telegram_bot:
                try:
                    self.telegram_bot.send_message(f"CAPITAL STARVED\n\n{alarm}")
                except Exception as exc:
                    logger.debug(f"Could not send the capital-regime alert: {exc}")

    def _account_equity(self, account_id: str) -> float | None:
        """Cash for one paper account, or None when it cannot be read.

        None means UNKNOWN and callers must stay silent — guessing an equity
        would produce a confident, wrong regime.
        """
        try:
            accounts = self.orchestrator.portfolio_bot.accounts
        except Exception:
            accounts = None
        if isinstance(accounts, dict):
            account = accounts.get(account_id)
            cash = getattr(account, "cash", None)
            if isinstance(cash, (int, float)):
                return float(cash)
        try:
            from shared.persistence.sqlite_stores import SqliteStores  # noqa: F401
        except Exception:
            pass
        try:
            import sqlite3

            db = self._resolver.resolve_brain_root() / "hokage.db"
            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "select cash from portfolio where account_id = ?", (account_id,)
                ).fetchone()
            return float(row[0]) if row else None
        except Exception as exc:
            logger.debug(f"Could not read equity for {account_id}: {exc}")
            return None

    def _announce_orphaned_assets(self) -> None:
        """Run the coverage audit once per boot and say so loudly if it bites.

        Deliberately CRITICAL and deliberately on Telegram. An orphaned asset
        produces no error, no exception and no failed order — only absence. The
        only way it becomes visible is if something announces it.
        """
        if getattr(self, "_coverage_audit_done", False):
            return
        self._coverage_audit_done = True
        try:
            findings = self.audit_asset_coverage()
        except Exception as exc:
            logger.error(f"Asset coverage audit failed: {exc}")
            return
        if not findings:
            # NAMES WHAT IT CHECKED. "every asset" was false the moment any
            # asset was parked - the audit skips those deliberately, and a
            # summary claiming to have cleared them is the kind of reassuring
            # sentence this project keeps paying for.
            parked = sorted(self.PARKED_ASSETS)
            if parked:
                logger.info(
                    "Asset coverage audit: every UNPARKED asset has a live "
                    "strategy that can trade it. Parked and not scanned: %s.",
                    ", ".join(parked))
            else:
                logger.info("Asset coverage audit: every asset has a live "
                            "strategy that can trade it.")
            return
        for line in findings:
            logger.critical(f"ORPHANED ASSET — {line}")
        if not self.telegram_bot:
            return
        try:
            self.telegram_bot.send_message(
                "ASSET CANNOT BE TRADED\n\n"
                + "\n\n".join(findings)
                + "\n\nThis raises no error and fills no order — it just never "
                  "trades. Scope a strategy onto it, or drop it from the universe."
            )
        except Exception as exc:
            logger.debug(f"Could not send the coverage audit alert: {exc}")

    def _announce_broke_strategies(self) -> None:
        """Run the chest audit once per boot and say so loudly if it bites."""
        if getattr(self, "_chest_audit_done", False):
            return
        self._chest_audit_done = True
        try:
            findings = self.audit_strategy_chests()
        except Exception as exc:
            logger.error(f"Strategy chest audit failed: {exc}")
            return
        if not findings:
            logger.info("Strategy chest audit: every competing strategy can afford to trade.")
            return
        for line in findings:
            logger.critical(f"BROKE STRATEGY — {line}")
        if not self.telegram_bot:
            return
        try:
            self.telegram_bot.send_message(
                "STRATEGY CANNOT TRADE\n\n"
                + "\n\n".join(findings)
                + "\n\nIt will still compete and win, then fail at the router. "
                  "Fix the chest or archive it."
            )
        except Exception as exc:
            logger.debug(f"Could not send the chest audit alert: {exc}")

    #: A loop iteration is ~60s. Anything past this means the process was not
    #: running the risk engine — almost always the machine slept.
    _MAX_LOOP_GAP_SECONDS = 300.0

    def _check_for_unconscious_gap(self) -> None:
        """Detect and announce a period where the loop was not running at all.

        A sleeping or suspended host does not merely pause scanning — it
        suspends the exit ladder, so every open position sits with no stop, no
        trail and no thesis-stop until the machine returns. That is the single
        most dangerous state Hokage can be in, and it is invisible: the loop
        simply resumes and the watchdog reports full health, because the gap is
        in the past. Compare wall clocks across iterations and say so.
        """
        now = self._now_ist()
        previous = getattr(self, "_last_loop_wall_clock", None)
        self._last_loop_wall_clock = now
        if previous is None:
            return
        gap = (now - previous).total_seconds()
        if gap <= self._MAX_LOOP_GAP_SECONDS:
            return

        minutes = gap / 60.0
        held = list(self._active_positions_tracking.keys())
        logger.critical(
            f"Loop gap of {minutes:.0f} minutes detected (host suspended?). "
            f"{len(held)} position(s) were unmanaged: {', '.join(held) if held else 'none'}."
        )
        if not self.telegram_bot:
            return
        if held:
            body = (
                "🚨 *HOKAGE WAS UNCONSCIOUS* 🚨\n"
                f"The loop did not run for *{minutes:.0f} minutes* — the machine was almost "
                "certainly asleep.\n"
                f"*{len(held)} position(s) had NO stop, NO trail and NO thesis-stop for that "
                "entire window*:\n"
                + "\n".join(f"• {self.telegram_bot.escape_markdown(s)}" for s in held)
                + "\n\nKeep the laptop plugged in and awake during market hours, or Hokage "
                "cannot manage risk on open trades."
            )
        else:
            body = (
                "⚠️ *HOKAGE WAS UNCONSCIOUS* ⚠️\n"
                f"The loop did not run for *{minutes:.0f} minutes* — the machine was almost "
                "certainly asleep. No positions were open, so nothing went unmanaged, but no "
                "scanning happened either."
            )
        self.telegram_bot.send_message(body)

    #: Warn while there is still runway to reach a charger. Windows' own
    #: critical-battery action fires far lower than this.
    _BATTERY_WARN_PERCENT = 30.0

    def _check_battery_runway(self) -> None:
        """Warn once per discharge cycle when the host is running out of power.

        Hokage's risk management only exists while the process runs. On
        2026-07-30 the battery hit critical at 10:28, Windows slept the machine,
        and an open position went 7.5 hours unmanaged. The battery level was
        knowable the whole time — nobody was watching it.
        """
        try:
            import psutil
            battery = psutil.sensors_battery()
        except Exception:
            return
        if battery is None:
            return

        if battery.power_plugged:
            # Reaching a charger re-arms the warning for the next discharge.
            self._battery_warning_sent = False
            return
        if battery.percent > self._BATTERY_WARN_PERCENT:
            self._battery_warning_sent = False
            return
        if getattr(self, "_battery_warning_sent", False):
            return

        held = list(self._active_positions_tracking.keys())
        logger.warning(
            f"Host on battery at {battery.percent:.0f}% with {len(held)} open position(s); "
            f"a critical-battery sleep would suspend all risk management."
        )
        if not self.telegram_bot:
            return
        detail = (
            f"*{len(held)} position(s) are open.* If this machine sleeps they lose their stops "
            "entirely."
            if held else
            "No positions are open right now, but scanning stops when the machine sleeps."
        )
        if self.telegram_bot.send_message(
            "🔌 *PLUG IN — BATTERY LOW* 🔌\n"
            f"Host battery is at *{battery.percent:.0f}%* and running on battery.\n"
            f"{detail}"
        ):
            self._battery_warning_sent = True

    def _record_feed_probe(self, ok: bool, reason: str) -> None:
        """Remember the outcome of the quote probe, and when.

        CONNECTION STATE IS NOT EVIDENCE. KiteConnectionManager.get_status()
        returns the state stored the last time connect() ran, and nothing
        updates it when the token dies underneath. On 2026-10-13 the token was
        invalidated at about 06:33, the feed logged CRITICAL every minute from
        06:33:24, and /broker/zerodha/status went on answering
        connected: true for another thirteen minutes - because the venue had
        connected successfully at 06:22:44 and nothing had told it otherwise.

        This is the one fact that cannot be stale in that way: a quote either
        came back or it did not, and the timestamp says how long ago. Anything
        asked to decide whether Hokage can see the market should ask here.

        Set by _check_data_feed_session only, which runs at the top of every
        loop iteration - roughly once a minute.
        """
        self._feed_probe_ok = ok
        self._feed_probe_at = datetime.now(timezone.utc)
        self._feed_probe_reason = reason

    def _nothing_trades_today(self) -> bool:
        """True ONLY when the calendar positively says every segment is shut.

        2026-11-07 was a Saturday. Hokage booted, found the overnight token
        dead as it is every morning, and sent "HOKAGE IS BLIND — ZERODHA LOGIN
        NEEDED" about a market that would not open for two days. There was
        nothing to be blind to.

        That is not a cosmetic complaint. This alarm exists because the feed
        once died for nine days and nobody was told; an alarm that also cries
        on every weekend and every holiday is how the real one gets ignored.
        `trading_calendar` was built on 2026-10-20 for exactly this - five
        login demands on Dussehra - and this alarm never asked it.

        UNKNOWN IS NOT CLOSED. `anything_trades` returns None for a date
        outside the calendar's span, and `is False` is the whole point: None
        and True both fall through to the alarm. A calendar that has not been
        updated for 2027 must produce noise, never silence.

        EVENING-ONLY DAYS STILL ALARM. On 2026-10-20 equities were shut but
        MCX ran from 17:00 - SessionShift's only window - so `anything_trades`
        is True and he still needs to log in.
        """
        try:
            from hokage.memory import trading_calendar

            return trading_calendar.nothing_trades(self._now_ist().date())
        except Exception:
            # A calendar that cannot be read must not silence an alarm.
            return False

    def _segment_shut_today(self, segment: str) -> bool:
        """True ONLY when the calendar positively says THIS league is shut.

        The daily plain-English report is not an alarm - nothing in it demands
        action - but on 2026-11-07, a Saturday, it still arrived at 15:35 to
        announce "No trades today" about a market that never opened. That is
        the same defect as the login nagging: a message whose content is the
        calendar, sent to someone who owns a calendar.

        PER LEAGUE, not per system. `_nothing_trades_today` is the right
        question for a whole-machine alarm and the wrong one here: on
        2026-10-20 equities were shut and MCX traded from 17:00, so the 15:35
        equity report was about nothing while the 23:35 MCX report was about
        a real session. One answer cannot serve both.

        Unknown still sends, for the same reason unknown still alarms.
        """
        try:
            from hokage.memory import trading_calendar

            return trading_calendar.segment_shut(self._now_ist().date(), segment)
        except Exception:
            # A calendar that cannot be read must not suppress a report.
            return False

    def _special_session_today(self) -> dict | None:
        """The special-session record for today, or None.

        A SPECIAL SESSION IS A TRADING DAY ON A DAY EVERY ORDINARY RULE CALLS
        SHUT. Three separate gates ask the weekday rather than the calendar -
        the engine's session status, the MCX entry guard and the Day-of-Week
        Isolator - and all three would have slept through Diwali Muhurat
        trading on Sunday 2026-11-08.
        """
        try:
            from hokage.memory import trading_calendar

            return trading_calendar.special_session(self._now_ist().date())
        except Exception:
            # A calendar that cannot be read changes nothing: the ordinary
            # weekday rules stand, exactly as they did before it existed.
            return None

    def _special_window_today(self, segment: str):
        """Today's published hours for one league, or None for ordinary ones.

        None is not "shut" - `is_tradable` and the calendar answer that.
        """
        try:
            from hokage.memory import trading_calendar

            return trading_calendar.session_window(self._now_ist().date(), segment)
        except Exception:
            return None

    #: Minutes before the exchange close that each league squares off. These
    #: are not new numbers - they are the gap already implied by the existing
    #: 15:20 (NSE, 15:30 close) and 23:15 (MCX, 23:30 close) constants, named
    #: here so a session with different hours can keep the same discipline.
    _SQUARE_OFF_BUFFER_MIN = {"NSE": 10, "MCX": 15}

    def _square_off_time(self, is_mcx: bool,
                         day: "dt_date | None" = None) -> tuple[int, int]:
        """When a day's positions must be flat, as (hour, minute) IST.

        `day` IS NOT OPTIONAL IN SPIRIT. Every caller that holds a session
        time must pass that time's date, because this function's first version
        read `self._now_ist()` while sitting inside `_adaptive_premium_target`,
        which is handed an injectable clock. On 2026-11-07 the two agreed and
        nothing showed; on 2026-11-08, a special session, the real date pulled
        the MCX square-off to 15:15 and silently rewrote the runway of a
        position filled two days earlier. A function given a clock that reads
        the wall clock instead is the defect this project keeps paying for.

        THE HAZARD THIS FIXES IS SPECIFIC. MCX squares off at 23:15 because
        MCX closes at 23:30. On Sunday 2026-11-08 MCX closes at 15:30, so a
        position opened that afternoon would have sat waiting for a 23:15
        square-off with no quotes to exit against from 15:30 onward - and
        then carried overnight into Monday, through a weekend gap, with no
        stop having ever run.

        NEVER LATER THAN THE ORDINARY TIME. The special session's own close
        can only bring this forward: equity F&O runs to 15:40 that day, and
        moving the 15:20 square-off out to 15:30 to match would be loosening
        a risk control on the strength of a calendar entry. `min` both fixes
        the MCX case and leaves the NSE constant exactly where it is.
        """
        segment = "MCX" if is_mcx else "NSE"
        ordinary = (23, 15) if is_mcx else (15, 20)

        if day is None:
            day = self._now_ist().date()

        try:
            from hokage.memory import trading_calendar

            window = trading_calendar.session_window(day, segment)
        except Exception:
            window = None       # an unreadable calendar changes nothing
        if window is None:
            return ordinary

        close = window[1]
        buffer_min = self._SQUARE_OFF_BUFFER_MIN[segment]
        flat_by = (datetime.combine(day, close)
                   - timedelta(minutes=buffer_min)).time()
        special = (flat_by.hour, flat_by.minute)
        return min(ordinary, special)

    #: Underlyings whose tape the archive is expected to hold. Deliberately
    #: the archiver's own list rather than a second copy: a symbol added
    #: there and not here would be silently exempt from this check.
    def _archive_assets(self) -> tuple[str, ...]:
        try:
            import sys
            from pathlib import Path as _P

            root = _P(__file__).resolve().parents[3]
            tools = str(root / "tools" / "research")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            from candle_archive import ASSETS

            return tuple(ASSETS)
        except Exception:
            return ()

    def _catch_up_candle_archive(self) -> None:
        """Once a day, repair any session the nightly sync could not write.

        RUNS ONLY WHEN THE ARCHIVE IS ACTUALLY BEHIND. A daily unconditional
        re-fetch of seven symbols over ninety days would hammer the broker for
        nothing on every day the 23:40 task worked.

        ON ITS OWN THREAD, ALWAYS. The fetch takes a minute or two and the
        trading loop must never wait for it; exits are managed from this loop
        and a blocked iteration is a position nobody is watching.

        Never raises. An archive top-up that fails is a measurement problem for
        later, not a reason to stop trading.
        """
        today = self._now_ist().strftime("%Y-%m-%d")
        if getattr(self, "_archive_catchup_date", None) == today:
            return
        if getattr(self, "_archive_catchup_running", False):
            return
        # getattr, because the flag is born on the first probe and this runs
        # straight after it. Absent is not False here either - but the safe
        # reading of "no probe yet" IS to wait, so the default is falsey.
        if not getattr(self, "_feed_probe_ok", False):
            return                  # no token, no point, and no false alarm

        missing = self._archive_sessions_missing()
        self._archive_catchup_date = today
        if not missing:
            return

        logger.warning(
            "Candle archive is missing %d session(s) (%s). Topping up on a "
            "background thread - the nightly sync could not reach the broker.",
            len(missing), ", ".join(sorted(missing)[:6]),
        )
        self._archive_catchup_running = True
        threading.Thread(
            target=self._run_candle_catchup, name="HokageCandleCatchup",
            daemon=True,
        ).start()

    def _archive_sessions_missing(self) -> set[str]:
        """Trading days in the recent past with no candles for some asset.

        Asks the calendar which days should have tape, so a holiday is never
        reported as a hole - that was the whole point of trading_calendar.

        THROUGH `market_was_open`, NOT `session_kind`. It answers True / False
        / None, and all three are needed here: None means the calendar cannot
        say, and a day it cannot speak to must be SKIPPED rather than counted
        as a missing session - otherwise the day this calendar's data runs out
        (2026-12-31) every morning starts a full re-fetch of everything.
        `segment_shut` collapses None and CLOSED into one answer, which is
        right for suppressing a message and wrong for this. It also already
        maps symbol to segment, so this no longer keeps its own copy of which
        underlyings are MCX.
        """
        import datetime as dt
        import sqlite3

        from hokage.memory.option_archive import market_was_open
        from hokage.memory.resolver import brain_root

        assets = self._archive_assets()
        if not assets:
            return set()

        path = brain_root() / "candles.db"
        if not path.exists():
            return set()

        today = self._now_ist().date()
        # Yesterday back two weeks. Not today: a session in progress has no
        # close yet, and Kite's bar for it is not one either.
        window = [today - dt.timedelta(days=n) for n in range(1, 15)]

        try:
            conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        except Exception:
            return set()
        try:
            have: dict[str, set[str]] = {}
            for symbol in assets:
                rows = conn.execute(
                    "SELECT DISTINCT substr(ts,1,10) FROM candles WHERE symbol=?",
                    (symbol,)).fetchall()
                have[symbol] = {r[0] for r in rows}
        except Exception:
            return set()
        finally:
            conn.close()

        missing: set[str] = set()
        for day in window:
            for symbol in assets:
                if market_was_open(symbol, day) is not True:
                    continue        # shut, or the calendar cannot say
                if day.isoformat() not in have.get(symbol, set()):
                    missing.add(day.isoformat())
        return missing

    def _run_candle_catchup(self) -> None:
        """The fetch itself, off the trading thread."""
        try:
            import sys
            from pathlib import Path as _P

            root = _P(__file__).resolve().parents[3]
            tools = str(root / "tools" / "research")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            import candle_archive

            added = 0
            for symbol in self._archive_assets():
                try:
                    added += candle_archive.sync(symbol, verbose=False)
                except Exception as exc:
                    logger.warning("Candle catch-up failed for %s: %s", symbol, exc)
            logger.info("Candle archive catch-up added %d bar(s).", added)
        except Exception as exc:
            logger.error("Candle archive catch-up aborted: %s", exc)
        finally:
            self._archive_catchup_running = False

    def _describe_today(self) -> str:
        """The calendar's one-line reason, for the log that says why it stayed
        quiet. A suppression with no stated reason is indistinguishable from a
        sender that crashed."""
        try:
            from hokage.memory import trading_calendar

            return trading_calendar.describe(self._now_ist().date())
        except Exception as exc:
            return f"calendar unreadable ({exc})"

    def _check_data_feed_session(self) -> None:
        """Probe the Kite market-data feed and alert once per IST date if blind.

        Runs in EVERY execution mode. Paper trading is real data with fake money,
        so a dead feed is a dead system regardless of where the orders go. Alert
        only — no halt: the entry path already fails closed without prices, and a
        sticky halt would make the commander send /resume after re-login for no
        added safety.
        """
        try:
            self.orchestrator.price_source.get_price("NIFTY 50")
            self._consecutive_network_failures = 0
            self._record_feed_probe(True, "")
        except Exception as exc:
            reason = str(exc)
            self._record_feed_probe(False, reason)
            today = self._now_ist().strftime("%Y-%m-%d")
            kind = self._diagnose_feed_failure(reason)

            # A NETWORK failure that will not clear is a poisoned connection
            # pool, and only rebuilding the client fixes it.
            #
            # 2026-09-02: a ~90-second DNS blip at 08:58 healed on its own. A
            # second one at 13:53 did NOT — Hokage logged "feed is DOWN
            # (network)" every minute for 47 minutes while DNS resolved
            # perfectly from a fresh process beside him, made zero trades, and
            # only recovered when restarted by hand. His last successful scan
            # was 13:45.
            #
            # The self-heal existed and was unreachable: `_try_broker_reconnect`
            # fired only when `kind == "unknown"`, which is the mid-session
            # login signature. A network diagnosis skipped it entirely, so he
            # retried a dead pool forever.
            #
            # NOT on the first failure. A genuine internet outage needs no
            # rebuild and churning the client through one would be noise; the
            # 08:58 blip healed by itself well inside this threshold. After
            # several consecutive failures the internet is not the explanation
            # any more — his own client is.
            if kind == "network":
                self._consecutive_network_failures = (
                    getattr(self, "_consecutive_network_failures", 0) + 1
                )
                if (self._consecutive_network_failures >= self._NETWORK_REBUILD_AFTER
                        and self._try_broker_reconnect()):
                    logger.info(
                        "Market data feed recovered by rebuilding the broker client "
                        "after %d consecutive network failures.",
                        self._consecutive_network_failures,
                    )
                    self._consecutive_network_failures = 0
                    self._last_feed_alert_date = None
                    if self.telegram_bot and getattr(self, "_feed_outage_announced", False):
                        self.telegram_bot.send_message(
                            "✅ *HOKAGE CAN SEE AGAIN*\n"
                            "The connection was stuck, not the internet. The broker "
                            "client was rebuilt and the feed is live. Scanning has "
                            "resumed — no restart needed."
                        )
                    self._feed_outage_announced = False
                    return
            else:
                self._consecutive_network_failures = 0

            # "unknown" means the standalone probe authenticated fine with the
            # CURRENT stored token while the feed still refused — which is the
            # exact signature of a connection manager holding a client built
            # from a token that has since been replaced. That is what a
            # mid-session login produces, and it used to require a restart the
            # commander had no way of knowing he needed. Re-read and retry
            # before saying a word: a feed that heals itself needs no alarm.
            if kind == "unknown" and self._try_broker_reconnect():
                logger.info("Market data feed recovered by re-authenticating the broker session.")
                self._last_feed_alert_date = None
                if self.telegram_bot and getattr(self, "_feed_outage_announced", False):
                    self.telegram_bot.send_message(
                        "✅ *HOKAGE CAN SEE AGAIN*\n"
                        "The broker session was refreshed and the market data feed is live. "
                        "Scanning has resumed — no restart needed."
                    )
                self._feed_outage_announced = False
                return

            # THE MARKET HAS TO BE OPEN FOR "BLIND" TO MEAN ANYTHING. The
            # probe and its record above are untouched - the feed IS down and
            # that stays a recorded fact - but a dead token on a Saturday is
            # not news, and an alarm that fires on days nothing trades is how
            # the one that matters gets ignored. Said once per day at INFO so
            # the log still shows why it kept quiet.
            if self._nothing_trades_today():
                if getattr(self, "_last_feed_quiet_date", None) != today:
                    from hokage.memory import trading_calendar

                    logger.info(
                        "Market data feed is down (%s) and staying quiet: %s",
                        kind, trading_calendar.describe(self._now_ist().date()),
                    )
                    self._last_feed_quiet_date = today
                return

            if getattr(self, "_last_feed_alert_date", None) == today:
                return
            logger.critical(f"Market data feed is DOWN ({kind}): {reason}")
            if self.telegram_bot:
                # Kite's own auth error is "Incorrect `api_key` or
                # `access_token`." — backticks and underscores that would make
                # Telegram reject this whole alert. It only survived on
                # 2026-07-30 because the wrapped message happened to be clean.
                reason = self.telegram_bot.escape_markdown(reason)
                if kind == "auth":
                    body = (
                        "🚨 *HOKAGE IS BLIND — ZERODHA LOGIN NEEDED* 🚨\n"
                        f"The market data feed rejected authentication: {reason}\n"
                        "No scans, no entries, no new trades until you log in again.\n"
                        "Open the dashboard and log in to Kite, or send `/token URL`."
                    )
                elif kind == "network":
                    body = (
                        "⚠️ *HOKAGE IS BLIND — MARKET DATA UNREACHABLE* ⚠️\n"
                        f"The Kite feed could not be reached: {reason}\n"
                        "No scans or entries until it comes back. Check the network."
                    )
                else:
                    body = (
                        "⚠️ *HOKAGE IS BLIND — MARKET DATA FAILING* ⚠️\n"
                        f"The feed stopped answering: {reason}\n"
                        "Your Zerodha login is still valid, so this is not a token problem.\n"
                        "No scans or entries until it recovers."
                    )
                # Only burn the day's alert once it has actually landed — the
                # same mark-before-send trap that swallowed the login prompt.
                if self.telegram_bot.send_message(body):
                    self._last_feed_alert_date = today
                    # Remember we told him it broke, so recovery is worth
                    # announcing. Without this the "can see again" message
                    # would fire after outages he was never told about.
                    self._feed_outage_announced = True
            else:
                self._last_feed_alert_date = today
            return
        # Feed answered: clear the latch so a later outage alerts again today.
        self._last_feed_alert_date = None
        self._feed_outage_announced = False
        # A heartbeat that can ONLY be published by a quote that actually came
        # back. The watchdog treats this as evidence the system can see; unlike
        # the timer-stamped engine heartbeats, it cannot report health while
        # blind. This is the signal that was missing for the seven silent days.
        try:
            self.orchestrator.publish_heartbeat("market_data", "HEALTHY")
        except Exception as exc:
            logger.debug(f"Could not publish market_data heartbeat: {exc}")

    def _check_broker_session_health(self) -> None:
        """Detect mid-session broker auth failure (e.g. Kite daily token expiry).

        Probes every live (non-paper) venue; on an auth-shaped failure, halts
        new entries and alerts the commander via Telegram once per IST date.
        Exits remain active. Paper/mock venues carry no ORDER token risk and are
        skipped for the venue probe.

        The DATA FEED is probed in every mode, paper included. Paper money still
        trades on real Kite data, so an expired token blinds the whole system.
        The entry path fails closed on missing prices, which is safe but utterly
        silent: on 2026-07-27 Hokage sat on a 7-day-expired token, refused every
        scan, and said nothing. `_check_data_feed_session` breaks that silence
        and runs at the top of every loop iteration, not from here.
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
                if any(tag in msg for tag in self._AUTH_ERROR_TAGS):
                    today = self._now_ist().strftime("%Y-%m-%d")
                    if getattr(self, "_last_token_alert_date", None) != today:
                        self._last_token_alert_date = today
                        self.intraday_override["halted"] = True
                        logger.critical(f"Broker session failure on venue {venue_id}: {exc}. Entries halted.")
                        if self.telegram_bot:
                            self.telegram_bot.send_message(
                                "🚨 *BROKER SESSION EXPIRED* 🚨\n"
                                f"Venue `{venue_id}` rejected authentication: "
                                f"{self.telegram_bot.escape_markdown(exc)}\n"
                                "Entries are HALTED. Re-login via the dashboard or /token, then send /resume."
                            )

    def handle_remote_command(self, command: str) -> str:
        """Execute a commander control command arriving via the Telegram uplink.

        Supported: /kill (halt + liquidate), /pause (halt entries), /resume,
        /close_all (liquidate, no halt), /status. Returns an acknowledgement
        string that the uplink sends back to the commander.
        """
        raw = command.strip()
        parts = raw.split()
        cmd = parts[0].strip().lower().lstrip("/") if parts else ""
        arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""

        # Instant exit of ONE named position (hard sell): "/exit NIFTY",
        # "/sell NIFTY", "/close NIFTY". Executes immediately, full bookkeeping.
        if cmd in ("exit", "sell", "close", "squareoff", "square_off"):
            if not arg:
                if not self._active_positions_tracking:
                    return "No open positions to close."
                open_list = ", ".join(self._active_positions_tracking.keys())
                return f"Which one? Say e.g. /exit NIFTY. Currently open: {open_list}."
            res = self.request_force_exit(arg)
            return ("✅ " if res.get("success") else "⚠️ ") + res.get("message", "Done.")

        # Instant entry of a named underlying (paper): "/buy NIFTY",
        # "/buy BANKNIFTY put", "/enter SENSEX call".
        if cmd in ("buy", "enter", "long", "short"):
            direction = "long"
            arg_l = (cmd + " " + arg).lower()
            if cmd == "short" or any(w in arg_l for w in ("put", " pe", "short", "bear")):
                direction = "short"
            underlying = arg
            for w in ("call", "put", "ce", "pe", "long", "short", "bull", "bear", "option", "options"):
                underlying = __import__("re").sub(rf"\b{w}\b", "", underlying, flags=__import__("re").IGNORECASE)
            underlying = underlying.strip().upper()
            if not underlying:
                return "Which index? Say e.g. /buy NIFTY call (or put). Tradable: NIFTY, BANKNIFTY, SENSEX."
            res = self.request_force_entry(underlying, direction)
            return ("✅ " if res.get("success") else "⚠️ ") + res.get("message", "Done.")

        if cmd in ("report", "summary", "eod", "daily"):
            try:
                return self.build_eod_plain_report()
            except Exception as e:
                return f"Couldn't build the report right now: {e}"

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
            # Telegram sends with parse_mode=Markdown: a raw underscore in a
            # dynamic value (e.g. gatekeeper_state="Await_Elder_Command")
            # opens an italics span and eats the rest of the line.
            gatekeeper_str = str(self.gatekeeper_state).replace("_", "\\_")
            header = (
                f"📡 *STATUS*: halted={self.intraday_override.get('halted', False)}, "
                f"gatekeeper={gatekeeper_str}, "
                f"tracked_positions={len(self._active_positions_tracking)}, "
                f"loop_active={self.is_active()}"
            )
            if not self._active_positions_tracking:
                return header
            lines = [header, "", "*Open Positions:*"]
            for sym, pos in self._active_positions_tracking.items():
                entry = float(pos.get("entry_price", 0.0))
                qty = float(pos.get("quantity", 0.0))
                # The level that can actually fire, not the seeded stop_price.
                # Printing the latter told the commander he had a 5% stop when
                # his real exposure was the 12% backstop — on GOLDM that was
                # the difference between Rs 1,910 and Rs 6,325.
                stop, stop_rung = self._effective_premium_floor(
                    entry, float(pos.get("peak_price") or entry), pos)
                stop = stop or None
                target = pos.get("target_price")
                try:
                    ltp = self.orchestrator.price_source.get_price(sym)
                except Exception:
                    ltp = None
                side = pos.get("side", "BUY")
                direction_sign = 1.0 if side == "BUY" else -1.0
                pnl_str = "N/A"
                ltp_str = "N/A"
                if isinstance(ltp, (int, float)):
                    ltp_str = f"{ltp:.2f}"
                    pnl = (ltp - entry) * qty * direction_sign
                    pnl_str = f"₹{pnl:+.2f}"
                stop_str = (f"{stop:.2f} ({stop_rung})"
                            if isinstance(stop, (int, float)) else "N/A")
                target_str = f"{target:.2f}" if isinstance(target, (int, float)) else "N/A"
                lines.append(
                    f"• *{sym}* {side} qty={qty:g} | entry={entry:.2f} LTP={ltp_str} "
                    f"| PnL={pnl_str} | stop={stop_str} target={target_str}"
                )
            return "\n".join(lines)
        return f"Unknown control command: /{cmd}"

    def request_force_exit(self, identifier: str) -> dict[str, Any]:
        """Close open position(s) matching ``identifier`` immediately (hard sell).

        ``identifier`` may be the option contract symbol OR its underlying —
        the commander types "NIFTY"; the tracked symbol is NIFTY2672124150CE.
        Runs one synchronous monitor pass so the exit fills right away with the
        SAME bookkeeping as a laddered exit (journal outcome, strategy stats,
        re-entry cooldown, tracking removal, Telegram notify). Returns a result
        dict the dashboard button and the Telegram command both render.
        """
        ident = (identifier or "").strip().upper()
        if not ident:
            return {"success": False, "message": "Tell me which position to close (e.g. NIFTY)."}

        tracked = dict(self._active_positions_tracking)
        if not tracked:
            return {"success": False, "message": "There are no open positions to close right now."}

        matches = []
        for sym, pos in tracked.items():
            underlying = str(pos.get("underlying") or "").upper()
            if ident == sym.upper() or (underlying and ident == underlying) or ident in sym.upper():
                matches.append(sym)
        if not matches:
            open_list = ", ".join(tracked.keys())
            return {"success": False, "message": f"No open position matches '{identifier}'. Currently open: {open_list}."}

        added: set[str] = set()
        for sym in matches:
            added.add(sym.upper())
            u = str(tracked[sym].get("underlying") or "").upper()
            if u:
                added.add(u)
        self._forced_exits |= added
        try:
            self._monitor_and_exit_positions(is_tick=True)
        except Exception as exc:
            logger.error(f"Force-exit monitor pass failed: {exc}")
        finally:
            self._forced_exits -= added

        closed = [s for s in matches if s not in self._active_positions_tracking]
        still_open = [s for s in matches if s in self._active_positions_tracking]
        if closed:
            logger.warning("Commander instant-exit closed: %s", ", ".join(closed))
            return {
                "success": True,
                "closed": closed,
                "still_open": still_open,
                "message": f"Closed immediately: {', '.join(closed)}.",
            }
        return {
            "success": False,
            "closed": [],
            "still_open": still_open,
            "message": (
                f"Sent the exit order for {', '.join(still_open)} but it hasn't confirmed closed yet "
                f"(likely a momentary data gap) — it will square off on the next check."
            ),
        }

    def request_force_entry(self, underlying: str, direction: str = "long") -> dict[str, Any]:
        """Manually open a paper option position (hard buy) on ``underlying``.

        Commander-commanded entries (dashboard / Telegram) skip the league vote
        and the daily-bar gates — the commander decides — but they STILL go
        through the real option router (nearest-expiry ATM CE for long / PE for
        short, real live premium, cash-capped size) and land on the PAPER venue
        ONLY. A chat/Telegram command must never touch live capital. The new
        position is tracked so the normal exit ladder and instant-exit manage it.
        """
        from bots.execution.options_router import OptionsRouter, OptionsRoutingError
        from integrations.brokers.models import OrderRequest, OrderSide, OrderType
        from integrations.data.models import Instrument

        underlying = (underlying or "").strip().upper()
        direction = "short" if str(direction).lower().startswith("s") else "long"

        if not OptionsRouter.routes(underlying):
            return {"success": False, "message": f"I only trade options on NIFTY, BANKNIFTY, SENSEX, CRUDEOIL, NATURALGAS, GOLDM, and SILVERM — '{underlying}' isn't one of those."}

        for sym, pos in self._active_positions_tracking.items():
            if str(pos.get("underlying") or "").upper() == underlying:
                return {"success": False, "message": f"There's already an open {underlying} position ({sym}). Close it first with /exit {underlying}."}

        entry_price, reason = self._get_validated_live_price(underlying)
        if entry_price is None:
            return {"success": False, "message": f"Couldn't get a fresh live price for {underlying} right now ({reason}). Try again in a moment."}

        # PAPER VENUE ONLY — hard safety seam for a commander-typed trade.
        # Routed to the underlying's OWN league: a commodity buy must land on
        # the MCX Arena's ledger, never the index Dojo's (the two accounts
        # exist specifically so their capital can never mix).
        from bots.strategy.mcx_portfolio import MCX_UNIVERSE
        if underlying in MCX_UNIVERSE:
            venue = getattr(self.orchestrator, "mcx_venue", None)
            manual_strategy_id = "COMMANDER_MANUAL_MCX"
        else:
            venue = self.orchestrator.paper_venue
            manual_strategy_id = "COMMANDER_MANUAL"
        if venue is None:
            return {"success": False, "message": f"No trading venue is available for {underlying} right now."}
        side = OrderSide.BUY if direction == "long" else OrderSide.SELL
        resolved_ac = self.orchestrator.session_manager.resolve_asset_class(underlying)
        resolved_exch = self.orchestrator.session_manager.resolve_exchange(underlying)
        inst = Instrument(symbol=underlying, asset_class=resolved_ac, exchange=resolved_exch)
        req = OrderRequest(
            instrument=inst, side=side, quantity=1.0, order_type=OrderType.MARKET,
            venue_id=venue.venue_id, strategy_id=manual_strategy_id,
            execution_reason="Commander manual entry (hard buy)",
        )

        try:
            cash = float(venue.get_account_balance().cash)
        except Exception:
            cash = None
        try:
            opt_router = OptionsRouter(price_source=self.orchestrator.price_source)
            req = opt_router.route_to_options(req, current_price=entry_price, available_cash=cash, risk_budget=cash)
        except OptionsRoutingError as e:
            return {"success": False, "message": f"Couldn't set up the {underlying} option trade: {e}"}

        try:
            resp = venue.place_order(req)
        except Exception as e:
            return {"success": False, "message": f"The order failed: {e}"}
        if resp is None or str(getattr(resp, "status", "")).upper() in ("REJECTED", "CANCELLED", "ERROR", "FAILED"):
            return {"success": False, "message": f"The order was rejected: {getattr(resp, 'error_message', 'unknown reason')}."}

        qty_filled = getattr(resp, "filled_quantity", req.quantity) or req.quantity
        req_meta = req.instrument.metadata or {}
        tracked_symbol = req.instrument.symbol
        tracked_entry_price = float(req_meta.get("premium_at_entry", entry_price)) if req_meta.get("is_option") else float(entry_price)
        entry_und_atr = self._get_atr_for_symbol(underlying)
        _target, _target_adaptive = self._seed_target_price(
            tracked_entry_price, underlying, float(entry_price),
            entry_und_atr, manual_strategy_id,
        )
        self._active_positions_tracking[tracked_symbol] = {
            "entry_price": tracked_entry_price,
            "peak_price": tracked_entry_price,
            "stop_price": tracked_entry_price * (1.0 - self.tsl_percent),
            # The risk actually accepted, frozen. "stop_price"
            # above is a LIVE floor the ladder ratchets to
            # break-even and beyond; reading it after the fact
            # measures nothing. See _compute_rr_achieved.
            "initial_stop_price": tracked_entry_price * (1.0 - self.tsl_percent),
            "target_price": _target,
            # False means the TARGET_HIT rung cannot fire for this position,
            # so the alert must not call the stored figure a target. See
            # _seed_target_price.
            "target_is_adaptive": _target_adaptive,
            "decision_id": f"manual-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "strategy_id": manual_strategy_id,
            # What the sizing grade is measured against. See
            # _chest_fraction_pct: this path never recorded a size at all, so
            # the review fabricated one and graded every manual trade CORRECT.
            "chest_fraction_pct": self._chest_fraction_pct(
                manual_strategy_id, tracked_entry_price, qty_filled
            ),
            # What the stop grade is measured against: the fraction of premium
            # whichever stop bites FIRST actually puts at risk. Frozen here
            # because the ATR it is computed from is an entry-time fact.
            "risk_pct_at_entry": self._risk_pct_for(
                tracked_entry_price, float(entry_price), entry_und_atr,
                manual_strategy_id, underlying,
            ),
            "side": side.value,
            "quantity": float(qty_filled),
            "venue_id": venue.venue_id,
            "underlying": underlying,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_underlying_price": float(entry_price),
            "entry_underlying_atr": float(entry_und_atr) if entry_und_atr else None,
            "lot_size": req_meta.get("lot_size"),
            "option_type": req_meta.get("option_type"),
            "strike": req_meta.get("strike"),
            "expiry": req_meta.get("expiry"),
        }
        self._save_positions_tracking()
        if self.telegram_bot and self.telegram_bot.enabled:
            try:
                self.telegram_bot.notify_entry(
                    symbol=tracked_symbol, cmp=tracked_entry_price,
                    target=self._active_positions_tracking[tracked_symbol]["target_price"],
                    target_adaptive=_target_adaptive, edge=100.0,
                    strategy=self._strategy_display_name(
                        self._active_positions_tracking[tracked_symbol].get("strategy_id")),
                )
            except Exception:
                pass
        kind = "call" if str(req_meta.get("option_type", "")).upper().startswith("C") else "put"
        return {
            "success": True,
            "symbol": tracked_symbol,
            "message": (
                f"Done — bought a {underlying} {kind} option ({tracked_symbol}) at ₹{tracked_entry_price:.2f} "
                f"for {int(qty_filled)} qty on paper. I'll manage the exit, or say /exit {underlying} to close it yourself."
            ),
        }

    def build_eod_plain_report(self, account_id: str = "paper", venue_id: str | None = None, title: str | None = None) -> str:
        """A plain-English recap of today's trades a non-trader can follow.

        Numbers come straight from the paper account (never guessed); exit
        reasons come from today's exit log. Reused by the dashboard, the
        /report Telegram command, the automatic end-of-day send, and (with
        account_id="paper_mcx", venue_id="paper_mcx") the MCX Arena's own
        23:35 evening report.
        """
        from bots.autonomous.plain_report import build_plain_report
        from integrations.brokers.session_manager import KolkataTime

        now_ist = datetime.now(timezone.utc).astimezone(KolkataTime())
        date_label = title or now_ist.strftime("%A, %d %b %Y")
        today = now_ist.strftime("%Y-%m-%d")

        reason_by_symbol: dict[str, Any] = {}
        for ex in getattr(self, "_exits_executed_today", []):
            reason_by_symbol[str(ex.get("symbol", "")).upper()] = ex.get("reason")

        closed: list[dict[str, Any]] = []
        try:
            account = self.orchestrator.portfolio_store.load_account(account_id)
            for pos in account.positions.values():
                if getattr(pos.status, "value", str(pos.status)) != "CLOSED":
                    continue
                if str(getattr(pos, "failure_reason", "") or "").startswith("PHANTOM"):
                    continue
                closed_at = getattr(pos, "closed_at", None)
                if closed_at is None:
                    continue
                try:
                    ist = closed_at.astimezone(KolkataTime())
                except Exception:
                    continue
                if ist.strftime("%Y-%m-%d") != today:
                    continue
                closed.append({
                    "symbol": pos.market,
                    "entry_price": pos.entry_price,
                    "exit_price": pos.current_price,
                    "quantity": pos.quantity,
                    "pnl": pos.realized_pnl,
                    "exit_reason": reason_by_symbol.get(str(pos.market).upper()) or getattr(pos, "failure_reason", None),
                    "closed_at_label": ist.strftime("%I:%M %p"),
                })
        except Exception as exc:
            logger.error(f"EOD report: failed to read closed trades ({account_id}): {exc}")

        open_trades: list[dict[str, Any]] = []
        for sym, pos in dict(self._active_positions_tracking).items():
            if venue_id is not None and pos.get("venue_id") != venue_id:
                continue
            entry = float(pos.get("entry_price", 0.0))
            ltp = None
            try:
                ltp, _ = self._get_validated_live_price(sym)
            except Exception:
                ltp = None
            unreal = None
            if isinstance(ltp, (int, float)):
                sign = 1.0 if pos.get("side", "BUY") == "BUY" else -1.0
                unreal = round((ltp - entry) * float(pos.get("quantity", 0.0)) * sign, 2)
            open_trades.append({
                "symbol": sym,
                "entry_price": entry,
                "current_price": ltp,
                "quantity": float(pos.get("quantity", 0.0)),
                "unrealized_pnl": unreal,
            })

        return build_plain_report(closed, open_trades, date_label)

    def _close_all_positions(self, reason: str) -> int:
        """Liquidate every tracked open position WITH full exit bookkeeping.

        Used by the kill switch and /close_all. Routes through the monitor's
        forced-exit path so each close records its journal outcome, strategy
        chest debit, and cooldown — the old direct-order version skipped all
        bookkeeping, which is how a kill-switch exit (PE -188.50 on
        2026-07-16) vanished from the strategy ledger while the account book
        took the loss.
        """
        symbols = list(self._active_positions_tracking.keys())
        if not symbols:
            return 0
        added: set[str] = set()
        for sym in symbols:
            added.add(sym.upper())
            u = str(self._active_positions_tracking[sym].get("underlying") or "").upper()
            if u:
                added.add(u)
        self._forced_exits |= added
        self._forced_exit_label = reason
        try:
            self._monitor_and_exit_positions(is_tick=True)
        except Exception as e:
            logger.error(f"Close-all monitor pass failed during {reason}: {e}")
        finally:
            self._forced_exits -= added
            self._forced_exit_label = None
        return len([s for s in symbols if s not in self._active_positions_tracking])

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
            execution_reason=reason,
            # This is the kill-switch / close-all seam. An exit must NEVER be
            # able to OPEN exposure: on 2026-07-15 a non-reduce-only exit storm
            # against an already-flat book minted 207 phantom positions. The
            # monitor's exit path carries this flag; this path had escaped.
            reduce_only=True,
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

        # 0. Commander instant-exit (hard sell). Outranks every ladder rung:
        # when the commander says close it, it closes now — matched by the
        # option contract symbol OR its underlying (they typed "NIFTY", the
        # tracked symbol is NIFTY2672124150CE).
        forced = getattr(self, "_forced_exits", set())
        if forced:
            underlying = str((tracking or {}).get("underlying") or "").upper()
            if symbol.upper() in forced or (underlying and underlying in forced):
                label = getattr(self, "_forced_exit_label", None) or "Commander instant-exit (hard sell)"
                return True, label, tracking

        # 1. Manual Kill Switch
        if getattr(self, "intraday_override", {}).get(symbol) == "KILL":
            return True, "Manual Kill Switch Activated", tracking

        symbol_upper = symbol.upper()
        is_option = symbol_upper.endswith("CE") or symbol_upper.endswith("PE")
        is_mcx_instrument = self._is_mcx_symbol(symbol_upper, venue)

        # 2. Time-Based Square-Off (loss protection outranks profit-taking;
        # MCX instruments are recognized by symbol so paper-venue commodity
        # options still square off at the 23:15 MCX close, not 15:20).
        is_crypto = venue and ("crypto" in venue.venue_id.lower() or "binance" in venue.venue_id.lower())
        if not is_crypto:
            sq_hour, sq_min = self._square_off_time(
                is_mcx_instrument, now_ist.date())
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
            tracking.setdefault("initial_stop_price", tracking["stop_price"])

        # Track peak price. "Peak" is directional (best price FOR the position),
        # "trough" is the worst — together they form the excursion envelope that
        # post-trade attribution needs to separate entry quality (how far price
        # ran our way) from exit quality (how much of that we captured).
        if side == OrderSide.BUY or side.value == "BUY":
            tracking["peak_price"] = max(tracking.get("peak_price", average_price), current_price)
            tracking["trough_price"] = min(tracking.get("trough_price", average_price), current_price)
        else:
            tracking["peak_price"] = min(tracking.get("peak_price", average_price), current_price)
            tracking["trough_price"] = max(tracking.get("trough_price", average_price), current_price)

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
    #: Tightened one notch 2026-07-17 (commander-approved) after the SENSEX CE
    #: rode its -25% tier and gap-filled at -28.4%: a backstop on a falling
    #: premium always slips a little past the line, so the line itself must
    #: sit tighter. Was (0.15, 0.25, 0.35, 0.50).
    _OPTION_BACKSTOP_TIERS = ((500.0, 0.12), (200.0, 0.20), (100.0, 0.28), (0.0, 0.40))
    #: Underlying thesis stop: adverse move >= this multiple of entry-time ATR
    #: on the UNDERLYING invalidates the directional premise. This is the
    #: DEFAULT; per-strategy overrides live in the table below.
    _OPTION_THESIS_ATR_MULT = 1.25

    #: Per-strategy thesis-stop distance, in ATR of the underlying.
    #:
    #: COMMANDER-APPROVED 2026-08-13, on the stop_lab measurements below. Only
    #: the two modules the tight stop was measurably HURTING are listed;
    #: RangeFade and MacroBreakout are deliberately absent because 1.25 tested
    #: optimal for them, and an entry here would make them worse.
    #:
    #: WHY IT MUST BE PER-STRATEGY (measured 2026-08-13,
    #: tools/research/stop_lab.py, 60-minute horizon, real candles). One stop
    #: distance is right for some modules and destroys others, and the split
    #: does NOT follow any tidy philosophical line — two mean-reversion modules
    #: land on opposite sides of it, which is precisely why it has to be
    #: measured per module rather than reasoned about:
    #:
    #:   module / asset            no stop        1.25 (live)      best in sweep
    #:   RangeFade NATURALGAS   +0.415 t=2.43   +0.455 t=2.95   1.25  <- optimal
    #:   MacroBreakout BANKNIFTY+0.309 t=1.42   +0.389 t=2.02   1.25  <- optimal
    #:   MacroBreakout SENSEX   +0.552 t=2.32   +0.512 t=2.15   2.00
    #:   MeanReversion BANKNIFTY+0.235 t=2.16   +0.196 t=1.77   none/2.50
    #:   MeanReversion SENSEX   +0.192 t=1.86   +0.095 t=0.83   none/2.00
    #:   SessionShift SILVERM   +0.233 t=2.46   +0.176 t=2.08   3.00 (+0.212)
    #:   SessionShift GOLDM     +0.327 t=3.13   +0.142 t=1.53   3.00 (+0.238)
    #:
    #: SessionShift on GOLDM is the extreme case: the live stop fires on 46% of
    #: its signals and removes 57% of its measured edge, dropping t from +3.13
    #: to +1.53 — below the t>=2 bar the module was selected on.
    #:
    #: TWO WARNINGS FOR WHOEVER FILLS THIS IN:
    #: 1. The lab measures the UNDERLYING, because that is what the thesis stop
    #:    watches. Option P&L also pays theta and spread on every bar held, and
    #:    a wider stop means holding losers longer. A wider stop measuring
    #:    better here is permission to TEST in paper, never proof.
    #: 2. At 2.5-3.0 ATR the stop fires on under 10% of trades, so it stops
    #:    being the real protection and TIERED_PREMIUM_BACKSTOP becomes the
    #:    floor that matters. Widening this is therefore a bigger change than
    #:    it looks: it moves which rung actually protects the account. That
    #:    handover is deliberate and accepted, not overlooked — the premium
    #:    backstop is a HARD cap on rupees lost, which the thesis stop never
    #:    was, so the account's worst case per trade does not widen with these
    #:    numbers even though the underlying leash does.
    #:
    #: FIRST THING TO CHECK IF RESULTS GET WORSE: these numbers say the wider
    #: stop is better ON THE UNDERLYING. If live paper shows SessionShift
    #: losing MORE per trade while its direction accuracy holds up, the cause
    #: is theta on the longer holds, not the direction call — and the answer is
    #: to shorten the horizon, not to re-tighten the stop blindly.
    #: Applies to every asset the strategy trades.
    #:
    #: MeanReversion at 2.5 measured better on all three indices under the FULL
    #: geometry (stop + the 1.5x target it implies, 120min):
    #:   NIFTY     +0.183 -> +0.216      BANKNIFTY +0.247 -> +0.296
    #:   SENSEX    +0.123 -> +0.257
    #: NIFTY alone peaks at 2.0 (+0.224) but the gap to 2.5 is 0.008 ATR, far
    #: inside the noise of n=39; one value for the module is the honest read.
    _THESIS_ATR_MULT_BY_STRATEGY: dict[str, float] = {
        "strat-meanreversion-sideways-v1": 2.5,
        # NOT LISTED, ON PURPOSE — 1.25 measured OPTIMAL for these two, so an
        # entry here would make them worse:
        #   strat-rangefade-mcx-v1             +0.227 at 1.25 vs +0.163 at 2.0
        #   strat-macrobreakout-commodities-v1 +0.389 t=+2.02 at 1.25
    }

    #: Per (strategy, ASSET), and it beats the table above.
    #:
    #: WHY THIS SECOND TABLE EXISTS. stop_lab measured the stop with a TIME
    #: exit and reported SessionShift better at 3.0 on BOTH its assets. But
    #: production also floors the target at 1.5x the risk the stop creates
    #: (see _risk_pct_for), so widening the stop widens the target with it.
    #: Measured TOGETHER, the two assets separate completely:
    #:
    #:   SessionShift GOLDM    1.25 +0.069 -> 3.0 +0.355   apply
    #:   SessionShift SILVERM  1.25 +0.007 -> 3.0 -0.061   DO NOT
    #:
    #: Silver is negative at 2.0, 2.5 AND 3.0. Applying one value per strategy
    #: would have shipped a measured-negative stop onto SILVERM on the strength
    #: of gold's numbers — the same "edge does not travel between assets"
    #: failure that per-symbol scoping was built to stop, in a new place.
    #:
    #: LEAD WORTH CHASING: SessionShift on SILVERM is +0.007 under full
    #: geometry — indistinguishable from zero at ANY stop width, while GOLDM is
    #: strongly positive. Its place in the lineup deserves review; that is a
    #: scoping decision for the commander, not a constant to tune.
    _THESIS_ATR_MULT_BY_STRATEGY_ASSET: dict[tuple[str, str], float] = {
        ("strat-sessionshift-mcx-v1", "GOLDM"): 3.0,
        # ("strat-sessionshift-mcx-v1", "SILVERM") deliberately absent -> 1.25
    }

    def _thesis_atr_mult_for(
        self, strategy_id: str | None, symbol: str | None = None
    ) -> float:
        """Thesis-stop distance for this strategy on this asset, in ATR.

        Resolution order: (strategy, asset) -> strategy -> shared default.
        Falls back at every step, so a strategy can never lose its stop by
        being absent from a table. Fails SAFE, unlike `supported_assets`
        which fails OPEN — an unknown scope must not mute a strategy, but an
        unknown stop distance must never leave a position unprotected.
        """
        if not strategy_id:
            return self._OPTION_THESIS_ATR_MULT
        if symbol:
            scoped = self._THESIS_ATR_MULT_BY_STRATEGY_ASSET.get(
                (strategy_id, symbol.upper())
            )
            if scoped is not None:
                return scoped
        return self._THESIS_ATR_MULT_BY_STRATEGY.get(
            strategy_id, self._OPTION_THESIS_ATR_MULT
        )
    #: TRAIL_LOCK arms once open profit reaches this FRACTION OF THE POSITION's
    #: premium notional, then never gives back more than the same fraction from
    #: peak. Commander-approved 2026-08-06, replacing a flat Rs 1,000.
    #:
    #: The flat figure was the same class of bug as the flat 6% target fixed the
    #: day before: one number applied to positions spanning a 4x size range, so
    #: it meant completely different things depending on what was being traded.
    #: Measured on 2026-08-06's actual fills, Rs 1,000 of giveback was:
    #:     SILVERM  Rs 37,168 position -> 2.69%      <- 4x tighter...
    #:     CRUDEOIL Rs 31,490 position -> 3.18%
    #:     GOLDM    Rs 26,200 position -> 3.82%
    #:     NATGAS   Rs 14,250 position -> 7.02%
    #:     NIFTY    Rs  8,616 position -> 11.61%     <- ...than here
    #:
    #: That day ALL THREE winners exited on TRAIL_LOCK and all four losers on
    #: the thesis stop — the trail was the binding constraint on every winner.
    #: SILVERM ran 6,900 -> 7,650 (+10.9%) and was banked at 7,433 (+7.7%)
    #: because a 2.69% wobble tripped it.
    #:
    #: Measured off the PEAK, not entry. Off entry the giveback stays constant
    #: in rupees, so it grows proportionally tighter the further a winner runs —
    #: which cuts exactly the trades worth holding. Off peak it widens with the
    #: position, which is what a trailing stop is for.
    #:
    #: It arms only once `peak * (1 - fraction)` clears entry, so an armed trail
    #: can never put the floor below entry: a winner cannot become a loser
    #: through this rung. Below that the trail stays out of the way entirely and
    #: the tiered backstop is the only floor.
    #:
    #: 10% sits at the bottom of the measured 10-15% premium oscillation band —
    #: loose enough that ordinary option noise does not end a trade, far looser
    #: than the 2.69% that ended the best trade of 2026-08-06.
    _OPTION_TRAIL_LOCK_FRACTION = 0.10

    #: How much profit must exist before the trail engages at all.
    #:
    #: THE TRAIL WAS INERT. Measured 2026-08-24 over 107 distinct trades with
    #: corrected excursions: it produced the binding floor on ONE of them.
    #: The old arming rule was implicit - the floor was only offered once
    #: peak*(1-0.10) cleared entry, i.e. peak >= +11.11%. Almost nothing peaks
    #: that high, so almost nothing was ever protected.
    #:
    #: 50 trades reached profit. TWENTY of them finished in a LOSS, and every
    #: single one had peaked under +11.11%, so the trail never armed on any:
    #:     SENSEX2681378500PE   peaked +8.13%   ended -22.11%
    #:     SENSEX2672378000CE   peaked +7.14%   ended -28.36%
    #:     NIFTY2680424300CE    peaked +6.04%   ended -17.64%
    #: 274 percentage-points of premium surrendered, mean 13.70pp each, with
    #: nothing underneath but the -12% hard backstop.
    #:
    #: THE FLOOR IS NOW max(trail, entry), WHICH IS WHY ARMING EARLY IS SAFE.
    #: Arming at +5% with a 10% giveback would otherwise put the floor at
    #: 1.05*0.90 = 0.945 - BELOW entry - and let a winner become a loser, which
    #: this rung exists to prevent. Taking the greater of the two keeps the old
    #: invariant exactly and adds a breakeven floor for the modest winners the
    #: proportional trail could never reach.
    #:
    #: Swept against the corpus, floor = max(peak*0.9, entry):
    #:     arm +11.11% (old)   1 trade protected   mean return -0.54%
    #:     arm  +5.00%         8 trades            mean return +0.35%
    #:     arm  +2.00%        16 trades            mean return +0.99%
    #:     arm  +0.50%        21 trades            mean return +1.32%
    #:
    #: 5% CHOSEN OVER THE APPARENT OPTIMUM ON PURPOSE. The sweep is blind to
    #: opportunity cost: it cannot see a winner that dipped through an early
    #: floor and would have recovered, because MFE records the peak and not the
    #: path. Options oscillate in a 10-15% premium band by this ladder's own
    #: measurement, so arming at +0.5% would be shaken out at breakeven by
    #: ordinary noise and the simulation would never show it. 5% demands a real
    #: move before Hokage refuses to give it all back.
    #:
    #: TARGET_HIT trades are immune either way - they exit AT their peak (100%
    #: capture, n=20), so no trail can cut them short.
    _OPTION_TRAIL_ARM_PCT = 0.05
    #: PROFIT_LOCK was retired 2026-08-06 (commander-approved) after being
    #: PROVED unreachable, not merely rare. Its stages were
    #: ((0.15, 0.08), (0.20, 0.10), (0.40, 0.50), (0.80, 0.65)).
    #:
    #: A stage could out-floor the trail only while gain < 0.1/(0.9 - lock),
    #: but every stage armed strictly AFTER that point:
    #:     lock 0.08 -> could bind below 12.2% gain, armed at 15%
    #:     lock 0.10 -> could bind below 12.5% gain, armed at 20%
    #:     lock 0.50 -> could bind below 25.0% gain, armed at 40%
    #:     lock 0.65 -> could bind below 40.0% gain, armed at 80%
    #: Swept across 286 grid points where a stage was armed, it produced the
    #: binding floor ZERO times. Each one woke up exactly too late to matter.
    #:
    #: The 2026-07-16 directive it implemented — "in profit must not become a
    #: loss, but leave room for option volatility" — is now carried by
    #: TRAIL_LOCK, which honours it strictly better: it arms at +11.1% where the
    #: earliest stage armed at +15%, and it is continuous rather than stepped.
    #: The directive is the requirement; those stages were only one expression
    #: of it.
    #:
    #: Removed rather than left in place because a rung that looks like a
    #: safeguard while never binding is how this system read 100/100 health
    #: through nine blind days. False safeguards are worse than absent ones.
    #: See test_trail_arms_before_any_profit_gap_can_open for the guard that
    #: fires if the trail is ever loosened enough to reopen that band.

    #: Adaptive target: fraction of the expected remaining underlying move,
    #: through an assumed ATM delta, clamped to a % band of entry premium.
    _OPTION_TARGET_MOVE_FRACTION = 0.30
    _OPTION_TARGET_ATM_DELTA = 0.45
    _OPTION_TARGET_MAX_PCT = 0.60

    #: The target floor is NOT a fixed percentage — it is this multiple of the
    #: position's OWN hard backstop, so reward is never smaller than the risk
    #: being taken (commander-approved 2026-08-05).
    #:
    #: It used to be a flat 6% while the backstop ranged 12-40%, which is a
    #: reward:risk of 0.33:1 on a cheap option. Hokage had to be right THREE
    #: TIMES IN FOUR merely to break even. Measured on 2026-08-05: the NIFTY put
    #: banked +6.5% at TARGET_HIT while the SENSEX put ran to the -12% backstop
    #: — a 50% hit rate that still lost money, which is what that geometry
    #: guarantees over time.
    #:
    #: Worse, `expected_move` scales with sqrt(bars_left), so the target SHRANK
    #: as the session wore on while the stop stayed full size: the 14:15 entry
    #: had 65 minutes left and collapsed straight onto the old floor. Tying the
    #: floor to the backstop removes that decay, because the floor no longer
    #: depends on how much day is left.
    #:
    #: 1.0 means "never risk more than you are trying to make". The tiers are
    #: premium-scaled (12% on a rich option, 40% on a cheap one) so the floor
    #: scales with them automatically and needs no second table.
    _OPTION_MIN_REWARD_RISK = 1.5

    def _backstop_pct_for(self, entry_premium: float) -> float:
        """The hard-backstop fraction this position is actually risking."""
        for tier_floor, max_loss_pct in self._OPTION_BACKSTOP_TIERS:
            if entry_premium >= tier_floor:
                return max_loss_pct
        return self._OPTION_BACKSTOP_TIERS[-1][1]

    def _risk_pct_for(
        self,
        entry_premium: float,
        entry_und_price: float | None,
        entry_und_atr: float | None,
        strategy_id: str | None = None,
        symbol: str | None = None,
    ) -> float:
        """Fraction of premium this position ACTUALLY risks, as a decimal.

        The risk is whichever stop fires FIRST, and measurement says that is
        almost never the premium backstop. Across the 11 trades from 2026-08-06
        and 08-07 the rungs that ended them were: THESIS_STOP 6, TRAIL 4,
        BACKSTOP 1, TARGET **0**.

        Targets had been floored at 1.5x the BACKSTOP, which put them at +18% to
        +60% of premium while trades were actually ending at plus or minus 5-9%.
        The target was therefore unreachable — it never fired once — so winners
        were left to the trail at ~+6.6% while losers ran to the thesis stop at
        ~-9.0%: an effective 0.74:1 needing a 58% hit rate against an actual
        36%. That geometry is the whole two-day loss.

        The thesis stop is an UNDERLYING move (1.25 x ATR by default), so it
        converts to a premium cost through the ATM delta. Checked against real
        fills: it predicts ~4.1% for NATURALGAS where thesis exits landed at
        2.9-5.3%.

        `strategy_id` selects that strategy's stop distance, so the target
        floor moves WITH its stop. Passing the two separately would let a
        strategy run a wide stop against a target priced off the narrow
        default — reintroducing the unreachable-target geometry this method
        was written to fix, in reverse.

        Falls back to the backstop when ATR is unavailable — never guesses.
        """
        backstop_pct = self._backstop_pct_for(entry_premium)
        if not entry_und_atr or entry_premium <= 0:
            return backstop_pct
        thesis_underlying_move = self._thesis_atr_mult_for(strategy_id, symbol) * float(entry_und_atr)
        thesis_premium_loss = thesis_underlying_move * self._OPTION_TARGET_ATM_DELTA
        thesis_pct = thesis_premium_loss / entry_premium
        # Whichever stop bites first is the real risk being taken.
        return max(0.0, min(backstop_pct, thesis_pct))

    @staticmethod
    def _excursion_pcts(
        entry_price: float,
        peak_price: float | None,
        trough_price: float | None,
        side: str = "BUY",
    ) -> tuple[float | None, float | None]:
        """Return (MFE%, MAE%) for a closed trade, signed relative to the position.

        MFE is the best unrealized move in the position's favour, MAE the worst
        against it — both as a percentage of entry. Returns None for a leg whose
        live extreme was never recorded: a missing excursion must read as
        "unknown" so attribution skips it, never as a fabricated 0.0 that would
        silently score the entry or exit as flat.
        """
        if not entry_price or entry_price <= 0:
            return None, None
        direction = 1.0 if str(side).upper() == "BUY" else -1.0
        mfe = None if peak_price is None else ((peak_price - entry_price) / entry_price) * 100.0 * direction
        mae = None if trough_price is None else ((trough_price - entry_price) / entry_price) * 100.0 * direction
        return (
            None if mfe is None else round(mfe, 4),
            None if mae is None else round(mae, 4),
        )

    #: MCX underlyings, recognised by symbol so paper-venue commodity options
    #: still use the 23:15 MCX close and the 5-minute bar rather than the NSE
    #: 15:20/15-minute pair. Extracted from the exit path so the entry path can
    #: size its target against the SAME session clock; two different clocks
    #: would reintroduce the divergence _adaptive_premium_target exists to end.
    _MCX_UNDERLYING_PREFIXES = ("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS")

    def _is_mcx_symbol(self, symbol: str, venue: Any | None = None) -> bool:
        return str(symbol).upper().startswith(self._MCX_UNDERLYING_PREFIXES) or (
            venue is not None and "mcx" in str(venue.venue_id).lower()
        )

    def _adaptive_premium_target(
        self,
        entry_premium: float,
        entry_und_price: float | None,
        entry_und_atr: float | None,
        strategy_id: str | None,
        underlying: str | None,
        is_mcx: bool,
        now_ist: datetime | None = None,
    ) -> float | None:
        """The ONE premium target. Returns None when no target rung is live.

        THERE USED TO BE TWO, AND THE COMMANDER WAS SHOWN THE DEAD ONE.
        Every entry path seeded `target_price` as entry * (1 + tp_percent) —
        10% — and the entry alert quoted that. About sixty seconds later the
        first exit-ladder tick overwrote it with the number computed here, and
        the revised value was never announced again.

        On 2026-11-06 the gas 280 CE was bought at 14.55. The alert said the
        target was ₹16.01. The engine wanted ₹16.73, decaying to ₹16.61.
        Premium crossed ₹16.01 at 11:28:01 and stayed above it for nine price
        marks, so for twenty-eight minutes the commander watched a position
        sitting past its stated target and not selling, and asked whether that
        was deliberate. It was not: he had been given a number nothing in the
        system acts on. Same shape as the `floor` that could not stop anything
        (fixed 2026-11-04) — and that one had already cost a real 7% on GOLDM.

        So the formula lives here, in one place, and the entry path seeds the
        tracking record by calling it. The number in the alert is now the
        number the exit engine uses.

        It does still MOVE: the target is sized from the underlying's ATR
        times the square root of the bars left in the session, so it decays as
        the day runs out of time to deliver the move. That is a property of
        the design, not a defect, which is why the alert says so out loud
        instead of printing a figure that looks fixed.

        None means the TARGET_HIT rung cannot fire for this position at all —
        without an entry ATR there is nothing to calibrate against, and the
        ladder has always skipped the rung rather than fabricate a level.
        Callers must say "no target" in that case, never substitute 10%.
        """
        if not entry_und_atr or entry_premium <= 0:
            return None
        import math

        now_ist = now_ist or self._now_ist()
        bar_minutes = 5 if is_mcx else 15
        # The runway to the SQUARE-OFF, which is what this has always meant
        # despite the name. On a special session the ordinary pair is badly
        # wrong: at 14:30 on 2026-11-08 an MCX position would be credited
        # 525 minutes of runway against a market closing in 60, inflating
        # the expected move by sqrt(105/12) and putting the target out of
        # reach of the session it has to be reached in.
        close_hour, close_min = self._square_off_time(is_mcx, now_ist.date())
        minutes_left = (close_hour - now_ist.hour) * 60 + (close_min - now_ist.minute)
        bars_left = max(0.0, minutes_left / bar_minutes)
        expected_move = float(entry_und_atr) * math.sqrt(bars_left)
        raw_target = entry_premium + (
            self._OPTION_TARGET_MOVE_FRACTION * self._OPTION_TARGET_ATM_DELTA * expected_move
        )
        # Floor the target at the risk this position is ACTUALLY taking —
        # measured with THIS strategy's stop distance, so reward:risk stays
        # honest for a strategy running a non-default stop.
        min_pct = self._risk_pct_for(
            entry_premium, entry_und_price, entry_und_atr,
            strategy_id, underlying,
        ) * self._OPTION_MIN_REWARD_RISK
        return min(
            max(raw_target, entry_premium * (1.0 + min_pct)),
            entry_premium * (1.0 + max(self._OPTION_TARGET_MAX_PCT, min_pct)),
        )

    def _seed_target_price(
        self,
        entry_premium: float,
        underlying: str | None,
        entry_und_price: float | None,
        entry_und_atr: float | None,
        strategy_id: str | None,
        now_ist: datetime | None = None,
    ) -> tuple[float, bool]:
        """What goes in tracking["target_price"] at fill. (value, is_adaptive).

        All three entry paths used to write entry * (1 + tp_percent) here and
        hand that figure straight to the entry alert, which is how the
        commander came to be told ₹16.01 on a position the engine would only
        sell at ₹16.61. See _adaptive_premium_target.

        When is_adaptive is False the TARGET_HIT rung CANNOT FIRE for this
        position — there was no entry ATR to calibrate against. The
        tp_percent figure is still stored, because the dashboard, the premium
        mark archive and the review all expect a float there, but it is NOT an
        exit level and the alert must not present it as one. That is what the
        second element of this tuple is for.

        `now_ist` defaults to the live clock. It is injectable because the
        target depends on how much of the session is LEFT, so a test that
        cannot fix the clock cannot pin the number against the figure the
        ladder printed on the real trade.
        """
        target = self._adaptive_premium_target(
            entry_premium, entry_und_price, entry_und_atr,
            strategy_id, underlying, self._is_mcx_symbol(underlying or ""),
            now_ist,
        )
        if target is None:
            return round(entry_premium * (1.0 + self.tp_percent), 2), False
        return round(target, 2), True

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
        # Excursion envelope for post-trade component attribution: the peak is
        # the profit that was ON THE TABLE (entry quality), the trough is the
        # worst heat taken (risk quality). Recorded live because neither can be
        # reconstructed after the fact from entry/exit prices alone.
        tracking["trough_price"] = min(tracking.get("trough_price", entry_premium), current_premium)

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
                atr_mult = self._thesis_atr_mult_for(tracking.get("strategy_id"), underlying)
                if adverse >= atr_mult * float(entry_und_atr):
                    return True, (
                        f"Underlying Thesis Stop: {underlying} moved {adverse:.2f} against "
                        f"position (>= {atr_mult} x ATR {float(entry_und_atr):.2f})"
                    ), tracking

        # Rung 3 — TARGET_HIT: adaptive, move-calibrated premium target sized
        # to how much the market can plausibly still move today.
        target = self._adaptive_premium_target(
            entry_premium, entry_und_price, entry_und_atr,
            tracking.get("strategy_id"), tracking.get("underlying"),
            is_mcx, now_ist,
        )
        if target is not None:
            tracking["target_price"] = round(target, 2)
            if current_premium >= target:
                return True, (
                    f"TARGET_HIT: premium {current_premium:.2f} reached adaptive "
                    f"target {target:.2f} (entry {entry_premium:.2f})"
                ), tracking

        # Rung 4 — PROFIT PROTECTION: a ratcheting floor that keeps a winner
        # from round-tripping into a loser (commander directive 2026-07-16:
        # "in profit must not become a loss, but leave room for option
        # volatility"). TRAIL_LOCK is the single source; the PROFIT_LOCK stages
        # that used to sit beside it were proved unreachable and retired.
        # The floor only ever rises; it is stored in tracking["stop_price"]
        # so the dashboard shows the live protective level.
        floor_candidates: list[tuple[float, str]] = []
        if quantity > 0 and entry_premium > 0:
            # Scaled to the position, not a flat rupee figure: the same giveback
            # must mean the same thing on a Rs 37k silver lot and a Rs 8.6k
            # NIFTY lot. Measured off PEAK so it widens as the winner runs, and
            # armed only once that floor clears entry — so an armed trail can
            # never turn a winner into a loser.
            trail_floor = peak_premium * (1.0 - self._OPTION_TRAIL_LOCK_FRACTION)
            armed = peak_premium >= entry_premium * (1.0 + self._OPTION_TRAIL_ARM_PCT)
            if armed:
                # Never below entry: a winner cannot round-trip into a loser
                # through this rung, which is the whole point of it.
                protective = max(trail_floor, entry_premium)
                if protective > trail_floor:
                    label = (
                        f"TRAIL_LOCK: breakeven floor held at entry {entry_premium:.2f} "
                        f"after peaking {(peak_premium / entry_premium - 1.0):.1%}"
                    )
                else:
                    label = (
                        f"TRAIL_LOCK: gave back {self._OPTION_TRAIL_LOCK_FRACTION:.0%} of peak "
                        f"(₹{(peak_premium - protective) * quantity:,.0f}) from peak {peak_premium:.2f}"
                    )
                floor_candidates.append((protective, label))
        if floor_candidates:
            floor_premium, floor_label = max(floor_candidates, key=lambda fc: fc[0])
            prev_floor = float(tracking.get("stop_price") or 0.0)
            if floor_premium > prev_floor:
                tracking["stop_price"] = round(floor_premium, 2)
                tracking["stop_label"] = floor_label
            active_floor = float(tracking["stop_price"])
            if current_premium <= active_floor:
                # THE LABEL MUST DESCRIBE THE FLOOR THAT ACTUALLY FIRED.
                # `stop_label` is only written when a candidate REPLACES the
                # stored floor, but `stop_price` is also seeded at entry with
                # no label at all — so a seeded floor that outranked every
                # candidate reported the CANDIDATE's label. On 2026-08-25 two
                # exits announced "breakeven floor held at entry 6839.50" while
                # 7181.48 did the work. Only use the freshly computed label
                # when the freshly computed floor is the one in force.
                if abs(floor_premium - active_floor) < 0.005:
                    _label = floor_label          # the computed floor IS in force
                else:
                    _label = tracking.get("stop_label") or "TRAIL_LOCK: protective floor"
                return True, (
                    f"{_label} — premium {current_premium:.2f} "
                    f"hit protective floor {active_floor:.2f}"
                ), tracking

        self._archive_mark(symbol, entry_premium, current_premium, peak_premium, tracking)
        self._trace_ladder(symbol, entry_premium, current_premium, peak_premium, tracking)
        return False, "", tracking

    #: A new peak must beat the last traced one by this much to be worth a line.
    _LADDER_TRACE_PEAK_STEP = 0.02

    def _effective_premium_floor(
        self, entry_premium: float, peak_premium: float, tracking: dict[str, Any],
    ) -> tuple[float, str]:
        """The premium level that would ACTUALLY trigger an exit, and its name.

        WHY THIS EXISTS. `tracking["stop_price"]` is SEEDED at entry x (1 -
        tsl_percent) — 5% below entry — and every display read it as "the live
        protective level". On a bought option it is not a stop at all. Rung 4
        is PROFIT protection: it arms only once the peak clears
        `_OPTION_TRAIL_ARM_PCT` above entry, and its enforcement lives inside
        `if floor_candidates:`, which is empty until then. So an un-armed
        position's seeded floor is never compared to anything.

        GOLDM26NOV138500PE, 2026-11-02: peaked +4.53%, missed arming by 16.83
        points, and the archive holds SEVEN consecutive one-minute marks with
        the premium 5-9% BELOW a floor of 3388.17 that every one of them
        printed. It exited on the -12% backstop at -17.7%, Rs 6,325. The exit
        was correct and the grades were already fixed (02dc802); the NUMBER ON
        THE SCREEN was the lie, and it misled the commander and me both.

        THE THESIS STOP IS NOT IN HERE, and cannot be: rung 2 fires on a move
        in the UNDERLYING, which has no premium level. It is the rung that
        actually ended both of 2026-11-03's trades. A caller showing this
        number must not imply it is the only way out.

        Returns (level, label). Never raises, and NEVER touches `stop_price` —
        the ladder's enforcement reads that field directly, and this method
        exists to describe the ladder, not to change it.
        """
        try:
            entry_premium = float(entry_premium or 0.0)
            if entry_premium <= 0:
                return 0.0, "unknown"
            backstop = entry_premium * (1.0 - self._backstop_pct_for(entry_premium))
            armed = float(peak_premium or 0.0) >= entry_premium * (
                1.0 + self._OPTION_TRAIL_ARM_PCT)
            if not armed:
                return backstop, "backstop"
            # Once armed the ladder enforces stop_price itself, so that is the
            # level in force — but the backstop never stops being live, and
            # whichever sits HIGHER is the one a falling premium meets first.
            trail = float(tracking.get("stop_price") or 0.0)
            if trail > backstop:
                return trail, "trail"
            return backstop, "backstop"
        except Exception:
            return 0.0, "unknown"

    @staticmethod
    def _auction_key(conf: float, sid: str, module: object) -> tuple:
        """How the MCX arena ranks one firing module. Lowest key wins.

        DECLARED HERE SO A FILE REWRITE CANNOT REACH IT. Until 2026-10-28 an
        exact tie was settled by the order of keys in the portfolio JSON:
        the loop kept the first module it met and replaced it only on a
        STRICTLY higher confidence. A mirror ties its original on every scan
        by design, so when a write re-sorted that file alphabetically the
        winner flipped from TrendRider to RiderTrend - 2 ties to 0 on
        2026-10-26, then 0 to 14 on 2026-10-27, with nothing about gas
        changed. An experiment whose outcome turns on a string comparison is
        not an experiment.

            1. confidence, highest first
            2. a mirror LOSES a tie to a non-mirror
            3. strategy_id, as a reproducible last resort

        Rung 2 is the rule: the experiment does not displace the measured
        strategy. The mirror is scored on every tie by signal_archive and
        needs no fill to be measured. It is NOT barred from winning - a
        mirror still out-bids a different module on higher confidence, and
        still wins alone when its original is archived or out of scope.
        Only the tie is decided.
        """
        return (-float(conf or 0.0),
                1 if getattr(module, "IS_MIRROR", False) else 0,
                str(sid))

    def _archive_scan(self, symbol, scan_verdicts, winner_sid, mkt_ctx):
        """Write one auction's full field to the signal archive.

        Returns the scan stamp so a later fill can be stamped against it, or
        None when nothing was written.

        NEVER RAISES. This sits inside the scan loop; a scan that died because
        a row could not be written would be far worse than a missing row.
        """
        try:
            from hokage.memory import signal_archive

            stamp = signal_archive.now_ist()
            signal_archive.remember_scan(
                symbol, scan_verdicts,
                winner_strategy_id=winner_sid,
                underlying=getattr(mkt_ctx, "price", None),
                when=stamp,
                premiums=self._scan_premiums(
                    symbol, scan_verdicts, getattr(mkt_ctx, "price", None)),
            )
            return stamp.isoformat()
        except Exception as exc:
            logger.debug(f"Could not archive the {symbol} scan: {exc}")
            return None

    def _scan_premiums(self, symbol, scan_verdicts, price) -> dict:
        """{direction: (option_symbol, premium)} for the sides that FIRED.

        WHY THIS COSTS A QUOTE. An option's premium history dies with its
        contract, so the cost of the trade a losing side would have taken can
        only ever be recorded at the instant it was proposed. The mirror
        experiment ran eleven days without it and could not be settled: both
        sides BUY options, both pay theta and the spread, so a mirror only
        wins where its original was wrong about DIRECTION rather than about
        MOVEMENT — and that distinction exists in premium and nowhere else.
        On the underlying a mirror's edge is exactly minus its original's,
        which is no information at all.

        AT MOST TWO QUOTES PER SCAN. The map is keyed by direction, not by
        module, so a mirror and its original share one resolution each way and
        a scan can never cost more than a CE and a PE however many modules
        fired.

        NEVER RAISES, AND NEVER DELAYS A DECISION. It runs after the auction
        has already been settled, so a dead feed or a thin chain costs a NULL
        column and nothing else. An unpriceable side is omitted rather than
        written as zero: 0.0 is a premium the venue might really have quoted.
        """
        out: dict[str, tuple[str, float]] = {}
        if not price or price <= 0:
            return out
        source = getattr(self.orchestrator, "price_source", None)
        resolver = getattr(source, "resolve_option_contract", None)
        if resolver is None:
            return out

        wanted = {
            (getattr(sig, "direction", "") or "").lower()
            for _sid, _mid, sig in scan_verdicts or ()
            if getattr(sig, "should_enter", False)
        }
        for direction in wanted:
            option_type = {"long": "CE", "short": "PE"}.get(direction)
            if option_type is None:
                continue
            try:
                contract = resolver(symbol, option_type, float(price))
                tradingsymbol = (contract or {}).get("tradingsymbol")
                if not tradingsymbol:
                    continue
                premium = float(source.get_quote(tradingsymbol).price)
                if premium > 0:
                    out[direction] = (tradingsymbol, premium)
            except Exception as exc:
                logger.debug(
                    f"Could not price the {direction} side of {symbol}: {exc}")
        return out

    def _opposing_leg_for(
        self, underlying: str, scanned_at: str | None, held_option: str,
    ) -> dict[str, Any] | None:
        """The losing side's contract and what it cost, or None.

        Read back out of the scan archive rather than threaded down from the
        auction, so there is one definition of "what the other side would have
        bought" and it is the one already being recorded. NEVER RAISES: this
        sits in the entry path, and a position must not fail to be tracked
        because an experiment could not be set up.
        """
        if not scanned_at:
            return None
        try:
            from hokage.memory import signal_archive

            leg = signal_archive.opposing_leg(underlying, scanned_at, held_option)
            if not leg:
                return None
            return {
                "symbol": str(leg["option_symbol"]).upper(),
                "entry": float(leg["option_premium"]),
                "module_id": leg.get("module_id"),
                "direction": leg.get("direction"),
                "scanned_at": str(scanned_at),
            }
        except Exception as exc:
            logger.debug(f"No opposing leg recorded for {held_option}: {exc}")
            return None

    def _start_shadow_path(
        self, symbol: str, scanned_at: str | None, reason: str,
    ) -> None:
        """Record the contract a BIAS-GATE refusal just prevented buying.

        The gate is the only component here whose effect has never been
        measurable: veto_lab can score it on the underlying over all history,
        but a blocked trade is never bought, so nothing has ever priced one.
        This writes the first mark of its path - the premium at the instant of
        the refusal - and the tick polls it from there.

        ONLY THE BIAS GATE. `_entry_conduct_gate` returns one reason string for
        several refusals, the IV premium guard and the late-session cutoff
        among them, and a shadow for those would be measuring something nobody
        asked about.

        NEVER RAISES. This sits in the entry path, immediately after a decision
        not to trade, and an experiment must not be able to disturb the loop
        that made it.
        """
        try:
            from hokage.memory import shadow_path, signal_archive

            if not scanned_at or not shadow_path.is_gate_block(reason):
                return
            # A symbol that already holds a position had no trade to lose, and
            # a shadow already running is the trade it would have had open.
            # One per underlying - see shadow_path's docstring for the bound.
            if symbol in self._active_positions_tracking:
                return
            if any(s["underlying"] == symbol.upper() for s in shadow_path.live()):
                return
            leg = signal_archive.winning_leg(symbol, scanned_at)
            if not leg:
                return
            premium = float(leg["option_premium"])
            wrote = shadow_path.remember(
                leg["option_symbol"], premium, premium,
                underlying=symbol, scanned_at=str(scanned_at),
                direction=leg.get("direction"), blocked_by=reason,
                module_id=leg.get("module_id"),
            )
            if wrote:
                logger.info(
                    "Shadow path opened on %s: the gate refused %s at %.2f, "
                    "pricing it for %d minutes to measure what the refusal "
                    "was worth.", symbol, leg["option_symbol"], premium,
                    shadow_path.WINDOW_MINUTES,
                )
        except Exception as exc:
            logger.debug(f"Could not open a shadow path for {symbol}: {exc}")

    def _poll_shadow_paths(self) -> None:
        """Price every refused contract still inside its window.

        AT MOST ONE QUOTE PER UNDERLYING PER TICK, bounded by
        `shadow_path.live`, which keeps one shadow per asset. Four MCX assets
        means at most four extra quotes, and only while a refusal is recent.

        Runs on the position-monitoring tick rather than the entry scan because
        a refusal produces NO position: there is no tracking loop to ride, and
        the scan only fires every fifteen minutes. NEVER RAISES.
        """
        try:
            from hokage.memory import shadow_path

            shadows = shadow_path.live()
            if not shadows:
                return
            source = getattr(self.orchestrator, "price_source", None)
            if source is None:
                return
            when = shadow_path.now_ist()
            for shadow in shadows:
                try:
                    premium = float(source.get_quote(shadow["symbol"]).price)
                except Exception:
                    continue          # a dead quote is not a price of zero
                if premium <= 0:
                    continue
                shadow_path.remember(
                    shadow["symbol"], premium, float(shadow["entry"]),
                    underlying=shadow["underlying"],
                    scanned_at=shadow["scanned_at"],
                    direction=shadow.get("direction"),
                    blocked_by=shadow.get("blocked_by"),
                    module_id=shadow.get("module_id"),
                    when=when,
                )
        except Exception as exc:
            logger.debug(f"Shadow path polling failed: {exc}")

    def _archive_mirror_mark(
        self,
        held_symbol: str,
        held_entry: float,
        held_premium: float,
        tracking: dict[str, Any],
        when,
    ) -> None:
        """Price the side that lost the auction, on the same tick as the one
        that won.

        ONE EXTRA QUOTE PER MARK, and only while a position is open. The leg
        is fixed at entry, so this cannot fan out: a scan prices at most one
        CE and one PE however many modules fired.

        NEVER RAISES, and deliberately runs AFTER the real mark is written -
        the held position's path is the one the trail study needs, and an
        experiment must not be able to cost it a row.
        """
        leg = tracking.get("mirror_leg")
        if not isinstance(leg, dict) or not leg.get("symbol"):
            return
        try:
            source = getattr(self.orchestrator, "price_source", None)
            if source is None:
                return
            premium = float(source.get_quote(leg["symbol"]).price)
            if premium <= 0:
                return
            from hokage.memory import mirror_path

            mirror_path.remember(
                leg["symbol"],
                premium,
                float(leg["entry"]),
                held_symbol=held_symbol,
                held_premium=held_premium,
                held_entry=held_entry,
                module_id=leg.get("module_id"),
                decision_id=tracking.get("decision_id"),
                scanned_at=leg.get("scanned_at"),
                when=when,
            )
        except Exception as exc:
            logger.debug(
                f"Could not price the opposing leg of {held_symbol}: {exc}")

    def _archive_mark(
        self,
        symbol: str,
        entry_premium: float,
        current_premium: float,
        peak_premium: float,
        tracking: dict[str, Any],
    ) -> None:
        """Write one point of this position's premium path to the archive.

        SEPARATE FROM _trace_ladder ON PURPOSE. That method logs the three
        transitions a human needs to understand a round trip, and returns
        early when nothing changed. The marks it skips are the ones a floor
        study needs most: a path recorded only at its corners says nothing
        about what happened along the edges.

        Rate-limited per position - see MIN_SECONDS_BETWEEN_MARKS for why the
        archive must not inherit the per-tick dump the log refuses.

        NEVER RAISES. This runs inside the exit path, and a position that
        cannot be closed because its history could not be written would be a
        far worse bug than a missing row.
        """
        try:
            from hokage.memory import premium_path

            now = premium_path.now_ist()
            # EPOCH SECONDS, NOT A datetime. This dict is the per-position
            # tracking record, and it is json.dump'ed to active_positions.json
            # on every tick - so a datetime here is not a local detail, it is
            # the thing that truncated the file holding every open position's
            # stop and target. A float makes the round trip; anything else that
            # ever lands here is treated as stale and re-stamped.
            last = tracking.get("_archived_at")
            if isinstance(last, (int, float)) and (
                now.timestamp() - float(last) < premium_path.MIN_SECONDS_BETWEEN_MARKS
            ):
                return
            tracking["_archived_at"] = now.timestamp()

            premium_path.remember(
                symbol,
                current_premium,
                entry_premium,
                peak=peak_premium,
                floor=tracking.get("stop_price"),
                target=tracking.get("target_price"),
                decision_id=tracking.get("decision_id"),
                when=now,
                # Stored BESIDE floor, not instead of it: the 1,141 marks
                # already written mean stop_price, and a floor study that
                # mixed the two meanings would be comparing two things it
                # believed were one.
                effective_floor=self._effective_premium_floor(
                    entry_premium, peak_premium, tracking)[0] or None,
            )
            self._archive_mirror_mark(
                symbol, entry_premium, current_premium, tracking, now)
        except Exception as exc:
            logger.debug(f"Could not archive the premium mark for {symbol}: {exc}")

    def _trace_ladder(
        self,
        symbol: str,
        entry_premium: float,
        current_premium: float,
        peak_premium: float,
        tracking: dict[str, Any],
    ) -> None:
        """Log the ladder's STATE CHANGES while a position is still open.

        2026-08-27: GOLDM26SEP157000PE was entered at 3750, peaked +6.7%, and
        exited three hours later at 3741 for -90. The only line the ladder ever
        wrote was the exit itself, so there was no way — for the commander or
        for me — to reconstruct why a position that was up 6.7% ended at zero.
        Every rung's state was computed on every tick and then discarded.

        This traces the three transitions that actually explain a round-trip:
        the trail ARMING, the protective floor RATCHETING, and a materially new
        PEAK. Deliberately NOT a per-tick dump — the watchdog already showed
        what happens when a subsystem logs its state every few seconds: 74% of
        2026-08-27's log was one sentence repeated, and it buried 135 real
        errors. A line here has to earn its place by reporting a change.
        """
        if entry_premium <= 0:
            return
        target = tracking.get("target_price")
        floor = float(tracking.get("stop_price") or 0.0)
        armed = peak_premium >= entry_premium * (1.0 + self._OPTION_TRAIL_ARM_PCT)
        # What the line SAYS is the level that can actually fire, not the
        # seeded stop_price it used to print. See _effective_premium_floor:
        # for seven minutes on 2026-11-02 this line reported "floor 3388.17"
        # while holding a position 5-9% below it, because rung 4 had never
        # armed and nothing was checking that number.
        live_floor, floor_rung = self._effective_premium_floor(
            entry_premium, peak_premium, tracking)

        events: list[str] = []
        if armed and not tracking.get("_traced_armed"):
            tracking["_traced_armed"] = True
            events.append(f"trail ARMED at peak {peak_premium:.2f} "
                          f"({peak_premium / entry_premium - 1.0:+.1%})")

        last_floor = float(tracking.get("_traced_floor") or 0.0)
        if floor > last_floor + 0.005:
            tracking["_traced_floor"] = floor
            if armed:
                events.append(f"floor RATCHETED {last_floor:.2f} -> {floor:.2f}")
            else:
                # THE LINE THAT MISLED EVERYONE. "floor RATCHETED 0.00 ->
                # 3388.17" was the first thing both GOLDM losses printed, and
                # it reads as protection arriving. Nothing arrived: that is
                # stop_price being SEEDED at entry x (1 - tsl_percent), and
                # rung 4 will not look at it until the peak clears +5%.
                events.append(
                    f"stop_price seeded at {floor:.2f} — NOT live, the trail "
                    f"arms at {entry_premium * (1.0 + self._OPTION_TRAIL_ARM_PCT):.2f} "
                    f"(+{self._OPTION_TRAIL_ARM_PCT:.0%})")

        last_peak = float(tracking.get("_traced_peak") or entry_premium)
        if peak_premium >= last_peak * (1.0 + self._LADDER_TRACE_PEAK_STEP):
            tracking["_traced_peak"] = peak_premium
            events.append(f"new peak {peak_premium:.2f} "
                          f"({peak_premium / entry_premium - 1.0:+.1%})")

        if not events:
            return
        logger.info(
            "Exit ladder %s: %s | now %.2f (%+.1f%%) peak %.2f floor %s "
            "target %s | + thesis stop on the underlying",
            symbol, "; ".join(events), current_premium,
            (current_premium / entry_premium - 1.0) * 100.0, peak_premium,
            # The rung is named because "floor 3138.52" and "floor 3566.50"
            # are different promises, and a reader cannot tell which they are
            # looking at from the number alone.
            f"{live_floor:.2f} ({floor_rung})" if live_floor else "none",
            f"{target:.2f}" if target else "not set",
        )

    def _monitor_and_exit_positions(self, is_tick: bool = True) -> None:
        """Check open positions across all active venues and enforce TSL/TP exits."""
        context = self.orchestrator.get_execution_context()
        if context.execution_mode == ExecutionMode.READ_ONLY:
            return

        # A refused trade has no position, so this tick is the only loop that
        # runs often enough to price one and runs whether or not anything is
        # open. Before the exit work, because a shadow mark is cheap and an
        # exception on the way out must not skip it.
        self._poll_shadow_paths()

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

        # Query all positions and map symbol to the venue where it belongs.
        #
        # DEDUPLICATED BY SYMBOL, and that is load-bearing. SIX paper venues are
        # registered (paper_main, paper_mcx, paper_alpaca, paper_coindcx,
        # paper_oanda, paper_zerodha) and several share the same underlying
        # account, so a single position is reported once PER VENUE. Without this,
        # every exit fires N times: the first fills and the rest are refused by
        # the reduce-only guard, logging "position remains open" about a position
        # that just closed.
        #
        # Observed live 2026-08-17: BANKNIFTY (on the shared `paper` account,
        # visible to five venues) took 5 exit attempts — 1 fill, 4 rejections —
        # while GOLDM (alone on paper_mcx) took exactly 1. No money was ever at
        # risk because reduce_only held, but the noise would mask a GENUINE
        # repeat-exit condition, which is the failure that produced 207 phantom
        # positions in July.
        #
        # Deduping by symbol is correct rather than merely convenient:
        # `_active_positions_tracking` is keyed by symbol alone, so the system
        # cannot represent two positions in the same symbol anyway. Where a
        # symbol is seen more than once, prefer the venue the entry was actually
        # placed on so the exit goes back to the same book.
        by_symbol: dict[str, tuple[Any, Any]] = {}
        for venue in active_venues:
            try:
                venue_positions = venue.get_positions()
            except Exception as exc:
                logger.error(f"Failed to fetch positions for venue {venue.venue_id}: {exc}")
                continue
            for pos in venue_positions:
                symbol = pos.instrument.symbol
                entry_venue = (self._active_positions_tracking.get(symbol) or {}).get("venue_id")
                if symbol not in by_symbol or venue.venue_id == entry_venue:
                    by_symbol[symbol] = (pos, venue)
        positions_with_venue = list(by_symbol.values())

        risk_state = self.cache.read_intelligence("risk_state.json") or {}
        vix_impact_delta = risk_state.get("vix_impact_delta", 0.0)
        regime_data = self.cache.read_intelligence("market_regime.json") or {}
        trend_score = regime_data.get("trend_score", 0.0)
        classified_regime = self.adv_regime_engine.classify_regime(trend_score, vix_impact_delta)

        updated_tracking = {}
        marked_to_market: dict[str, float] = {}
        for pos, venue in positions_with_venue:
            symbol = pos.instrument.symbol
            tracking = self._active_positions_tracking.get(symbol)

            # Stamp WHICH STRATEGY owns this position onto the position itself,
            # every pass. The tracking dict is the authoritative source but it
            # is in-memory only; `save_account` persists whatever the position
            # carries. Re-stamping each loop is deliberately self-healing: a
            # position that existed before this shipped, or whose attribution
            # was lost, gets it back on the next iteration rather than staying
            # anonymous forever. Never overwrite a known id with None.
            _owner = (tracking or {}).get("strategy_id")
            if _owner and getattr(pos, "strategy_id", None) != _owner:
                try:
                    pos.strategy_id = _owner
                except Exception:
                    pass  # some venue position types are immutable; not fatal

            # LIVE price for the exit ladder. pos.current_price comes from the
            # paper account book, which nothing marks to market — it stays at
            # the ENTRY price forever. On 2026-07-16 the ladder spent a whole
            # session comparing a NIFTY option against its own entry (124 vs
            # 124): the premium crossed the target AND broke the stop and no
            # premium rung ever saw either — only the underlying thesis stop
            # and the EOD clock (which fetch their own data) have ever fired.
            # A failed live fetch falls back to the stored price: exits are
            # never refused outright on data quality, but a rung that needs
            # the live premium simply cannot trigger that cycle (never guess).
            live_price, _live_reason = self._get_validated_live_price(symbol)
            if live_price is not None:
                marked_to_market[symbol] = float(live_price)
            current_price = live_price if live_price is not None else (pos.current_price or pos.average_price)

            # Evaluate open position via Cascading Exits Stack
            trigger_exit, exit_reason, tracking = self._evaluate_cascading_exits(
                symbol=symbol,
                side=pos.side,
                quantity=pos.quantity,
                average_price=pos.average_price,
                current_price=current_price,
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
                    execution_reason=exit_reason,
                    # An exit may only ever reduce exposure. Without this the
                    # venue executes it as a fresh opposite-side entry when the
                    # position is already gone, and the monitor then exits THAT.
                    reduce_only=True,
                )
                try:
                    logger.info(f"Triggering Exit for {symbol} ({exit_reason})")
                    resp = venue.place_order(exit_req)

                    # The response used to be discarded. A rejected or unfilled
                    # exit then looked identical to a successful one: the
                    # commander got a "position closed" alert, the position
                    # stayed open, and the next tick exited it again — 377 times
                    # on 2026-07-15. Treat a non-fill as "still open": no
                    # notification, no analytics, no tracking teardown. The
                    # position stays under management and is retried on merit.
                    if resp is None or resp.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                        reason_txt = getattr(resp, "error_message", None) or "venue returned no fill"
                        logger.warning(
                            f"Exit for {symbol} did NOT fill ({reason_txt}); "
                            f"position remains open, skipping exit bookkeeping."
                        )
                        continue

                    # PnL from the price the exit ACTUALLY FILLED AT. pos.
                    # unrealized_pnl is the stale book value (never marked to
                    # market = always 0.0), which scored every exit as
                    # BREAKEVEN and fed the strategy scoreboard zeros for real
                    # wins and losses.
                    #
                    # It used to use `current_price` — the quote the exit
                    # DECISION was made on. The venue books the account from
                    # resp.average_price instead, so the war chest and the
                    # account recorded different numbers for the same exit and
                    # the two drifted apart by the tick plus modelled friction
                    # on every single trade. They are meant to be ONE ledger.
                    # Observed 2026-07-30: the NIFTY thesis-stop credited the
                    # chest -1,043.25 while the account booked -1,036.75, and
                    # three exits left 6.50 of drift the panel then reported.
                    # Friction is one-directional, so this accumulates.
                    _pnl_sign = 1.0 if pos.side == OrderSide.BUY else -1.0
                    fill_price = float(getattr(resp, "average_price", 0.0) or 0.0)
                    if fill_price <= 0.0:
                        # Venue reported a fill without a price; the decision
                        # quote is the only number available.
                        fill_price = current_price
                        logger.warning(
                            f"Exit for {symbol} filled without an average_price; "
                            f"booking PnL from the decision quote {current_price}."
                        )
                    live_pnl = round((fill_price - pos.average_price) * pos.quantity * _pnl_sign, 2)

                    exit_record = {
                        "symbol":     symbol,
                        "side":       exit_side.value,
                        "quantity":   pos.quantity,
                        "reason":     exit_reason,
                        "pnl":        live_pnl,
                        "timestamp":  datetime.now(timezone.utc).isoformat(),
                    }
                    self._exits_executed_today.append(exit_record)

                    # Notify immediately, isolated from every downstream
                    # analytics/journal step below: those can throw (and did
                    # — an exception anywhere past this point used to skip
                    # the Telegram notification entirely, since notify_exit
                    # previously only fired at the tail end of the async
                    # post-exit analysis block).
                    if self.telegram_bot and self.telegram_bot.enabled:
                        try:
                            self.telegram_bot.notify_exit(
                                symbol, price=current_price, reason=exit_reason,
                                strategy=self._strategy_display_name(tracking.get("strategy_id")),
                                pnl=live_pnl,
                                context=self._trade_context(
                                    symbol, tracking, side="exit",
                                    exit_price=current_price,
                                    exit_reason=exit_reason, pnl=live_pnl,
                                ),
                            )
                        except Exception as exc:
                            logger.error(f"Failed to send exit notification for {symbol}: {exc}")

                    # Resolve metadata stored at entry time
                    entry_meta = tracking or {}
                    stored_decision_id   = entry_meta.get("decision_id", "")
                    stored_entry_price   = entry_meta.get("entry_price", pos.average_price)
                    # initial_stop_price first: "stop_price" is the ratcheted
                    # floor, and on a winner it sits ON entry by exit time.
                    stored_stop_price    = (
                        entry_meta.get("initial_stop_price")
                        or entry_meta.get("stop_price", 0.0)
                    )
                    stored_target_price  = entry_meta.get("target_price", pos.average_price * 1.10)
                    stored_conviction    = entry_meta.get("conviction_score", 75)
                    stored_alloc_pct     = entry_meta.get("allocation_pct", 1.0)
                    # No default. A missing size must reach the review as None
                    # so the sizing grade can say UNKNOWN; the 1.0 above is
                    # what made it answer CORRECT for every MCX and manual
                    # trade ever taken.
                    stored_chest_pct     = entry_meta.get("chest_fraction_pct")
                    # No default here either. `stop_price` is NOT the stop on a
                    # bought option — it is the TRAIL_LOCK profit floor — so
                    # the stop grade reads the risk frozen at entry or nothing.
                    stored_risk_pct      = entry_meta.get("risk_pct_at_entry")
                    stored_sector        = entry_meta.get("sector", self.portfolio_intel.symbol_sectors.get(symbol.upper(), "other"))
                    stored_personality   = entry_meta.get("personality_mode", "BALANCED")
                    stored_sector_flow   = entry_meta.get("sector_flow", "N/A")
                    # Real time on the clock, not the 3 days every site below
                    # used to assume. See _holding_seconds.
                    held_seconds         = self._holding_seconds(entry_meta)
                    held_days            = int(held_seconds // 86400)

                    symbol_sec = stored_sector
                    regime_data = self.cache.read_intelligence("market_regime.json")
                    regime_str = regime_data.get("prediction", "NORMAL")

                    # The live-marked price, not the stale book price (which
                    # sat at entry and scored every exit as breakeven PnL=0).
                    exit_price_actual = current_price or stored_entry_price
                    return_pct = (
                        ((exit_price_actual - stored_entry_price) / stored_entry_price)
                        if stored_entry_price > 0 else 0.0
                    )
                    is_win = (live_pnl > 0.0)
                    outcome_str = "WIN" if is_win else ("LOSS" if live_pnl < 0 else "BREAKEVEN")

                    if not is_win:
                        self._log_post_mortem_failure(
                            symbol=symbol,
                            trade_id=tracking.get("decision_id", "UNKNOWN"),
                            exit_price=exit_price_actual,
                            exit_reason=exit_reason,
                            entry_price=stored_entry_price,
                            stop_price=stored_stop_price,
                            pnl=live_pnl
                        )

                    # --- Layer 1: Synchronous outcome recording ---
                    self.analytics_engine.record_trade_outcome(
                        symbol=symbol,
                        sector=symbol_sec,
                        market_regime=regime_str,
                        conviction_score=stored_conviction,
                        holding_period_days=held_days,
                        pnl=live_pnl,
                        is_win=is_win,
                        decision_id=stored_decision_id,
                        entry_price=stored_entry_price,
                        exit_price=exit_price_actual,
                        return_pct=return_pct,
                    )

                    # Excursion envelope, measured live during the hold (see the
                    # exit ladders). MFE = how far price ran in our favour =
                    # entry quality; MAE = worst heat taken. Capture efficiency
                    # (realized / MFE) is what separates a bad exit from a bad
                    # entry — neither is recoverable from entry/exit prices
                    # alone, which is why these were previously mocked.
                    # THE SIDE HERE IS THE POSITION, NOT THE SIGNAL.
                    #
                    # entry_meta["side"] stores the UNDERLYING signal direction
                    # (autonomous_bot.py:2533 / :4258 set SELL for a bearish
                    # call), but the OptionsRouter turns a bearish signal into
                    # BUY A PUT. Hokage only ever BUYS options, and the tracked
                    # peak/trough are PREMIUMS, so the position is long the
                    # thing being measured either way.
                    #
                    # Passing the signal side flipped the sign on every PUT.
                    # Found 2026-08-22: all four winning puts in the corpus
                    # carried an impossible NEGATIVE MFE, two of them the exact
                    # negation of the realised return -
                    #     CRUDEOIL26AUG8050PE   MFE -3.85   ret +3.85
                    #     NATURALGAS26AUG255PE  MFE -17.87  ret +10.14
                    # while all seven calls were correct.
                    #
                    # A negative MFE on a LOSING trade is legitimate (the best
                    # moment was still under water), which is why this hid: it
                    # only looks impossible on a put that WON.
                    # `symbol` is the loop variable from `for pos, venue in
                    # positions_with_venue` (:3484). NOT `_symbol` — that is a
                    # keyword-default parameter of the _async_post_exit closure
                    # defined ~70 lines BELOW here, so referencing it raised
                    # NameError at runtime on the first real exit after this
                    # shipped (NATURALGAS26SEP265PE, 2026-08-24 14:41). The
                    # order had already filled and the P&L was recorded; what
                    # was lost was the autopsy.
                    _is_option = str(symbol or "").upper().endswith(("CE", "PE"))
                    _mfe_pct, _mae_pct = self._excursion_pcts(
                        entry_price=stored_entry_price,
                        peak_price=entry_meta.get("peak_price"),
                        trough_price=entry_meta.get("trough_price"),
                        side="BUY" if _is_option else entry_meta.get("side", "BUY"),
                    )

                    # Record strategy portfolio trade outcome based on registered strategy ID.
                    # Keyed by the UNDERLYING, never the option contract: keying by
                    # contract (CRUDEOIL26JUL7750CE) minted a fresh stats domain for
                    # every strike/expiry, so confidence could never accumulate and
                    # strategies were never comparable on the same axis.
                    # NO PHANTOM DEFAULT. This used to fall back to
                    # "strat-autotrend-equities-v1", an id that exists in
                    # NEITHER portfolio — the same dead id that silently
                    # disabled the ImprovementBot's evolution path for months.
                    # Attributing a real outcome to a strategy that does not
                    # exist is worse than recording nothing: it writes stats
                    # for a ghost and hides that attribution was lost.
                    stored_strategy_id = (
                        entry_meta.get("strategy_id")
                        or getattr(pos, "strategy_id", None)
                    )
                    if not stored_strategy_id:
                        logger.warning(
                            f"No strategy attribution for {symbol}; recording the "
                            f"outcome WITHOUT crediting any strategy rather than "
                            f"guessing one."
                        )
                    outcome_asset = entry_meta.get("underlying") or symbol
                    if stored_strategy_id:
                        self._portfolio_manager_for_strategy(stored_strategy_id).record_trade_outcome(
                            strategy_id=stored_strategy_id,
                            asset=outcome_asset,
                            is_win=is_win,
                            pnl=live_pnl,
                            market_regime=regime_str
                        )

                    # Arm the same-day re-entry cooldown for this underlying:
                    # re-entries are allowed, immediate revenge re-entry is not.
                    self._underlying_exit_cooldowns[str(outcome_asset).upper()] = datetime.now(timezone.utc)

                    # After a TARGET_HIT win, remember the index level where
                    # profit was taken: same-direction re-entry only unlocks
                    # PAST that level (never buy the dip of our own winner —
                    # the 2026-07-17 13:03 re-entry gave back -1,774).
                    if str(exit_reason or "").upper().startswith("TARGET_HIT"):
                        _und_sym = str(outcome_asset).upper()
                        _und_level, _ = self._get_validated_live_price(_und_sym)
                        if _und_level is not None:
                            _dir = self._position_direction(entry_meta)
                            self._target_exit_watermarks[_und_sym] = {
                                "direction": _dir,
                                "level": float(_und_level),
                                "set_at": datetime.now(timezone.utc).isoformat(),
                            }
                            logger.info(
                                f"Re-entry watermark set: {_und_sym} {_dir} unlocks past {_und_level:.2f}."
                            )

                    # --- Layer 1: Journal outcome update ---
                    if stored_decision_id:
                        self.journal.update_decision_outcome(
                            decision_id=stored_decision_id,
                            outcome=outcome_str,
                            pnl=live_pnl,
                            exit_reason=exit_reason,
                            holding_days=held_days,
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
                        _chest_pct=stored_chest_pct,
                        _risk_pct=stored_risk_pct,
                        _exit_reason=exit_reason,
                        _pnl=live_pnl,
                        _return_pct=return_pct,
                        _regime=regime_str,
                        _mfe_pct=_mfe_pct,
                        _mae_pct=_mae_pct,
                        _sector=symbol_sec,
                        _personality=stored_personality,
                        _sector_flow=stored_sector_flow,
                        _result=outcome_str,
                        _held_days=held_days,
                        _held_seconds=held_seconds,
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
                                # The chest fraction, not allocation_pct: see
                                # the note where chest_fraction_pct is stamped.
                                position_size_pct=_chest_pct,
                                # The heat this hold actually took. Entry
                                # quality is graded on this and nothing else.
                                mae_pct=_mae_pct,
                                # The risk whichever stop bites first actually
                                # accepted, frozen at entry.
                                risk_pct=_risk_pct,
                                holding_days=_held_days,
                                holding_seconds=_held_seconds,
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
                                holding_period_days=_held_days,
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
                                holding_time_seconds=_held_seconds,
                                exit_reason=_exit_reason,
                                ml_edge_score_at_entry=_conviction,
                                vix_at_entry=15.0, # Defaulting for now
                                market_regime_at_entry=_regime,
                                # Real excursions measured during the hold. None
                                # (extreme never recorded) stays None so the
                                # Pattern Reader skips the trade instead of
                                # scoring a fabricated flat excursion.
                                max_adverse_excursion_pct=_mae_pct,
                                max_favorable_excursion_pct=_mfe_pct,
                            )
                            if self.orchestrator.improvement_bot:
                                self.orchestrator.improvement_bot.process_autopsy(autopsy)
                            # Telegram exit notification already sent synchronously
                            # right after the fill (see above) — not repeated here.
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

        # BLIND-MONITOR ALARM: positions are open but not one live quote came
        # back this tick. The ladder silently degrades to frozen book prices —
        # exactly the blind-exit disease of 2026-07-16 morning, except caused
        # by a dead feed (expired Kite token, network) instead of a code bug.
        # Escalate ONCE after 3 consecutive blind ticks; never a message storm.
        if positions_with_venue and not marked_to_market:
            self._blind_monitor_ticks = getattr(self, "_blind_monitor_ticks", 0) + 1
            if self._blind_monitor_ticks == 3:
                blind_msg = (
                    f"Exit monitor is BLIND: {len(positions_with_venue)} open position(s) "
                    f"and no live quotes for {self._blind_monitor_ticks} consecutive checks. "
                    f"Premium exits are frozen at book prices — check the Kite session/login."
                )
                logger.critical(blind_msg)
                if self.telegram_bot and self.telegram_bot.enabled:
                    try:
                        self.telegram_bot.send_message(blind_msg)
                    except Exception as exc:
                        logger.error(f"Failed to send blind-monitor alert: {exc}")
        elif marked_to_market:
            self._blind_monitor_ticks = 0

        # Mark the paper book to market with the live prices fetched above, so
        # the dashboard's Net Worth / Today's P&L / positions table stop showing
        # entry-price freezes (Current 124.00 / PnL 0.00 on a -754 position).
        if marked_to_market:
            try:
                from bots.execution.models import TradeStatus

                # EVERY venue holding one of these positions, not just the
                # index book. `paper_venue` is paper_main, account "paper"; the
                # MCX Arena is a SEPARATE venue with account "paper_mcx". This
                # loaded only the former, so every commodity position stayed
                # frozen at its entry price forever.
                #
                # Found 2026-08-18 on a live position: a CRUDEOIL call stored
                # at 454.50 while it genuinely traded at 468.20, hiding +1,370
                # of unrealized P&L. EXITS WERE NEVER AFFECTED — the ladder
                # reads its own freshly fetched live_price, and that same
                # position later closed correctly on TARGET_HIT — but MCX
                # equity, the drift panel and every unrealized number the
                # commander READS are computed from this book.
                #
                # Same shape as the exit-loop venue bug fixed 2026-08-17: the
                # loop was taught about multiple venues, the write-back was not.
                account_ids: list[str] = []
                for _pos, _venue in positions_with_venue:
                    _aid = getattr(_venue, "_account_id", None)
                    if _aid and _aid not in account_ids:
                        account_ids.append(_aid)
                if not account_ids:
                    account_ids = [self.orchestrator.paper_venue._account_id]

                for _account_id in account_ids:
                    account = self.orchestrator.portfolio_store.load_account(_account_id)
                    changed = False
                    for position in account.positions.values():
                        live = marked_to_market.get(position.market)
                        if live is not None and position.status == TradeStatus.OPEN:
                            position.update_price(live)
                            changed = True
                    if changed:
                        self.orchestrator.portfolio_store.save_account(account)
            except Exception as exc:
                logger.error(f"Mark-to-market write-back failed (non-fatal): {exc}")


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
        """Trigger direct broker reconciliation and forcefully flatten unindexed ghost positions.

        LIVE mode only: ghost detection compares the real broker's positions
        against Hokage's own local ledger to catch drift from manual trades
        or crashed order acks — that divergence is only possible against a
        real external broker. In PAPER/HYBRID the "broker" IS the paper
        venue, so it can never disagree with itself; the local ledger this
        function queries (self.orchestrator.portfolio_store, account_id
        "paper") is also a different store than the one the paper venue
        actually persists to, which made every paper position look like an
        unindexed ghost and get force-flattened ~3 minutes after entry,
        before the exit ladder or stop-loss ever got a chance to run.
        """
        try:
            context = self.orchestrator.get_execution_context()
        except Exception:
            return
        if context.execution_mode != ExecutionMode.LIVE:
            return

        logger.info("Direct Broker Sync: Running 180s reconciliation audit for ghost positions...")
        try:
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
                    if self.telegram_bot and self.telegram_bot.enabled:
                        try:
                            self.telegram_bot.notify_exit(
                                symbol, price=0.0,
                                reason=f"Ghost position force-flattened ({b_pos.quantity:g} units, broker/ledger drift)",
                            )
                        except Exception as exc:
                            logger.error(f"Failed to send ghost-flatten notification for {symbol}: {exc}")

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
        """Run Research -> Strategy -> Backtest for a single asset.

        The daily-bar ML verdict and the daily-bar heuristic backtest are
        ADVISORY, never a veto (2026-07-16): both run on yfinance 1d candles —
        wrong granularity for an intraday options league — and their silent
        hard vetoes starved whole sessions (SENSEX: 24 invisible ML skips in
        one day on a static 55.5%; the league modules never saw the asset).
        The league's live-tape entry modules decide entries; these daily views
        travel along as context. Every stand-aside returns a journaled
        ``blocked_reason`` — an asset must never vanish without a reason.
        """
        try:
            # 1. Fetch historical data and engineer features
            from bots.strategy.features import fetch_and_cache_ohlcv, calculate_features
            from bots.strategy.ml_engine import MLEngine

            advisories: list[str] = []
            rec, prob = "neutral", 0.5
            df = fetch_and_cache_ohlcv(symbol, timeframe="1d")
            if df is not None and not df.empty and len(df) >= 20:
                df = calculate_features(df)
                ml_engine = MLEngine()
                rec, prob = ml_engine.get_zone_recommendation(symbol, df)
                if rec == "neutral":
                    advisories.append(
                        f"MLAdvisory: daily-bar model neutral ({prob:.0%} up) — league decides on live tape."
                    )
            else:
                # Doctrine: never fabricate a verdict from missing data. The
                # daily series only feeds the ADVISORY ML view, so its absence
                # is noted, not a stand-aside — the league judges live candles.
                advisories.append(
                    f"MLAdvisory: insufficient daily history for {symbol}; ML view unavailable."
                )
                logger.warning(advisories[-1])

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
            
            # 4. Validate via Backtest — advisory, not a veto. Its real numbers
            # (win rate, profit factor) still feed conviction and ranking.
            backtest_result = self.orchestrator.backtest_bot.validate_strategy(proposal)
            if not backtest_result.passed:
                advisories.append(
                    f"BacktestAdvisory: daily heuristic backtest failed "
                    f"(win_rate={backtest_result.win_rate}, trades={backtest_result.total_trades}) — league decides on live tape."
                )
                logger.info(f"{symbol}: {advisories[-1]}")

            return {
                "proposal": proposal,
                "backtest_result": backtest_result,
                "score": proposal.confidence_score * (backtest_result.win_rate / 100.0),
                "advisories": advisories,
            }
        except Exception as exc:
            logger.error(f"Failed to scan opportunity for {symbol}: {exc}")
            return {"blocked_reason": f"Scan pipeline error for {symbol}: {exc}"}

    #: MCX Arena entry window (commander-approved 2026-07-18): the exchange
    #: itself trades 09:00-23:30 IST; Hokage opens entries at 09:30 (after a
    #: short observation window, same discipline as the index open) and takes
    #: no NEW risk after 22:30, leaving 45 minutes of runway before the
    #: 23:15 square-off already enforced by the option exit ladder.
    _MCX_FIRST_ENTRY = (9, 30)
    _MCX_LAST_ENTRY = (22, 30)

    def _scan_and_enter_mcx_opportunities(self) -> None:
        """MCX Commodity Arena: winner-take-asset entries for CRUDEOIL/
        NATURALGAS/GOLDM/SILVERM, on its own venue, its own war chests, its
        own 4-strategy league. Sibling to `_scan_and_enter_opportunities` —
        deliberately NOT a shared code path: a bug in this method can never
        touch the index Dojo's scan logic. The two leagues DO share the
        hardened lower-level primitives (options router, exit ladder, gate
        journaling, reduce_only) — those are what were tested and fixed
        first, so reusing them here is a feature, not a shortcut.
        """
        from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES
        from bots.strategy.mcx_portfolio import MCX_UNIVERSE, MCX_FAMILY_ENERGY, MCX_FAMILY_PRECIOUS
        from bots.execution.options_router import OptionsRouter, OptionsRoutingError
        from integrations.brokers.models import OrderRequest, OrderSide, OrderType
        from integrations.data.models import Instrument
        from hokage.dashboard.event_bus import EventBus

        context = self.orchestrator.get_execution_context()
        if context.execution_mode == ExecutionMode.READ_ONLY:
            return

        now_ist = self._now_ist()
        # Weekday guard: MCX runs Monday-Friday, EXCEPT on a special session.
        # Diwali Muhurat trading is a Sunday, and `weekday() >= 5` would have
        # returned before the entry window was even looked at.
        special_window = self._special_window_today("MCX")
        if now_ist.weekday() >= 5 and special_window is None:
            return
        hm = (now_ist.hour, now_ist.minute)
        if special_window is not None:
            # The published hours REPLACE the usual 09:30-22:30 window. On
            # 2026-11-08 that is 14:20-15:30, so the normal window would both
            # open five hours early and stay open seven hours after the close.
            start, end = special_window
            if not ((start.hour, start.minute) <= hm < (end.hour, end.minute)):
                return
        elif hm < self._MCX_FIRST_ENTRY or hm >= self._MCX_LAST_ENTRY:
            return

        venue = getattr(self.orchestrator, "mcx_venue", None)
        if venue is None:
            return

        try:
            bal = venue.get_account_balance()
            if bal.cash <= 1000.0:
                return
        except Exception as exc:
            logger.error(f"MCX Arena: failed to query account balance: {exc}")
            return

        # Skip underlyings that already have an open MCX position (dedup by
        # underlying, same discipline as the index league).
        existing_underlyings: set[str] = set()
        for trk in self._active_positions_tracking.values():
            if trk.get("venue_id") == "paper_mcx":
                und = str(trk.get("underlying") or "").upper()
                if und:
                    existing_underlyings.add(und)

        bus = EventBus()
        _ctx_cache: dict[str, Any] = {}

        for symbol in MCX_UNIVERSE:
            if symbol in existing_underlyings:
                continue
            # A standing decision, already announced at boot with its reason.
            # Re-deciding it every cycle only buries the decisions that matter.
            if self.is_parked(symbol):
                logger.debug(f"MCX Arena: {symbol} is parked; not scanned.")
                continue
            if not self.orchestrator.session_manager.is_tradable(symbol):
                continue

            # Post-exit re-entry cooldown (shared dict with the index league;
            # MCX underlyings are distinct strings, no collision risk).
            exited_at = self._underlying_exit_cooldowns.get(symbol)
            if exited_at is not None:
                elapsed_min = (datetime.now(timezone.utc) - exited_at).total_seconds() / 60.0
                if elapsed_min < self._REENTRY_COOLDOWN_MINUTES:
                    logger.info(
                        f"MCX Arena: {symbol} re-entry cooldown, "
                        f"{self._REENTRY_COOLDOWN_MINUTES - elapsed_min:.0f}m remaining."
                    )
                    continue

            mkt_ctx = self._build_market_context(symbol, cache=_ctx_cache)
            if mkt_ctx is None:
                logger.info(self._note_context_miss(symbol))
                continue
            self._clear_context_miss(symbol)

            module_verdicts: list[str] = []
            #: The same verdicts, kept as DATA rather than as a log sentence,
            #: so the losing side of the mirror experiment can be scored. See
            #: hokage.memory.signal_archive for why the loser cannot simply be
            #: filled instead.
            scan_verdicts: list[tuple] = []
            winner = None  # (rank_key, confidence, strategy_dict, signal)
            out_of_scope: list[str] = []
            scoped_count = 0
            # A SCOPE IS CONFIGURATION, NOT A VERDICT.
            #
            # This used to append "{name}: not scoped to {symbol}." to the
            # journal on every pass. On 2026-10-13 that was 19 of 98 entries,
            # all of them "MeanReversion: not scoped to BANKNIFTY" - and
            # MeanReversion is scoped to NIFTY and SENSEX by deliberate
            # decision, so the answer could not change between cycles. 19% of
            # the day's record restating a settled choice, which is the same
            # defect as the parked-asset lines removed a day earlier: it buries
            # the entries that carry information.
            #
            # Quiet, never invisible. audit_asset_coverage still names every
            # asset and its strategies once per boot, and if a symbol reaches
            # this loop with nothing scoped to it, the no-trade reason says so
            # explicitly below - "ceasing to trade an asset silently is a worse
            # failure than trading it badly".
            for sid, strat in self.mcx_strategy_portfolio.portfolio.get("strategies", {}).items():
                if strat.get("status") == "ARCHIVED":
                    continue
                if not self._strategy_supports(strat, symbol):
                    out_of_scope.append(str(strat.get("name", sid)))
                    continue
                scoped_count += 1
                module = MCX_ENTRY_MODULES.get(sid)
                if module is None:
                    continue
                sig = module.evaluate(mkt_ctx)
                scan_verdicts.append((sid, getattr(module, "module_id", None), sig))
                if not sig.should_enter:
                    module_verdicts.append(f"EntrySignal: {strat.get('name', sid)}: {sig.reason}")
                    continue
                conf = float(sig.confidence or 0.0)
                module_verdicts.append(f"EntrySignal: {strat.get('name', sid)}: {sig.direction.upper()} (conf {conf:.0f})")
                rank = self._auction_key(conf, sid, module)
                if winner is None or rank < winner[0]:
                    winner = (rank, conf, strat, sig)

            if winner is None:
                # A NO-TRADE WITH NO REASON IS WORSE THAN A NOISY ONE.
                # Dropping the scope lines above can empty this list, and an
                # empty reason reads as "nothing was even considered". Say
                # which of the two it was, by name.
                if not module_verdicts:
                    module_verdicts.append(self._no_verdict_reason(
                        symbol, scoped_count, out_of_scope))
                reason_txt = "MCX league stand-aside on " + symbol + ": " + " | ".join(module_verdicts)
                logger.info(reason_txt)
                # THE REFUSALS ARE PART OF THE DENOMINATOR. A module that
                # stands aside ninety-nine times in a hundred has a different
                # character from one that fires constantly, and an archive of
                # only the fires cannot tell them apart.
                self._archive_scan(symbol, scan_verdicts, None, mkt_ctx)
                bus.publish("OPPORTUNITY_REJECTED", {"symbol": symbol, "reason": reason_txt, "timestamp": datetime.now(timezone.utc).isoformat()})
                self._journal_no_trade(symbol, module_verdicts)
                continue

            _rank, win_conf, selected_strat, signal = winner
            direction = signal.direction
            # Resolved ONCE here, because everything downstream — the order's
            # attribution, the war chest, the fill stamp, the position record
            # — used to subscript it straight off the record.
            selected_sid = self._resolve_strategy_id(
                selected_strat,
                self.mcx_strategy_portfolio.portfolio.get("strategies", {}),
            )
            if not selected_sid:
                logger.error(
                    "MCX Arena: %s won the auction for %s but its record "
                    "cannot say what it is called, and an unknown id draws a "
                    "FULL FRESH CHEST rather than its real balance. Standing "
                    "aside — the boot audit names the record to repair.",
                    selected_strat.get("name"), symbol,
                )
                self._journal_no_trade(
                    symbol, ["winning strategy record carries no id"]
                )
                continue
            logger.info(
                f"MCX league entry for {symbol}: {selected_strat.get('name')} wins with "
                f"{direction.upper()} (conf {win_conf:.0f}) — {signal.reason}. Field: {' | '.join(module_verdicts)}"
            )
            # BEFORE the conduct gate on purpose. Winning is not filling - the
            # bias veto, correlation cap, IV guard and affordability all still
            # stand between here and an order, and on 2026-10-26 the gas winner
            # was blocked by "underlying tape is MIXED" after winning. The row
            # records the SIGNAL; mark_filled records what became of it.
            _scan_stamp = self._archive_scan(
                symbol, scan_verdicts, selected_sid, mkt_ctx)

            # Entry conduct gate (bias alignment + IV premium guard) is
            # universe-agnostic and already MCX-aware for its NSE-only time
            # windows (skipped for MCX symbols there) — reused as-is.
            conduct_ok, conduct_reason = self._entry_conduct_gate(
                symbol, direction,
                counter_trend=self._is_counter_trend_strategy(selected_sid),
            )
            if not conduct_ok:
                logger.info(f"MCX Arena entry blocked for {symbol}: {conduct_reason}")
                self._journal_no_trade(symbol, [conduct_reason])
                # THE ONLY RECORD THIS REFUSAL WILL EVER LEAVE IN PREMIUM.
                # The journal row says the gate said no; nothing prices what
                # it said no TO, so the gate has never been scored in the
                # units Hokage trades. Written after the journal, so an
                # experiment cannot cost the decision its audit row.
                self._start_shadow_path(symbol, _scan_stamp, conduct_reason)
                continue

            try:
                entry_price = self.orchestrator.price_source.get_price(symbol)
                valid_price = isinstance(entry_price, (int, float)) and entry_price > 0.0
            except Exception:
                entry_price, valid_price = 0.0, False
            if not valid_price:
                logger.info(f"MCX Arena: no valid live price for {symbol}; standing aside.")
                continue

            # Correlation cap: ENERGY (crude/natgas) and PRECIOUS (gold/silver
            # minis) are separate families with independent drivers — same
            # discipline as the index family cap, applied to the right family.
            # Caps are set from MEASURED correlation of hourly returns
            # (2026-06-01 to 2026-08-05, 711 aligned bars), not from how the
            # commodities are grouped in a catalogue:
            #     GOLDM vs SILVERM    +0.87   -> effectively ONE instrument
            #     CRUDEOIL vs NATGAS  +0.20   -> barely related
            #     metals vs crude     -0.26   -> mildly OPPOSED
            # So PRECIOUS is capped at 1: on 2026-08-05 Hokage held GOLDM and
            # SILVERM calls simultaneously and they lost -4,325 and -2,917 in
            # the same 24 minutes, which is one bet paid for twice. ENERGY keeps
            # 2 because 0.20 is genuine diversification.
            if symbol in MCX_FAMILY_ENERGY:
                family, label, cap = MCX_FAMILY_ENERGY, "ENERGY", 2
            elif symbol in MCX_FAMILY_PRECIOUS:
                family, label, cap = MCX_FAMILY_PRECIOUS, "PRECIOUS(corr 0.87)", 1
            else:
                family, label, cap = set(), "unclassified", 2
            cluster_ok, cluster_reason = self._entry_cluster_gate(
                symbol, direction, entry_price, family=family, max_same_direction=cap, family_label=label,
                counter_trend=self._is_counter_trend_strategy(selected_sid),
            )
            if not cluster_ok:
                logger.info(f"MCX Arena entry blocked for {symbol}: {cluster_reason}")
                self._journal_no_trade(symbol, [cluster_reason])
                continue

            side = OrderSide.BUY if direction == "long" else OrderSide.SELL
            resolved_ac = self.orchestrator.session_manager.resolve_asset_class(symbol)
            # DAILY CHURN CAP. The MCX path called record_trade() but never
            # is_entry_allowed(), so it COUNTED entries against the cap and then
            # ignored the count: the index league was capped at 3 entries per
            # symbol and 5 unique symbols a day, the commodity league at
            # nothing. Found 2026-08-18, when SessionShift entered SILVERM three
            # times in one evening and lost twice in a row, the second trade
            # lasting two minutes. The cap's own docstring is the reason it
            # exists: "churn on one symbol is revenge trading, not data
            # collection."
            #
            # Ahead of the OrderRequest, so a blocked entry builds nothing,
            # routes nothing, and leaves no half-state behind.
            # NO ENTRY WITHOUT THE NUMBER THAT STOPS IT.
            #
            # The underlying thesis stop is 1.25 x ATR and is the exit that has
            # fired more often than any other in Hokage's history — on the
            # illiquid SILVERM of 2026-08-24 it was the ONLY one that could see
            # anything at all. ATR was fetched AFTER the fill, purely for
            # tracking, so a failed fetch produced a position whose main stop
            # could not be computed.
            #
            # 2026-08-25 19:00:49 a Kite rate limit failed GOLDM's ATR, and one
            # second later Hokage entered GOLDM. Checked BEFORE the order now,
            # so a missing ATR costs an entry rather than a stop.
            _entry_atr = self._get_atr_for_symbol(symbol)
            if not _entry_atr or _entry_atr <= 0:
                logger.warning(
                    f"MCX Arena: entry for {symbol} stood down — ATR unavailable, "
                    f"so the 1.25x ATR thesis stop cannot be sized. A position "
                    f"without its main stop is not a position worth opening."
                )
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": "NoATR: thesis stop cannot be sized",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                continue

            _playbook_id = f"MCX_{selected_strat['name']}"
            _allowed, _cap_reason = self.strategy_engine.is_entry_allowed(
                _playbook_id, symbol, now_ist.strftime("%Y-%m-%d")
            )
            if not _allowed:
                logger.warning(f"MCX Arena: entry for {symbol} blocked. {_cap_reason}")
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"DailyCap: {_cap_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                continue

            resolved_exch = self.orchestrator.session_manager.resolve_exchange(symbol)
            inst = Instrument(symbol=symbol, asset_class=resolved_ac, exchange=resolved_exch)
            req = OrderRequest(
                instrument=inst, side=side, quantity=1.0, order_type=OrderType.MARKET,
                venue_id=venue.venue_id, strategy_id=selected_sid,
                execution_reason=f"MCX Arena: {selected_strat.get('name')} {direction} — {signal.reason}",
                # Carried so the position records WHICH playbook opened it. The
                # index path has always set this; MCX never did, leaving all 42
                # commodity positions with playbook_id NULL and the boot-time
                # cap recovery nothing to match on.
                playbook_id=_playbook_id,
            )

            if not OptionsRouter.routes(symbol):
                logger.warning(f"MCX Arena: {symbol} is not options-routed; skipping (never trade spot/futures).")
                continue
            try:
                cash_for_premium = float(venue.get_account_balance().cash)
            except Exception:
                cash_for_premium = None
            chest_budget = self._strategy_available_capital(selected_sid)

            try:
                opt_router = OptionsRouter(price_source=self.orchestrator.price_source)
                req = opt_router.route_to_options(
                    req, current_price=entry_price, available_cash=cash_for_premium, risk_budget=chest_budget,
                )
            except OptionsRoutingError as e:
                logger.warning(f"MCX Arena: options routing blocked entry for {symbol}: {e}")
                bus.publish("OPPORTUNITY_REJECTED", {"symbol": symbol, "reason": f"OptionsRouter: {e}", "timestamp": datetime.now(timezone.utc).isoformat()})
                continue

            req_meta = req.instrument.metadata or {}
            entry_cost = float(req_meta.get("premium_at_entry", entry_price)) * float(req.quantity)
            if entry_cost > chest_budget:
                logger.warning(
                    f"MCX Arena: war chest exhausted for {selected_sid}: "
                    f"entry cost Rs{entry_cost:,.0f} exceeds remaining Rs{chest_budget:,.0f}."
                )
                continue

            try:
                resp = venue.place_order(req)
            except Exception as e:
                logger.error(f"MCX Arena: exception during place_order for {symbol}: {e}")
                resp = None
            if resp is None:
                logger.warning(f"MCX Arena: order for {symbol} returned None; skipping tracking.")
                continue
            if str(getattr(resp, "status", "")).upper() in ("REJECTED", "CANCELLED", "ERROR", "FAILED"):
                logger.error(f"MCX Arena: order for {symbol} REJECTED: {getattr(resp, 'error_message', 'unknown')}")
                continue

            # THE SIGNAL BECAME A POSITION. Winning the auction did not
            # guarantee this - the bias veto, correlation cap, IV guard and
            # affordability all sit between the two - so the archive keeps
            # them as separate facts.
            try:
                from hokage.memory import signal_archive
                if _scan_stamp:
                    signal_archive.mark_filled(
                        symbol, selected_sid, _scan_stamp, True)
            except Exception as exc:
                logger.debug(f"Could not stamp the fill for {symbol}: {exc}")

            qty_filled = getattr(resp, "filled_quantity", req.quantity) or req.quantity
            tracked_symbol = req.instrument.symbol
            tracked_entry_price = float(req_meta.get("premium_at_entry", entry_price))
            entry_und_atr = _entry_atr
            # The SAME target the exit ladder will use, not entry * 1.10. The
            # alert quotes this, so the two can no longer disagree.
            _target, _target_adaptive = self._seed_target_price(
                tracked_entry_price, symbol, float(entry_price),
                entry_und_atr, selected_sid,
            )

            self.strategy_engine.record_trade(_playbook_id, symbol, now_ist.strftime("%Y-%m-%d"))

            self._active_positions_tracking[tracked_symbol] = {
                "entry_price": tracked_entry_price,
                "peak_price": tracked_entry_price,
                # A BOUGHT OPTION IS ALWAYS LONG ITS PREMIUM, CALL OR PUT.
                #
                # `side` here is the UNDERLYING SIGNAL's direction — SELL for a
                # bearish call that the router turns into BUY A PUT — the same
                # root cause as the inverted put excursions fixed 2026-08-22.
                # Seeding off it put the protective floor 5% ABOVE entry on
                # every put, which is a ceiling, not a stop. Worse, the floor
                # only ever RISES, so that seeded value out-ranked the real
                # rungs: on 2026-08-25 it fired twice, and the log claimed the
                # breakeven floor had held while 1.05x entry did the work.
                #
                #   SILVERM26SEP245000PE  entry 6839.50  floor fired 7181.48
                #   GOLDM26AUG161000PE    entry 1664.00  floor fired 1747.20
                #
                # Both were wins, which is luck of direction — the same seeding
                # on a trade that dipped to +4% before running would cut a
                # winner off at the knees.
                "stop_price": tracked_entry_price * (1.0 - self.tsl_percent),
                # The risk actually accepted, frozen. "stop_price"
                # above is a LIVE floor the ladder ratchets to
                # break-even and beyond; reading it after the fact
                # measures nothing. See _compute_rr_achieved.
                "initial_stop_price": tracked_entry_price * (1.0 - self.tsl_percent),
                "target_price": _target,
                # False means the TARGET_HIT rung cannot fire for this
                # position, so the alert must not call the stored figure a
                # target. See _seed_target_price.
                "target_is_adaptive": _target_adaptive,
                "decision_id": f"mcx-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                # THE OPPOSITE OPTION, so it can be priced for as long as this
                # position lives. The mirror never fills, so its contract had
                # exactly one price in the whole brain - what it cost at the
                # instant it was proposed - and one number is not a round
                # trip. Plain str/float only: this dict is json.dump'ed to
                # active_positions.json on every tick. See mirror_path.
                "mirror_leg": self._opposing_leg_for(
                    symbol, _scan_stamp, tracked_symbol),
                "strategy_id": selected_sid,
                "conviction_score": int(win_conf),
                # What the sizing grade is measured against. See
                # _chest_fraction_pct: this path never recorded a size at all,
                # so the review fabricated one and graded every commodity
                # trade CORRECT.
                "chest_fraction_pct": self._chest_fraction_pct(
                    selected_sid, tracked_entry_price, qty_filled
                ),
                # What the stop grade is measured against. See the manual path.
                "risk_pct_at_entry": self._risk_pct_for(
                    tracked_entry_price, float(entry_price), _entry_atr,
                    selected_sid, symbol,
                ),
                "side": side.value,
                "quantity": float(qty_filled),
                "venue_id": venue.venue_id,
                "underlying": symbol,
                "entry_timestamp": datetime.now(timezone.utc).isoformat(),
                "entry_underlying_price": float(entry_price),
                "entry_underlying_atr": float(entry_und_atr) if entry_und_atr else None,
                "lot_size": req_meta.get("lot_size"),
                "option_type": req_meta.get("option_type"),
                "strike": req_meta.get("strike"),
                "expiry": req_meta.get("expiry"),
            }
            self._save_positions_tracking()

            if self.telegram_bot and self.telegram_bot.enabled:
                try:
                    _track = self._active_positions_tracking[tracked_symbol]
                    self.telegram_bot.notify_entry(
                        symbol=tracked_symbol, cmp=tracked_entry_price,
                        target=_track["target_price"],
                        target_adaptive=_track.get("target_is_adaptive"),
                        edge=win_conf,
                        strategy=self._strategy_display_name(_track.get("strategy_id")),
                        context=self._trade_context(
                            tracked_symbol, _track, side="entry",
                            premium=tracked_entry_price,
                            target=_track["target_price"], edge=win_conf,
                        ),
                    )
                except Exception:
                    pass
            bus.publish("EXECUTION_COMPLETED", {
                "symbol": symbol, "side": side.value, "quantity": qty_filled,
                "price": tracked_entry_price, "status": "SUCCESS", "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def _scan_and_enter_opportunities(self) -> None:
        """Scan watchlist/market universe for opportunities, rank, size and place entry orders."""
        from bots.strategy.components.entries import ENTRY_MODULES

        # Live market context, built once per symbol per scan and shared by the
        # champion's entry module below — the same cache discipline the shadow
        # loop uses, so champion and challengers judge identical candles.
        _ctx_cache: dict[str, Any] = {}

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

        # The opening bell is not always 09:15. A special session has its own
        # open - Muhurat trading starts at 14:20 - and a window hardcoded to
        # 09:15-09:30 simply does not apply, so Hokage would enter from the
        # first tick of the noisiest fifteen minutes of a thin 80-minute
        # session. The window follows the session's real open instead.
        _obs_open, _obs_end = dt_time(9, 15), dt_time(9, 30)
        _special_window = self._special_window_today("NSE")
        if _special_window is not None:
            _obs_open = _special_window[0]
            _obs_end = (datetime.combine(ist_now.date(), _obs_open)
                        + timedelta(minutes=15)).time()
        is_observation_window = _obs_open <= ist_now.time() < _obs_end



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

        # Option positions live under the CONTRACT symbol (NIFTY2672124150CE)
        # while the scan iterates UNDERLYINGs (NIFTY) — a bare symbol match
        # never blocked a duplicate entry on an underlying with an open option.
        # The old once-per-day playbook rule masked that hole; with same-day
        # re-entries now allowed, map every open tracked position back to its
        # underlying and exclude those from the scan.
        for trk in self._active_positions_tracking.values():
            und = str(trk.get("underlying") or "").upper()
            if und:
                existing_symbols.add(und)

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

        # Tracking evaluations to update states. Initialized BEFORE the
        # day-of-week filter below: that filter journals blocked symbols into
        # eval_results, and on weekends every equity/index symbol is blocked —
        # referencing it before assignment crashed every Saturday/Sunday scan
        # with UnboundLocalError (latent since the filter was added; the test
        # suite only caught it the first time it ran on a Saturday).
        eval_results = {}

        # Day-of-Week Isolator Filter. Weekday comes from the injectable clock
        # seam so tests can pin a weekday instead of inheriting the wall clock.
        ist_now = self._now_ist()
        weekday = ist_now.weekday() # 0 = Monday, 6 = Sunday
        
        # A SPECIAL SESSION IS NOT A WEEKEND. This filter is the last gate
        # before the scan, and on a Sunday it blocks every index, equity and
        # commodity symbol - so Diwali Muhurat trading would have been a
        # no-op even with the session manager reporting OPEN. The per-exchange
        # hours are already enforced upstream by `is_tradable`, which is why
        # this can simply allow the weekday list once the day is a session.
        special_today = self._special_session_today()
        if 0 <= weekday <= 4 or special_today is not None:
            allowed_sectors = ["index", "it", "energy", "banking", "fintech", "defence", "us_tech", "commodity"]
            if special_today is not None and weekday >= 5:
                day_desc = f"Special session ({special_today['name']}) - normal universe"
            else:
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

        # (eval_results is initialized above the day-of-week filter — a second
        # init here would silently wipe the day-filter's journaled blocks.)

        # Add observation blocked symbols to eval results early
        for s in observation_blocked:
            obs_reason = (
                "Opening Bell Observation Protocol: Prohibited from executing entry orders"
                f" until {_obs_end.strftime('%H:%M')} IST.")
            eval_results[s] = {
                "state": "NO_TRADE",
                "blockers": [obs_reason],
                "confirmations": [],
                "conviction": 0,
                "risk": 0.0,
                "reasons": [obs_reason]
            }

        # Post-exit re-entry cooldown: an underlying that just exited stands
        # down before it may be re-entered — journaled, never silent.
        _cooldown_ok: list[str] = []
        for s in symbols_to_scan:
            _exited_at = self._underlying_exit_cooldowns.get(s)
            _remaining_min = None
            if _exited_at is not None:
                _elapsed = (datetime.now(timezone.utc) - _exited_at).total_seconds() / 60.0
                if _elapsed < self._REENTRY_COOLDOWN_MINUTES:
                    _remaining_min = self._REENTRY_COOLDOWN_MINUTES - _elapsed
            if _remaining_min is None:
                _cooldown_ok.append(s)
                continue
            cd_reason = (
                f"Re-entry cooldown: {s} exited {int(round(_elapsed))}m ago; "
                f"standing down another {int(round(_remaining_min))}m before re-entry."
            )
            logger.info(cd_reason)
            eval_results[s] = {
                "state": "NO_TRADE",
                "blockers": [cd_reason],
                "confirmations": [],
                "conviction": 0,
                "risk": 0.0,
                "reasons": [cd_reason],
            }
        symbols_to_scan = _cooldown_ok

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
                    if res is not None and "blocked_reason" in res:
                        # A stand-aside with its reason — journal it so the
                        # gate tally sees it (ML skips used to vanish here).
                        blocked_reason = res["blocked_reason"]
                        eval_results[symbol] = {
                            "state": "NO_TRADE",
                            "blockers": [blocked_reason],
                            "confirmations": [],
                            "conviction": 0,
                            "risk": 0.0,
                            "reasons": [blocked_reason],
                        }
                        bus.publish("OPPORTUNITY_REJECTED", {
                            "symbol": symbol,
                            "reason": blocked_reason,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                    elif res is not None:
                        for _adv in res.get("advisories", []):
                            logger.info(f"{symbol}: {_adv}")
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
            _volume_ctx_for_winner = vol_ctx  # re-checked once the league picks
            if vol_ctx is None:
                logger.info(f"Volume context unavailable for {symbol}; skipping volume gate (no fabricated volumes).")
                is_vol_valid, vol_reason = True, "volume data unavailable; gate skipped"
            else:
                current_vol, avg_vol = vol_ctx
                # PRE-LEAGUE, so nobody knows yet which module will trade this
                # symbol. Hold it only to the DEAD-TAPE FLOOR here; the
                # family-specific surge demand is applied after the league
                # names a winner, against that winner's own family. Rejecting a
                # symbol early on a threshold borrowed from a strategy that has
                # not won is how MeanReversion lost 242 entries it qualified for.
                is_vol_valid, vol_reason = self.volume_engine.validate_breakout(
                    current_vol, avg_vol, entry_family="trend"
                )
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
            # Same reason as the MCX path: resolved once, and an unresolvable
            # record stands aside rather than drawing a fresh chest.
            selected_sid = self._resolve_strategy_id(
                selected_strat,
                self.strategy_portfolio.portfolio.get("strategies", {}),
            )
            if not selected_sid:
                logger.error(
                    "Index Dojo: %s was selected for %s but its record cannot "
                    "say what it is called, and an unknown id draws a FULL "
                    "FRESH CHEST rather than its real balance. Standing aside "
                    "— the boot audit names the record to repair.",
                    selected_strat.get("name"), symbol,
                )
                continue
            logger.info(selection_res["reason"])
            bus.publish("STRATEGY_COMPLETED", {
                "symbol": symbol,
                "strategy_id": selected_sid,
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
            self.committee_ledger.record_decision(decision_id, selected_sid, symbol, committee_decision)
            
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

                # ONE LEAGUE — winner-take-asset (commander directive
                # 2026-07-16: "stop this nonsense of shadow and live; it's all
                # paper"). EVERY registered strategy judges this asset's live
                # tape through its own entry module; among those that fire, the
                # most confident signal takes the REAL paper trade with ITS
                # war chest and ITS name on the position. Status (ACTIVE /
                # SHADOW_MODE) no longer decides who may trade paper — it only
                # marks the promotion track toward real cash. The stale
                # daily-bar ML verdict (yfinance 1d, frozen intraday) never
                # decides direction; the winning module's live-tape signal does.
                _mkt_ctx = self._build_market_context(symbol, cache=_ctx_cache)
                if _mkt_ctx is None:
                    logger.info(
                        f"Entry skipped for {symbol}: no live market context "
                        f"(insufficient candles). Standing aside, never a stale signal."
                    )
                    continue
                _module_verdicts: list[str] = []
                _winner = None  # (confidence, strategy_dict, signal)
                _out_of_scope: list[str] = []
                _scoped_count = 0
                # A SCOPE IS CONFIGURATION, NOT A VERDICT.
                #
                # This used to append "{name}: not scoped to {symbol}." to the
                # journal on every pass. On 2026-10-13 that was 19 of 98 entries,
                # all of them "MeanReversion: not scoped to BANKNIFTY" - and
                # MeanReversion is scoped to NIFTY and SENSEX by deliberate
                # decision, so the answer could not change between cycles. 19% of
                # the day's record restating a settled choice, which is the same
                # defect as the parked-asset lines removed a day earlier: it buries
                # the entries that carry information.
                #
                # Quiet, never invisible. audit_asset_coverage still names every
                # asset and its strategies once per boot, and if a symbol reaches
                # this loop with nothing scoped to it, the no-trade reason says so
                # explicitly below - "ceasing to trade an asset silently is a worse
                # failure than trading it badly".
                for _sid, _strat in self.strategy_portfolio.portfolio.get("strategies", {}).items():
                    if _strat.get("status") == "ARCHIVED":
                        continue
                    if not self._strategy_supports(_strat, symbol):
                        _out_of_scope.append(str(_strat.get("name", _sid)))
                        continue
                    _scoped_count += 1
                    _module = ENTRY_MODULES.get(_sid)
                    if _module is None:
                        continue
                    _sig = _module.evaluate(_mkt_ctx)
                    if not _sig.should_enter:
                        _module_verdicts.append(f"EntrySignal: {_strat.get('name', _sid)}: {_sig.reason}")
                        continue
                    _conf = float(_sig.confidence or 0.0)
                    _module_verdicts.append(
                        f"EntrySignal: {_strat.get('name', _sid)}: {_sig.direction.upper()} (conf {_conf:.0f})"
                    )
                    if _winner is None or _conf > _winner[0]:
                        _winner = (_conf, _strat, _sig)

                if _winner is None:
                    # Same rail as the MCX loop: see _no_verdict_reason.
                    if not _module_verdicts:
                        _module_verdicts.append(self._no_verdict_reason(
                            symbol, _scoped_count, _out_of_scope))
                    reason_txt = "League stand-aside on " + symbol + ": " + " | ".join(_module_verdicts)
                    logger.info(reason_txt)
                    eval_results[symbol] = {
                        "state": "NO_TRADE",
                        "blockers": _module_verdicts,
                        "confirmations": [],
                        "conviction": int(committee_decision.decision_confidence),
                        "risk": 0.0,
                        "reasons": _module_verdicts,
                        "proposal_name": proposal.name,
                    }
                    continue

                _win_conf, selected_strat, _signal = _winner

                # NOW the family is knowable, so ask the volume question of the
                # module that actually won. A breakout winner must still show
                # the surge; a mean-reversion winner never had to and no longer
                # inherits the demand from a rival it just beat.
                if _volume_ctx_for_winner is not None:
                    _cur_vol, _avg_vol = _volume_ctx_for_winner
                    _fam = self._entry_family_of(selected_strat.get("name"))
                    _fam_ok, _fam_reason = self.volume_engine.validate_breakout(
                        _cur_vol, _avg_vol, entry_family=_fam
                    )
                    if not _fam_ok:
                        logger.info(
                            f"League entry for {symbol} refused after the auction: "
                            f"{selected_strat.get('name')} is a {_fam} entry and "
                            f"{_fam_reason}"
                        )
                        eval_results[symbol] = {
                            "state": "NO_TRADE",
                            "blockers": [f"VolumeEngine: {_fam_reason}"],
                            "confirmations": [],
                            "conviction": int(committee_decision.decision_confidence),
                            "risk": 0.0,
                            "reasons": [f"VolumeEngine: {_fam_reason}"],
                            "proposal_name": proposal.name,
                        }
                        bus.publish("OPPORTUNITY_REJECTED", {
                            "symbol": symbol,
                            "reason": f"VolumeEngine: {_fam_reason}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        continue

                logger.info(
                    f"League entry for {symbol}: {selected_strat.get('name')} wins with "
                    f"{_signal.direction.upper()} (conf {_win_conf:.0f}) — {_signal.reason}. "
                    f"Field: {' | '.join(_module_verdicts)}"
                )
                original_entry = _signal.direction
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
                conduct_ok, conduct_reason = self._entry_conduct_gate(
                    symbol, original_entry,
                    counter_trend=self._is_counter_trend_strategy(selected_sid),
                )
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

                # Portfolio-level cluster gates: correlation cap across the
                # index family + post-win re-entry watermark (2026-07-17:
                # three simultaneous same-direction CE = one bet tripled).
                cluster_ok, cluster_reason = self._entry_cluster_gate(
                    symbol, original_entry, entry_price,
                    counter_trend=self._is_counter_trend_strategy(selected_sid),
                )
                if not cluster_ok:
                    logger.info(f"Entry blocked for {symbol}: {cluster_reason}")
                    eval_results[symbol] = {
                        "state": "NO_TRADE",
                        "blockers": [cluster_reason],
                        "confirmations": [],
                        "conviction": int(committee_decision.decision_confidence),
                        "risk": 0.0,
                        "reasons": [cluster_reason],
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
                        # The strategy's remaining war chest is the rupee risk
                        # budget the router sizes lots from — an exhausted chest
                        # skips the trade at the sizing seam instead of the
                        # router buying a lot the risk framework never funded.
                        _chest_budget = self._strategy_available_capital(selected_sid)
                        opt_router = OptionsRouter(price_source=self.orchestrator.price_source)
                        req = opt_router.route_to_options(
                            req,
                            current_price=entry_price,
                            available_cash=cash_for_premium,
                            risk_budget=_chest_budget,
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

                # Strategy war chest gate: each strategy competes with its own
                # paper capital. Entry cost (option premium * lots, or notional
                # for non-option instruments) must fit the strategy's remaining
                # balance, or the entry is refused and journaled.
                _entry_meta = req.instrument.metadata or {}
                if _entry_meta.get("is_option"):
                    entry_cost = float(_entry_meta.get("premium_at_entry", entry_price)) * float(req.quantity)
                else:
                    entry_cost = float(entry_price) * float(req.quantity)
                _strat_id_for_chest = selected_sid
                available_chest = self._strategy_available_capital(_strat_id_for_chest)
                if entry_cost > available_chest:
                    chest_reason = (
                        f"War chest exhausted for {selected_sid}: entry cost "
                        f"₹{entry_cost:,.0f} exceeds remaining ₹{available_chest:,.0f}."
                    )
                    logger.warning(chest_reason)
                    bus.publish("OPPORTUNITY_REJECTED", {
                        "symbol": symbol,
                        "reason": chest_reason,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    eval_results[symbol] = {
                        "state": "NO_TRADE",
                        "blockers": [chest_reason],
                        "confirmations": [],
                        "conviction": int(committee_decision.decision_confidence),
                        "risk": 0.0,
                        "reasons": [chest_reason],
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
                # Only the option ladder has an adaptive target; a non-option
                # entry keeps the percentage take-profit, and says so.
                _target = round(tracked_entry_price * (1.0 + self.tp_percent), 2)
                _target_adaptive = False
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
                        # What the stop grade is measured against. Stamped
                        # inside the option block because the ATR it needs is
                        # only fetched for an option-routed entry.
                        "risk_pct_at_entry": self._risk_pct_for(
                            tracked_entry_price, float(entry_price),
                            entry_und_atr, selected_sid, symbol,
                        ),
                        "lot_size": req_meta.get("lot_size"),
                        "option_type": req_meta.get("option_type"),
                        "strike": req_meta.get("strike"),
                        "expiry": req_meta.get("expiry"),
                    }
                    # The SAME target the exit ladder will use. Computed here,
                    # after tracked_entry_price has become the premium.
                    _target, _target_adaptive = self._seed_target_price(
                        tracked_entry_price, symbol, float(entry_price),
                        entry_und_atr, selected_sid,
                    )

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
                    # Bought option, always long the premium — see the note on
                    # the MCX path. Never seed the floor above entry.
                    "stop_price": tracked_entry_price * (1.0 - self.tsl_percent),
                    # The risk actually accepted, frozen. "stop_price"
                    # above is a LIVE floor the ladder ratchets to
                    # break-even and beyond; reading it after the fact
                    # measures nothing. See _compute_rr_achieved.
                    "initial_stop_price": tracked_entry_price * (1.0 - self.tsl_percent),
                    "target_price": _target,
                    # False means the TARGET_HIT rung cannot fire for this
                    # position, so the alert must not call the stored figure a
                    # target. See _seed_target_price.
                    "target_is_adaptive": _target_adaptive,
                    "decision_id": decision_id,
                    "strategy_id": selected_sid,
                    "conviction_score": int(committee_decision.decision_confidence),
                    "allocation_pct": alloc_pct,
                    # NOT allocation_pct. That is a percentage of TOTAL
                    # capital, this is a percentage of the strategy's own war
                    # chest, and only the second one shares a denominator with
                    # the premium cap the router enforces. Grading one trade in
                    # each unit under a single field name is how sizing came to
                    # read CORRECT 487 times out of 488.
                    "chest_fraction_pct": self._chest_fraction_pct(
                        selected_sid, tracked_entry_price, qty_filled
                    ),
                    "sector": symbol_sec,
                    "personality_mode": personality_profile.get("active_mode", "BALANCED"),
                    "sector_flow": sector_rotation_dir,
                    "side": tracked_side.value if hasattr(tracked_side, "value") else tracked_side,
                    "quantity": float(qty_filled),
                    "venue_id": getattr(venue, "venue_id", "paper_main"),
                    "underlying": symbol,
                    "unconfirmed": (status_str == "UNCONFIRMED"),
                    "entry_timestamp": datetime.now(timezone.utc).isoformat(),
                    **option_tracking_extras,
                }
                self._save_positions_tracking()

                if self.telegram_bot and self.telegram_bot.enabled:
                    self.telegram_bot.notify_entry(
                        symbol=tracked_symbol,
                        cmp=tracked_entry_price,
                        target=self._active_positions_tracking[tracked_symbol]["target_price"],
                        target_adaptive=self._active_positions_tracking[
                            tracked_symbol].get("target_is_adaptive"),
                        edge=float(committee_decision.decision_confidence),
                        strategy=self._strategy_display_name(
                            self._active_positions_tracking[tracked_symbol].get("strategy_id")),
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

        # ONE LEAGUE (2026-07-16): the shadow-simulation loop that used to sit
        # here is gone. Every strategy now competes for REAL paper entries in
        # the winner-take-asset block above — same venue, same exit ladder,
        # same accounting — so there is no separate simulated book to feed.


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
                    # THIS USED TO COERCE PRODUCTION INTO ACTIVE, inside the
                    # trading loop, and save it. That is the whole distance
                    # between "a candidate advanced a rung" and "a strategy
                    # nobody approved is now taking real entries and competing
                    # for a chest". Promotion proposes now; a PRODUCTION status
                    # arriving here is a bug and must not be activated.
                    if strat.get("status") == "PRODUCTION":
                        logger.error(
                            "Strategy %s came back PRODUCTION from the "
                            "pipeline. Promotion needs the commander's "
                            "approval, so it was NOT activated.", strat_id)
                        strat["status"] = "PROBATION"
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
            # Same rule in both leagues, so parking an index asset later needs
            # no second change here.
            if self.is_parked(symbol_upper):
                logger.debug(f"Index Dojo: {symbol_upper} is parked; not scanned.")
                continue
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
