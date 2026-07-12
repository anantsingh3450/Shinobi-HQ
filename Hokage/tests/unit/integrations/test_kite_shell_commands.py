from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter
from integrations.brokers.kite_venue import KiteVenue
from integrations.brokers.models import OrderRequest, OrderSide, OrderType
from integrations.data.models import Instrument, AssetClass, Exchange


@patch("integrations.brokers.secrets.SecretManager.get_secret", return_value="mock_credential")
@patch("integrations.brokers.kite_connection.KiteConnect")
def test_orchestrator_get_kite_profile(mock_kite_class, mock_secret):
    # Mock connection manager connect profile check
    mock_kite = MagicMock()
    mock_kite.profile.return_value = {
        "user_name": "Test User",
        "user_id": "TU1234",
        "broker": "ZERODHA",
        "user_type": "individual"
    }
    mock_kite_class.return_value = mock_kite

    orch = HokageOrchestrator()
    # Connect
    orch.kite_venue.connect()

    profile = orch.get_kite_profile()
    assert profile["user_name"] == "Test User"
    assert profile["user_id"] == "TU1234"
    assert profile["broker"] == "ZERODHA"
    assert profile["account_type"] == "individual"


@patch("integrations.brokers.secrets.SecretManager.get_secret", return_value="mock_credential")
@patch("integrations.brokers.kite_connection.KiteConnect")
def test_orchestrator_get_kite_funds(mock_kite_class, mock_secret):
    mock_kite = MagicMock()
    mock_kite.margins.return_value = {
        "equity": {
            "net": 150000.0,
            "available": {"cash": 120000.0},
            "utilised": {"debits": 30000.0}
        }
    }
    mock_kite_class.return_value = mock_kite

    orch = HokageOrchestrator()
    orch.kite_venue.connect()

    funds = orch.get_kite_funds()
    assert funds["available_cash"] == 120000.0
    assert funds["utilized_margin"] == 30000.0
    assert funds["available_margin"] == 120000.0


@patch("integrations.brokers.secrets.SecretManager.get_secret", return_value="mock_credential")
@patch("integrations.brokers.kite_connection.KiteConnect")
def test_orchestrator_get_kite_holdings(mock_kite_class, mock_secret):
    mock_kite = MagicMock()
    mock_kite.holdings.return_value = [
        {
            "tradingsymbol": "TCS",
            "exchange": "NSE",
            "quantity": 5,
            "average_price": 3200.0,
            "last_price": 3300.0,
            "pnl": 500.0,
            "isin": "INE467B01029"
        }
    ]
    mock_kite_class.return_value = mock_kite

    orch = HokageOrchestrator()
    orch.kite_venue.connect()

    holdings = orch.get_kite_holdings()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "TCS"
    assert holdings[0]["quantity"] == 5
    assert holdings[0]["average_cost"] == 3200.0
    assert holdings[0]["current_value"] == 16500.0
    assert holdings[0]["unrealized_pnl"] == 500.0


@patch("integrations.brokers.secrets.SecretManager.get_secret", return_value="mock_credential")
@patch("integrations.brokers.kite_connection.KiteConnect")
def test_orchestrator_get_kite_positions(mock_kite_class, mock_secret):
    mock_kite = MagicMock()
    mock_kite.positions.return_value = {
        "net": [
            {
                "tradingsymbol": "INFY",
                "exchange": "NSE",
                "quantity": 10,
                "average_price": 1400.0,
                "last_price": 1420.0,
                "unrealised": 200.0
            }
        ]
    }
    mock_kite_class.return_value = mock_kite

    orch = HokageOrchestrator()
    orch.kite_venue.connect()

    positions = orch.get_kite_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "INFY"
    assert positions[0]["quantity"] == 10
    assert positions[0]["side"] == "BUY"
    assert positions[0]["pnl"] == 200.0


@patch("integrations.brokers.secrets.SecretManager.get_secret", return_value="mock_credential")
@patch("integrations.brokers.kite_connection.KiteConnect")
def test_orchestrator_get_kite_quote(mock_kite_class, mock_secret):
    mock_kite = MagicMock()
    mock_kite.quote.return_value = {
        "NSE:TCS": {
            "last_price": 3300.0,
            "ohlc": {"close": 3200.0}
        }
    }
    mock_kite_class.return_value = mock_kite

    orch = HokageOrchestrator()
    orch.kite_venue.connect()

    quote = orch.get_kite_quote("TCS")
    assert quote["symbol"] == "TCS"
    assert quote["last_traded_price"] == 3300.0
    assert quote["change"] == 100.0
    assert quote["percentage_change"] == 3.12


