from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from bots.strategy.models import StrategyProposal
from bots.backtest.models import BacktestResult
from bots.risk.models import RiskVerdict
from integrations.brokers.models import AccountBalance, VenuePosition, ExecutionMode, ExecutionContext
from integrations.data.models import Instrument, AssetClass, Exchange


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.get_market_status.return_value = {"is_open": True}
    
    # Configure mock ExecutionContext
    orch.get_execution_context.return_value = ExecutionContext(
        execution_mode=ExecutionMode.PAPER,
        active_venue_id="paper_main",
        brain_id="primary_brain",
        authority_level="elder"
    )
    
    # Configure mock venue
    mock_venue = MagicMock()
    mock_venue.venue_id = "paper_main"
    mock_venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_main", total_equity=100000.0, cash=50000.0, margin_available=50000.0, margin_used=0.0
    )
    mock_venue.get_positions.return_value = []
    
    orch.registry.get_venue.return_value = mock_venue
    # Real registry surface: the bot iterates list_venues() and resolves each id.
    # "paper_main" contains "paper" so PAPER mode selects it.
    orch.registry.list_venues.return_value = ["paper_main"]
    # Live-provenance quote: the entry path refuses to execute against synthetic
    # or stale quotes (commander doctrine), so the fixture must present a fresh,
    # non-mock-provider quote.
    mock_quote = MagicMock()
    mock_quote.price = 3000.0
    mock_quote.bid = 2999.7
    mock_quote.ask = 3000.3
    mock_quote.volume = 10000.0
    mock_quote.provider = "test-live-feed"
    mock_quote.quoted_at = datetime.now(timezone.utc)
    orch.price_source.get_quote.return_value = mock_quote
    # Asset-venue resolution used on the entry path.
    orch.broker_registry.get_venue_for_asset.return_value = mock_venue
    orch.paper_venue._account_id = "paper"
    return orch


@pytest.fixture(autouse=True)
def isolate_path_resolver(tmp_path):
    from hokage.memory.resolver import PathResolver
    def mock_init(self, brain_root=None):
        self._brain_root = tmp_path
    
    with patch.object(PathResolver, "__init__", mock_init):
        yield


def test_autonomous_bot_lifecycle(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)

    assert not bot.is_active()
    bot.start()
    assert bot.is_active()
    bot.stop()
    assert not bot.is_active()


def test_price_provenance_guard_blocks_synthetic_and_stale(mock_orchestrator):
    """Doctrine: entry orders never execute against synthetic or stale prices."""
    from datetime import timedelta

    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    quote = MagicMock()
    quote.price = 3000.0

    # 1. Synthetic provider (mock price table) -> blocked
    quote.provider = "mock-market-data-v1"
    quote.quoted_at = datetime.now(timezone.utc)
    mock_orchestrator.price_source.get_quote.return_value = quote
    price, reason = bot._get_validated_live_price("TCS")
    assert price is None
    assert "synthetic" in reason

    # 2. Live provider but stale (1 hour old, max 600s) -> blocked
    quote.provider = "kite"
    quote.quoted_at = datetime.now(timezone.utc) - timedelta(seconds=3600)
    price, reason = bot._get_validated_live_price("TCS")
    assert price is None
    assert "stale" in reason

    # 3. Missing timestamp -> blocked
    quote.quoted_at = None
    price, reason = bot._get_validated_live_price("TCS")
    assert price is None

    # 4. Invalid price -> blocked
    quote.quoted_at = datetime.now(timezone.utc)
    quote.price = 0.0
    price, reason = bot._get_validated_live_price("TCS")
    assert price is None

    # 5. Fresh, live-provider, valid price -> passes
    quote.price = 3000.0
    price, reason = bot._get_validated_live_price("TCS")
    assert price == 3000.0
    assert reason == "live"


