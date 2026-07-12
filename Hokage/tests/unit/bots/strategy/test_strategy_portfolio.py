from hokage.memory.resolver import PathResolver
from bots.strategy.portfolio import StrategyPortfolioManager

def test_strategy_portfolio_initialization(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    
    # Verify default strategies registered
    assert len(manager.portfolio["strategies"]) == 3
    assert "strat-autotrend-equities-v1" in manager.portfolio["strategies"]
    assert "strat-macrobreakout-commodities-v1" in manager.portfolio["strategies"]
    assert "strat-meanreversion-sideways-v1" in manager.portfolio["strategies"]

def test_strategy_selection_doctrine(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    
    # 1. Commodity selection under RISK-OFF regime -> should match MacroBreakout
    res = manager.select_strategy("CRUDE_OIL", market_regime="RISK-OFF", volatility_regime="HIGH")
    assert res["strategy"]["name"] == "MacroBreakout"
    
    # 2. Equity selection under normal BULL regime -> should match AutoTrend
    res = manager.select_strategy("TCS", market_regime="BULL", volatility_regime="LOW")
    assert res["strategy"]["name"] == "AutoTrend"
    
    # 3. Non-existent asset fallback to default Heuristic AutoTrend
    res = manager.select_strategy("XYZ_UNSUPPORTED", market_regime="BULL", volatility_regime="LOW")
    assert res["strategy"]["name"] == "AutoTrend"

def test_strategy_registration_and_probation(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    
    strat_id = manager.register_strategy(
        name="MeanReversionPro",
        version="1.1.0",
        supported_assets=["TCS", "INFY"],
        supported_regimes=["SIDEWAYS"]
    )
    
    assert strat_id.startswith("strat-meanreversionpro-")
    strat = manager.portfolio["strategies"][strat_id]
    assert strat["status"] == "PROBATION"
    assert strat["version"] == "1.1.0"
    
    # Verify that probation strategy matches but gets penalized so ACTIVE strategy is still selected
    res = manager.select_strategy("TCS", market_regime="SIDEWAYS", volatility_regime="LOW")
    # Even though TCS and SIDEWAYS matches our new strategy, it's under probation and shouldn't immediately replace ACTIVE MeanReversion
    assert res["strategy"]["name"] == "MeanReversion"

def test_strategy_confidence_evolution_and_promotion(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    
    # Register under probation
    strat_id = manager.register_strategy(
        name="NewGen",
        version="1.0.0",
        supported_assets=["TCS"],
        supported_regimes=["BULL"]
    )
    
    # Simulate 5 winning trades (evidence count = 5)
    for _ in range(5):
        manager.record_trade_outcome(strat_id, "TCS", is_win=True, pnl=100000.0)
        
    # Check that it got promoted to ACTIVE
    strat = manager.portfolio["strategies"][strat_id]
    assert strat["status"] == "ACTIVE"
    assert strat["trade_count"]["TCS"] == 5
    assert strat["win_rate"]["TCS"] == 100.0
    assert strat["domain_confidence"]["TCS"] > 50.0  # evolved gradually

def test_strategy_demotion_on_poor_performance(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    
    # Fetch AutoTrend equities strategy and verify it's ACTIVE
    s_id = "strat-autotrend-equities-v1"
    assert manager.portfolio["strategies"][s_id]["status"] == "ACTIVE"
    
    # Record 10 losses to simulate expectancy deterioration
    for _ in range(10):
        manager.record_trade_outcome(s_id, "TCS", is_win=False, pnl=-2000.0)
        
    # Check that it got demoted to ARCHIVED
    strat = manager.portfolio["strategies"][s_id]
    assert strat["status"] == "ARCHIVED"
