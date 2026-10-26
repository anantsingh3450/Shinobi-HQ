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

# ===================================================== 2026-10-23 / 2026-10-26
# A PER-ASSET VERDICT WAS ARCHIVING THE STRATEGY ON EVERY ASSET.
#
#     DEMOTION: Strategy TrendRider demoted to ARCHIVED for GOLDM due to
#     negative expectancy after 10 trades (Win Rate: 10.0%, Expectancy: -1420.0).
#
# The message said "for GOLDM". The code said strat["status"] = "ARCHIVED",
# and status is ONE field for the whole strategy - so ten bad gold trades
# switched TrendRider off on gas, silver and crude too, including a silver
# cell that had returned +3,117 that same evening.
#
# Same disease as detect_patterns pooling every asset into one number, pointed
# the other way: there, one number stood in for many cells; here, one cell's
# verdict was applied to all of them. The system has been able to say "this
# asset, this side" since 2026-08-26 (_direction_allowed). The demoter had
# never been told.
def test_a_failing_cell_is_retired_without_touching_the_others(tmp_path):
    """The fix. Ten losing NIFTY trades retire NIFTY, and the strategy keeps
    trading the assets it was never judged on."""
    manager = StrategyPortfolioManager(PathResolver(tmp_path))
    s_id = "strat-trendpullback-v2"
    strat = manager.portfolio["strategies"][s_id]
    assert strat["status"] == "ACTIVE"
    before = list(strat["supported_assets"])
    assert len(before) > 1, "this test needs a multi-asset strategy to mean anything"

    for _ in range(10):
        manager.record_trade_outcome(s_id, "NIFTY", is_win=False, pnl=-2000.0)

    strat = manager.portfolio["strategies"][s_id]
    assert strat["status"] == "ACTIVE", "one bad cell must not archive the strategy"
    assert "NIFTY" not in strat["supported_assets"]
    assert strat["supported_assets"] == [a for a in before if a != "NIFTY"]


def test_the_retirement_says_which_cell_and_what_survives(tmp_path):
    manager = StrategyPortfolioManager(PathResolver(tmp_path))
    s_id = "strat-trendpullback-v2"
    for _ in range(10):
        manager.record_trade_outcome(s_id, "NIFTY", is_win=False, pnl=-2000.0)
    last = manager.portfolio["strategies"][s_id]["history"][-1]["event"]
    assert "CELL RETIRED" in last and "NIFTY" in last
    assert "Still scoped to" in last


def test_the_last_failing_cell_archives_rather_than_emptying_the_scope(tmp_path):
    """THE TRAP THIS FIX HAD TO AVOID. An empty supported_assets FAILS OPEN -
    _strategy_supports reads it as "no restriction recorded", not "trades
    nothing". Emptying the scope would arm the strategy against the ENTIRE
    universe at the exact moment it had proved worthless. Two other tests in
    this codebase already pin that trap from the other direction."""
    manager = StrategyPortfolioManager(PathResolver(tmp_path))
    s_id = "strat-trendpullback-v2"
    manager.portfolio["strategies"][s_id]["supported_assets"] = ["NIFTY"]

    for _ in range(10):
        manager.record_trade_outcome(s_id, "NIFTY", is_win=False, pnl=-2000.0)

    strat = manager.portfolio["strategies"][s_id]
    assert strat["status"] == "ARCHIVED", "the last cell failing does archive it"
    assert strat["supported_assets"] == ["NIFTY"], "the scope is never emptied"
    assert "LAST remaining cell" in strat["history"][-1]["event"]


def test_a_winning_cell_is_never_retired(tmp_path):
    """The demotion still needs all four of its conditions. This is the
    control for the two tests above."""
    manager = StrategyPortfolioManager(PathResolver(tmp_path))
    s_id = "strat-trendpullback-v2"
    before = list(manager.portfolio["strategies"][s_id]["supported_assets"])
    for _ in range(10):
        manager.record_trade_outcome(s_id, "NIFTY", is_win=True, pnl=+2000.0)
    strat = manager.portfolio["strategies"][s_id]
    assert strat["status"] != "ARCHIVED"
    assert strat["supported_assets"] == before


def test_fewer_than_ten_trades_decides_nothing(tmp_path):
    """Nine losses is not evidence. The 10-trade floor is the only thing
    standing between a bad afternoon and a retired cell."""
    manager = StrategyPortfolioManager(PathResolver(tmp_path))
    s_id = "strat-trendpullback-v2"
    before = list(manager.portfolio["strategies"][s_id]["supported_assets"])
    for _ in range(9):
        manager.record_trade_outcome(s_id, "NIFTY", is_win=False, pnl=-2000.0)
    assert manager.portfolio["strategies"][s_id]["supported_assets"] == before


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
