"""Unit tests for Execution Bot domain models."""
from __future__ import annotations

import pytest

from bots.execution.models import ExecutionMode, TradeDirection, TradeRecord, TradeStatus


class TestTradeRecord:
    def test_valid_trade_record(self) -> None:
        trade = TradeRecord(
            proposal_id="proposal-123",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=1000.0,
            entry_price=1.0850,
            simulated_value=1085.0,
            strategy_name="Bullish Strategy",
            sources_cited=("source-1",),
        )
        assert trade.proposal_id == "proposal-123"
        assert trade.market == "EUR/USD"
        assert trade.direction == TradeDirection.LONG
        assert trade.quantity == 1000.0
        assert trade.entry_price == 1.0850
        assert trade.simulated_value == 1085.0
        assert trade.mode == ExecutionMode.PAPER
        assert trade.status == TradeStatus.OPEN
        assert trade.strategy_name == "Bullish Strategy"
        assert trade.sources_cited == ("source-1",)
        assert trade.trade_id
        assert trade.executed_at

    def test_rejects_empty_market(self) -> None:
        with pytest.raises(ValueError, match="market must not be empty"):
            TradeRecord(
                proposal_id="proposal-123",
                market="   ",
                direction=TradeDirection.LONG,
                quantity=1.0,
                entry_price=1.0,
                simulated_value=1.0,
                strategy_name="Strategy",
                sources_cited=(),
            )

    def test_rejects_non_positive_quantity(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            TradeRecord(
                proposal_id="proposal-123",
                market="EUR/USD",
                direction=TradeDirection.LONG,
                quantity=0.0,
                entry_price=1.0,
                simulated_value=0.0,
                strategy_name="Strategy",
                sources_cited=(),
            )

        with pytest.raises(ValueError, match="quantity must be positive"):
            TradeRecord(
                proposal_id="proposal-123",
                market="EUR/USD",
                direction=TradeDirection.LONG,
                quantity=-5.0,
                entry_price=1.0,
                simulated_value=-5.0,
                strategy_name="Strategy",
                sources_cited=(),
            )

    def test_rejects_non_positive_entry_price(self) -> None:
        with pytest.raises(ValueError, match="entry_price must be positive"):
            TradeRecord(
                proposal_id="proposal-123",
                market="EUR/USD",
                direction=TradeDirection.LONG,
                quantity=1.0,
                entry_price=0.0,
                simulated_value=0.0,
                strategy_name="Strategy",
                sources_cited=(),
            )

        with pytest.raises(ValueError, match="entry_price must be positive"):
            TradeRecord(
                proposal_id="proposal-123",
                market="EUR/USD",
                direction=TradeDirection.LONG,
                quantity=1.0,
                entry_price=-1.0,
                simulated_value=-1.0,
                strategy_name="Strategy",
                sources_cited=(),
            )

    def test_rejects_live_mode(self) -> None:
        with pytest.raises(ValueError, match="Live trading capability exists but is not active in the current execution mode"):
            TradeRecord(
                proposal_id="proposal-123",
                market="EUR/USD",
                direction=TradeDirection.LONG,
                quantity=1.0,
                entry_price=1.0,
                simulated_value=1.0,
                strategy_name="Strategy",
                sources_cited=(),
                mode=ExecutionMode.LIVE,
            )

    def test_to_dict_and_from_dict_parity(self) -> None:
        trade = TradeRecord(
            proposal_id="proposal-123",
            market="BTC/USD",
            direction=TradeDirection.SHORT,
            quantity=0.5,
            entry_price=65000.0,
            simulated_value=32500.0,
            strategy_name="Short BTC",
            sources_cited=("source-1", "source-2"),
        )
        serialized = trade.to_dict()
        assert serialized["trade_id"] == trade.trade_id
        assert serialized["proposal_id"] == "proposal-123"
        assert serialized["market"] == "BTC/USD"
        assert serialized["direction"] == "SHORT"
        assert serialized["quantity"] == 0.5
        assert serialized["entry_price"] == 65000.0
        assert serialized["simulated_value"] == 32500.0
        assert serialized["mode"] == "PAPER"
        assert serialized["status"] == "OPEN"
        assert serialized["strategy_name"] == "Short BTC"
        assert serialized["sources_cited"] == ["source-1", "source-2"]

        deserialized = TradeRecord.from_dict(serialized)
        assert deserialized.trade_id == trade.trade_id
        assert deserialized.proposal_id == trade.proposal_id
        assert deserialized.market == trade.market
        assert deserialized.direction == trade.direction
        assert deserialized.quantity == trade.quantity
        assert deserialized.entry_price == trade.entry_price
        assert deserialized.simulated_value == trade.simulated_value
        assert deserialized.mode == trade.mode
        assert deserialized.status == trade.status
        assert deserialized.strategy_name == trade.strategy_name
        assert deserialized.sources_cited == trade.sources_cited
        assert deserialized.executed_at == trade.executed_at
