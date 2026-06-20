"""Unit tests for Portfolio and Account domain models."""
from __future__ import annotations

from datetime import UTC, datetime

from bots.execution.models import TradeDirection, TradeRecord, TradeStatus
from bots.portfolio.models import Account, Position


class TestPosition:
    def test_position_pnl_long(self) -> None:
        pos = Position(
            position_id="t-1",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=1000.0,
            entry_price=1.0800,
            current_price=1.0800,
            opened_at=datetime.now(UTC),
        )
        assert pos.unrealized_pnl == 0.0

        # Price moves up
        pos.update_price(1.0850)
        assert pos.unrealized_pnl == 5.0  # (1.0850 - 1.0800) * 1000

        # Close position
        pos.close(1.0900, datetime.now(UTC))
        assert pos.status == TradeStatus.CLOSED
        assert pos.realized_pnl == 10.0
        assert pos.unrealized_pnl == 0.0

    def test_position_pnl_short(self) -> None:
        pos = Position(
            position_id="t-2",
            market="BTC/USD",
            direction=TradeDirection.SHORT,
            quantity=0.5,
            entry_price=65000.0,
            current_price=65000.0,
            opened_at=datetime.now(UTC),
        )
        assert pos.unrealized_pnl == 0.0

        # Price moves down (profit for short)
        pos.update_price(64000.0)
        assert pos.unrealized_pnl == 500.0  # (65000 - 64000) * 0.5

        # Close position at loss
        pos.close(66000.0, datetime.now(UTC))
        assert pos.status == TradeStatus.CLOSED
        assert pos.realized_pnl == -500.0
        assert pos.unrealized_pnl == 0.0


class TestAccount:
    def test_account_initial_state(self) -> None:
        acc = Account(account_id="acc-1", initial_balance=10000.0, cash=10000.0)
        assert acc.equity == 10000.0
        assert not acc.positions

    def test_apply_trade_multiple_positions_same_market(self) -> None:
        acc = Account(account_id="acc-1", initial_balance=10000.0, cash=10000.0)

        # 1. First long trade EUR/USD
        t1 = TradeRecord(
            proposal_id="p-1",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=1000.0,
            entry_price=1.0800,
            simulated_value=1080.0,
            strategy_name="Long 1",
            sources_cited=(),
            trade_id="trade-1",
        )
        acc.apply_trade(t1)

        assert len(acc.positions) == 1
        assert "trade-1" in acc.positions
        assert acc.positions["trade-1"].quantity == 1000.0
        assert acc.equity == 10000.0  # Cash is still 10000.0, unrealized is 0

        # 2. Second long trade EUR/USD (simulates scaling in/multiple entries)
        t2 = TradeRecord(
            proposal_id="p-2",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=500.0,
            entry_price=1.0900,
            simulated_value=545.0,
            strategy_name="Long 2",
            sources_cited=(),
            trade_id="trade-2",
        )
        acc.apply_trade(t2)

        # Should create a separate Position object
        assert len(acc.positions) == 2
        assert "trade-2" in acc.positions
        assert acc.positions["trade-2"].entry_price == 1.0900
        assert acc.positions["trade-2"].quantity == 500.0

    def test_apply_trade_fifo_exit_matching(self) -> None:
        acc = Account(account_id="acc-1", initial_balance=10000.0, cash=10000.0)

        # Open t1 (LONG 1000 units @ 1.08)
        t1 = TradeRecord(
            proposal_id="p-1",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=1000.0,
            entry_price=1.0800,
            simulated_value=1080.0,
            strategy_name="Long 1",
            sources_cited=(),
            trade_id="trade-1",
            executed_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        )
        acc.apply_trade(t1)

        # Open t2 (LONG 500 units @ 1.09)
        t2 = TradeRecord(
            proposal_id="p-2",
            market="EUR/USD",
            direction=TradeDirection.LONG,
            quantity=500.0,
            entry_price=1.0900,
            simulated_value=545.0,
            strategy_name="Long 2",
            sources_cited=(),
            trade_id="trade-2",
            executed_at=datetime(2026, 6, 18, 12, 5, tzinfo=UTC),
        )
        acc.apply_trade(t2)

        # Match opposite trade (SHORT 1200 units @ 1.10)
        # Under FIFO, it fully closes trade-1 (1000 units) and partially closes trade-2 (200 units)
        t_exit = TradeRecord(
            proposal_id="p-3",
            market="EUR/USD",
            direction=TradeDirection.SHORT,
            quantity=1200.0,
            entry_price=1.1000,
            simulated_value=1320.0,
            strategy_name="Exit Short",
            sources_cited=(),
            trade_id="trade-3",
            executed_at=datetime(2026, 6, 18, 12, 10, tzinfo=UTC),
        )
        acc.apply_trade(t_exit)

        # trade-1 fully closed: realized PnL = (1.10 - 1.08) * 1000 = +20.0
        # trade-2 partially closed: realized PnL = (1.10 - 1.09) * 200 = +2.0
        # Total realized PnL = +22.0
        assert acc.realized_pnl == 22.0
        assert acc.cash == 10022.0

        # trade-1 should be removed/inactive
        assert "trade-1" not in acc.positions or acc.positions["trade-1"].status == TradeStatus.CLOSED

        # trade-2 should remain with 300 units open
        assert "trade-2" in acc.positions
        open_pos = acc.positions["trade-2"]
        assert open_pos.status == TradeStatus.OPEN
        assert open_pos.quantity == 300.0
        assert open_pos.entry_price == 1.0900

    def test_account_serialization_roundtrip(self) -> None:
        acc = Account(account_id="acc-test", initial_balance=5000.0, cash=4900.0, realized_pnl=-100.0)
        pos = Position(
            position_id="pos-1",
            market="GBP/USD",
            direction=TradeDirection.LONG,
            quantity=50.0,
            entry_price=1.2500,
            current_price=1.2600,
            unrealized_pnl=0.5,
            opened_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
        )
        acc.positions["pos-1"] = pos

        sdict = acc.to_dict()
        deserialized = Account.from_dict(sdict)

        assert deserialized.account_id == "acc-test"
        assert deserialized.cash == 4900.0
        assert deserialized.realized_pnl == -100.0
        assert len(deserialized.positions) == 1
        dpos = deserialized.positions["pos-1"]
        assert dpos.market == "GBP/USD"
        assert dpos.direction == TradeDirection.LONG
        assert dpos.quantity == 50.0
        assert dpos.entry_price == 1.2500
        assert dpos.current_price == 1.2600
        assert dpos.unrealized_pnl == 0.5
        assert dpos.opened_at == pos.opened_at
