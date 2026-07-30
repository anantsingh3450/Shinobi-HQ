"""A sleeping host suspends the risk engine, and nothing used to say so.

2026-07-30, from Windows' own event log:
  10:28:21  Critical Battery Trigger Met
  10:28:25  The system is entering sleep
  18:03:47  Power source change  (plugged in -> woke)

Hokage's log for that process has entries in hour 10 and hour 18 and nothing
between. It was awake for 42 minutes of a 6h15m session. An open BANKNIFTY put
sat 7.5 hours with no stop, no trail and no thesis-stop, then squared off after
the close for -4,248 — two thirds of the day's loss. On waking, the loop simply
resumed and the watchdog reported 100/100, because the gap was in the past.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from integrations.notifications.telegram_bot import TelegramBotUplink

_GAP = AutonomousTradingBot._check_for_unconscious_gap
_BATTERY = AutonomousTradingBot._check_battery_runway


def _bot(now: datetime, positions=None):
    telegram = MagicMock()
    telegram.send_message.return_value = True
    telegram.escape_markdown = TelegramBotUplink.escape_markdown
    return SimpleNamespace(
        _now_ist=lambda: now,
        _active_positions_tracking=positions or {},
        telegram_bot=telegram,
        _MAX_LOOP_GAP_SECONDS=AutonomousTradingBot._MAX_LOOP_GAP_SECONDS,
        _BATTERY_WARN_PERCENT=AutonomousTradingBot._BATTERY_WARN_PERCENT,
    )


def test_first_iteration_never_reports_a_gap():
    bot = _bot(datetime(2026, 7, 30, 9, 46))
    _GAP(bot)
    bot.telegram_bot.send_message.assert_not_called()


def test_normal_sixty_second_cadence_is_silent():
    bot = _bot(datetime(2026, 7, 30, 9, 46))
    _GAP(bot)
    bot._now_ist = lambda: datetime(2026, 7, 30, 9, 47)
    _GAP(bot)
    bot.telegram_bot.send_message.assert_not_called()


def test_the_seven_and_a_half_hour_coma_is_announced_with_the_positions():
    bot = _bot(datetime(2026, 7, 30, 10, 28), positions={"BANKNIFTY26AUG57000PE": {}})
    _GAP(bot)
    bot._now_ist = lambda: datetime(2026, 7, 30, 18, 3)
    _GAP(bot)

    bot.telegram_bot.send_message.assert_called_once()
    body = bot.telegram_bot.send_message.call_args[0][0]
    assert "UNCONSCIOUS" in body
    assert "455" in body            # minutes asleep
    assert "BANKNIFTY" in body
    assert "NO stop" in body


def test_a_gap_with_no_open_positions_is_reported_more_softly():
    bot = _bot(datetime(2026, 7, 30, 10, 28))
    _GAP(bot)
    bot._now_ist = lambda: datetime(2026, 7, 30, 18, 3)
    _GAP(bot)

    body = bot.telegram_bot.send_message.call_args[0][0]
    assert "UNCONSCIOUS" in body
    assert "nothing went unmanaged" in body


def test_gap_just_over_the_threshold_still_counts():
    bot = _bot(datetime(2026, 7, 30, 12, 0))
    _GAP(bot)
    bot._now_ist = lambda: datetime(2026, 7, 30, 12, 6)
    _GAP(bot)
    bot.telegram_bot.send_message.assert_called_once()


def test_battery_warning_fires_once_per_discharge(monkeypatch):
    bot = _bot(datetime(2026, 7, 30, 10, 0), positions={"BANKNIFTY26AUG57000PE": {}})
    fake = SimpleNamespace(percent=22.0, power_plugged=False)
    monkeypatch.setattr("psutil.sensors_battery", lambda: fake)

    for _ in range(4):
        _BATTERY(bot)
    assert bot.telegram_bot.send_message.call_count == 1
    body = bot.telegram_bot.send_message.call_args[0][0]
    assert "PLUG IN" in body
    assert "22%" in body
    assert "lose their stops" in body


def test_reaching_a_charger_rearms_the_warning(monkeypatch):
    bot = _bot(datetime(2026, 7, 30, 10, 0))
    fake = SimpleNamespace(percent=22.0, power_plugged=False)
    monkeypatch.setattr("psutil.sensors_battery", lambda: fake)
    _BATTERY(bot)
    assert bot.telegram_bot.send_message.call_count == 1

    fake.power_plugged = True
    _BATTERY(bot)
    assert bot._battery_warning_sent is False

    fake.power_plugged = False
    _BATTERY(bot)
    assert bot.telegram_bot.send_message.call_count == 2


def test_healthy_battery_is_silent(monkeypatch):
    bot = _bot(datetime(2026, 7, 30, 10, 0))
    monkeypatch.setattr(
        "psutil.sensors_battery", lambda: SimpleNamespace(percent=88.0, power_plugged=False)
    )
    _BATTERY(bot)
    bot.telegram_bot.send_message.assert_not_called()