def test_negative_kelly_blocks_sizing(mock_orchestrator, monkeypatch):
    """A non-positive Kelly fraction must size ZERO — never a placeholder 1 lot."""
    from bots.strategy.midnight_crucible import crucible

    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    # Real numeric price so the ATR fallback (price * 1.5%) is numeric.
    mock_orchestrator.price_source.get_price.return_value = 3000.0

    # Fully-blended empirical parameters with clear negative edge:
    # kelly_f = (p*b - (1-p)*L) / (b*L) = (0.2*0.01 - 0.8*0.02) / 0.0002 < 0
    monkeypatch.setattr(
        crucible, "get_bayesian_kelly_parameters",
        lambda: {"total_trades": 100, "p": 0.2, "b": 0.01, "L": 0.02},
    )
    qty = bot._calculate_dynamic_lot_size("TCS", 500000.0, entry_price=3000.0, alloc_pct=2.0, confidence_score=80.0)
    assert qty == 0.0

    # Clear positive edge sizes a real (positive) quantity.
    monkeypatch.setattr(
        crucible, "get_bayesian_kelly_parameters",
        lambda: {"total_trades": 100, "p": 0.7, "b": 0.02, "L": 0.01},
    )
    qty_pos = bot._calculate_dynamic_lot_size("TCS", 500000.0, entry_price=3000.0, alloc_pct=2.0, confidence_score=80.0)
    assert qty_pos > 0.0


def test_telegram_remote_commands(mock_orchestrator):
    """Commander control commands: /pause /resume /close_all /kill /status."""
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    mock_venue = mock_orchestrator.registry.get_venue.return_value

    # The uplink must be wired to this bot as its command handler.
    assert bot.telegram_bot.command_handler is bot

    bot._active_positions_tracking["TCS"] = {
        "entry_price": 3000.0, "side": "BUY", "quantity": 5.0, "venue_id": "paper_main",
    }

    # /pause halts entries
    ack = bot.handle_remote_command("/pause")
    assert bot.intraday_override.get("halted") is True
    assert "PAUSED" in ack

    # /resume lifts the halt
    ack = bot.handle_remote_command("/resume")
    assert not bot.intraday_override.get("halted", False)
    assert "RESUMED" in ack

    # /close_all liquidates tracked positions WITHOUT halting entries
    mock_venue.place_order.reset_mock()
    ack = bot.handle_remote_command("/close_all")
    assert mock_venue.place_order.call_count == 1
    assert not bot.intraday_override.get("halted", False)

    # /kill halts, engages the kill switch, liquidates, and refuses /resume
    mock_venue.place_order.reset_mock()
    ack = bot.handle_remote_command("/kill")
    assert bot.intraday_override.get("halted") is True
    assert bot.gatekeeper_state == "KILL_SWITCH_ENGAGED"
    assert mock_venue.place_order.call_count == 1
    ack = bot.handle_remote_command("/resume")
    assert "refused" in ack
    assert bot.intraday_override.get("halted") is True

    # /status reports state
    ack = bot.handle_remote_command("/status")
    assert "STATUS" in ack


def test_circuit_breaker_blocks_entries(mock_orchestrator):
    """A >=9% index move vs previous close stands entries down; exits unaffected."""
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    quote = mock_orchestrator.price_source.get_quote.return_value

    # -10% limit move -> blocked
    quote.price = 21870.0
    quote.previous_close = 24300.0
    blocked, reason = bot._check_circuit_breaker()
    assert blocked
    assert "Circuit breaker" in reason

    # Scan-level integration: entry scan aborts before any order placement.
    bot.telegram_bot.send_message = MagicMock(return_value=True)
    mock_venue = mock_orchestrator.registry.get_venue.return_value
    mock_venue.place_order.reset_mock()
    bot._scan_and_enter_opportunities()
    mock_venue.place_order.assert_not_called()
    bot.telegram_bot.send_message.assert_called_once()
    assert "CIRCUIT BREAKER" in bot.telegram_bot.send_message.call_args[0][0]

    # Normal move -> not blocked
    quote.price = 24000.0
    blocked, _ = bot._check_circuit_breaker()
    assert not blocked

    # Missing benchmark data -> fail-open (never freeze on absent index data)
    quote.previous_close = None
    blocked, _ = bot._check_circuit_breaker()
    assert not blocked


