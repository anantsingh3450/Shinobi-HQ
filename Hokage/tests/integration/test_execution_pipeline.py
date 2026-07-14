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
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_TAX_LEDGER_DIR", tmp_path / "tax")

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act: Process a trade command
    result = router.handle_command("trade GBP/USD macro breakout")

    # Assert
    assert isinstance(result, dict)
    # Generator now resolves the concrete symbol from the query text.
    assert result["market"] == "GBP/USD"
    assert result["direction"] in ("LONG", "SHORT")
    assert result["quantity"] > 0
    assert result["entry_price"] == 1.27  # Mock price table value for GBP/USD
    assert result["simulated_value"] == result["quantity"] * result["entry_price"]
    assert result["status"] == "OPEN"
    assert result["mode"] == "PAPER"
    assert result["trade_id"]
    assert "dummy-source-v1" in result["sources_cited"]

    # Verify that the trade record was written to the temp jsonl store
    trades_file = tmp_path / "trades.jsonl"
    assert trades_file.exists()
    tax_file = tmp_path / "tax" / "tax_events.jsonl"
    assert tax_file.exists()

    # Read trades file content and verify the entry
    lines = trades_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_trade_command_syncs_portfolio_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: trade command must write trade history, tax history, AND update portfolio.

    Previously execute_paper_trade() wrote trades.jsonl and tax_events.jsonl but
    never called portfolio_store.save_account(), leaving account_paper.json stale.
    This test locks in all four required side-effects of the trade command.
    """
    # Arrange
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PORTFOLIO_DIR", tmp_path / "portfolio")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_TAX_LEDGER_DIR", tmp_path / "tax")

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act
    result = router.handle_command("trade GBP/USD macro breakout")

    # 1. Trade history written
    trades_file = tmp_path / "trades.jsonl"
    assert trades_file.exists(), "trades.jsonl must exist after trade command"
    trade_lines = trades_file.read_text(encoding="utf-8").splitlines()
    assert len(trade_lines) == 1, "exactly one trade should be recorded"

    # 2. Tax history written
    tax_file = tmp_path / "tax" / "tax_events.jsonl"
    assert tax_file.exists(), "tax_events.jsonl must exist after trade command"

    # 3. Portfolio state written (this was the missing side-effect)
    import json
    account_file = tmp_path / "portfolio" / "account_paper.json"
    assert account_file.exists(), (
        "account_paper.json must be created by trade command â€” "
        "previously this was missing, leaving portfolio state stale"
    )

    # 4. Portfolio state synchronized with trade history
    account_data = json.loads(account_file.read_text(encoding="utf-8"))
    open_positions = {
        pid: pos
        for pid, pos in account_data["positions"].items()
        if pos["status"] == "OPEN"
    }
    assert len(open_positions) == len(trade_lines), (
        f"open position count ({len(open_positions)}) must equal "
        f"trade line count ({len(trade_lines)}) â€” portfolio diverged from trade log"
    )

    # 5. The position in account matches the trade_id returned
    trade_id = result["trade_id"]
    assert trade_id in open_positions, (
        f"trade_id '{trade_id}' must appear as an open position in account_paper.json"
    )


def test_multiple_trade_commands_keep_portfolio_in_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: N sequential trade commands must keep trades.jsonl and account in sync.

    This is the exact scenario that was previously broken:
    - N calls to `trade` wrote N rows to trades.jsonl
    - account_paper.json was never updated (showed 0 positions)
    - The full-trade risk gate then saw zero existing exposure, producing
      incorrect risk decisions.
    """
    import json

    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PORTFOLIO_DIR", tmp_path / "portfolio")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_TAX_LEDGER_DIR", tmp_path / "tax")

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    topics = [
        "NIFTY breakout momentum",
        "BTC/USD trend following",
    ]

    for topic in topics:
        result = router.handle_command(f"trade {topic}")
        assert isinstance(result, dict), f"trade command must return a dict for topic: {topic}"

    # Both trades must appear in trades.jsonl
    trades_file = tmp_path / "trades.jsonl"
    assert trades_file.exists()
    trade_lines = trades_file.read_text(encoding="utf-8").splitlines()
    assert len(trade_lines) == len(topics), (
        f"expected {len(topics)} trade records, got {len(trade_lines)}"
    )

    # Account must have been updated for each trade â€” no divergence
    account_file = tmp_path / "portfolio" / "account_paper.json"
    assert account_file.exists()
    account_data = json.loads(account_file.read_text(encoding="utf-8"))
    open_positions = {
        pid: pos
        for pid, pos in account_data["positions"].items()
        if pos["status"] == "OPEN"
    }
    assert len(open_positions) == len(topics), (
        f"portfolio has {len(open_positions)} open positions but "
        f"{len(topics)} trades were executed â€” state is out of sync"
    )


