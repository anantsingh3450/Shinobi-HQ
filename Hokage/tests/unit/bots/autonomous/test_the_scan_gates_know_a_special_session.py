"""Three more gates that would have slept through a live session.

Teaching the calendar to the five senders and to the engine's session status
was not enough. Between "the exchange is open" and "an order is placed" sit
three more weekday rules, and every one of them would have made Diwali
Muhurat trading a no-op on Sunday 2026-11-08:

    Day-of-Week Isolator      on a weekend the allowed sectors are crypto and
                              forex ONLY, so every index, equity and commodity
                              symbol is blocked - index options are the whole
                              tradable universe
    MCX entry guard           `if now_ist.weekday() >= 5: return`, before the
                              entry window is even looked at
    Opening bell observation   hardcoded 09:15-09:30, so a 14:20 open gets no
                              observation at all and Hokage enters on the
                              first tick of the noisiest part of a thin
                              80-minute session

The first two are the dangerous direction - a session missed in silence. The
third is the opposite, and it is the one that was fixed by TIGHTENING: the
window now follows the session's real open, 14:20-14:35.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

MUHURAT = dt.date(2026, 11, 8)          # Sunday, trades 14:20-15:40
DEAD_SUNDAY = dt.date(2026, 11, 15)
MONDAY = dt.date(2026, 11, 9)


def _bot(day: dt.date, hhmm: str = "14:30"):
    hour, minute = (int(x) for x in hhmm.split(":"))
    moment = dt.datetime.combine(day, dt.time(hour, minute))
    bot = SimpleNamespace(_now_ist=lambda: moment)
    return bot


# ============================================= what the accessors answer
def test_the_special_record_is_found_on_the_muhurat_sunday():
    record = Bot._special_session_today(_bot(MUHURAT))
    assert record is not None
    assert "Muhurat" in record["name"]


@pytest.mark.parametrize("day", [DEAD_SUNDAY, MONDAY])
def test_an_ordinary_day_has_no_special_record(day):
    assert Bot._special_session_today(_bot(day)) is None


def test_the_window_is_per_league():
    bot = _bot(MUHURAT)
    assert Bot._special_window_today(bot, "NSE") == (dt.time(14, 20), dt.time(15, 40))
    assert Bot._special_window_today(bot, "MCX") == (dt.time(14, 20), dt.time(15, 30))
    assert Bot._special_window_today(_bot(MONDAY), "NSE") is None


def test_an_unreadable_calendar_changes_nothing(monkeypatch):
    """Both accessors swallow a failure and report "ordinary day", so a
    broken calendar leaves the weekday rules exactly as they were rather
    than crashing the scan."""
    import hokage.memory.trading_calendar as tc

    def boom(*a, **k):
        raise RuntimeError("calendar unreadable")

    monkeypatch.setattr(tc, "special_session", boom)
    monkeypatch.setattr(tc, "session_window", boom)
    assert Bot._special_session_today(_bot(MUHURAT)) is None
    assert Bot._special_window_today(_bot(MUHURAT), "NSE") is None


# ================================================= the Day-of-Week Isolator
def _isolator_sectors(day: dt.date):
    """Run the isolator's branch exactly as the scan does, from its source.

    The scan around it needs a venue, a profile, a price source and a cache,
    so the branch is executed here rather than the whole function - but it is
    EXECUTED, compiled from the production lines themselves, so a change to
    them changes this test's answer too.
    """
    import pathlib
    import textwrap

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    start = src.index("        # A SPECIAL SESSION IS NOT A WEEKEND. This filter")
    end = src.index('            day_desc = "Weekend (Sat-Sun) - Forex/Crypto only"')
    block = textwrap.dedent(src[start:end] + '            day_desc = "Weekend (Sat-Sun) - Forex/Crypto only"\n')

    bot = _bot(day)
    scope = {
        "self": SimpleNamespace(
            _special_session_today=lambda: Bot._special_session_today(bot)),
        "weekday": day.weekday(),
    }
    exec(compile(block, "<isolator>", "exec"), scope)
    return scope["allowed_sectors"], scope["day_desc"]


def test_the_isolator_allows_the_normal_universe_on_a_special_session():
    """THE GATE THAT WOULD HAVE DECIDED TOMORROW. Index options are the whole
    universe, and on a Sunday this filter allowed crypto and forex only."""
    sectors, desc = _isolator_sectors(MUHURAT)
    assert "index" in sectors
    assert "commodity" in sectors
    assert "Special session" in desc
    assert "Muhurat" in desc


def test_the_isolator_still_blocks_a_dead_weekend():
    sectors, desc = _isolator_sectors(DEAD_SUNDAY)
    assert sectors == ["crypto", "forex"]
    assert "Weekend" in desc


def test_the_isolator_is_unchanged_on_an_ordinary_weekday():
    sectors, desc = _isolator_sectors(MONDAY)
    assert "index" in sectors
    assert desc == "Weekday (Mon-Fri) - Indices/Equities/Commodities only"


# ======================================================== the MCX entry guard
def test_the_mcx_guard_no_longer_returns_on_the_weekday_alone():
    """The published hours REPLACE the usual 09:30-22:30 window. Reusing that
    window on 2026-11-08 would open five hours before the session and stay
    open seven hours after it closed."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    guard = src.split("# Weekday guard: MCX runs Monday-Friday")[1][:1200]
    assert "now_ist.weekday() >= 5 and special_window is None" in guard
    assert "self._MCX_FIRST_ENTRY" in guard      # the ordinary path survives