def test_broker_session_health_halts_on_token_expiry(mock_orchestrator):
    """Mid-session token expiry on a LIVE venue halts entries + alerts commander."""
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    bot.telegram_bot.send_message = MagicMock(return_value=True)

    # PAPER mode: no broker-token risk, health check is a no-op.
    bot._check_broker_session_health()
    assert not bot.intraday_override.get("halted", False)

    # LIVE mode with an auth-failing live venue -> halt + alert.
    mock_orchestrator.get_execution_context.return_value = ExecutionContext(
        execution_mode=ExecutionMode.LIVE,
        active_venue_id="kite_main",
        brain_id="primary_brain",
        authority_level="elder",
    )
    mock_orchestrator.registry.list_venues.return_value = ["kite_main"]
    live_venue = MagicMock()
    live_venue.get_account_balance.side_effect = RuntimeError("TokenException: access token expired")
    mock_orchestrator.registry.get_venue.return_value = live_venue

    bot._check_broker_session_health()
    assert bot.intraday_override.get("halted") is True
    bot.telegram_bot.send_message.assert_called_once()
    assert "BROKER SESSION EXPIRED" in bot.telegram_bot.send_message.call_args[0][0]

    # Same date: alert not repeated.
    bot._check_broker_session_health()
    bot.telegram_bot.send_message.assert_called_once()


def test_autonomous_bot_monitor_exit_long_tsl(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1, tsl_percent=0.05, tp_percent=0.10)
    
    # Mock position to monitor
    inst = Instrument(symbol="TCS", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    
    # Position: Entry price = 3000.0, Current price = 2800.0 (below TSL trigger 3000 * 0.95 = 2850)
    from integrations.brokers.models import OrderSide
    pos = VenuePosition(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=5.0,
        average_price=3000.0,
        current_price=2800.0,
        unrealized_pnl=-1000.0,
        venue_id="paper_main"
    )
    
    mock_venue = mock_orchestrator.registry.get_venue.return_value
    mock_venue.get_positions.return_value = [pos]

    # Real price so _get_atr_for_symbol returns a numeric ATR (fallback = price*1.5%).
    mock_orchestrator.price_source.get_price.return_value = 2800.0
    # Pin the exit clock to mid-session (11:00 IST) so the EOD square-off does not fire.
    bot._now_ist = lambda: datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)

    bot._monitor_and_exit_positions()

    # Verify exit order was placed
    mock_venue.place_order.assert_called_once()
    exit_req = mock_venue.place_order.call_args[0][0]
    assert exit_req.instrument.symbol == "TCS"
    assert exit_req.side == OrderSide.SELL
    assert exit_req.quantity == 5.0
    # Production Assassin rule: stop at 1.5x ATR below entry (3000 - 1.5*42 = 2937);
    # current 2800 is below it -> full exit. (Was "ATR Thesis Stop" under the removed
    # pytest-only exit branch.)
    assert "Assassin Stop-Loss" in exit_req.execution_reason or "Trailing" in exit_req.execution_reason


