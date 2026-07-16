from hokage.memory.resolver import PathResolver
from bots.strategy.portfolio import StrategyPortfolioManager

def test_strategy_portfolio_initialization(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)

    # Verify Dojo seeds registered (4 competitors: the 3 originals + Malfoy).
    assert len(manager.portfolio["strategies"]) == 4
    assert "strat-trendpullback-v2" in manager.portfolio["strategies"]
    assert "strat-macrobreakout-commodities-v1" in manager.portfolio["strategies"]
    assert "strat-meanreversion-sideways-v1" in manager.portfolio["strategies"]
    assert "strat-malfoy-momentum-v1" in manager.portfolio["strategies"]

def test_seed_statistics_are_earned_only(tmp_path):
    """Regression: earlier seeds shipped fabricated win rates/expectancies for
    trades that never happened, and Kelly sizing consumed them as evidence.
    Every seed must start with zeroed stats and neutral confidence."""
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)

    for strat in manager.portfolio["strategies"].values():
        assert strat["win_rate"] == {"DEFAULT": 0.0}
        assert strat["expectancy"] == {"DEFAULT": 0.0}
        assert strat["trade_count"] == {"DEFAULT": 0}
        assert strat["domain_confidence"] == {"DEFAULT": 50.0}

def test_breakout_family_starts_in_shadow(tmp_path):
    """Measured live evidence elsewhere: breakout entries are a net leak
    (PF ~0.4-0.7). They must earn promotion from SHADOW_MODE."""
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)

    assert manager.portfolio["strategies"]["strat-macrobreakout-commodities-v1"]["status"] == "SHADOW_MODE"
    assert manager.portfolio["strategies"]["strat-trendpullback-v2"]["status"] == "ACTIVE"

def test_strategy_selection_doctrine(tmp_path):
    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)

    # 1. NIFTY under BULL regime matches the ACTIVE trend family
    res = manager.select_strategy("NIFTY", market_regime="BULL", volatility_regime="LOW")
    assert res["strategy"]["name"] == "TrendPullback"

    # 2. Non-existent asset falls back to the flagship trend family
    res = manager.select_strategy("XYZ_UNSUPPORTED", market_regime="BULL", volatility_regime="LOW")
    assert res["strategy"]["name"] == "TrendPullback"

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

    # The flagship trend strategy starts ACTIVE
    s_id = "strat-trendpullback-v2"
    assert manager.portfolio["strategies"][s_id]["status"] == "ACTIVE"

    # Record 10 losses to simulate expectancy deterioration
    for _ in range(10):
        manager.record_trade_outcome(s_id, "NIFTY", is_win=False, pnl=-2000.0)

    # Check that it got demoted to ARCHIVED
    strat = manager.portfolio["strategies"][s_id]
    assert strat["status"] == "ARCHIVED"


def test_war_chest_seeded_and_migrated(tmp_path):
    """Every strategy gets a 50k war chest; persisted portfolios without the
    capital block are migrated on load."""
    import json
    from bots.strategy.portfolio import STRATEGY_STARTING_CAPITAL

    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    for strat in manager.portfolio["strategies"].values():
        assert strat["capital"] == {"starting": STRATEGY_STARTING_CAPITAL, "realized_pnl": 0.0}

    # Simulate a pre-ledger portfolio on disk: strip capital, reload.
    for strat in manager.portfolio["strategies"].values():
        strat.pop("capital", None)
    manager.save()
    manager2 = StrategyPortfolioManager(resolver)
    for strat in manager2.portfolio["strategies"].values():
        assert strat["capital"]["starting"] == STRATEGY_STARTING_CAPITAL


def test_war_chest_realized_pnl_and_report(tmp_path):
    from bots.strategy.portfolio import STRATEGY_STARTING_CAPITAL

    resolver = PathResolver(tmp_path)
    manager = StrategyPortfolioManager(resolver)
    sid = "strat-trendpullback-v2"

    manager.record_trade_outcome(strategy_id=sid, asset="NIFTY", is_win=True, pnl=1500.0)
    manager.record_trade_outcome(strategy_id=sid, asset="NIFTY", is_win=False, pnl=-400.0)
    assert manager.portfolio["strategies"][sid]["capital"]["realized_pnl"] == 1100.0

    report = manager.get_capital_report({sid: 12000.0})
    row = next(r for r in report if r["strategy_id"] == sid)
    assert row["starting_capital"] == STRATEGY_STARTING_CAPITAL
    assert row["deployed"] == 12000.0
    assert row["available"] == STRATEGY_STARTING_CAPITAL + 1100.0 - 12000.0

    # Strategies with no deployment report full availability
    idle = next(r for r in report if r["strategy_id"] != sid)
    assert idle["deployed"] == 0.0
    assert idle["available"] == idle["starting_capital"]
