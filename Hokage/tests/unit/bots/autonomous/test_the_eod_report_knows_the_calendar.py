"""The fifth sender, found by watching rather than by reading.

Four alarms were taught the calendar on 2026-11-07. A few hours later, at
15:35 on that same Saturday, this arrived:

    Hokage - how today went (Saturday, 07 Nov 2026)
    No trades today - Hokage watched the mar...

Not an alarm - nothing in it demands action - but still a message whose entire
content is the calendar, sent to the man who owns the calendar. The MCX league
has its own copy at 23:35 with the same blindness.

PER LEAGUE, NOT PER SYSTEM. `nothing_trades` is the wrong question here. On
2026-10-20 equities were shut and MCX traded from 17:00, so the equity report
was about a market that never opened while the MCX report was about a real
session. One answer cannot serve both, which is why `segment_shut` exists.

These tests RUN the loop. The whole lesson of that Saturday was that a guard
read in the source is not a guard proven in the process.
"""
from __future__ import annotations

import datetime as dt
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hokage.memory import trading_calendar as tc

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

SATURDAY = dt.date(2026, 11, 14)
SUNDAY = dt.date(2026, 11, 15)
MONDAY = dt.date(2026, 11, 16)
MUHURAT = dt.date(2026, 11, 8)          # a SUNDAY that trades, 14:20-15:40
DUSSEHRA = dt.date(2026, 10, 20)        # equities CLOSED, MCX evening from 17:00
BEYOND = dt.date(2027, 3, 2)            # a Tuesday outside the calendar's data

#: The two windows, inside the spans the loop actually tests for.
EQUITY_WINDOW = dt.time(15, 40)
MCX_WINDOW = dt.time(23, 40)


class _FrozenClock:
    """The module's `datetime`, pinned, and the loop's brake.

    It stops the loop itself rather than a timer in the test: the sleep at the
    bottom of that loop ticks in whole seconds, so a wall-clock brake would
    make every test here a race.
    """

    def __init__(self, moment: dt.datetime, stop: threading.Event) -> None:
        self._moment = moment
        self._stop = stop
        self.calls = 0

    def now(self, tz=None):
        self.calls += 1
        if self.calls >= 3:        # one full pass uses two
            self._stop.set()
        return self._moment.astimezone(tz) if tz else self._moment

    def __getattr__(self, name):
        return getattr(dt.datetime, name)


def _bot(day: dt.date, at: dt.time, monkeypatch):
    from bots.autonomous import autonomous_bot as mod

    moment = dt.datetime.combine(day, at, tzinfo=IST)
    stop = threading.Event()
    monkeypatch.setattr(mod, "datetime", _FrozenClock(moment, stop))

    telegram = MagicMock()
    telegram.enabled = True
    bot = SimpleNamespace(
        _stop_event=stop,
        scan_interval=0,
        telegram_bot=telegram,
        orchestrator=MagicMock(),
        _last_midnight_reset_date=day.strftime("%Y-%m-%d"),
        intraday_override={},
        elder_manual_input_received=True,
        gatekeeper_state=None,
        _eod_report_sent_date=None,
        _mcx_eod_report_sent_date=None,
        _now_ist=lambda: moment,
        build_eod_plain_report=MagicMock(return_value="report body"),
    )
    Bot = mod.AutonomousTradingBot
    bot._segment_shut_today = lambda seg: Bot._segment_shut_today(bot, seg)
    bot._describe_today = lambda: Bot._describe_today(bot)
    return bot, telegram, stop, Bot


def _run(day, at, monkeypatch):
    bot, telegram, stop, Bot = _bot(day, at, monkeypatch)
    thread = threading.Thread(target=lambda: Bot._run_loop(bot), daemon=True)
    thread.start()
    thread.join(timeout=10.0)
    assert not thread.is_alive(), "the loop did not stop"
    return telegram, bot


# ============================================ the day is what I claim it is
def test_the_calendar_separates_the_two_leagues_on_dussehra():
    """The whole reason this is per-segment and not `nothing_trades`."""
    assert tc.segment_shut(DUSSEHRA, "NSE") is True
    assert tc.segment_shut(DUSSEHRA, "MCX") is False
    assert tc.nothing_trades(DUSSEHRA) is False     # so the old question fails


@pytest.mark.parametrize("day", [SATURDAY, SUNDAY])
def test_both_leagues_are_shut_all_weekend(day):
    assert tc.segment_shut(day, "NSE") is True
    assert tc.segment_shut(day, "MCX") is True


def test_a_weekend_is_not_decided_by_the_weekday():
    """Both of these are Sundays. Only one is shut."""
    assert SUNDAY.weekday() == MUHURAT.weekday() == 6
    assert tc.segment_shut(SUNDAY, "NSE") is True
    assert tc.segment_shut(MUHURAT, "NSE") is False


def test_monday_is_shut_for_neither():
    assert tc.segment_shut(MONDAY, "NSE") is False
    assert tc.segment_shut(MONDAY, "MCX") is False


