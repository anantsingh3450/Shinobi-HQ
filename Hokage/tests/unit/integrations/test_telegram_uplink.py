"""Telegram uplink hermeticity: tests must never be able to send real messages.

Regression guard for the 2026-07-13 incident where the unit-test suite sent
real Telegram trade alerts to the commander (test fixtures leaked through a
real TELEGRAM_BOT_TOKEN loaded from .env at import time).
"""
from __future__ import annotations

from integrations.notifications.telegram_bot import TelegramBotUplink


def test_uplink_forced_off_by_disable_flag(monkeypatch):
    """HOKAGE_DISABLE_TELEGRAM=true must force mock-outbox mode even when real
    credentials are present."""
    monkeypatch.setenv("HOKAGE_DISABLE_TELEGRAM", "true")
    uplink = TelegramBotUplink(bot_token="123456:fake-token", chat_id="99999")
    assert uplink.enabled is False
    # send_message must short-circuit to the mock outbox (returns True, no HTTP).
    assert uplink.send_message("hermeticity check") is True
    # start() must not launch the polling thread when disabled.
    uplink.start()
    assert uplink._thread is None


def test_suite_environment_is_hermetic():
    """conftest must have scrubbed telegram credentials and set the disable flag."""
    import os
    assert os.environ.get("HOKAGE_DISABLE_TELEGRAM") == "true"
    assert "TELEGRAM_BOT_TOKEN" not in os.environ
    assert "TELEGRAM_CHAT_ID" not in os.environ


def test_session_validation_rejects_missing_secrets(monkeypatch):
    """Regression: 2026-07-13 false 'Login Successful' message.

    The daily 09:00 confirmation used to announce a live broker connection
    if an access-token string merely EXISTED in the secret store, even when
    that token was stale/expired. Validation must require a real Kite API
    round-trip; with no credentials it must return False.
    """
    uplink = TelegramBotUplink(bot_token=None, chat_id=None)

    class _EmptyVault:
        def get_secret(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.SecretManager", lambda: _EmptyVault()
    )
    assert uplink._validate_broker_session() is False


def test_session_validation_rejects_stale_token(monkeypatch):
    """A token that exists but fails the kite.profile() round-trip is invalid."""
    uplink = TelegramBotUplink(bot_token=None, chat_id=None)

    class _StaleVault:
        def get_secret(self, name, broker=None):
            return "stale-token-or-key"

    class _RejectingKite:
        def __init__(self, api_key=None):
            pass

        def set_access_token(self, token):
            pass

        def profile(self):
            raise RuntimeError("TokenException: Incorrect `api_key` or `access_token`.")

    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.SecretManager", lambda: _StaleVault()
    )
    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.KiteConnect", _RejectingKite
    )
    assert uplink._validate_broker_session() is False


def test_session_validation_accepts_live_token(monkeypatch):
    """A token that passes the kite.profile() round-trip is a live session."""
    uplink = TelegramBotUplink(bot_token=None, chat_id=None)

    class _LiveVault:
        def get_secret(self, name, broker=None):
            return "valid-value"

    class _AcceptingKite:
        def __init__(self, api_key=None):
            pass

        def set_access_token(self, token):
            pass

        def profile(self):
            return {"user_id": "AB1234"}

    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.SecretManager", lambda: _LiveVault()
    )
    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.KiteConnect", _AcceptingKite
    )
    assert uplink._validate_broker_session() is True
