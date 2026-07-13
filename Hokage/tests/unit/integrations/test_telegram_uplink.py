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