def test_an_unknown_date_is_not_shut():
    """Unknown still SENDS, exactly as unknown still alarms. From 1 January
    every answer here is None and both reports come back - that is the
    intended failure, not a bug."""
    assert tc.session_kind(BEYOND, "NSE") is None
    assert tc.segment_shut(BEYOND, "NSE") is False
    assert tc.segment_shut(BEYOND, "MCX") is False


# ================================================== the equity report, 15:35
@pytest.mark.parametrize("day", [SATURDAY, SUNDAY, DUSSEHRA])
def test_the_equity_report_is_silent_when_equities_were_shut(day, monkeypatch):
    telegram, bot = _run(day, EQUITY_WINDOW, monkeypatch)
    telegram.send_message.assert_not_called()
    bot.build_eod_plain_report.assert_not_called()


def test_the_equity_report_still_arrives_on_a_trading_day(monkeypatch):
    """The other half of the proof. Without this, deleting the sender outright
    would pass every test above."""
    telegram, bot = _run(MONDAY, EQUITY_WINDOW, monkeypatch)
    telegram.send_message.assert_called_once_with("report body")


def test_a_skipped_equity_report_still_counts_as_done(monkeypatch):
    """The date latch must be stamped either way, or the skip log repeats on
    every tick of a 55-minute window."""
    telegram, bot = _run(SATURDAY, EQUITY_WINDOW, monkeypatch)
    assert bot._eod_report_sent_date == "2026-11-14"


def test_both_reports_arrive_on_the_muhurat_sunday(monkeypatch):
    """THE DANGEROUS DIRECTION, and the reason the weekend rule had to stop
    answering first. 2026-11-08 is a Sunday with a live session; a gate that
    reads it off the weekday suppresses a report about real trades."""
    telegram, _ = _run(MUHURAT, EQUITY_WINDOW, monkeypatch)
    telegram.send_message.assert_called_once_with("report body")

    telegram, _ = _run(MUHURAT, MCX_WINDOW, monkeypatch)
    telegram.send_message.assert_called_once_with("report body")


# ===================================================== the MCX report, 23:35
@pytest.mark.parametrize("day", [SATURDAY, SUNDAY])
def test_the_mcx_report_is_silent_on_the_weekend(day, monkeypatch):
    telegram, bot = _run(day, MCX_WINDOW, monkeypatch)
    telegram.send_message.assert_not_called()


def test_the_mcx_report_still_arrives_on_dussehra(monkeypatch):
    """THE CASE A SHARED ANSWER WOULD HAVE GOT WRONG. Equities were closed all
    day, MCX traded from 17:00, and that evening window is the only one
    SessionShift has. Suppressing this report would hide a real session."""
    telegram, bot = _run(DUSSEHRA, MCX_WINDOW, monkeypatch)
    telegram.send_message.assert_called_once_with("report body")


def test_the_mcx_report_still_arrives_on_a_trading_day(monkeypatch):
    telegram, bot = _run(MONDAY, MCX_WINDOW, monkeypatch)
    telegram.send_message.assert_called_once_with("report body")


# ====================================================== how it is written
def test_the_guard_does_not_short_circuit_the_tick():
    """A `continue` was my first version of this, and it was wrong twice: the
    MCX report and every per-exchange shadow session sit below these blocks,
    and the loop's own sleep is at the very bottom - so it would have skipped
    the rest of the tick AND spun the CPU."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    block = src.split("Auto-send the plain-language end-of-day report")[1]
    block = block.split("# Manage shadow sessions independently")[0]
    # Comments stripped first: the code carries a comment explaining exactly
    # this trap, and that comment is the reason it stays understood.
    code = " ".join(line.split("#")[0] for line in block.splitlines())
    assert "continue" not in code
    assert block.count('_segment_shut_today("NSE")') == 1
    assert block.count('_segment_shut_today("MCX")') == 1


def test_an_unreadable_calendar_leaves_both_reports_sending():
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    body = src.split("def _segment_shut_today")[1].split("def _describe_today")[0]
    assert "except Exception:" in body
    assert "return False" in body


def test_nobody_asks_session_kind_by_hand_to_suppress_a_message():
    """THE RAIL, the same one `nothing_trades` has. `session_kind` answers
    None outside the data and CLOSED inside it, so

        if session_kind(day, seg) != FULL:      # silences on None

    reads naturally and goes quiet on exactly the dates nobody has maintained.
    Suppression goes through segment_shut. option_archive is listed because it
    asks in order to LABEL an archived day, not to withhold a message.
    """
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    # session_manager asks in order to STATE whether the market is open, and
    # option_archive in order to LABEL an archived day. Neither withholds a
    # message, which is what this rail is about.
    allowed = {"trading_calendar.py", "option_archive.py", "session_manager.py"}
    offenders = []
    for path in (root / "src").rglob("*.py"):
        if path.name in allowed:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "session_kind(" in line.split("#")[0]:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "call trading_calendar.segment_shut instead:\n" + "\n".join(offenders))
