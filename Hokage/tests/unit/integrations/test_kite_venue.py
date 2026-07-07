from __future__ import annotations

import json
import pytest
from pathlib import Path
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from integrations.brokers.secrets import SecretManager
from integrations.brokers.kite_connection import KiteConnectionManager
from integrations.brokers.kite_account import KiteAccountService
from integrations.brokers.kite_market_data_provider import KiteMarketDataProvider
from integrations.brokers.kite_venue import KiteVenue
from integrations.brokers.models import ConnectionState, OrderRequest, OrderSide, OrderType
from integrations.data.models import Instrument, AssetClass, Exchange, HistoricalDataRequest, CandleInterval


def test_secret_manager_default_path():
    sm = SecretManager()
    assert sm.secrets_file_path is not None
    assert isinstance(sm.secrets_file_path, Path)


def test_secret_manager_custom_path_bootstrapping(tmp_path: Path):
    secrets_file = tmp_path / "secrets.json"
    sm = SecretManager(secrets_file_path=secrets_file)
    
    # First time loading raises FileNotFoundError because it bootstraps the template
    with pytest.raises(FileNotFoundError, match="Secrets file not found"):
        sm.load_secrets()
        
    assert secrets_file.exists()
    # Reading template returns None for secrets since they match placeholders
    assert sm.get_secret("api_key") is None


def test_secret_manager_read_valid_secrets(tmp_path: Path):
    secrets_file = tmp_path / "secrets.json"
    with secrets_file.open("w") as fh:
        json.dump({"api_key": "real_key", "access_token": "real_token"}, fh)
        
    sm = SecretManager(secrets_file_path=secrets_file)
    assert sm.get_secret("api_key") == "real_key"
    assert sm.get_secret("access_token") == "real_token"


@patch("integrations.brokers.kite_connection.KiteConnect")
def test_kite_connection_manager_success(mock_kite_class, tmp_path: Path):
    secrets_file = tmp_path / "secrets.json"
    with secrets_file.open("w") as fh:
        json.dump({"api_key": "real_key", "access_token": "real_token"}, fh)
        
    sm = SecretManager(secrets_file_path=secrets_file)
    cm = KiteConnectionManager(sm)
    
    # Mock profile call succeeds
    mock_kite = MagicMock()
    mock_kite.profile.return_value = {"user_id": "test_user"}
    mock_kite_class.return_value = mock_kite
    
    status = cm.connect()
    assert status.state == ConnectionState.CONNECTED
    assert cm.connection_state == ConnectionState.CONNECTED
    assert cm.get_kite_client() is mock_kite


@patch("integrations.brokers.kite_connection.KiteConnect")
def test_kite_connection_manager_auth_failure(mock_kite_class, tmp_path: Path):
    secrets_file = tmp_path / "secrets.json"
    with secrets_file.open("w") as fh:
        json.dump({"api_key": "real_key", "access_token": "real_token"}, fh)
        
    sm = SecretManager(secrets_file_path=secrets_file)
    cm = KiteConnectionManager(sm)
    
    # Mock profile call fails
    mock_kite = MagicMock()
    mock_kite.profile.side_effect = Exception("Invalid token")
    mock_kite_class.return_value = mock_kite
    
    with pytest.raises(RuntimeError, match="Authentication failed: Invalid token"):
        cm.connect()
        
    assert cm.connection_state == ConnectionState.DISCONNECTED


def test_kite_venue_safety_locks(tmp_path: Path):
    # Set up credentials mock so venue doesn't crash on connecting
    secrets_file = tmp_path / "secrets.json"
    with secrets_file.open("w") as fh:
        json.dump({"api_key": "real_key", "access_token": "real_token"}, fh)
        
    sm = SecretManager(secrets_file_path=secrets_file)
    cm = KiteConnectionManager(sm)
    venue = KiteVenue(connection_manager=cm)
    
    inst = Instrument(symbol="TCS", asset_class=AssetClass.INDIAN_EQUITY, exchange=Exchange.NSE)
    req = OrderRequest(instrument=inst, side=OrderSide.BUY, quantity=1.0, order_type=OrderType.MARKET)
    
    # Safety locks raise RuntimeError even if not connected
    with pytest.raises(RuntimeError, match="Live trading disabled"):
        venue.place_order(req)
        
    with pytest.raises(RuntimeError, match="Live trading disabled"):
        venue.cancel_order("order-1")
        
    with pytest.raises(RuntimeError, match="Live trading disabled"):
        venue.modify_order()


