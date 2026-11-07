"""The blind alarm demanded a Zerodha login on a Saturday.

2026-11-07, 08:41:47. Hokage booted, found the overnight token dead as it is
every single morning, and sent "HOKAGE IS BLIND - ZERODHA LOGIN NEEDED" about a
market that would not open for two days. There was nothing to be blind to.

WHY THAT IS NOT COSMETIC. This alarm exists because the feed died for seven
days in July and nobody was told - `_check_broker_session_health` was LIVE-only
and Hokage is paper-locked, so the one token alarm was dead code in the only
mode it runs. The fix was to shout. An alarm that also shouts on every weekend
and every exchange holiday is how the shout that matters gets ignored.

AND THE ANSWER ALREADY EXISTED. `trading_calendar` was built on 2026-10-20
after Dussehra produced five demands that the commander log in to a shut
exchange. It knew this Saturday was closed. This alarm never asked it. So did
the watchdog's staleness window, whose own docstring accepted holiday noise as
"the safe direction to be wrong in" - written eight days before the calendar
existed.

THE RULE THESE TESTS HOLD DOWN: silence requires a POSITIVE "nothing trades".
Unknown is not closed, an unreadable calendar is not closed, and an
evening-only holiday is not closed - on 2026-10-20 equities were shut while MCX
ran from 17:00, which is SessionShift's only window.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from hokage.memory import trading_calendar as tc

_PROBE = Bot._check_data_feed_session

DEAD_TOKEN = Exception("Incorrect `api_key` or `access_token`.")

#: Real dates, each one checked against the calendar in the tests below.
SATURDAY = datetime(2026, 11, 7, 8, 41, 47)      # the false alarm
SUNDAY = datetime(2026, 11, 15, 9, 0, 0)         # a Sunday that really is dead
MUHURAT = datetime(2026, 11, 8, 9, 0, 0)         # a Sunday that TRADES, 14:20
MONDAY = datetime(2026, 11, 9, 8, 41, 47)        # normal session
DUSSEHRA = datetime(2026, 10, 20, 9, 0, 0)       # equities shut, MCX evening
BEYOND = datetime(2027, 3, 1, 9, 0, 0)           # outside the calendar


def _stub(when: datetime, error: Exception = DEAD_TOKEN) -> SimpleNamespace:
    price_source = MagicMock()
    price_source.get_price.side_effect = error
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
        _now_ist=lambda: when,
        _try_broker_reconnect=lambda: False,
    )
    bot._diagnose_feed_failure = lambda reason: Bot._diagnose_feed_failure(bot, reason)
    bot._record_feed_probe = lambda ok, reason: Bot._record_feed_probe(bot, ok, reason)
    bot._nothing_trades_today = lambda: Bot._nothing_trades_today(bot)
    return bot


# ============================================ the dates are what I claim they are
def test_the_dates_in_this_file_are_what_the_calendar_says():
    """A test that silently depends on a wrong date proves nothing."""
    assert tc.anything_trades(SATURDAY.date()) is False
    assert tc.anything_trades(SUNDAY.date()) is False
    assert tc.anything_trades(MUHURAT.date()) is True       # Muhurat session
    assert tc.anything_trades(MONDAY.date()) is True
    assert tc.anything_trades(DUSSEHRA.date()) is True      # MCX evening
    assert tc.anything_trades(BEYOND.date()) is None        # unknown


# =================================================== no alarm on a closed day
def test_a_dead_token_on_a_saturday_raises_no_alarm():
    """THE DEFECT, by its own date and time."""
    bot = _stub(SATURDAY)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_not_called()
    assert bot._last_feed_alert_date is None


def test_a_dead_token_on_a_sunday_raises_no_alarm():
    bot = _stub(SUNDAY)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_not_called()


def test_a_dead_token_on_the_muhurat_sunday_still_alarms():
    """The day this whole guard could have gone wrong in the dangerous
    direction. 2026-11-08 is a Sunday with a live session from 14:20, and a
    dead token on it is exactly the nine-days-blind failure this alarm
    exists for."""
    bot = _stub(MUHURAT)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_called_once()


def test_the_quiet_day_is_latched_so_the_log_says_it_once():
    bot = _stub(SATURDAY)
    _PROBE(bot)
    assert bot._last_feed_quiet_date == "2026-11-07"
    _PROBE(bot)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_not_called()


def test_a_network_failure_on_a_closed_day_is_also_quiet():
    """It is not only the token. Nothing about the feed matters when nothing
    trades."""
    bot = _stub(SATURDAY, error=Exception("Max retries exceeded: getaddrinfo failed"))
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_not_called()


# ===================================== the alarm is untouched on a trading day
def test_a_dead_token_on_a_monday_still_alarms():
    """The seven-days-blind case this alarm was built for must still fire."""
    bot = _stub(MONDAY)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_called_once()
    assert "LOGIN NEEDED" in bot.telegram_bot.send_message.call_args[0][0]
    assert bot._last_feed_alert_date == "2026-11-09"


def test_an_evening_only_holiday_still_alarms():
    """2026-10-20: equities shut, MCX running from 17:00 - SessionShift's only
    window, and the one that has produced trades. Writing the day off is the
    other way to be wrong, and the calendar exists so neither happens."""
    bot = _stub(DUSSEHRA)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_called_once()


def test_a_date_the_calendar_has_never_heard_of_still_alarms():
    """UNKNOWN IS NOT CLOSED. The list ends 2026-12-31, and a 2027 date is not
    a holiday merely because the 2026 list does not mention it. Noise is the
    acceptable failure here; silence is not."""
    bot = _stub(BEYOND)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_called_once()


def test_a_calendar_that_cannot_be_read_does_not_silence_the_alarm(monkeypatch):
    bot = _stub(SATURDAY)
    monkeypatch.setattr(tc, "anything_trades",
                        lambda day: (_ for _ in ()).throw(RuntimeError("boom")))
    assert bot._nothing_trades_today() is False
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_called_once()


def test_a_calendar_answering_true_does_not_silence_the_alarm():
    """Belt and braces on the `is False` comparison: only a positive closure
    quietens this, never a truthy or missing answer."""
    bot = _stub(MONDAY)
    assert bot._nothing_trades_today() is False


# ======================================== the feed's state is still recorded
def test_the_probe_still_records_the_outage_on_a_closed_day():
    """The feed IS down and that stays a recorded fact - the dashboard and
    /broker/zerodha/status read this, and a connection flag stays CONNECTED
    after a token dies. Only the ALARM is suppressed, never the measurement."""
    bot = _stub(SATURDAY)
    _PROBE(bot)
    assert bot._feed_probe_ok is False
    assert "access_token" in bot._feed_probe_reason
    assert bot._feed_probe_at is not None


# ============================================== the watchdog window agrees
@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 11, 7, 12, 0), False),    # Saturday
    (datetime(2026, 11, 15, 12, 0), False),   # a dead Sunday
    (datetime(2026, 11, 8, 12, 0), False),    # Muhurat Sunday, BEFORE 14:20
    (datetime(2026, 11, 8, 14, 30), True),    # Muhurat Sunday, mid-session
    (datetime(2026, 11, 8, 15, 45), False),   # Muhurat Sunday, after 15:40
    (datetime(2026, 11, 9, 12, 0), True),     # Monday, inside the window
    (datetime(2026, 10, 20, 12, 0), True),    # Dussehra: MCX trades in the evening
    (datetime(2027, 3, 1, 12, 0), True),      # unknown date, still alarms
])
def test_the_staleness_window_uses_the_same_calendar(when, expected):
    """The watchdog's own docstring accepted holiday noise as the safe
    direction, written eight days before the calendar existed. Closed now, on
    the same rule: positive closure only."""
    from shared.watchdog.watchdog import Watchdog

    assert Watchdog.feed_expected_now(when) is expected


def test_a_closed_equity_holiday_with_no_mcx_session_is_quiet():
    """The one case where both segments are shut on a weekday. Taken from the
    calendar rather than asserted, so it stays true if the list changes."""
    import datetime as dt

    from shared.watchdog.watchdog import Watchdog

    shut = [d for d in tc._EQUITY_HOLIDAYS_2026
            if tc.anything_trades(d) is False and d.weekday() < 5]
    if not shut:
        pytest.skip("no full-closure weekday holiday in the calendar")
    when = dt.datetime.combine(shut[0], dt.time(12, 0))
    assert Watchdog.feed_expected_now(when) is False
    bot = _stub(when)
    _PROBE(bot)
    bot.telegram_bot.send_message.assert_not_called()
