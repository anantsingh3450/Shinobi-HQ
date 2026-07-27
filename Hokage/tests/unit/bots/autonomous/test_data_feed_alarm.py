"""Hokage must say so when it goes blind.

On 2026-07-27 the Zerodha data token had been dead for seven days. Every scan
failed with `Incorrect api_key or access_token`, the entry path correctly failed
closed — and nothing told the commander. The only mid-session token alarm,
`_check_broker_session_health`, returns early unless execution_mode is LIVE, and
Hokage is paper-locked, so it was dead code in the only mode it ever runs.

Paper trading is real data with fake money: a dead feed is a dead system no
matter where the orders go.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from bots.autonomous.autonomous_bot import AutonomousTradingBot

_PROBE = AutonomousTradingBot._check_data_feed_session


def _stub(price_error: Exception | None = None, send_ok: bool = True) -> SimpleNamespace:
    price_source = MagicMock()
    if price_error is not None:
        price_source.get_price.side_effect = price_error
    else:
        price_source.get_price.return_value = 25000.0

    telegram = MagicMock()
    telegram.send_message.return_value = send_ok

    bot = SimpleNamespace(
        orchestrator=SimpleNamespace(price_source=price_source),
        telegram_bot=telegram,
        _AUTH_ERROR_TAGS=AutonomousTradingBot._AUTH_ERROR_TAGS,
        _NETWORK_ERROR_TAGS=AutonomousTradingBot._NETWORK_ERROR_TAGS,
        _last_feed_alert_date=None,
        _now_ist=lambda: datetime(2026, 7, 27, 12, 0, 0),
    )
    # Bind the real classifier; tests that need the ambiguous path override it
    # so no test ever reaches out to Kite.
    bot._diagnose_feed_failure = lambda reason: AutonomousTradingBot._diagnose_feed_failure(bot, reason)
    return bot


def test_expired_token_alerts_the_commander():
    bot = _stub(price_error=Exception("Incorrect `api_key` or `access_token`."))
    _PROBE(bot)

    bot.telegram_bot.send_message.assert_called_once()
    body = bot.telegram_bot.send_message.call_args[0][0]
    assert "LOGIN NEEDED" in body
    assert "log in" in body.lower()
    assert bot._last_feed_alert_date == "2026-07-27"


def test_network_outage_is_reported_as_unreachable_not_as_a_login_problem():
    """Telling the commander to re-login when the WiFi is down wastes his time."""
    bot = _stub(price_error=Exception("getaddrinfo failed"))
    _PROBE(bot)

    body = bot.telegram_bot.send_message.call_args[0][0]
    assert "UNREACHABLE" in body
    assert "LOGIN NEEDED" not in body


def test_wrapped_auth_failure_is_still_reported_as_a_login_problem():
    """The live restart on 2026-07-27 surfaced a rejected token as the generic
    "Venue is not connected." — matching neither tag set. Classifying that as a
    network fault would have sent the commander to check his WiFi while the real
    fix was a two-minute login."""
    bot = _stub(price_error=Exception("Venue is not connected."))
    bot._diagnose_feed_failure = lambda reason: "auth"
    _PROBE(bot)

    assert "LOGIN NEEDED" in bot.telegram_bot.send_message.call_args[0][0]


def test_feed_failure_with_valid_credentials_does_not_blame_the_token():
    bot = _stub(price_error=Exception("Venue is not connected."))
    bot._diagnose_feed_failure = lambda reason: "unknown"
    _PROBE(bot)

    body = bot.telegram_bot.send_message.call_args[0][0]
    assert "LOGIN NEEDED" not in body
    assert "not a token problem" in body


def test_classifier_reads_plain_message_without_calling_kite():
    """Tag-matched failures must never trigger the network round trip."""
    bot = _stub()
    assert AutonomousTradingBot._diagnose_feed_failure(bot, "Incorrect `api_key`.") == "auth"
    assert AutonomousTradingBot._diagnose_feed_failure(bot, "Max retries exceeded") == "network"


def test_alert_fires_once_per_day_not_once_per_minute():
    """The probe runs every 60s loop iteration; it must not spam."""
    bot = _stub(price_error=Exception("Incorrect `api_key` or `access_token`."))
    for _ in range(5):
        _PROBE(bot)
    assert bot.telegram_bot.send_message.call_count == 1


def test_failed_send_is_retried_rather_than_silently_swallowed():
    """Same mark-before-send trap that swallowed the login prompt."""
    bot = _stub(price_error=Exception("Incorrect `api_key` or `access_token`."), send_ok=False)
    _PROBE(bot)
    assert bot._last_feed_alert_date is None

    bot.telegram_bot.send_message.return_value = True
    _PROBE(bot)
    assert bot._last_feed_alert_date == "2026-07-27"
    assert bot.telegram_bot.send_message.call_count == 2


def test_healthy_feed_is_silent_and_rearms_the_alarm():
    bot = _stub()
    bot._last_feed_alert_date = "2026-07-27"
    _PROBE(bot)

    bot.telegram_bot.send_message.assert_not_called()
    # Latch cleared, so an outage later the same day still gets announced.
    assert bot._last_feed_alert_date is None
