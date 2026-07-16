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


def test_bare_callback_url_is_processed_as_login_token(monkeypatch):
    """Regression: 2026-07-13 pasted Kite callback URL without '/token ' prefix
    was routed to the conversational LLM, which hallucinated a successful
    broker connection while the request_token was silently discarded. Any
    message containing request_token= must hit the token handler."""
    uplink = TelegramBotUplink(bot_token="123456:fake", chat_id="777")

    bare_url = (
        "http://127.0.0.1:5000/api/v1/broker/zerodha/callback?"
        "request_token=abc123token&action=login&status=success"
    )

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "result": [
                    {
                        "update_id": 1,
                        "message": {"chat": {"id": 777}, "text": bare_url},
                    }
                ]
            }

    captured = {}

    class _FakeKite:
        def __init__(self, api_key=None):
            pass

        def generate_session(self, request_token, api_secret=None):
            captured["request_token"] = request_token
            return {"access_token": "new-live-token"}

    class _Vault:
        def get_secret(self, name, broker=None):
            return "secret-value"

        def set_secret(self, name, value, broker=None):
            captured["stored_access_token"] = value

    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.requests.get",
        lambda *a, **k: _FakeResponse(),
    )
    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.KiteConnect", _FakeKite
    )
    monkeypatch.setattr(
        "integrations.notifications.telegram_bot.SecretManager", lambda: _Vault()
    )
    monkeypatch.setattr(
        "integrations.brokers.secrets.update_env_file", lambda *a, **k: None
    )
    uplink.llm_processor = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    # The handler writes ZERODHA_ACCESS_TOKEN to os.environ; registering the
    # key with monkeypatch first guarantees teardown restores the suite env.
    monkeypatch.setenv("ZERODHA_ACCESS_TOKEN", "sentinel-before-login")

    uplink._check_telegram_updates()

    assert captured["request_token"] == "abc123token"
    assert captured["stored_access_token"] == "new-live-token"
    # The LLM must never see a login URL.
    uplink.llm_processor.generate_response.assert_not_called()


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


class TestMarkdownEscaping:
    """Values carrying _ * ` [ must not open a Markdown entity.

    Messages go out with parse_mode "Markdown". On 2026-07-15 the reason string
    "Underlying Thesis Stop: CRUDE_OIL moved 40.00 against position" left an
    unclosed italic run; Telegram replied 400 "can't parse entities" and the
    whole exit alert was dropped, so real CRUDE_OIL exits went unannounced.
    """

    def test_underscores_in_a_value_are_escaped(self):
        from integrations.notifications.telegram_bot import TelegramBotUplink

        assert TelegramBotUplink.escape_markdown("CRUDE_OIL") == r"CRUDE\_OIL"

    def test_every_markdown_control_character_is_escaped(self):
        from integrations.notifications.telegram_bot import TelegramBotUplink

        assert TelegramBotUplink.escape_markdown("a_b*c`d[e") == r"a\_b\*c\`d\[e"

    def test_plain_text_is_left_alone(self):
        from integrations.notifications.telegram_bot import TelegramBotUplink

        assert TelegramBotUplink.escape_markdown("Time-Based Square-Off (EOD)") == "Time-Based Square-Off (EOD)"

    def test_exit_alert_escapes_the_reason_that_broke_telegram(self, monkeypatch):
        """The verbatim 2026-07-15 thesis-stop reason must survive intact."""
        from integrations.notifications.telegram_bot import TelegramBotUplink

        bot = TelegramBotUplink()
        sent = []
        monkeypatch.setattr(bot, "send_message", lambda text: sent.append(text) or True)

        bot.notify_exit(
            "CRUDEOIL26JUL7750CE",
            price=62.8,
            reason="Underlying Thesis Stop: CRUDE_OIL moved 40.00 against position (>= 1.25 x ATR 31.64)",
        )

        assert len(sent) == 1
        body = sent[0]
        assert r"CRUDE\_OIL moved 40.00" in body
        # The template's own emphasis must survive escaping of the values.
        assert "*Exit Price*" in body
