from __future__ import annotations

import pytest
from pathlib import Path

from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


def test_improvement_pipeline_integration(tmp_path: Path) -> None:
    """Verify integration of ImprovementBot in HokageOrchestrator and CommandRouter."""
    # 1. Initialize orchestrator and command router with a temp brain root
    orch = HokageOrchestrator(brain_root=tmp_path)
    router = CommandRouter(orch)
    
    # Register a strategy to simulate drift
    pm = orch.autonomous_bot.strategy_portfolio
    strat_id = pm.register_strategy(
        name="Integration Trend",
        version="1.0.0",
        supported_assets=["RELIANCE"],
        supported_regimes=["BULL"],
        status="ACTIVE",
        supporting_evidence={
            "backtest_win_rate": 65.0,
            "backtest_expectancy": 400.0,
            "max_drawdown": 5.0
        }
    )
    
    # Manually modify metrics to trigger a proposal
    strat = pm.portfolio["strategies"][strat_id]
    strat["win_rate"]["RELIANCE"] = 45.0
    strat["expectancy"]["RELIANCE"] = -50.0
    strat["drawdown"]["RELIANCE"] = 12.0
    strat["trade_count"]["RELIANCE"] = 4
    pm.save()
    
    # 2. Test 'hokage analyze-drift' command
    drift_output = router.handle_command(f"hokage analyze-drift {strat_id} RELIANCE")
    assert isinstance(drift_output, str)
    assert "Drift Analysis:" in drift_output
    assert "RELIANCE" in drift_output
    assert "Drift=-20.00%" in drift_output
    
    # 3. Test running the EOD improvement cycle via the orchestrator
    proposals = orch.run_performance_improvement_cycle()
    assert len(proposals) == 1
    proposal_id = proposals[0]["proposal_id"]
    
    # 4. Test 'hokage proposals' command
    proposals_output = router.handle_command("hokage proposals")
    assert isinstance(proposals_output, str)
    assert "PENDING COMMANDER APPROVAL" in proposals_output
    assert proposal_id in proposals_output
    
    # 5. Test 'hokage improve <proposal_id>' command to apply
    improve_output = router.handle_command(f"hokage improve {proposal_id}")
    assert isinstance(improve_output, str)
    assert "Successfully approved and applied strategy improvement proposal" in improve_output
    
    # Verify that changes were applied in the portfolio and logged
    pm._load_portfolio()
    updated_strat = pm.portfolio["strategies"][strat_id]
    assert updated_strat["status"] == "PROBATION"
    assert updated_strat["risk_multipliers"]["RELIANCE"] == 0.5
    
    # Check 'hokage proposals' output again to see APPLIED section
    proposals_output_after = router.handle_command("hokage proposals")
    assert "APPLIED HISTORICAL IMPROVEMENTS" in proposals_output_after
    assert proposal_id in proposals_output_after