def test_orchestrator_get_market_status():
    orch = HokageOrchestrator()
    status = orch.get_market_status()
    assert status["market"] == "NSE/BSE"
    assert status["status"] in ("OPEN", "CLOSED", "PRE_OPEN", "POST_CLOSE", "MAINTENANCE")
    assert "is_open" in status
    assert "time_ist" in status


def test_command_router_kite_queries():
    orch = MagicMock()
    orch.get_kite_profile.return_value = {
        "user_name": "Test User",
        "user_id": "TU1234",
        "broker": "ZERODHA",
        "account_type": "individual"
    }
    orch.get_kite_funds.return_value = {
        "available_cash": 120000.0,
        "utilized_margin": 30000.0,
        "available_margin": 120000.0
    }
    orch.get_kite_holdings.return_value = [
        {"symbol": "TCS", "quantity": 5, "average_cost": 3200.0, "current_value": 16500.0, "unrealized_pnl": 500.0}
    ]
    orch.get_kite_positions.return_value = [
        {"symbol": "INFY", "quantity": 10, "side": "BUY", "pnl": 200.0}
    ]
    orch.get_kite_quote.return_value = {
        "symbol": "TCS",
        "last_traded_price": 3300.0,
        "change": 100.0,
        "percentage_change": 3.12
    }
    orch.get_market_status.return_value = {
        "market": "NSE/BSE",
        "status": "OPEN",
        "time_ist": "2026-06-21 21:38:46",
        "reason": "Active trading hours"
    }
    orch.get_kite_watchlist.return_value = ["TCS", "INFY"]

    router = CommandRouter(orch)

    # 1. Profile Queries
    for cmd in ("show my zerodha account", "show account profile", "show profile", "profile"):
        res = router.handle_command(cmd)
        assert "=== Zerodha Account Profile ===" in res
        assert "User Name: Test User" in res
        assert "User ID: TU1234" in res

    # 2. Funds Queries
    for cmd in ("show funds", "show balance", "show available cash", "show zerodha funds"):
        res = router.handle_command(cmd)
        assert "=== Zerodha Funds & Margin ===" in res
        assert "Available Cash: INR 120000.00" in res

    # 3. Holdings Queries
    for cmd in ("show holdings", "show zerodha holdings", "what stocks do i own"):
        res = router.handle_command(cmd)
        assert "=== Zerodha Holdings ===" in res
        assert "TCS" in res
        assert "3200.00" in res

    # 4. Positions Queries
    for cmd in ("show positions", "show zerodha positions", "open positions"):
        res = router.handle_command(cmd)
        assert "=== Zerodha Open Positions ===" in res
        assert "INFY" in res
        assert "BUY" in res

    # 5. Price Queries
    for cmd in ("show price of TCS", "current price of TCS", "quote TCS", "price TCS"):
        res = router.handle_command(cmd)
        assert "=== Zerodha Market Quote ===" in res
        assert "Symbol: TCS" in res
        assert "Last Traded Price: INR 3300.00" in res
        assert "Change: INR +100.00 (+3.12%)" in res

    # 6. Market Status Queries
    for cmd in ("market status", "market open?", "is nse open?"):
        res = router.handle_command(cmd)
        assert "=== Market Status ===" in res
        assert "Status: OPEN" in res

    # 7. Watchlist Queries
    res = router.handle_command("watchlist")
    assert "=== Watchlist ===" in res
    assert "- TCS" in res
    assert "- INFY" in res


def test_safety_locks_regression():
    # Ensure KiteVenue safety locks raise RuntimeError regardless of parameters or connection
    venue = KiteVenue()
    inst = Instrument(symbol="TCS", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    req = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=1.0, order_type=OrderType.MARKET)
    
    with pytest.raises(RuntimeError, match="Live trading disabled"):
        venue.place_order(req)
        
    with pytest.raises(RuntimeError, match="Live trading disabled"):
        venue.cancel_order("order-1")
        
    with pytest.raises(RuntimeError, match="Live trading disabled"):
        venue.modify_order()
