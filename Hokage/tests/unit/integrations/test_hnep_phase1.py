from __future__ import annotations
from unittest.mock import MagicMock, patch
from integrations.brokers.base_venue import BaseVenue
from integrations.brokers.paper_venue import PaperVenue
from integrations.brokers.kite_venue import KiteVenue
from integrations.notifications.telegram_bot import TelegramBotUplink

def test_venue_inheritance():
    """Verify that PaperVenue and KiteVenue cleanly inherit from BaseVenue."""
    assert BaseVenue in PaperVenue.__mro__
    assert BaseVenue in KiteVenue.__mro__

@patch("integrations.notifications.telegram_bot.requests.post")
def test_telegram_bot_send_message(mock_post):
    """Verify TelegramBotUplink send_message formatting and execution."""
    mock_post.return_value = MagicMock(status_code=200)
    
    bot = TelegramBotUplink(bot_token="test_token", chat_id="12345")
    assert bot.enabled is True
    
    res = bot.send_message("Hello World")
    assert res is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "test_token" in args[0]
    assert kwargs["json"]["chat_id"] == "12345"
    assert kwargs["json"]["text"] == "Hello World"

@patch("integrations.notifications.telegram_bot.requests.get")
def test_telegram_bot_totp_polling(mock_get):
    """Verify TelegramBotUplink extracts 6-digit TOTP token during polling."""
    # Mock Telegram Bot getUpdates response containing a 6-digit TOTP
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "result": [
            {
                "update_id": 1001,
                "message": {
                    "chat": {"id": 12345},
                    "text": "654321"
                }
            }
        ]
    }
    mock_get.return_value = mock_response
    
    bot = TelegramBotUplink(bot_token="test_token", chat_id="12345")
    bot._check_telegram_updates()
    
    assert bot._last_update_id == 1001
    assert bot.latest_totp == "654321"