def test_autonomous_bot_monitor_take_profit(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["INFY"], scan_interval_seconds=1, tsl_percent=0.05, tp_percent=0.10)
    
    inst = Instrument(symbol="INFY", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    from integrations.brokers.models import OrderSide
    
    # Position: Entry price = 1000.0, Current price = 1150.0 (above Take Profit 1100.0)
    pos = VenuePosition(
        instrument=inst,
        side=OrderSide.BUY,
        quantity=10.0,
        average_price=1000.0,
        current_price=1150.0,
        unrealized_pnl=1500.0,
        venue_id="paper_main"
    )
    
    mock_venue = mock_orchestrator.registry.get_venue.return_value
    mock_venue.get_positions.return_value = [pos]

    # Real price so _get_atr_for_symbol returns a numeric ATR (fallback = price*1.5%).
    mock_orchestrator.price_source.get_price.return_value = 1150.0
    # Pin the exit clock to mid-session (11:00 IST) so the EOD square-off does not fire.
    bot._now_ist = lambda: datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)

    bot._monitor_and_exit_positions()

    # Verify profit-taking exit order was placed. Production Connoisseur rule scales
    # out 1/3 at Target 1 (entry + 1.5x ATR = 1000 + 1.5*17.25 = ~1025.9); current 1150
    # clears it, firing a partial exit. (Was "Time-Decaying Profit Target" under the
    # removed pytest-only exit branch.)
    mock_venue.place_order.assert_called_once()
    exit_req = mock_venue.place_order.call_args[0][0]
    assert exit_req.instrument.symbol == "INFY"
    assert exit_req.side == OrderSide.SELL
    assert "Connoisseur" in exit_req.execution_reason or "Time-Decaying" in exit_req.execution_reason


def _run_entry_scan(mock_orchestrator, tmp_path, place_order_side_effect=None):
    """Drive _scan_and_enter_opportunities through a fully approved TCS long.

    Research/strategy/backtest/risk/profile are all mocked to approve the trade,
    so the scan reaches venue.place_order. `place_order_side_effect` (e.g. one of
    the conftest OrderResponse factories) controls the venue's fill behavior.
    Returns (bot, mock_venue).
    """
    from hokage.memory.resolver import PathResolver

    def mock_init(self, brain_root=None):
        self._brain_root = tmp_path

    with patch.object(PathResolver, "__init__", mock_init):
        bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)

        mock_orchestrator.research_bot.research.return_value = MagicMock()

        proposal = StrategyProposal(
            name="AutoTrend",
            description="Auto long TCS",
            market="TCS",
            entry_rule="long",
            exit_rule="none",
            stop_loss_rule="none",
            take_profit_rule="none",
            timeframe="1m",
            confidence_score=0.9,
            sources_cited=()
        )
        mock_orchestrator.strategy_bot.generate.return_value = proposal

        br = BacktestResult(
            proposal_id="proposal-123",
            total_trades=10,
            win_rate=60.0,
            net_profit=5000.0,
            max_drawdown=5.0,
            profit_factor=2.0,
            passed=True,
            summary="Passed",
            after_tax_net_profit=4500.0,
            tax_estimate=500.0,
            provider="HistoricalBacktestEngine"
        )
        mock_orchestrator.backtest_bot.validate_strategy.return_value = br

        mock_orchestrator.price_source.get_price.return_value = 3000.0
        mock_orchestrator.risk_bot.check_proposal.return_value = RiskVerdict(
            is_approved=True,
            max_approved_quantity=2.0,
            reason="Approved"
        )

        mock_venue = mock_orchestrator.registry.get_venue.return_value
        mock_venue.get_positions.return_value = []
        mock_venue.get_account_balance.return_value = AccountBalance(
            venue_id="paper_main", total_equity=400000.0, cash=400000.0, margin_available=400000.0, margin_used=0.0
        )
        if place_order_side_effect is not None:
            mock_venue.place_order.side_effect = place_order_side_effect

        with patch("hokage.memory.profile.ProfileService.get_profile") as mock_get_profile:
            from hokage.memory.profile import CommanderProfile, EnvironmentConfig, HorizonConfig, RiskConfig, PortfolioConfig, TaxConfig
            from shared.discovery.models import HorizonMode, ProgressionPhase, RiskMode
            from integrations.brokers.models import ExecutionMode

            mock_profile = CommanderProfile(
                commander_name="Anant",
                commander_title="Elder",
                environment=EnvironmentConfig(mode=ExecutionMode.PAPER, base_currency="INR"),
                horizon=HorizonConfig(phase=ProgressionPhase.ALPHA, mode=HorizonMode.FOCUSED, active_universe=["TCS"]),
                risk=RiskConfig(risk_mode=RiskMode.DEFENSIVE, capital_preservation=True, max_positions=1),
                portfolio=PortfolioConfig(starting_capital=500000),
                tax=TaxConfig(tax_aware=True)
            )
            mock_get_profile.return_value = mock_profile

            bot._scan_and_enter_opportunities()

    return bot, mock_venue


