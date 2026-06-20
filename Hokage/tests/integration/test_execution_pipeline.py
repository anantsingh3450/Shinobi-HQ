"""Integration tests for the end-to-end Hokage execution pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

import hokage.orchestrator.pipeline
from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


def test_trade_command_pipeline_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: Redirect paper trades directory to a temporary folder
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act: Process a trade command
    result = router.handle_command("trade EUR/USD macro breakout")

    # Assert
    assert isinstance(result, dict)
    assert result["market"] == "MARKET"
    assert result["direction"] in ("LONG", "SHORT")
    assert result["quantity"] > 0
    assert result["entry_price"] == 100.0  # Mock price for MARKET (default)
    assert result["simulated_value"] == result["quantity"] * result["entry_price"]
    assert result["status"] == "OPEN"
    assert result["mode"] == "PAPER"
    assert result["trade_id"]
    assert "dummy-source-v1" in result["sources_cited"]

    # Verify that the trade record was written to the temp jsonl store
    trades_file = tmp_path / "trades.jsonl"
    assert trades_file.exists()

    # Read trades file content and verify the entry
    lines = trades_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_research_command_does_not_persist_trades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: Redirect paper trades directory to a temporary folder
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act: Process a research command
    result = router.handle_command("research EUR/USD macro breakout")

    # Assert: Result is a dictionary representing the StrategyProposal
    assert isinstance(result, dict)
    assert result["market"] == "MARKET"
    assert "entry_rule" in result
    assert "exit_rule" in result

    # Verify that NO trade record was written
    trades_file = tmp_path / "trades.jsonl"
    assert not trades_file.exists()


def test_trade_command_empty_and_unknown_handling() -> None:
    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Empty trade topic
    res1 = router.handle_command("trade ")
    assert "Error: Please specify a topic" in res1

    # Unknown command
    res2 = router.handle_command("unknown_command topic")
    assert "Unknown command" in res2


def test_full_trade_pipeline_with_backtest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the full pipeline: Research → Strategy → Backtest → Execution."""
    # Arrange: Redirect paper trades directory to a temporary folder
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act: Process a full-trade command
    result = router.handle_command("full-trade EUR/USD momentum strategy")

    # Assert: Verify backtest results are in the output
    assert isinstance(result, dict)
    assert "backtest_passed" in result
    assert result["backtest_passed"] is True
    assert "total_trades" in result
    assert result["total_trades"] > 0
    assert "win_rate" in result
    assert result["win_rate"] >= 50
    assert "max_drawdown" in result
    assert result["max_drawdown"] < 20
    assert "profit_factor" in result
    assert "backtest_summary" in result

    # Assert: Verify trade execution happened after backtest passed
    assert result["market"] == "MARKET"  # DummySource returns MARKET
    assert result["direction"] in ("LONG", "SHORT")
    assert result["quantity"] > 0
    assert result["entry_price"] == 100.0  # Mock price
    assert result["status"] == "OPEN"
    assert result["mode"] == "PAPER"
    assert result["trade_id"]

    # Verify trade was persisted
    trades_file = tmp_path / "trades.jsonl"
    assert trades_file.exists()
    lines = trades_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_full_trade_command_empty_topic() -> None:
    """Test that full-trade command rejects empty topic."""
    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    result = router.handle_command("full-trade ")
    assert isinstance(result, str)
    assert "Error: Please specify a topic" in result


def test_full_trade_backtest_failure_blocks_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that execution is blocked when backtest fails."""
    from unittest.mock import MagicMock, patch

    from bots.strategy.models import StrategyProposal

    # Arrange
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)

    orchestrator = HokageOrchestrator()
    
    # Create a proposal with low confidence that will fail backtest
    failing_proposal = StrategyProposal(
        name="Failing Strategy",
        description="This strategy has low confidence",
        market="TEST/USD",
        entry_rule="long on signal",
        exit_rule="short on signal",
        stop_loss_rule="2% stop",
        take_profit_rule="5% profit target",
        timeframe="1D",
        confidence_score=0.3,  # Low confidence triggers backtest failure
        sources_cited=("test-source",),
    )

    # Mock the strategy generator to return the failing proposal
    with patch.object(orchestrator.strategy_bot.generator, "generate", return_value=failing_proposal):
        # Act & Assert: Pipeline should raise ValueError on backtest failure
        with pytest.raises(ValueError) as exc_info:
            orchestrator.execute_full_pipeline("test query")

        assert "Backtest failed" in str(exc_info.value)
        assert "Win rate" in str(exc_info.value)
        assert "Drawdown" in str(exc_info.value)

    # Verify no trade was persisted
    trades_file = tmp_path / "trades.jsonl"
    assert not trades_file.exists()
