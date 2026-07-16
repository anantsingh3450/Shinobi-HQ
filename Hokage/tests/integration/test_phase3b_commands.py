"""Integration tests for Phase 3B query commands: portfolio, positions, predictions, tax."""
from __future__ import annotations

from pathlib import Path

import pytest

import hokage.orchestrator.pipeline
from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CommandRouter:
    """Return a router wired to isolated tmp_path stores."""
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PAPER_TRADES_DIR", tmp_path / "trades")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PORTFOLIO_DIR", tmp_path / "portfolio")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_PREDICTION_LEDGER_DIR", tmp_path / "predictions")
    monkeypatch.setattr(hokage.orchestrator.pipeline, "_TAX_LEDGER_DIR", tmp_path / "tax")
    return CommandRouter(HokageOrchestrator())


# ---------------------------------------------------------------------------
# portfolio command
# ---------------------------------------------------------------------------

class TestPortfolioCommand:
    def test_portfolio_empty_state_returns_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """portfolio command must work even if no trades have been run yet."""
        router = _make_router(tmp_path, monkeypatch)
        result = router.handle_command("portfolio")

        assert isinstance(result, dict)
        assert result["account_id"] == "paper"
        # 500000 is BrainBootstrapper's seeded starting_capital default for a
        # brand-new brain profile (not a hardcoded 10000 fallback) — the
        # portfolio store now correctly resolves the real brain root to read it.
        assert result["initial_balance"] == 500000.0
        assert result["cash"] == 500000.0
        assert result["realized_pnl"] == 0.0
        assert result["open_positions"] == 0
        assert result["unrealized_pnl"] == "N/A (live price feed inactive)"

    def test_portfolio_after_trade_shows_updated_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """portfolio command must reflect trade after trade command runs."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD macro breakout")

        result = router.handle_command("portfolio")

        assert isinstance(result, dict)
        assert result["open_positions"] == 1
        assert result["unrealized_pnl"] == "N/A (live price feed inactive)"

    def test_portfolio_open_position_count_increments_per_trade(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each trade command must increment the open_positions count by 1."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade NIFTY breakout")
        router.handle_command("trade BTC/USD trend")

        result = router.handle_command("portfolio")

        assert result["open_positions"] == 2

    def test_portfolio_currency_field_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """portfolio response must include currency field."""
        router = _make_router(tmp_path, monkeypatch)
        result = router.handle_command("portfolio")
        assert "currency" in result


# ---------------------------------------------------------------------------
# positions command
# ---------------------------------------------------------------------------

class TestPositionsCommand:
    def test_positions_empty_state_returns_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """positions command must return an empty list when no trades exist."""
        router = _make_router(tmp_path, monkeypatch)
        result = router.handle_command("positions")

        assert isinstance(result, list)
        assert result == []

    def test_positions_after_trade_returns_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """positions command must return one entry per open trade."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD macro breakout")

        result = router.handle_command("positions")

        assert isinstance(result, list)
        assert len(result) == 1

        pos = result[0]
        assert "market" in pos
        assert "direction" in pos
        assert pos["direction"] in ("LONG", "SHORT")
        assert "quantity" in pos
        assert pos["quantity"] > 0
        assert "entry_price" in pos
        assert pos["entry_price"] > 0
        assert "opened_at" in pos

    def test_positions_filters_only_open_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """positions must show only OPEN positions — not CLOSED ones."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade NIFTY breakout")
        router.handle_command("trade NIFTY momentum")

        result = router.handle_command("positions")

        assert isinstance(result, list)
        assert len(result) == 2
        for pos in result:
            assert "status" not in pos

    def test_positions_multiple_trades_all_visible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """positions must list all open positions, one per trade."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD momentum")
        router.handle_command("trade BTC/USD breakout")

        result = router.handle_command("positions")

        # Both trades produce separate open positions. The mock DummyResearchSource
        # always resolves to "MARKET" regardless of topic, so we assert on position
        # count rather than market symbol distinctness.
        assert len(result) == 2

    def test_positions_sorted_chronologically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """positions must be returned sorted by opened_at (ascending)."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD first")
        router.handle_command("trade BTC/USD second")

        result = router.handle_command("positions")

        assert len(result) == 2
        opened_ats = [pos["opened_at"] for pos in result]
        assert opened_ats == sorted(opened_ats)


# ---------------------------------------------------------------------------
# predictions command
# ---------------------------------------------------------------------------

class TestPredictionsCommand:
    def test_predictions_empty_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """predictions command must return zero counts when no full-trades run."""
        router = _make_router(tmp_path, monkeypatch)
        result = router.handle_command("predictions")

        assert isinstance(result, dict)
        assert result["total_predictions"] == 0
        assert result["passed"] == 0
        assert result["failed"] == 0
        assert result["average_win_rate"] == "N/A"

    def test_predictions_after_full_trade_shows_one_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """predictions command must count one record after one full-trade run."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("full-trade EUR/USD momentum")

        result = router.handle_command("predictions")

        assert isinstance(result, dict)
        assert result["total_predictions"] == 1
        assert result["passed"] + result["failed"] == 1
        assert isinstance(result["average_win_rate"], float)
        assert 0.0 <= result["average_win_rate"] <= 100.0

    def test_predictions_pass_fail_sum_equals_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """passed + failed must always equal total_predictions."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("full-trade EUR/USD momentum")
        router.handle_command("full-trade EUR/USD momentum")

        result = router.handle_command("predictions")

        assert result["passed"] + result["failed"] == result["total_predictions"]


# ---------------------------------------------------------------------------
# tax command
# ---------------------------------------------------------------------------

class TestTaxCommand:
    def test_tax_empty_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tax command must return zero totals when no trades have run."""
        router = _make_router(tmp_path, monkeypatch)
        result = router.handle_command("tax")

        assert isinstance(result, dict)
        assert result["total_events"] == 0
        assert result["total_tax"] == 0.0
        assert result["by_component"] == {}

    def test_tax_after_trade_shows_one_event(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tax command must count one event per trade."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD macro breakout")

        result = router.handle_command("tax")

        assert isinstance(result, dict)
        assert result["total_events"] == 1
        assert result["total_tax"] >= 0.0
        assert isinstance(result["by_component"], dict)
        assert len(result["by_component"]) >= 1

    def test_tax_component_values_are_non_negative(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All component tax amounts must be non-negative."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD macro breakout")

        result = router.handle_command("tax")

        for component_type, amount in result["by_component"].items():
            assert amount >= 0.0, f"Component '{component_type}' has negative tax: {amount}"

    def test_tax_total_equals_sum_of_components(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """total_tax must equal the sum of all by_component values."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD macro breakout")

        result = router.handle_command("tax")

        component_sum = round(sum(result["by_component"].values()), 6)
        assert abs(result["total_tax"] - component_sum) < 1e-5

    def test_tax_multiple_trades_accumulate_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tax event count must increment with each trade."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD trade one")
        router.handle_command("trade BTC/USD trade two")

        result = router.handle_command("tax")

        assert result["total_events"] == 2

    def test_tax_components_accumulate_across_trades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tax component amounts must accumulate across multiple trades."""
        router = _make_router(tmp_path, monkeypatch)
        router.handle_command("trade EUR/USD first")
        result1 = router.handle_command("tax")
        first_total = result1["total_tax"]

        router.handle_command("trade EUR/USD second")
        result2 = router.handle_command("tax")

        assert result2["total_tax"] > first_total


# ---------------------------------------------------------------------------
# Help text coverage
# ---------------------------------------------------------------------------

class TestHelpText:
    def test_help_includes_all_phase3b_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """help output must advertise portfolio, positions, predictions, and tax."""
        router = _make_router(tmp_path, monkeypatch)
        result = router.handle_command("help")

        assert isinstance(result, str)
        assert "portfolio" in result
        assert "positions" in result
        assert "predictions" in result
        assert "tax" in result
