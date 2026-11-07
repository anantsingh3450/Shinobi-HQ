"""Proof by running the loops, not by reading them.

The calendar fix of 2026-11-07 was checked two ways, and only one of them was
evidence. The feed probe and the watchdog window were EXERCISED with a closed
day's clock. The 08:45 checklist and the two login prompts were checked by
asserting their source contains a guard - which proves the guard was typed, not
that the loop goes quiet. Those are different claims, and the first restart
that day showed why: the alarm I had tested was silent and two I had only read
still fired.

So these tests freeze each loop's clock to a Sunday, run it for one pass, and
assert the Telegram transport was never asked to send anything.

SUNDAY, specifically. Saturday was the day of the incident and is the day every
other test uses, so a bug that keyed on weekday 5 rather than "the exchange is
shut" would pass everything and still nag on a Sunday.

AND A DEAD SUNDAY, CHOSEN FROM THE CALENDAR RATHER THAN FROM THE WEEKDAY. The
first version of this file used 2026-11-08, which is Diwali Muhurat trading -
a live session. Every assertion of silence here was, for one day, an assertion
that Hokage should sleep through a trading afternoon.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hokage.memory import trading_calendar as tc

#: Sunday 2026-11-15, 09:05 IST = 03:35 UTC. Past 06:30, past 08:45 and past
#: 09:00, so EVERY time gate in both loops is open and only the calendar is
#: standing between the clock and a Telegram message.
#:
#: NOT 2026-11-08, WHICH WAS THE FIRST CHOICE AND WAS WRONG. That Sunday is
#: Diwali Muhurat trading - a live session from 14:20 - so every test here
#: asserting silence on it was asserting that Hokage should go quiet through
#: a trading day. A test is not evidence that a day is closed; the calendar
#: is, and `test_this_sunday_really_is_a_dead_one` below says so out loud.
SUNDAY_UTC = dt.datetime(2026, 11, 15, 3, 35, 0, tzinfo=dt.timezone.utc)
MONDAY_UTC = dt.datetime(2026, 11, 16, 3, 35, 0, tzinfo=dt.timezone.utc)

#: The Sunday that DOES trade, kept here as the control.
MUHURAT_UTC = dt.datetime(2026, 11, 8, 3, 35, 0, tzinfo=dt.timezone.utc)


class _FrozenClock:
    """Stands in for the `datetime` class each loop calls .now() on."""

    def __init__(self, moment: dt.datetime) -> None:
        self._moment = moment

    def now(self, tz=None):
        return self._moment.astimezone(tz) if tz else self._moment

    def __getattr__(self, name):            # fromisoformat, strptime, etc.
        return getattr(dt.datetime, name)


def _run_one_pass(target, stop_event) -> None:
    """Let a while/wait loop complete one iteration, then stop it."""
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    for _ in range(100):                    # up to ~1s, usually one tick
        time.sleep(0.01)
        if stop_event is not None:
            break
    stop_event.set()
    thread.join(timeout=5.0)
    assert not thread.is_alive(), "loop did not stop"


# ================================================= the day is what I claim
def test_sunday_is_a_closed_day_and_monday_is_not():
    assert tc.nothing_trades(SUNDAY_UTC.date()) is True
    assert tc.nothing_trades(MONDAY_UTC.date()) is False


def test_this_sunday_really_is_a_dead_one():
    """A weekday number is not a closure. Picking a Sunday off the calendar
    and calling it closed is how the first version of this file came to
    assert silence through Muhurat trading."""
    assert SUNDAY_UTC.weekday() == 6
    assert tc.session_kind(SUNDAY_UTC.date(), "NSE") == tc.CLOSED
    assert tc.special_session(SUNDAY_UTC.date()) is None


def test_the_muhurat_sunday_is_not_silenced():
    """THE CONTROL FOR EVERY TEST IN THIS FILE. 2026-11-08 is a Sunday that
    trades, and a gate that cannot tell it from 2026-11-15 is a gate that
    goes quiet through a live session."""
    assert MUHURAT_UTC.weekday() == 6
    assert tc.nothing_trades(MUHURAT_UTC.date()) is False
    assert tc.segment_shut(MUHURAT_UTC.date(), "NSE") is False
    assert tc.segment_shut(MUHURAT_UTC.date(), "MCX") is False


def test_sunday_is_past_every_time_gate_in_both_loops():
    """Otherwise these tests would pass because the clock was too early, which
    proves nothing about the calendar."""
    ist = SUNDAY_UTC + dt.timedelta(hours=5, minutes=30)
    assert ist.hour >= 9                       # 09:00 confirmation
    assert (ist.hour, ist.minute) >= (8, 45)   # morning checklist
    assert (ist.hour, ist.minute) >= (6, 30)   # login brief
    assert ist.weekday() == 6                  # and it really is a Sunday


# ====================================================== the morning checklist
def _scheduler(monkeypatch, moment):
    from bots.autonomous import cron_reset

    monkeypatch.setattr(cron_reset, "datetime", _FrozenClock(moment))
    telegram = MagicMock()
    telegram.enabled = True
    venue = MagicMock()
    venue.get_account_balance.side_effect = Exception("Venue is not connected.")
    bot = SimpleNamespace(
        telegram_bot=telegram,
        orchestrator=SimpleNamespace(resolver=MagicMock(),
                                     registry=SimpleNamespace(get_venue=lambda _: venue)),
        is_active=lambda: True,
        free_mind_free_hand=False,
        intraday_override={},
        _trades_taken_today={},
        _exits_executed_today={},
    )
    sched = cron_reset.CronScheduler(bot, threading.Lock())
    return sched, telegram


def test_the_checklist_sends_nothing_on_a_sunday(monkeypatch):
    """The broker is deliberately stubbed to FAIL here, exactly as it does
    every night when the token expires. On a Sunday that is not news."""
    sched, telegram = _scheduler(monkeypatch, SUNDAY_UTC)
    _run_one_pass(sched.run, sched._stop_event)
    telegram.send_message.assert_not_called()


def test_the_checklist_still_reports_on_a_monday(monkeypatch):
    """The other half of the proof: the same stubbed failure MUST be reported
    on a trading day, or this fix has broken the check instead of scoping it."""
    sched, telegram = _scheduler(monkeypatch, MONDAY_UTC)
    _run_one_pass(sched.run, sched._stop_event)
    telegram.send_message.assert_called_once()
    body = telegram.send_message.call_args[0][0]
    assert "Morning Systems Check" in body
    assert "ACTION REQUIRED BEFORE OPEN" in body


# ================================================= the two login prompts
def _uplink(monkeypatch, moment, tmp_path):
    from integrations.notifications import telegram_bot as tb

    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    monkeypatch.setattr(tb, "datetime", _FrozenClock(moment))
    uplink = tb.TelegramBotUplink(bot_token="123456:test-token", chat_id="999")
    # Never touch the network, in either direction.
    monkeypatch.setattr(uplink, "_post", lambda body: True)
    monkeypatch.setattr(uplink, "_validate_broker_session", lambda: False)
    sends = MagicMock(return_value=True)
    monkeypatch.setattr(uplink, "send_message", sends)
    polled = MagicMock()
    monkeypatch.setattr(uplink, "_check_telegram_updates", polled)
    # The suite sets HOKAGE_DISABLE_TELEGRAM=true so no test can ever reach
    # the real transport, which also leaves `enabled` False and the command
    # poller skipped. That env var is a safety seam and stays set; `enabled`
    # is flipped here instead, with _post and send_message already stubbed, so
    # the loop takes the same branches production does and still cannot send.
    uplink.enabled = True
    return uplink, sends, polled


def test_neither_login_prompt_fires_on_a_sunday(monkeypatch, tmp_path):
    """06:30 "ZERODHA LIVE AUTONOMOUS LOGIN REQUIRED" and 09:00 "Login
    Missing". The session is stubbed invalid, which is the true state of every
    weekend morning."""
    uplink, sends, polled = _uplink(monkeypatch, SUNDAY_UTC, tmp_path)
    _run_one_pass(uplink._run_loop, uplink._stop_event)
    # THE PASS IS VERIFIED, NOT ASSUMED. Without this, a loop that never got
    # as far as its body would also "send nothing" and the test would be
    # proving the thread was slow.
    assert polled.called, "the loop body never ran, so sending nothing proves nothing"
    assert sends.call_args_list == []


def test_the_login_prompt_still_fires_on_a_monday(monkeypatch, tmp_path):
    """Same invalid session, a day that trades: he must still be told."""
    uplink, sends, polled = _uplink(monkeypatch, MONDAY_UTC, tmp_path)
    _run_one_pass(uplink._run_loop, uplink._stop_event)
    bodies = " ".join(str(c[0][0]) for c in sends.call_args_list)
    assert bodies, "a trading day with no session must prompt"
    assert "LOGIN" in bodies.upper()


def test_his_commands_are_still_polled_on_a_sunday(monkeypatch, tmp_path):
    """The guard covers the prompts only. /status and /token must keep
    answering on a closed day - stopping them would be a worse bug than the
    nagging this fixes."""
    from integrations.notifications import telegram_bot as tb

    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    monkeypatch.setattr(tb, "datetime", _FrozenClock(SUNDAY_UTC))
    uplink = tb.TelegramBotUplink(bot_token="123456:test-token", chat_id="999")
    monkeypatch.setattr(uplink, "_post", lambda body: True)
    monkeypatch.setattr(uplink, "send_message", MagicMock(return_value=True))
    polled = MagicMock()
    monkeypatch.setattr(uplink, "_check_telegram_updates", polled)
    uplink.enabled = True
    _run_one_pass(uplink._run_loop, uplink._stop_event)
    assert polled.called, "the command poller was skipped on a closed day"


# ============================================ the feed probe, on a Sunday
def test_the_feed_probe_is_quiet_on_a_sunday():
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    price_source = MagicMock()
    price_source.get_price.side_effect = Exception(
        "Incorrect `api_key` or `access_token`.")
    telegram = MagicMock()
    telegram.send_message.return_value = True
    telegram.escape_markdown = lambda text: text
    bot = SimpleNamespace(
        orchestrator=SimpleNamespace(price_source=price_source),
        telegram_bot=telegram,
        _AUTH_ERROR_TAGS=Bot._AUTH_ERROR_TAGS,
        _NETWORK_ERROR_TAGS=Bot._NETWORK_ERROR_TAGS,
        _NETWORK_REBUILD_AFTER=Bot._NETWORK_REBUILD_AFTER,
        _consecutive_network_failures=0,
        _last_feed_alert_date=None,
        _last_feed_quiet_date=None,
        _feed_outage_announced=False,
        _now_ist=lambda: dt.datetime(2026, 11, 15, 9, 5, 0),
        _try_broker_reconnect=lambda: False,
    )
    bot._diagnose_feed_failure = lambda r: Bot._diagnose_feed_failure(bot, r)
    bot._record_feed_probe = lambda ok, r: Bot._record_feed_probe(bot, ok, r)
    bot._nothing_trades_today = lambda: Bot._nothing_trades_today(bot)
    Bot._check_data_feed_session(bot)
    telegram.send_message.assert_not_called()
    assert bot._last_feed_quiet_date == "2026-11-15"


def test_the_staleness_window_is_disarmed_on_a_sunday():
    from shared.watchdog.watchdog import Watchdog

    assert Watchdog.feed_expected_now(dt.datetime(2026, 11, 15, 12, 0)) is False


# =========================================== and the whole weekend, together
@pytest.mark.parametrize("day", [dt.date(2026, 11, 14), dt.date(2026, 11, 15)])
def test_every_sender_is_quiet_across_the_whole_weekend(day):
    from shared.watchdog.watchdog import Watchdog

    assert tc.nothing_trades(day) is True
    assert Watchdog.feed_expected_now(
        dt.datetime.combine(day, dt.time(12, 0))) is False
