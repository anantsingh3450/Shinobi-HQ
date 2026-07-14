from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from bots.strategy.models import StrategyProposal
from bots.backtest.models import BacktestResult
from integrations.brokers.models import ExecutionMode, ExecutionContext, AccountBalance
from bots.risk.models import RiskVerdict

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.get_market_status.return_value = {"is_open": True}
    
    orch.get_execution_context.return_value = ExecutionContext(
        execution_mode=ExecutionMode.PAPER,
        active_venue_id="paper_main",
        brain_id="primary_brain",
        authority_level="elder"
    )
    
    mock_venue = MagicMock()
    mock_venue.venue_id = "paper_main"
    mock_venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_main", total_equity=100000.0, cash=50000.0, margin_available=50000.0, margin_used=0.0
    )
    mock_venue.get_positions.return_value = []
    
    orch.registry.get_venue.return_value = mock_venue
    # Real registry surface: the bot iterates list_venues() and resolves each id.
    orch.registry.list_venues.return_value = ["paper_main"]
    orch.broker_registry.get_venue_for_asset.return_value = mock_venue
    orch.paper_venue._account_id = "paper"

    # RiskBot must return a real RiskVerdict — the entry path reads
    # max_approved_quantity to clamp sizing, so a bare MagicMock would break the
    # numeric comparison. inf = approved with no quantity ceiling for this test.
    orch.risk_bot.check_proposal.return_value = RiskVerdict(
        is_approved=True,
        max_approved_quantity=float("inf"),
        reason="Approved",
    )
    
    # Mock price source
    orch.price_source.get_price.return_value = 100.0
    mock_quote = MagicMock()
    mock_quote.volume = 10000.0
    mock_quote.price = 100.0
    mock_quote.bid = 99.9
    mock_quote.ask = 100.1
    # Live provenance: entry path blocks synthetic/stale quotes (doctrine).
    mock_quote.provider = "test-live-feed"
    mock_quote.quoted_at = datetime.now(timezone.utc)
    orch.price_source.get_quote.return_value = mock_quote
    
    return orch

@pytest.fixture(autouse=True)
def isolate_path_resolver(tmp_path):
    from hokage.memory.resolver import PathResolver
    def mock_init(self, brain_root=None):
        self._brain_root = tmp_path
    
    with patch.object(PathResolver, "__init__", mock_init):
        yield

