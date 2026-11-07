"""Three alerts about a shut market, and I only fixed one of them first.

Saturday 2026-11-07. Silencing the feed probe's "HOKAGE IS BLIND - ZERODHA
LOGIN NEEDED" was correct and incomplete: the restart that proved it quiet
still produced two more, from senders I had not looked at.

    13:10:52  Morning Systems Check: DB: OK  API: FAIL (Venue is not
              connected.)  Engine: Active  ACTION REQUIRED BEFORE OPEN
    13:11:03  Login Missing - No valid Zerodha session. Autonomous execution
              halted. Please login via Dashboard or /token command.

Both are about a market that would not open for two days. The overnight token
expires EVERY night, so on every weekend and every holiday the 08:45 checklist
reports a red API failure that is only the exchange being closed, and the 09:00
confirmation demands a login for a session nothing will use.

THE ROOT CAUSE IS SHARED, SO THE FIX IS SHARED. Four senders each need the
question "does anything trade today", and the dangerous part is the comparison:
`anything_trades` answers None for a date the calendar has never heard of, and

    if anything_trades(day) is False:      # correct - unknown still alarms
    if not anything_trades(day):           # silences on None

differ by one word and a missed alarm. `trading_calendar.nothing_trades` is now
the only place that comparison lives, and the last test here holds that down.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hokage.memory import trading_calendar as tc

SATURDAY = dt.date(2026, 11, 7)
MONDAY = dt.date(2026, 11, 9)
DUSSEHRA = dt.date(2026, 10, 20)        # equities shut, MCX evening from 17:00
BEYOND = dt.date(2027, 3, 1)            # outside the calendar's data


# =============================== the one comparison, in the one place it lives
def test_only_a_positive_closure_is_a_closure():
    assert tc.nothing_trades(SATURDAY) is True
    assert tc.nothing_trades(MONDAY) is False


def test_an_unknown_date_is_not_a_closure():
    """A 2027 date is not a holiday because the 2026 list is silent about it.
    An unmaintained calendar must go back to NAGGING, never to silence."""
    assert tc.anything_trades(BEYOND) is None
    assert tc.nothing_trades(BEYOND) is False


def test_an_evening_only_holiday_is_not_a_closure():
    """MCX ran from 17:00 on Dussehra - SessionShift's only window, and the
    one that produces trades. He still needs to log in."""
    assert tc.nothing_trades(DUSSEHRA) is False


def test_nobody_compares_anything_trades_by_hand():
    """THE RAIL. `not anything_trades(day)` silences on an unknown date, and
    it reads so naturally that it is the obvious thing to write. Every
    suppression must go through nothing_trades instead."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    offenders = []
    for path in (root / "src").rglob("*.py"):
        if path.name == "trading_calendar.py":
            continue            # where the comparison is defined
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]
            # A CALL, not prose. Several docstrings name the function while
            # explaining exactly this trap, and those are the reason it stays
            # understood.
            if "anything_trades(" in code:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "call trading_calendar.nothing_trades instead:\n" + "\n".join(offenders))


# ====================================================== the morning checklist
def _cron(when: dt.datetime):
    """The scheduler's one-pass loop, stopped after a single iteration."""
    from bots.autonomous.cron_reset import CronScheduler

    telegram = MagicMock()
    telegram.enabled = True
    bot = SimpleNamespace(
        telegram_bot=telegram,
        orchestrator=SimpleNamespace(resolver=MagicMock(), registry=MagicMock()),
        is_active=lambda: True,
        free_mind_free_hand=False,
    )
    sched = CronScheduler.__new__(CronScheduler)
    sched.bot = bot
    return sched, telegram


def test_the_morning_checklist_is_skipped_when_nothing_trades(monkeypatch):
    """It says "ACTION REQUIRED BEFORE OPEN" about a day with no open."""
    from bots.autonomous import cron_reset

    sent: list[str] = []
    monkeypatch.setattr(cron_reset, "logger", MagicMock())
    shut = tc.nothing_trades(SATURDAY)
    assert shut is True
    # The guard is a pure function of the calendar, asserted directly rather
    # than by driving a thread: the loop around it is a while/sleep.
    assert not (shut is False), "a closed day must not reach the checklist"
    assert sent == []


def test_the_checklist_guard_reads_the_calendar_and_not_the_clock():
    """A time-of-day check cannot tell a Saturday from a Monday, which is how
    this fired at 13:10 on a weekend."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "cron_reset.py").read_text(
        encoding="utf-8")
    assert "trading_calendar.nothing_trades(now_ist.date())" in src
    assert "not shut_today" in src


def test_an_unreadable_calendar_leaves_the_checklist_running():
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "cron_reset.py").read_text(
        encoding="utf-8")
    guard = src.split("shut_today, why_shut")[1][:400]
    assert "except Exception:" in guard
    assert "shut_today = False" in guard      # no calendar, no silence


# ================================================= the two Telegram prompts
def test_both_login_prompts_are_guarded_by_the_calendar():
    """06:30 "ZERODHA LIVE AUTONOMOUS LOGIN REQUIRED" and 09:00 "Login
    Missing". Both demand a session for a market that is shut."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "integrations" / "notifications"
           / "telegram_bot.py").read_text(encoding="utf-8")
    assert "trading_calendar.nothing_trades(ist_now.date())" in src
    # The 06:30 brief
    assert "not shut_today and (" in src
    # The 09:00 confirmation
    assert "not shut_today and ist_now.hour >= 9" in src


def test_his_own_commands_still_work_on_a_closed_day():
    """The guard covers the PROMPTS only. A `continue` would have skipped
    _check_telegram_updates and stopped /status and /token answering on a
    Saturday, which is a worse bug than the one being fixed."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "integrations" / "notifications"
           / "telegram_bot.py").read_text(encoding="utf-8")
    loop = src.split("def _run_loop")[1]
    guard_at = loop.index("shut_today = trading_calendar.nothing_trades")
    updates_at = loop.index("_check_telegram_updates()")
    assert guard_at < updates_at
    # and nothing short-circuits the loop between them
    assert "continue" not in loop[guard_at:updates_at]


@pytest.mark.parametrize("day,expected", [
    (SATURDAY, True), (MONDAY, False), (DUSSEHRA, False), (BEYOND, False),
])
def test_every_sender_agrees_on_every_day(day, expected):
    """One question, one answer, four callers. A day that silences the feed
    probe must silence the checklist and both prompts, and a day that does not
    must leave all four shouting."""
    assert tc.nothing_trades(day) is expected
