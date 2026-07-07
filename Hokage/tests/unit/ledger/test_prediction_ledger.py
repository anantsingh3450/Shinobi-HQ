from __future__ import annotations

from bots.backtest.models import BacktestResult
from bots.strategy.models import StrategyProposal
from hokage.ledger.prediction_ledger import JsonPredictionLedger, PredictionRecord


def test_prediction_ledger_roundtrip(tmp_path) -> None:
    ledger = JsonPredictionLedger(tmp_path)
    proposal = StrategyProposal(
        name="Prediction Strategy",
        description="Test strategy",
        market="EUR/USD",
        entry_rule="Enter long",
        exit_rule="Exit",
        stop_loss_rule="2%",
        take_profit_rule="3:1",
        timeframe="1D",
        confidence_score=0.8,
        sources_cited=("test",),
    )
    backtest = BacktestResult(
        proposal_id=proposal.proposal_id,
        total_trades=10,
        win_rate=60.0,
        net_profit=100.0,
        max_drawdown=3.0,
        profit_factor=1.5,
        passed=True,
        summary="ok",
        after_tax_net_profit=90.0,
        provider="mock",
    )
    record = PredictionRecord.from_pipeline(proposal, backtest)

    ledger.record(record)
    loaded = ledger.load_all()

    assert len(loaded) == 1
    assert loaded[0].proposal_id == proposal.proposal_id
    assert loaded[0].after_tax_net_profit == 90.0
