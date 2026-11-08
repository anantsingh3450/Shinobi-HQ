"""The login link existed once a day, at a fixed hour, behind a gate.

2026-11-08 was a Sunday with a live session at 14:20. The 06:30 brief is the
only thing that carries a tappable Kite link and a live TOTP, and that morning
it was suppressed - correctly, by a calendar that had not yet learned about
Muhurat trading - leaving no way to ask for another. The commander asked for
the link to be sent through Telegram and there was no command that did it.

So `/login` exists, and it is DELIBERATELY NOT CALENDAR-GATED: he asked, which
is the whole condition. A reactive reply cannot nag, which is the entire reason
the other senders needed a gate in the first place.

`/token <url>` is the real token exchange, and the first version of this branch
matched on the first word alone - which would have captured it and broken the
one path that actually logs him in. That is what `test_a_real_token_submission
_is_not_swallowed` holds down.
"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def uplink(monkeypatch, tmp_path):
    from integrations.notifications import telegram_bot as tb

    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    monkeypatch.setenv("ZERODHA_TOTP_SECRET", "JBSWY3DPEHPK3PXP")   # RFC 4226 sample
    up = tb.TelegramBotUplink(bot_token="123456:test-token", chat_id="999")
    monkeypatch.setattr(up, "_post", lambda body: True)
    monkeypatch.setattr(up, "send_message", MagicMock(return_value=True))
    # The api_key is read through SecretManager; never a real one here.
    monkeypatch.setattr(
        tb, "SecretManager",
        lambda *a, **k: MagicMock(get_secret=MagicMock(return_value="test_api_key")))
    up.enabled = True
    return up


class _Res:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _deliver(up, text, monkeypatch):
    """Hand the uplink one Telegram message and let it dispatch.

    `requests.get` is replaced for the duration, so no test here can reach
    api.telegram.org - the poller calls it directly.
    """
    from integrations.notifications import telegram_bot as tb

    payload = {"result": [{"update_id": 1,
                           "message": {"chat": {"id": "999"}, "text": text}}]}
    monkeypatch.setattr(tb.requests, "get", lambda *a, **k: _Res(payload))
    up._check_telegram_updates()


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


# ============================================================ the brief body
def test_the_brief_carries_a_tappable_link_and_a_live_code(uplink):
    body = uplink.build_login_brief("HEADLINE")
    assert body.startswith("HEADLINE")
    assert "[Kite Login](https://kite.trade/connect/login?v=3&api_key=" in body
    assert "Live TOTP" in body
    assert "/token URL" in body          # the fallback, still stated


def test_the_brief_still_works_without_a_totp_secret(monkeypatch, uplink):
    monkeypatch.delenv("ZERODHA_TOTP_SECRET", raising=False)
    body = uplink.build_login_brief("HEADLINE")
    assert "Kite Login" in body
    assert "Live TOTP" not in body


def test_one_body_serves_both_callers():
    """The 06:30 brief and `/login` must not drift into two sets of steps."""
    src = (_repo_root() / "src" / "integrations" / "notifications"
           / "telegram_bot.py").read_text(encoding="utf-8")
    assert src.count("def build_login_brief") == 1
    assert src.count("self.build_login_brief(") == 2
    # and the steps live in exactly one place
    assert src.count("Click here to login: [Kite Login]") == 1


def test_the_brief_is_never_logged():
    """The URL carries the api_key and the message carries a live one-time
    code. Nothing in the builder may reach a logger."""
    src = (_repo_root() / "src" / "integrations" / "notifications"
           / "telegram_bot.py").read_text(encoding="utf-8")
    body = src.split("def build_login_brief")[1].split(
        "def _validate_broker_session")[0]
    assert "logger." not in body
    for leak in ("login_url", "totp_pin", "api_key"):
        assert f"logger.info({leak}" not in body
        assert f"print({leak}" not in body


# ============================================================ the command
@pytest.mark.parametrize("text", ["/login", "/relogin", "/token",
                                  "/LOGIN", "  /login  "])
def test_asking_for_the_link_sends_it(text, monkeypatch, uplink):
    monkeypatch.setattr(uplink, "_validate_broker_session", lambda: False)
    _deliver(uplink, text, monkeypatch)
    uplink.send_message.assert_called_once()
    body = uplink.send_message.call_args[0][0]
    assert "ZERODHA LOGIN LINK" in body
    assert "Kite Login" in body


def test_an_already_valid_session_says_so_instead(monkeypatch, uplink):
    """Handing him a login link when he is already connected would send him
    to re-authenticate for nothing."""
    monkeypatch.setattr(uplink, "_validate_broker_session", lambda: True)
    _deliver(uplink, "/login", monkeypatch)
    body = uplink.send_message.call_args[0][0]
    assert "Already connected" in body
    assert "Kite Login" not in body


def test_a_real_token_submission_is_not_swallowed(monkeypatch, uplink):
    """THE BUG IN THE FIRST VERSION. Matching the first word alone made
    `/token <url>` an alias for "send me a link", which would have left the
    one path that actually logs him in unreachable."""
    exchanged = {}

    def fake_set(request_token):
        exchanged["token"] = request_token
        raise RuntimeError("stop here - the exchange was reached")

    monkeypatch.setattr(uplink, "_validate_broker_session", lambda: False)
    monkeypatch.setattr(
        uplink, "command_handler",
        MagicMock(handle_remote_command=MagicMock(return_value="ack")),
        raising=False)

    src = (_repo_root() / "src" / "integrations" / "notifications"
           / "telegram_bot.py").read_text(encoding="utf-8")
    branch = src.split("BARE only.")[1].split("elif text.startswith")[0]
    assert 'text.strip().lower() in ("/login", "/relogin", "/token")' in branch

    # and behaviourally: a token-bearing message must NOT get the link reply
    _deliver(uplink, "/token abc123def456", monkeypatch)
    bodies = " ".join(str(c[0][0]) for c in uplink.send_message.call_args_list)
    assert "ZERODHA LOGIN LINK" not in bodies


def test_a_pasted_callback_url_is_not_swallowed(monkeypatch, uplink):
    monkeypatch.setattr(uplink, "_validate_broker_session", lambda: False)
    _deliver(uplink, "http://127.0.0.1:5000/cb?request_token=abc123", monkeypatch)
    bodies = " ".join(str(c[0][0]) for c in uplink.send_message.call_args_list)
    assert "ZERODHA LOGIN LINK" not in bodies


def test_the_command_is_not_calendar_gated():
    """Today is exactly the case: a closed-looking Sunday with a live session.
    A gate here would have reproduced the problem it was asked to solve."""
    src = (_repo_root() / "src" / "integrations" / "notifications"
           / "telegram_bot.py").read_text(encoding="utf-8")
    branch = src.split("ASK FOR THE LINK, ANY TIME.")[1].split(
        "elif text.startswith")[0]
    assert "shut_today" not in branch
    assert "nothing_trades" not in branch
    assert "_mark_prompted" not in branch       # must not burn the day's prompt


def test_a_failure_to_build_still_answers_him(monkeypatch, uplink):
    """Silence after he asks for a link is the worst outcome: he waits."""
    monkeypatch.setattr(uplink, "_validate_broker_session", lambda: False)
    monkeypatch.setattr(uplink, "build_login_brief",
                        MagicMock(side_effect=RuntimeError("no api key")))
    _deliver(uplink, "/login", monkeypatch)
    body = uplink.send_message.call_args[0][0]
    assert "Could not build the login link" in body
    assert "dashboard" in body.lower()
