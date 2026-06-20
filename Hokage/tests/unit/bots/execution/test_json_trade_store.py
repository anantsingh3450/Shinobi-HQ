"""Unit tests for the JsonTradeStore."""
from __future__ import annotations

from pathlib import Path

from bots.execution.models import TradeDirection, TradeRecord
from bots.execution.store.json_trade_store import JsonTradeStore


class TestJsonTradeStore:
    def test_json_trade_store_lifecycle(self, tmp_path: Path) -> None:
        # Arrange
        store_dir = tmp_path / "trades"
        store = JsonTradeStore(store_dir)

        # 1. Loading from empty store returns empty tuple
        assert not store.trades_file.exists()
        assert store.load_all() == ()

        # 2. Save first trade
        t1 = TradeRecord(
            proposal_id="p-1",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=100.0,
            entry_price=1.08,
            simulated_value=108.0,
            strategy_name="Strat 1",
            sources_cited=("src-a",),
        )
        store.save(t1)

        assert store.trades_file.exists()

        # 3. Save second trade
        t2 = TradeRecord(
            proposal_id="p-2",
            market="GBP/USD",
            direction=TradeDirection.SHORT,
            quantity=50.0,
            entry_price=1.27,
            simulated_value=63.5,
            strategy_name="Strat 2",
            sources_cited=("src-b", "src-c"),
        )
        store.save(t2)

        # 4. Load all and assert correctness
        loaded = store.load_all()
        assert len(loaded) == 2

        assert loaded[0].proposal_id == "p-1"
        assert loaded[0].market == "EUR/USD"
        assert loaded[0].direction == TradeDirection.LONG
        assert loaded[0].quantity == 100.0
        assert loaded[0].entry_price == 1.08
        assert loaded[0].simulated_value == 108.0
        assert loaded[0].strategy_name == "Strat 1"
        assert loaded[0].sources_cited == ("src-a",)
        assert loaded[0].trade_id == t1.trade_id

        assert loaded[1].proposal_id == "p-2"
        assert loaded[1].market == "GBP/USD"
        assert loaded[1].direction == TradeDirection.SHORT
        assert loaded[1].quantity == 50.0
        assert loaded[1].entry_price == 1.27
        assert loaded[1].simulated_value == 63.5
        assert loaded[1].strategy_name == "Strat 2"
        assert loaded[1].sources_cited == ("src-b", "src-c")
        assert loaded[1].trade_id == t2.trade_id
        # Confirm dates match
        assert loaded[0].executed_at == t1.executed_at
        assert loaded[1].executed_at == t2.executed_at