@patch("integrations.brokers.kite_connection.KiteConnect")
def test_kite_account_service_data(mock_kite_class, tmp_path: Path):
    secrets_file = tmp_path / "secrets.json"
    with secrets_file.open("w") as fh:
        json.dump({"api_key": "real_key", "access_token": "real_token"}, fh)
        
    sm = SecretManager(secrets_file_path=secrets_file)
    cm = KiteConnectionManager(sm)
    
    mock_kite = MagicMock()
    # Mock profile
    mock_kite.profile.return_value = {"user_id": "test_user", "email": "test@test.com"}
    # Mock margins
    mock_kite.margins.return_value = {
        "equity": {
            "net": 150000.0,
            "available": {"cash": 120000.0},
            "utilised": {"debits": 30000.0}
        }
    }
    # Mock positions
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
    # Mock holdings
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
    cm.connect()
    
    venue = KiteVenue(connection_manager=cm)
    
    # Test balance parsing
    bal = venue.get_account_balance()
    assert bal.total_equity == 150000.0
    assert bal.cash == 120000.0
    assert bal.margin_used == 30000.0
    
    # Test positions parsing
    positions = venue.get_positions()
    assert len(positions) == 1
    assert positions[0].instrument.symbol == "INFY"
    assert positions[0].quantity == 10
    assert positions[0].unrealized_pnl == 200.0
    
    # Test holdings parsing
    holdings = venue.get_holdings()
    assert len(holdings) == 1
    assert holdings[0].instrument.symbol == "TCS"
    assert holdings[0].quantity == 5
    assert holdings[0].unrealized_pnl == 500.0


@patch("integrations.brokers.kite_connection.KiteConnect")
def test_kite_market_data_provider(mock_kite_class, tmp_path: Path):
    secrets_file = tmp_path / "secrets.json"
    with secrets_file.open("w") as fh:
        json.dump({"api_key": "real_key", "access_token": "real_token"}, fh)
        
    sm = SecretManager(secrets_file_path=secrets_file)
    cm = KiteConnectionManager(sm)
    
    mock_kite = MagicMock()
    mock_kite.quote.return_value = {
        "NSE:TCS": {
            "last_price": 3300.0,
            "instrument_token": 123456,
            "buy": [{"price": 3299.0}],
            "sell": [{"price": 3301.0}],
            "volume": 50000.0
        }
    }
    mock_kite.historical_data.return_value = [
        {"date": "2026-06-21T10:00:00+00:00", "open": 3290.0, "high": 3310.0, "low": 3280.0, "close": 3300.0, "volume": 1000.0}
    ]
    mock_kite_class.return_value = mock_kite
    cm.connect()
    
    provider = KiteMarketDataProvider(cm)
    
    # Test quote
    quote = provider.get_quote("NSE:TCS")
    assert quote.price == 3300.0
    assert quote.bid == 3299.0
    assert quote.ask == 3301.0
    
    # Test historical data
    inst = provider.resolve_instrument("NSE:TCS")
    req = HistoricalDataRequest(
        instrument=inst,
        start=datetime(2026, 6, 21, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 21, 11, 0, tzinfo=UTC),
        interval=CandleInterval.ONE_HOUR
    )
    res = provider.get_historical_candles(req)
    assert len(res.candles) == 1
    assert res.candles[0].open == 3290.0
    assert res.candles[0].close == 3300.0
    
    # Test watchlist
    provider.add_to_watchlist("NSE:TCS")
    assert "NSE:TCS" in provider.get_watchlist()
    provider.remove_from_watchlist("NSE:TCS")
    assert "NSE:TCS" not in provider.get_watchlist()


def test_secrets_isolation_from_brain_root():
    from hokage.memory.resolver import PathResolver
    resolver = PathResolver()
    brain_root = resolver.resolve_brain_root().resolve()
    
    sm = SecretManager()
    secrets_path = sm.secrets_file_path.resolve()
    
    # Assert that default credentials folder is NOT inside brain root folder to avoid leaks
    assert brain_root not in secrets_path.parents
    assert secrets_path != brain_root