def test_autonomous_bot_scan_and_entry(mock_orchestrator, tmp_path, filled_order_response):
    bot, mock_venue = _run_entry_scan(mock_orchestrator, tmp_path, place_order_side_effect=filled_order_response)

    # Verify entry order placed
    mock_venue.place_order.assert_called_once()
    entry_req = mock_venue.place_order.call_args[0][0]
    assert entry_req.instrument.symbol == "TCS"
    from integrations.brokers.models import OrderSide
    assert entry_req.side == OrderSide.BUY
    # RiskManager approved a maximum of 2.0 units (max_approved_quantity above).
    # The dynamic Kelly sizer wants far more, but the entry path MUST clamp the
    # order to the risk-approved ceiling. (Previously this asserted 3 — the fixed
    # output of a now-removed `if "pytest" in sys.modules` sizing bypass, which
    # never exercised real sizing or the risk clamp at all.)
    assert entry_req.quantity == 2.0
    # A FILLED response must create a confirmed tracked position.
    tracked = bot._active_positions_tracking.get("TCS")
    assert tracked is not None
    assert tracked["quantity"] == 2.0
    assert tracked["unconfirmed"] is False
    assert len(bot._trades_taken_today) == 1


def test_scan_and_entry_rejected_order_no_phantom_position(mock_orchestrator, tmp_path, rejected_order_response):
    """A REJECTED order response must not create a tracked position (phantom-position bug)."""
    bot, mock_venue = _run_entry_scan(mock_orchestrator, tmp_path, place_order_side_effect=rejected_order_response)

    mock_venue.place_order.assert_called_once()
    assert "TCS" not in bot._active_positions_tracking
    assert len(bot._trades_taken_today) == 0


def test_scan_and_entry_none_order_marks_unconfirmed(mock_orchestrator, tmp_path, timeout_order_response):
    """A None (timeout) order response must be tracked as UNCONFIRMED, never as a clean fill."""
    bot, mock_venue = _run_entry_scan(mock_orchestrator, tmp_path, place_order_side_effect=timeout_order_response)

    mock_venue.place_order.assert_called_once()
    tracked = bot._active_positions_tracking.get("TCS")
    assert tracked is not None
    assert tracked["unconfirmed"] is True
    assert tracked["quantity"] == 0.0


