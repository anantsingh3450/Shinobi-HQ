"""A formatting mistake must never cost the commander an alert.

Telegram rejects the ENTIRE message with 400 "can't parse entities" when an
interpolated value opens a Markdown entity it cannot close. Observed live:
  - 2026-07-30 09:37 — the login reply died on the literal "request_token"
    (underscore at byte offset 23), so the commander got no confirmation.
  - 2026-07-15 — every CRUDE_OIL exit alert was dropped the same way.
Kite's own auth error, "Incorrect `api_key` or `access_token`.", carries both
backticks and underscores, so the alerts most worth delivering are the most
likely to be rejected.

Escaping every call site is whack-a-mole; the transport itself must refuse to
lose a message.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from integrations.notifications.telegram_bot import TelegramBotUplink


def _uplink() -> TelegramBotUplink:
    up = TelegramBotUplink(bot_token="123456:fake", chat_id="777")
    up.enabled = True  # conftest scrubs credentials; force the HTTP path open
    return up


def _resp(status: int, text: str = ""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


_PARSE_ERROR = (
    '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse '
    'entities: Can\'t find end of the entity starting at byte offset 23"}'
)


def test_markdown_rejection_is_resent_as_plain_text():
    up = _uplink()
    with patch("integrations.notifications.telegram_bot.requests.post") as post:
        post.side_effect = [_resp(400, _PARSE_ERROR), _resp(200)]
        assert up.send_message("🚨 Incorrect `api_key` or `access_token`.") is True

    assert post.call_count == 2
    # The retry drops the formatting but keeps every character of the message.
    retry_payload = post.call_args_list[1].kwargs["json"]
    assert "parse_mode" not in retry_payload
    assert retry_payload["text"] == "🚨 Incorrect `api_key` or `access_token`."


def test_successful_markdown_send_is_not_retried():
    up = _uplink()
    with patch("integrations.notifications.telegram_bot.requests.post") as post:
        post.return_value = _resp(200)
        assert up.send_message("all good") is True
    assert post.call_count == 1


def test_non_parse_errors_are_not_retried_as_plain_text():
    """A 429 or 403 is not a formatting problem; resending changes nothing."""
    up = _uplink()
    with patch("integrations.notifications.telegram_bot.requests.post") as post:
        post.return_value = _resp(429, '{"description":"Too Many Requests"}')
        assert up.send_message("hello") is False
    assert post.call_count == 1


def test_plain_text_retry_failure_is_reported_not_swallowed():
    up = _uplink()
    with patch("integrations.notifications.telegram_bot.requests.post") as post:
        post.side_effect = [_resp(400, _PARSE_ERROR), _resp(500, "boom")]
        assert up.send_message("bad `markdown_") is False
    assert post.call_count == 2


def test_the_exact_string_that_failed_live_survives():
    """Regression: this literal was dropped in production on 2026-07-30."""
    up = _uplink()
    with patch("integrations.notifications.telegram_bot.requests.post") as post:
        post.return_value = _resp(200)
        up.send_message("🔄 Processing request\\_token...")
    body = post.call_args.kwargs["json"]["text"]
    # The underscore is escaped, so Telegram never opens an italic entity.
    assert "request\\_token" in body


def test_entry_alerts_escape_the_symbol_like_exit_alerts_already_did():
    up = _uplink()
    with patch.object(up, "send_message") as send:
        up.notify_entry("CRUDE_OIL", 7660.0, 7800.0, 62.0)
    assert "CRUDE\\_OIL" in send.call_args[0][0]