@pytest.mark.parametrize("hhmm,inside", [
    ("09:30", False),       # the ordinary first entry, hours before this open
    ("14:19", False),
    ("14:20", True),
    ("15:29", True),
    ("15:30", False),       # MCX closes here, equity F&O runs to 15:40
    ("22:00", False),       # inside the ordinary window, outside this session
])
def test_the_mcx_entry_window_follows_the_published_hours(hhmm, inside):
    start, end = Bot._special_window_today(_bot(MUHURAT), "MCX")
    hour, minute = (int(x) for x in hhmm.split(":"))
    assert (((start.hour, start.minute) <= (hour, minute)
             < (end.hour, end.minute))) is inside


# ================================================= the observation window
def _observation(day: dt.date, hhmm: str) -> tuple[bool, dt.time]:
    """The production lines, executed."""
    import pathlib
    import textwrap

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    start = src.index("        # The opening bell is not always 09:15.")
    end = src.index("        is_observation_window = _obs_open <= ist_now.time() < _obs_end")
    block = textwrap.dedent(
        src[start:end]
        + "        is_observation_window = _obs_open <= ist_now.time() < _obs_end\n")

    hour, minute = (int(x) for x in hhmm.split(":"))
    moment = dt.datetime.combine(day, dt.time(hour, minute))
    bot = _bot(day, hhmm)
    scope = {
        "self": SimpleNamespace(
            _special_window_today=lambda seg: Bot._special_window_today(bot, seg)),
        "ist_now": moment,
        "dt_time": dt.time,
        "datetime": dt.datetime,
        "timedelta": dt.timedelta,
    }
    exec(compile(block, "<observation>", "exec"), scope)
    return scope["is_observation_window"], scope["_obs_end"]


@pytest.mark.parametrize("hhmm,expected", [
    ("14:19", False),
    ("14:20", True),        # the session opens
    ("14:34", True),
    ("14:35", False),       # fifteen minutes later, entries allowed
    ("09:20", False),       # the ordinary window does NOT apply to this day
])
def test_the_observation_window_follows_a_special_open(hhmm, expected):
    blocked, end = _observation(MUHURAT, hhmm)
    assert blocked is expected
    assert end == dt.time(14, 35)


@pytest.mark.parametrize("hhmm,expected", [
    ("09:14", False), ("09:15", True), ("09:29", True), ("09:30", False),
    ("14:25", False),
])
def test_the_ordinary_observation_window_is_untouched(hhmm, expected):
    blocked, end = _observation(MONDAY, hhmm)
    assert blocked is expected
    assert end == dt.time(9, 30)


def test_the_blocked_reason_states_the_real_time():
    """A reason that says "until 09:30 AM IST" during a 14:20 session is a
    fabricated explanation, which is the defect family this project keeps
    paying for."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    assert "_obs_end.strftime('%H:%M')} IST." in src
    assert "until 09:30 AM IST" not in src
