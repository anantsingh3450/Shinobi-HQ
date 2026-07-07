from __future__ import annotations

from pathlib import Path

from bots.execution.store.json_trade_store import JsonTradeStore
from hokage.orchestrator.pipeline import HokageOrchestrator


def test_portable_brain_recovery_and_portability(tmp_path: Path) -> None:
    # 1. Create a temporary brain directory
    brain_root = tmp_path / "my_portable_brain"

    # 2. Instantiate and bootstrap first orchestrator instance
    orch1 = HokageOrchestrator(brain_root=brain_root)

    # Verify that the bootstrapper created the directories and default metadata files
    assert (brain_root / "brain.json").exists()
    assert (brain_root / "config" / "venues.json").exists()

    # 3. Execute paper trade using the full pipeline (ensures trades, predictions, portfolio, and tax are touched)
    result = orch1.execute_full_pipeline("EUR/USD trend breakout")

    trade_id = result["trade_id"]
    assert trade_id
    assert result["backtest_passed"] is True
    assert result["simulated_tax"] > 0

    # Verify that files exist in the first run
    assert (brain_root / "trades" / "trades.jsonl").exists()
    assert (brain_root / "portfolio" / "account_paper.json").exists()
    assert (brain_root / "tax" / "tax_events.jsonl").exists()
    assert (brain_root / "predictions" / "predictions.jsonl").exists()

    # Get initial values from first run stores
    trade_store1 = JsonTradeStore(brain_root / "trades")
    trades1 = trade_store1.load_all()
    account1 = orch1.portfolio_store.load_account("paper")
    taxes1 = orch1.tax_ledger.load_events()
    predictions1 = orch1.prediction_ledger.load_all()

    assert len(trades1) == 1
    assert len(taxes1) == 1
    assert len(predictions1) == 1
    assert len(account1.positions) == 1

    # 4. Restart orchestrator (simulate migrating or restarting the system by pointing a new instance to the same root)
    orch2 = HokageOrchestrator(brain_root=brain_root)

    # 5. Verify that all history recovers and matches
    trade_store2 = JsonTradeStore(brain_root / "trades")
    trades2 = trade_store2.load_all()
    account2 = orch2.portfolio_store.load_account("paper")
    taxes2 = orch2.tax_ledger.load_events()
    predictions2 = orch2.prediction_ledger.load_all()

    # Assert matching count and records
    assert len(trades2) == 1
    assert trades2[0].trade_id == trade_id
    assert trades2[0].market == trades1[0].market

    assert len(account2.positions) == 1
    assert "pos_0" in account2.positions or any(pos.market == "MARKET" for pos in account2.positions.values())
    assert account2.cash == account1.cash
    assert account2.realized_pnl == account1.realized_pnl

    assert len(taxes2) == 1
    assert taxes2[0].trade_id == trade_id
    assert taxes2[0].total_tax == taxes1[0].total_tax

    assert len(predictions2) == 1
    assert predictions2[0].proposal_id == predictions1[0].proposal_id