def test_research_command_does_not_persist_trades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: Redirect paper trades directory to a temporary folder
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_TAX_LEDGER_DIR", tmp_path / "tax")

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act: Process a research command
    result = router.handle_command("research GBP/USD macro breakout")

    # Assert: Result is a dictionary representing the StrategyProposal
    assert isinstance(result, dict)
    assert result["market"] == "GBP/USD"
    assert "entry_rule" in result
    assert "exit_rule" in result

    # Verify that NO trade record was written
    trades_file = tmp_path / "trades.jsonl"
    assert not trades_file.exists()
    tax_file = tmp_path / "tax" / "tax_events.jsonl"
    assert not tax_file.exists()


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
    """Test the full pipeline: Research â†’ Strategy â†’ Backtest â†’ Execution."""
    # Arrange: Redirect paper trades directory to a temporary folder
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path)
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PORTFOLIO_DIR", tmp_path / "portfolio")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PREDICTION_LEDGER_DIR", tmp_path / "predictions")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_TAX_LEDGER_DIR", tmp_path / "tax")

    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    # Act: Process a full-trade command
    result = router.handle_command("full-trade CRUDE_OIL momentum strategy")

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
    assert "after_tax_net_profit" in result
    assert "backtest_provider" in result
    assert "backtest_summary" in result
    assert "simulated_tax" in result

    # Assert: Verify trade execution happened after backtest passed.
    # The generator resolves the concrete symbol from the query text; the old
    # "MARKET" placeholder is no longer executable (it once created a ghost
    # paper position at a default price).
    assert result["market"] == "CRUDE_OIL"
    assert result["direction"] in ("LONG", "SHORT")
    assert result["quantity"] > 0
    assert result["entry_price"] == 6800.0  # Mock price table value for CRUDE_OIL
    assert result["status"] == "OPEN"
    assert result["mode"] == "PAPER"
    assert result["trade_id"]

    # Verify trade was persisted
    trades_file = tmp_path / "trades.jsonl"
    assert trades_file.exists()
    lines = trades_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    prediction_file = tmp_path / "predictions" / "predictions.jsonl"
    tax_file = tmp_path / "tax" / "tax_events.jsonl"
    assert prediction_file.exists()
    assert tax_file.exists()


def test_full_trade_command_empty_topic() -> None:
    """Test that full-trade command rejects empty topic."""
    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    result = router.handle_command("full-trade ")
    assert isinstance(result, str)
    assert "Error: Please specify a topic" in result


def test_full_trade_backtest_failure_blocks_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that execution is blocked when backtest fails."""

    from unittest.mock import MagicMock

    # Arrange
    monkeypatch.setattr(
        hokage.orchestrator.pipeline,
        "_PAPER_TRADES_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        hokage.orchestrator.pipeline,
        "_PORTFOLIO_DIR",
        tmp_path / "portfolio",
    )
    monkeypatch.setattr(
        hokage.orchestrator.pipeline,
        "_PREDICTION_LEDGER_DIR",
        tmp_path / "predictions",
    )
    monkeypatch.setattr(
        hokage.orchestrator.pipeline,
        "_TAX_LEDGER_DIR",
        tmp_path / "tax",
    )

    orchestrator = HokageOrchestrator()

    # Force backtest failure
    failing_result = MagicMock()
    failing_result.passed = False
    failing_result.win_rate = 42.0
    failing_result.max_drawdown = 25.0
    failing_result.profit_factor = 0.8
    failing_result.net_profit = -100.0
    failing_result.after_tax_net_profit = -100.0
    failing_result.summary = "Forced test failure"
    failing_result.provider = "mock"

    orchestrator.backtest_bot.validate_strategy = MagicMock(
        return_value=failing_result
    )

    with pytest.raises(ValueError) as exc_info:
        orchestrator.execute_full_pipeline(
            "GBP/USD momentum strategy"
        )

    assert "Backtest failed" in str(exc_info.value)

    trades_file = tmp_path / "trades.jsonl"
    assert not trades_file.exists()

    prediction_file = (
        tmp_path / "predictions" / "predictions.jsonl"
    )
    assert prediction_file.exists()
