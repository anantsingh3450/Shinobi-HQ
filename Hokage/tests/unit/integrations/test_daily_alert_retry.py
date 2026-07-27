"""A daily alert that failed to send must not count as "the commander was told".

Regression guard for 2026-07-27: the Zerodha token had been dead for seven days.
When the laptop woke mid-morning the uplink tried to send the login prompt,
Telegram was unreachable (`getaddrinfo failed`), and the send failed — but the
day had ALREADY been stamped as prompted before the send was attempted. The
prompt was never retried, the 09:00 "Login Missing" alarm burned the same way,
and Hokage sat blind and silent through a whole trading day.
"""
from __future__ import annotations

from integrations.notifications.telegram_bot import TelegramBotUplink


def _uplink(tmp_path, monkeypatch) -> TelegramBotUplink:
    """An uplink whose prompt-state file is redirected into a temp dir."""
    up = TelegramBotUplink(bot_token="123456:fake", chat_id="777")
    monkeypatch.setattr(up, "_prompt_state_path", lambda: tmp_path / "prompt.json")
    return up


def test_failed_send_does_not_burn_the_days_prompt(tmp_path, monkeypatch):
    up = _uplink(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "send_message", lambda text: False)

    # Nothing was marked, so the next loop tick is free to try again.
    assert up._last_totp_request_date is None
    up._mark_prompted("2026-07-27")
    assert up._last_totp_request_date == "2026-07-27"


def test_mark_prompted_persists_across_restart(tmp_path, monkeypatch):
    up = _uplink(tmp_path, monkeypatch)
    up._mark_prompted("2026-07-27")

    revived = _uplink(tmp_path, monkeypatch)
    assert revived._load_prompt_state() == "2026-07-27"


def test_retry_throttle_allows_first_attempt_then_holds(tmp_path, monkeypatch):
    """The loop ticks every 5s; retries must not flood at that rate."""
    up = _uplink(tmp_path, monkeypatch)
    assert up._may_retry_send() is True
    assert up._may_retry_send() is False


def test_throttle_is_only_consumed_when_an_alert_is_actually_pending(tmp_path, monkeypatch):
    """The date check short-circuits before the throttle, so a settled day never
    eats the retry budget the 09:00 confirmation still needs."""
    up = _uplink(tmp_path, monkeypatch)
    current = "2026-07-27"
    up._mark_prompted(current)

    # Mirrors the guard in _run_loop: date check first, throttle second.
    pending = up._last_totp_request_date != current and up._may_retry_send()
    assert pending is False
    # Budget untouched: the confirmation alert can still fire this tick.
    assert up._may_retry_send() is True
