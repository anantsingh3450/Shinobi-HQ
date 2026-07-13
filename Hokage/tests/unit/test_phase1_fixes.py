import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import sys

from bots.autonomous.capital_preservation import RiskManager
from bots.autonomous.autonomous_bot import AutonomousTradingBot
from integrations.brokers.models import OrderRequest, OrderSide, OrderType, OrderResponse, OrderStatus
from integrations.data.models import Instrument, AssetClass, Exchange

def test_kill_switch_liquidation_no_crash():
    bot_mock = MagicMock()
    bot_mock._active_positions_tracking = {
        "NIFTY": {"side": "BUY", "quantity": 2.0, "venue_id": "mock_venue"},
        "CRUDEOIL": {"side": "SELL", "quantity": 1.0, "venue_id": "mock_venue"}
    }
    venue_mock = MagicMock()
    venue_mock.venue_id = "mock_venue"
    bot_mock.orchestrator = MagicMock()
    bot_mock.orchestrator.registry.get_venue.return_value = venue_mock
    bot_mock._execute_partial_exit = MagicMock()

    engine = RiskManager(bot_mock, max_daily_drawdown_pct=15.0)
    
    result = engine.check_portfolio_health(current_equity=80000, starting_equity=100000)
    
    assert result is False
    assert engine._killed is True
    assert bot_mock.gatekeeper_state == "KILL_SWITCH_ENGAGED"
    assert bot_mock._execute_partial_exit.call_count == 2
    
    calls = bot_mock._execute_partial_exit.call_args_list
    symbols_called = [call.kwargs.get("symbol") for call in calls]
    assert "NIFTY" in symbols_called
    assert "CRUDEOIL" in symbols_called

# NOTE: the former test_order_response_rejected here was a hollow test (its body
# was `pass`) that always reported green while testing nothing. Real coverage of
# rejected/None order responses on the actual entry path now lives in
# tests/unit/bots/autonomous/test_autonomous_bot.py:
#   - test_scan_and_entry_rejected_order_no_phantom_position
#   - test_scan_and_entry_none_order_marks_unconfirmed

def test_hard_lot_cap_rule():
    from bots.risk.rules import HardLotCapRule
    from bots.risk.models import RiskVerdict
    
    rule = HardLotCapRule(resolver=None)
    
    proposal = MagicMock()
    proposal.market = "NIFTY"
    verdict = rule.check_order(account=MagicMock(), proposal=proposal, entry_price=100.0)
    assert verdict.is_approved is True
    assert verdict.max_approved_quantity == 1.0

    proposal.market = "CRUDEOIL"
    verdict = rule.check_order(account=MagicMock(), proposal=proposal, entry_price=100.0)
    assert verdict.is_approved is True
    assert verdict.max_approved_quantity == 1.0


