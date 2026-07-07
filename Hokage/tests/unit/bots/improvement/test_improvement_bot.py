from __future__ import annotations

import json
import pytest
from pathlib import Path

from hokage.memory.resolver import PathResolver
from bots.strategy.portfolio import StrategyPortfolioManager
from bots.improvement.improvement_bot import ImprovementBot
from hokage.ledger.prediction_ledger import JsonPredictionLedger
from bots.execution.store.json_trade_store import JsonTradeStore


def test_improvement_bot_drift_and_proposals(tmp_path: Path) -> None:
    """Verify that ImprovementBot calculates performance drift and generates advisory proposals correctly."""
    resolver = PathResolver(tmp_path)
    
    # 1. Initialize portfolio manager and register a mock strategy with historical evidence
    pm = StrategyPortfolioManager(resolver)
    
    strat_id = pm.register_strategy(
        name="Trend Alpha",
        version="1.0.0",
        supported_assets=["TCS"],
        supported_regimes=["BULL"],
        status="ACTIVE",
        supporting_evidence={
            "backtest_win_rate": 60.0,
            "backtest_expectancy": 500.0,
            "max_drawdown": 8.0
        }
    )
    
    # Manually modify the strategy's actual execution metrics in the portfolio to simulate severe negative drift
    strat = pm.portfolio["strategies"][strat_id]
    strat["win_rate"]["TCS"] = 40.0        # win rate dropped by 20%
    strat["expectancy"]["TCS"] = -200.0    # negative expectancy
    strat["drawdown"]["TCS"] = 14.0        # drawdown increased by 6%
    strat["trade_count"]["TCS"] = 5        # sufficient trades to trigger analysis
    pm.save()
    
    # 2. Instantiate ImprovementBot and run drift analysis
    bot = ImprovementBot(
        portfolio_manager=pm,
        resolver=resolver
    )
    
    drift = bot.analyze_performance_drift(strat_id, "TCS")
    assert drift["drift"]["win_rate_drift"] == -20.0
    assert drift["drift"]["expectancy_drift"] == -700.0
    assert drift["drift"]["drawdown_drift"] == 6.0
    
    # 3. Generate proposals
    proposals = bot.generate_improvement_proposals()
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["strategy_id"] == strat_id
    assert proposal["asset"] == "TCS"
    assert proposal["action"] == "DEMOTE"
    assert proposal["status"] == "PENDING_APPROVAL"
    assert proposal["previous_values"]["status"] == "ACTIVE"
    assert proposal["new_values"]["status"] == "PROBATION"
    
    # Check that proposals are persisted
    assert bot._proposals_file.exists()
    loaded_proposals = bot.load_proposals()
    assert len(loaded_proposals) == 1
    assert loaded_proposals[0]["proposal_id"] == proposal["proposal_id"]
    
    # 4. Apply the proposal with a Commander name
    success = bot.apply_improvement_proposal(proposal["proposal_id"], "Elder Anant")
    assert success
    
    # Verify portfolio strategy was updated
    pm._load_portfolio()  # reload from disk
    updated_strat = pm.portfolio["strategies"][strat_id]
    assert updated_strat["status"] == "PROBATION"
    assert updated_strat["risk_multipliers"]["TCS"] == 0.5
    
    # Verify proposal status was updated in ledger
    proposals_after = bot.load_proposals()
    assert proposals_after[0]["status"] == "APPLIED"
    assert proposals_after[0]["approving_commander"] == "Elder Anant"
    assert proposals_after[0]["applied_at"] is not None
    
    # Verify immutable applied improvements audit trail was logged
    assert bot._applied_improvements_file.exists()
    with bot._applied_improvements_file.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
        assert len(lines) == 1
        audit_record = json.loads(lines[0].strip())
        assert audit_record["proposal_id"] == proposal["proposal_id"]
        assert audit_record["approving_commander"] == "Elder Anant"
        assert audit_record["previous_values"]["status"] == "ACTIVE"
        assert audit_record["new_values"]["status"] == "PROBATION"
