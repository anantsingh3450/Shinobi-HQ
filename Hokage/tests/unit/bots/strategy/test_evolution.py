from hokage.memory.resolver import PathResolver
from bots.strategy.evolution import StrategyEvolutionEngine

def test_evolution_engine_lifecycle_and_promotions(tmp_path):
    resolver = PathResolver(tmp_path)
    engine = StrategyEvolutionEngine(resolver)
    
    # 1. Discover candidate in RESEARCH
    candidate = engine.discover_candidate(
        parent_id="strat-parent-123",
        name="EvolutionAlpha",
        version="1.0.0",
        intended_assets=["TCS"],
        intended_regimes=["BULL"],
        evidence={"backtest_win_rate": 56.0, "backtest_expectancy": 100.0, "max_drawdown": 8.0}
    )
    
    assert candidate["status"] == "RESEARCH"
    assert candidate["parent_strategy_id"] == "strat-parent-123"
    
    # Check notifications logged
    notifs = engine.load_notifications()
    assert len(notifs) == 1
    assert notifs[0]["change_type"] == "DISCOVERY"
    
    # 2. Transition RESEARCH -> BACKTEST
    changed, msg = engine.evaluate_pipeline_transition(candidate, None)
    assert changed
    assert candidate["status"] == "BACKTEST"
    
    # 3. Transition BACKTEST -> PAPER_VALIDATION
    changed, msg = engine.evaluate_pipeline_transition(candidate, None)
    assert changed
    assert candidate["status"] == "PAPER_VALIDATION"
    
    # 4. Transition PAPER_VALIDATION -> SHADOW_MODE
    # Set sufficient trades and win rate
    candidate["trade_count"]["DEFAULT"] = 6
    candidate["win_rate"]["DEFAULT"] = 58.0
    changed, msg = engine.evaluate_pipeline_transition(candidate, None)
    assert changed
    assert candidate["status"] == "SHADOW_MODE"
    
    # Check promotion notification logged
    notifs = engine.load_notifications()
    assert len(notifs) == 2
    assert notifs[1]["change_type"] == "PROMOTION"
    assert notifs[1]["validation_status"] == "SHADOW_MODE"

    # Test shadow mode decision logging
    engine.log_shadow_decision("strat-123", "TCS", "ENTRY", {"price": 3000.0})
    # Check shadow decision file created
    shadow_file = resolver.resolve_brain_root() / "journal" / "shadow_decisions.jsonl"
    assert shadow_file.exists()
    
    # 5. Transition SHADOW_MODE -> PROBATION
    candidate["trade_count"]["DEFAULT"] = 9
    candidate["win_rate"]["DEFAULT"] = 60.0
    changed, msg = engine.evaluate_pipeline_transition(candidate, None)
    assert changed
    assert candidate["status"] == "PROBATION"

    # 6. Transition PROBATION -> PRODUCTION (with statistical comparison)
    # Active production strategy setup
    active_prod = {
        "strategy_id": "strat-prod-123",
        "name": "ProductionStrat",
        "status": "PRODUCTION",
        "trade_count": {"DEFAULT": 20},
        "win_rate": {"DEFAULT": 52.0},
        "expectancy": {"DEFAULT": 500.0},
        "sharpe_ratio": {"DEFAULT": 1.0},
        "drawdown": {"DEFAULT": 5.0}
    }
    
    # Case A: Probation strategy does not have enough trades (needs >= 5)
    candidate["trade_count"]["DEFAULT"] = 4
    changed, msg = engine.evaluate_pipeline_transition(candidate, active_prod)
    assert not changed
    
    # Case B: Probation strategy has trades but fails t-test confidence interval (t-stat < 1.645)
    candidate["trade_count"]["DEFAULT"] = 6
    candidate["sharpe_ratio"]["DEFAULT"] = 1.0
    candidate["drawdown"]["DEFAULT"] = 3.0
    candidate["expectancy"]["DEFAULT"] = 600.0  # slightly better expectancy, but high variance/small count leads to low t-stat
    changed, msg = engine.evaluate_pipeline_transition(candidate, active_prod)
    assert not changed
    assert "statistical confidence" in msg.lower()
    
    # Case C: Probation strategy has trades and passes t-test confidence with 95% confidence
    candidate["trade_count"]["DEFAULT"] = 15
    candidate["sharpe_ratio"]["DEFAULT"] = 2.0
    candidate["drawdown"]["DEFAULT"] = 2.0
    candidate["expectancy"]["DEFAULT"] = 2000.0  # much higher expectancy, standard error is small, t-stat is huge
    changed, msg = engine.evaluate_pipeline_transition(candidate, active_prod)
    assert changed
    assert candidate["status"] == "PRODUCTION"
    assert active_prod["status"] == "PROBATION"  # demoted


