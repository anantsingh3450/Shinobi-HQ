"""Two StrategyPortfolioManager instances (index Dojo + MCX Arena) must never
touch each other's file, capital, or promotion state."""
from __future__ import annotations

from hokage.memory.resolver import PathResolver
from bots.strategy.portfolio import StrategyPortfolioManager, STRATEGY_STARTING_CAPITAL
from bots.strategy.mcx_portfolio import (
    generate_mcx_seed_portfolio,
    MCX_STRATEGY_STARTING_CAPITAL,
    MCX_UNIVERSE,
)


def test_mcx_manager_writes_a_separate_file_with_separate_capital(tmp_path):
    resolver = PathResolver(tmp_path)
    index_mgr = StrategyPortfolioManager(resolver)
    mcx_mgr = StrategyPortfolioManager(
        resolver,
        file_name="mcx_strategy_portfolio.json",
        starting_capital=MCX_STRATEGY_STARTING_CAPITAL,
        seed_generator=generate_mcx_seed_portfolio,
    )

    assert index_mgr.file_path != mcx_mgr.file_path
    assert index_mgr.file_path.exists() and mcx_mgr.file_path.exists()

    # Index keeps its original 4-strategy lineup at its original capital.
    assert len(index_mgr.portfolio["strategies"]) == 4
    for strat in index_mgr.portfolio["strategies"].values():
        assert strat["capital"]["starting"] == STRATEGY_STARTING_CAPITAL

    # MCX gets its own 4-strategy lineup at 100,000 each — untouched by the index seed.
    assert set(mcx_mgr.portfolio["strategies"].keys()) == {
        "strat-sessionshift-mcx-v1", "strat-eventrider-mcx-v1",
        "strat-rangefade-mcx-v1", "strat-trendrider-mcx-v1",
    }
    for strat in mcx_mgr.portfolio["strategies"].values():
        assert strat["capital"]["starting"] == 100_000.0
        assert strat["status"] == "SHADOW_MODE"
        assert strat["supported_assets"] == MCX_UNIVERSE


def test_recording_an_mcx_outcome_never_touches_the_index_file(tmp_path):
    resolver = PathResolver(tmp_path)
    index_mgr = StrategyPortfolioManager(resolver)
    mcx_mgr = StrategyPortfolioManager(
        resolver, file_name="mcx_strategy_portfolio.json",
        starting_capital=MCX_STRATEGY_STARTING_CAPITAL, seed_generator=generate_mcx_seed_portfolio,
    )

    index_before = index_mgr.file_path.read_text(encoding="utf-8")
    mcx_mgr.record_trade_outcome(
        strategy_id="strat-trendrider-mcx-v1", asset="CRUDEOIL", is_win=True, pnl=4200.0, market_regime="BULL",
    )
    assert index_mgr.file_path.read_text(encoding="utf-8") == index_before  # byte-identical, untouched

    chest = mcx_mgr.get_capital_report()
    row = next(r for r in chest if r["strategy_id"] == "strat-trendrider-mcx-v1")
    assert row["realized_pnl"] == 4200.0
    assert row["available"] == 104_200.0


def test_total_mcx_war_chest_is_four_lakh():
    seed = generate_mcx_seed_portfolio()
    total = sum(s["capital"]["starting"] for s in seed["strategies"].values())
    assert total == 400_000.0