def test_shadow_mode_lifecycle_and_promotion(mock_orchestrator, tmp_path, filled_order_response):
    # Initialize bot
    bot = AutonomousTradingBot(mock_orchestrator, watchlist=["TCS"], scan_interval_seconds=1)
    # Pin session time to 10:00 IST: outside the opening-bell observation
    # window, midday blackout, and late-entry cutoff (deterministic scan).
    bot._now_ist = lambda: datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
    bot._compute_underlying_bias = lambda symbol: None
    bot._india_vix_percentile = lambda: None
    # The shadow comparison reports the ACTIVE production strategy's action
    # for the same asset; the flagship must claim TCS for this fixture.
    bot.strategy_portfolio.portfolio["strategies"]["strat-trendpullback-v2"]["supported_assets"].append("TCS")

    mock_orchestrator.registry.get_venue.return_value.place_order.side_effect = filled_order_response

    # 1. Register candidate strategy under SHADOW_MODE
    strat_id = bot.strategy_portfolio.register_strategy(
        name="ShadowAlpha",
        version="1.0.0",
        supported_assets=["TCS"],
        supported_regimes=["BULL"],
        status="SHADOW_MODE"
    )
    
    # Setup mock discovery engine
    bot.discovery_engine.discover_opportunities = MagicMock(return_value=["TCS"])
    
    # Setup mock proposal and backtest result
    proposal = StrategyProposal(
        name="BreakoutMaster",
        market="TCS",
        entry_rule="long",
        exit_rule="trailing-stop",
        description="Simulated shadow breakout",
        stop_loss_rule="5%",
        take_profit_rule="10%",
        timeframe="15m",
        confidence_score=0.85
    )
    backtest_result = BacktestResult(
        proposal_id=proposal.proposal_id,
        total_trades=10,
        win_rate=60.0,
        net_profit=1000.0,
        max_drawdown=5.0,
        profit_factor=2.0,
        passed=True,
        summary="Passed"
    )
    
    # Mock research, strategy, and backtest bot
    bot.orchestrator.research_bot.research.return_value = MagicMock()
    bot.orchestrator.strategy_bot.generate.return_value = proposal
    bot.orchestrator.backtest_bot.validate_strategy.return_value = backtest_result
    
    # Setup intelligence cache for risk/regime
    bot.cache.write_intelligence("risk_state.json", {"risk_on_off_status": "RISK-ON", "vix_impact_delta": 0.0})
    bot.cache.write_intelligence("market_regime.json", {"trend_score": 0.8})
    
    # Run opportunities scan -> Should simulate entry decision in Shadow Mode (no live execution)
    bot._scan_and_enter_opportunities()
    
    # Verify shadow position is tracked
    assert strat_id in bot._shadow_positions_tracking
    assert "TCS" in bot._shadow_positions_tracking[strat_id]
    pos = bot._shadow_positions_tracking[strat_id]["TCS"]
    assert pos["entry_price"] == 100.0
    assert pos["side"] == "BUY"
    
    # Verify shadow decision is logged to shadow_decisions.jsonl
    shadow_file = tmp_path / "journal" / "shadow_decisions.jsonl"
    assert shadow_file.exists()
    lines = shadow_file.read_text().splitlines()
    entry_dec = json.loads(lines[0])
    assert entry_dec["strategy_id"] == strat_id
    assert entry_dec["decision_type"] == "ENTRY"
    assert entry_dec["details"]["verdict"] == "ENTERED"
    assert entry_dec["details"]["active_production_strategy_action"] == "ENTERED"
    
    # 2. Run monitoring loop - HOLD decision
    bot.orchestrator.price_source.get_price.return_value = 102.0
    import unittest.mock
    original_eval = bot._evaluate_cascading_exits
    bot._evaluate_cascading_exits = unittest.mock.MagicMock(return_value=(False, "HOLD", {"entry_price": 100.0, "peak_price": 102.0, "stop_price": 100.5, "quantity": 10.0, "side": "BUY"}))
    bot._monitor_and_exit_positions()
    bot._evaluate_cascading_exits = original_eval
    
    # Verify trailing stop adjusted (peak updated to 102.0)
    pos = bot._shadow_positions_tracking[strat_id]["TCS"]
    assert pos["peak_price"] == 102.0
    
    # Verify HOLD logged
    lines = shadow_file.read_text().splitlines()
    assert len(lines) >= 2
    hold_dec = json.loads(lines[-1])
    assert hold_dec["decision_type"] == "HOLD"
    
    # 3. Run monitoring loop - stop hit. Entry 100, ATR fallback = 95*1.5% = 1.425,
    # Assassin stop = 100 - 1.5*1.425 = ~97.86; price 95 is below it -> exit.
    # Pin the clock mid-session so the EOD square-off does not pre-empt the stop.
    bot._now_ist = lambda: datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)
    bot.orchestrator.price_source.get_price.return_value = 95.0
    bot._monitor_and_exit_positions()
    
    # Verify shadow position is cleared
    assert "TCS" not in bot._shadow_positions_tracking.get(strat_id, {})
    
    # Verify trade outcome recorded
    strat = bot.strategy_portfolio.portfolio["strategies"][strat_id]
    assert strat["trade_count"]["TCS"] == 1
    assert strat["win_rate"]["TCS"] == 0.0  # Loss
    
    # Verify shadow exit logged
    lines = shadow_file.read_text().splitlines()
    exit_dec = json.loads(lines[-1])
    assert exit_dec["decision_type"] == "EXIT"
    # Production Assassin/Connoisseur ladder (was "ATR Thesis Stop" under the removed
    # pytest-only exit branch).
    assert "Assassin Stop-Loss" in exit_dec["details"]["exit_reason"] or "Trailing Stop" in exit_dec["details"]["exit_reason"]
    
    # 4. Check statistical validation transitions
    # Register probation strategy
    prob_id = bot.strategy_portfolio.register_strategy(
        name="ProbationAlpha",
        version="1.0.0",
        supported_assets=["TCS"],
        supported_regimes=["BULL"],
        status="PROBATION"
    )
    
    # Get active production strategy (Dojo v2 flagship)
    active_prod = bot.strategy_portfolio.portfolio["strategies"]["strat-trendpullback-v2"]
    active_prod["trade_count"]["DEFAULT"] = 10
    active_prod["expectancy"]["DEFAULT"] = 500.0
    active_prod.setdefault("sharpe_ratio", {})["DEFAULT"] = 1.0
    active_prod.setdefault("drawdown", {})["DEFAULT"] = 5.0
    
    # Setup probation strategy with excellent metrics but too few trades (< 5)
    prob_strat = bot.strategy_portfolio.portfolio["strategies"][prob_id]
    prob_strat["trade_count"]["DEFAULT"] = 4
    prob_strat["expectancy"]["DEFAULT"] = 2000.0
    prob_strat["sharpe_ratio"]["DEFAULT"] = 2.5
    
    # Should fail due to sample size
    changed, msg = bot.strategy_evolution.evaluate_pipeline_transition(prob_strat, active_prod)
    assert not changed
    assert "statistical confidence" in msg.lower()
    
    # Setup probation strategy with sufficient trades and passes t-statistic Promotion
    prob_strat["trade_count"]["DEFAULT"] = 6
    prob_strat.setdefault("pnl_history", {})["DEFAULT"] = [2000.0, 2100.0, 1950.0, 2050.0, 1980.0, 2020.0]
    prob_strat["expectancy"]["DEFAULT"] = 2000.0
    prob_strat["sharpe_ratio"]["DEFAULT"] = 2.5
    
    # Setup active prod with history
    active_prod.setdefault("pnl_history", {})["DEFAULT"] = [500.0, 520.0, 480.0, 510.0, 490.0, 530.0, 470.0, 500.0, 510.0, 490.0]
    
    changed, msg = bot.strategy_evolution.evaluate_pipeline_transition(prob_strat, active_prod)
    assert changed
    assert prob_strat["status"] == "PRODUCTION"
    assert active_prod["status"] == "PROBATION"  # demoted