def test_evolution_engine_hac_classification(tmp_path):
    resolver = PathResolver(tmp_path)
    engine = StrategyEvolutionEngine(resolver)
    
    # Setup probation strategy
    probation_strat = {
        "strategy_id": "strat-probation-hac",
        "name": "HacProbation",
        "status": "PROBATION",
        "trade_count": {"DEFAULT": 40},
        "win_rate": {"DEFAULT": 60.0},
        "expectancy": {"DEFAULT": 2.0},
        "sharpe_ratio": {"DEFAULT": 2.0},
        "drawdown": {"DEFAULT": 2.0},
        "history": []
    }
    
    # Setup production strategy
    active_prod = {
        "strategy_id": "strat-prod-hac",
        "name": "HacProduction",
        "status": "PRODUCTION",
        "trade_count": {"DEFAULT": 15},
        "win_rate": {"DEFAULT": 52.0},
        "expectancy": {"DEFAULT": 1.0},
        "sharpe_ratio": {"DEFAULT": 1.0},
        "drawdown": {"DEFAULT": 4.0},
        "history": []
    }
    
    # 1. Test FALSE_POSITIVE_PREVENTED
    # x has mean ~19.5, but is a trend (strongly autocorrelated), making HAC SE very large
    # so HAC t-statistic drops below 1.645, but classical Welch t-statistic remains high
    x = [float(i) for i in range(40)]
    
    # y is independent and stable (mean = 15.0)
    y = [15.0] * 15
    
    probation_strat["pnl_history"] = {"DEFAULT": x}
    active_prod["pnl_history"] = {"DEFAULT": y}
    
    changed, msg = engine.evaluate_pipeline_transition(probation_strat, active_prod)
    
    # HAC must reject the promotion because of serial correlation increasing the SE
    assert not changed
    assert "FALSE_POSITIVE_PREVENTED" in msg
    assert probation_strat["status"] == "PROBATION"  # rejected!
    
    # Verify history contains FALSE_POSITIVE_PREVENTED
    history_events = [e["event"] for e in probation_strat["history"]]
    assert any("FALSE_POSITIVE_PREVENTED" in e for e in history_events)
    
    # Verify notification logged to Commander with FALSE_POSITIVE_PREVENTED
    notifs = engine.load_notifications()
    assert len(notifs) > 0
    # The last notification should be the evolution evaluation
    last_notif = notifs[-1]
    assert last_notif["change_type"] == "EVOLUTION"
    assert last_notif["supporting_evidence"]["event_classification"] == "FALSE_POSITIVE_PREVENTED"
    assert "classical_t_statistic" in last_notif["supporting_evidence"]
    assert "hac_t_statistic" in last_notif["supporting_evidence"]
    assert last_notif["supporting_evidence"]["selected_lag_probation"] > 0
    
    # 2. Test STATISTICAL_CONSENSUS
    # Reset probation with independent returns of high mean (should pass both)
    x_independent = [3.0, 3.2, 2.8, 3.1, 2.9, 3.3, 2.7, 3.1, 3.0, 3.2, 2.9, 3.1, 3.0, 3.2, 2.8, 3.0] * 2
    probation_strat["pnl_history"] = {"DEFAULT": x_independent}
    probation_strat["trade_count"]["DEFAULT"] = len(x_independent)
    
    y_independent = [1.0, 1.2, 0.8, 1.1, 0.9, 1.3, 0.7, 1.1, 1.0, 1.2, 0.9, 1.1, 1.0, 1.2, 0.8]
    active_prod["pnl_history"] = {"DEFAULT": y_independent}
    active_prod["trade_count"]["DEFAULT"] = len(y_independent)
    
    changed, msg = engine.evaluate_pipeline_transition(probation_strat, active_prod)
    assert changed
    assert "STATISTICAL_CONSENSUS" in msg
    assert probation_strat["status"] == "PRODUCTION"
    assert active_prod["status"] == "PROBATION"  # demoted
    
    # Verify history contains STATISTICAL_CONSENSUS
    history_events_2 = [e["event"] for e in probation_strat["history"]]
    assert any("STATISTICAL_CONSENSUS" in e for e in history_events_2)