def test_autonomous_bot_daily_report(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    
    # Add dummy executed trade data
    bot._trades_taken_today.append({
        "symbol": "TCS", "side": "BUY", "quantity": 2.0, "entry_price": 3000.0, "reason": "test entry"
    })
    bot._exits_executed_today.append({
        "symbol": "INFY", "side": "SELL", "quantity": 10.0, "reason": "TSL", "pnl": 500.0
    })
    
    report = bot.generate_daily_report()
    assert report.realized_pnl == 500.0
    assert report.win_rate == 100.0
    assert len(report.trades_taken) == 1
    assert len(report.exits_executed) == 1


def test_market_intelligence_rss_fallback(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"])
    quotes = bot.scanner.scan_indices()
    assert "NIFTY 50" in quotes
    assert quotes["NIFTY 50"] == 23500.0
    
    events = bot.news_engine.fetch_news_events()
    assert len(events) > 0
    assert events[0]["source"] in ("RSS_News_Feed", "Mock_Fallback")


def test_memory_manager_read_write(tmp_path):
    from bots.autonomous.memory import MemoryManager
    
    mgr = MemoryManager(brain_root=tmp_path)
    mock_event = {
        "event_id": "test_event_123",
        "event_title": "Test Event",
        "sentiment_score": 0.5,
        "vix_impact_delta": 1.0
    }
    
    mgr.record_event(mock_event)
    events = mgr.load_all_events()
    assert len(events) == 1
    assert events[0]["event_id"] == "test_event_123"


def test_historical_analog_matching(tmp_path):
    from bots.autonomous.memory import MemoryManager
    from bots.autonomous.analogs import HistoricalAnalogEngine
    from unittest.mock import MagicMock
    mgr = MemoryManager(brain_root=tmp_path)
    engine = HistoricalAnalogEngine(mgr, MagicMock())
    
    # Test fallback analog when memory is empty
    analogs = engine.find_analogs("GEOPOLITICAL", -0.5, 2.0)
    assert len(analogs) > 0
    assert analogs[0]["similarity_score"] == 92.50
    
    # Test real matching when memory exists
    mgr.record_event({
        "event_id": "oil_spike",
        "event_category": "GEOPOLITICAL",
        "sentiment_score": -0.6,
        "vix_impact_delta": 2.5
    })
    
    analogs = engine.find_analogs("GEOPOLITICAL", -0.5, 2.0)
    assert len(analogs) == 1
    assert analogs[0]["event_id"] == "oil_spike"
    assert analogs[0]["similarity_score"] > 80.0


def test_opportunity_discovery_modes(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator)
    
    # Mode A: Open Market
    opps = bot.discovery_engine.discover_opportunities("OPEN_MARKET")
    assert "TCS" in opps
    assert "RELIANCE" in opps
    
    # Mode B: Sector
    opps = bot.discovery_engine.discover_opportunities("SECTOR_RESTRICTED", "it")
    assert "TCS" in opps
    assert "INFY" in opps
    assert "RELIANCE" not in opps
    
    # Mode C: Watchlist
    opps = bot.discovery_engine.discover_opportunities("WATCHLIST_RESTRICTED", ["INFY"])
    assert opps == ["INFY"]
    
    # Mode D: Single Asset
    opps = bot.discovery_engine.discover_opportunities("SINGLE_ASSET", "reliance")
    assert opps == ["RELIANCE"]


def test_briefing_generation(mock_orchestrator):
    bot = AutonomousTradingBot(mock_orchestrator)
    briefing = bot.briefing_generator.generate_morning_briefing("OPEN_MARKET")
    assert "Global Markets" in briefing
    assert "Discovered Candidates" in briefing
    
    rep = bot.generate_daily_report()
    daily_brief = bot.briefing_generator.generate_daily_briefing(rep)
    assert "Financial Performance Metrics" in daily_brief


def test_eod_learning_loop(mock_orchestrator, tmp_path):
    from bots.autonomous.memory import MemoryManager
    from bots.autonomous.learning import EODLearningLoop
    from unittest.mock import MagicMock
    
    # Setup mock predictions
    pred = MagicMock()
    pred.predicted_at = datetime.now()
    pred.market = "TCS"
    pred.entry_price = 3000.0
    pred.direction = "LONG"
    
    mock_orchestrator.prediction_ledger.load_all.return_value = [pred]
    mock_orchestrator.price_source.get_price.return_value = 3100.0
    
    mgr = MemoryManager(brain_root=tmp_path)
    loop = EODLearningLoop(mock_orchestrator, mgr)
    
    res = loop.run_close_of_day_learning()
    assert res["predictions_checked"] == 1
    assert res["prediction_win_rate"] == 100.0
    
    # Verify it saved into memory
    events = mgr.load_all_events()
    assert len(events) == 1
    assert "prediction outcome check" in events[0]["event_description"]


def test_intelligence_cache(tmp_path):
    from bots.autonomous.cache import IntelligenceCache
    
    cache = IntelligenceCache(brain_root=tmp_path)
    test_data = {"test_key": "test_val"}
    
    cache.write_intelligence("test_cache.json", test_data)
    loaded = cache.read_intelligence("test_cache.json")
    assert loaded["test_key"] == "test_val"


def test_sector_rotation_engine(mock_orchestrator, tmp_path):
    from bots.autonomous.cache import IntelligenceCache
    from bots.autonomous.sector_rotation import SectorRotationEngine
    
    cache = IntelligenceCache(brain_root=tmp_path)
    engine = SectorRotationEngine(mock_orchestrator, cache)
    
    res = engine.compute_rotation()
    assert "strongest" in res
    assert "weakest" in res
    assert "capital_rotation_direction" in res
    assert "sector_details" in res
    
    # Verify it saved to sector_rotation.json
    cached_data = cache.read_intelligence("sector_rotation.json")
    assert cached_data["capital_rotation_direction"] == res["capital_rotation_direction"]


def test_two_speed_brain_risk_off(mock_orchestrator, tmp_path):
    from bots.autonomous.cache import IntelligenceCache
    # Configure Fast Trading Bot with cached RISK-OFF state
    bot = AutonomousTradingBot(mock_orchestrator)
    bot.cache = IntelligenceCache(brain_root=tmp_path)
    bot.cache.write_intelligence("risk_state.json", {"risk_on_off_status": "RISK-OFF"})
    
    mock_venue = mock_orchestrator.registry.get_venue.return_value
    mock_venue.get_positions.return_value = []
    
    bot._scan_and_enter_opportunities()
    
    # Check that research, strategy or order placement were bypassed in RISK-OFF
    mock_orchestrator.research_bot.research.assert_not_called()
    mock_venue.place_order.assert_not_called()


def test_generate_daily_report_no_trades_eod(mock_orchestrator, tmp_path):
    """Regression test: generate_daily_report must load profile/universe/portfolio_metrics
    locally when no trades were executed (previously caused NameError)."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot
    from bots.autonomous.cache import IntelligenceCache

    with patch("bots.autonomous.autonomous_bot.PathResolver") as MockResolver:
        mock_resolver_inst = MagicMock()
        mock_resolver_inst.resolve_brain_root.return_value = tmp_path
        MockResolver.return_value = mock_resolver_inst

        bot = AutonomousTradingBot(mock_orchestrator)
        # Redirect key dirs to tmp_path
        bot._autonomous_dir = tmp_path / "autonomous"
        bot._autonomous_dir.mkdir(parents=True, exist_ok=True)
        bot._positions_file = bot._autonomous_dir / "active_positions.json"
        bot._reports_dir = tmp_path / "reports"
        bot._reports_dir.mkdir(parents=True, exist_ok=True)
        bot.cache = IntelligenceCache(brain_root=tmp_path)
        # Patch the resolver used inside generate_daily_report to use tmp_path
        bot._resolver = mock_resolver_inst

    # Ensure zero trades day
    bot._trades_taken_today = []
    bot._exits_executed_today = []

    # Mock venue for daily report queries
    mock_venue = mock_orchestrator.registry.get_venue.return_value
    mock_venue.get_positions.return_value = []
    mock_venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_main", total_equity=500000.0, cash=500000.0,
        margin_available=500000.0, margin_used=0.0
    )

    # Must not raise NameError; EOD report should be generated
    report = bot.generate_daily_report()

    assert report.date is not None
    assert report.realized_pnl == 0.0
    assert report.win_rate == 0.0
    assert len(report.trades_taken) == 0


def test_cache_freshness_age_validation(tmp_path):
    from bots.autonomous.cache import IntelligenceCache
    from datetime import datetime, timedelta

    cache = IntelligenceCache(brain_root=tmp_path)
    
    # 1. Fresh file
    fresh_data = {
        "status": "OK",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    cache.write_intelligence("test_fresh.json", fresh_data)
    
    # Reading with max_age_seconds=60 should return the data
    read_data = cache.read_intelligence("test_fresh.json", max_age_seconds=60)
    assert read_data["status"] == "OK"

    # 2. Stale file
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
    stale_data = {
        "status": "OLD",
        "updated_at": stale_time.isoformat()
    }
    cache.write_intelligence("test_stale.json", stale_data)
    
    # Reading with max_age_seconds=60 should discard the data and return default empty dict
    read_data = cache.read_intelligence("test_stale.json", max_age_seconds=60)
    assert read_data == {}


def test_live_mode_mock_protection(mock_orchestrator):
    # Set execution mode to LIVE
    mock_orchestrator.get_execution_context.return_value = ExecutionContext(
        execution_mode=ExecutionMode.LIVE,
        active_venue_id="paper_main",
        brain_id="primary_brain",
        authority_level="elder"
    )
    
    # In live mode, venue_id contains "paper_main" which is a mock/paper venue
    bot = AutonomousTradingBot(mock_orchestrator)
    
    # The scan must abort and return early without querying or scanning
    bot._scan_and_enter_opportunities()
    
    mock_orchestrator.research_bot.research.assert_not_called()


def test_bot_crash_recovery_and_duplicate_prevention(mock_orchestrator, tmp_path):
    # Setup some pre-existing tracking on disk to simulate previous execution state (crash recovery)
    autonomous_dir = tmp_path / "autonomous"
    autonomous_dir.mkdir(parents=True, exist_ok=True)
    positions_file = autonomous_dir / "active_positions.json"
    
    # TCS was entered before crash
    tracking_state = {
        "TCS": {
            "entry_price": 3000.0,
            "peak_price": 3000.0,
            "stop_price": 2850.0,
            "target_price": 3300.0,
            "decision_id": "decision-xyz-999",
            "strategy_id": "strat-autotrend-equities-v1"
        }
    }
    with positions_file.open("w") as fh:
        json.dump(tracking_state, fh)
        
    # Reload bot (simulates startup after crash)
    bot = AutonomousTradingBot(mock_orchestrator)
    bot._autonomous_dir = autonomous_dir
    bot._positions_file = positions_file
    bot._active_positions_tracking = bot._load_positions_tracking()
    
    # Verify loaded state
    assert "TCS" in bot._active_positions_tracking
    
    # Configure mock venue to return empty broker positions (simulation of lag where broker position is not filled yet)
    mock_venue = mock_orchestrator.registry.get_venue.return_value
    mock_venue.get_positions.return_value = []
    
    # Mock scanner/discovery to return TCS
    bot.discovery_engine.discover_opportunities = MagicMock(return_value=["TCS"])
    
    # Run opportunities evaluation
    bot._scan_and_enter_opportunities()
    
    # Order placement must NOT be called for TCS because it is already merged from active tracking (duplicate prevention)
    mock_venue.place_order.assert_not_called()



def test_quote_liquidity_inputs_real_depth_and_none_fallbacks():
    """Liquidity inputs come from the live quote only: real spread from
    bid/ask, real book ratio from bid_qty/ask_qty, None when absent."""
    quote = MagicMock()
    quote.price = 100.0
    quote.bid = 99.9
    quote.ask = 100.1
    quote.bid_qty = 500.0
    quote.ask_qty = 250.0

    spread_pct, ratio = AutonomousTradingBot._quote_liquidity_inputs(quote)
    assert spread_pct == pytest.approx(0.2)
    assert ratio == pytest.approx(2.0)

    # No depth data: ratio None (imbalance check skipped, not neutral-faked)
    quote.bid_qty = None
    quote.ask_qty = None
    spread_pct, ratio = AutonomousTradingBot._quote_liquidity_inputs(quote)
    assert spread_pct == pytest.approx(0.2)
    assert ratio is None

    # No quote at all: both None
    spread_pct, ratio = AutonomousTradingBot._quote_liquidity_inputs(None)
    assert spread_pct is None
    assert ratio is None
