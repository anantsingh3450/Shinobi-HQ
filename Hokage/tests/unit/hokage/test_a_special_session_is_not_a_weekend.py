"""The day a weekend trades.

2026-11-07, late evening. The five calendar-blind senders had just been taught
to go quiet when nothing trades, and the commander said: tomorrow is Diwali
Muhurat trading, be ready for such things as well.

He was right, and the gate shipped that afternoon was five hours from its
first real failure. `session_kind` answered CLOSED for Sunday 2026-11-08 on
the weekend rule alone, before consulting any list, so for the whole of a live
session the feed alarm, the login prompt, the morning checklist and both
end-of-day reports would have said nothing. Nagging is visible. Silence is
not, and this system has already spent nine days blind without a word.

Two more things were wrong behind it, both found on the same thread:

  * The ENGINE keeps a second, hand-typed holiday list. It would have slept
    through the Muhurat session and archived no candles - a hole in the tape
    of exactly the kind that cost three months of training data on an MCX
    roll - and it did not contain 2026-11-10 or 2026-11-24, so it would have
    scanned two shut markets as if they were open.
  * The watchdog's staleness window starts at 09:00 on weekdays. Muhurat runs
    14:20-15:40 on a Sunday: disarmed through the session, and armed five
    hours before a quote could arrive.

The rule this file holds down: A WEEKDAY NUMBER IS NOT A CLOSURE. Only the
calendar decides, and it consults the special-session table first.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from hokage.memory import trading_calendar as tc

MUHURAT = dt.date(2026, 11, 8)          # Sunday, and it trades
DEAD_SUNDAY = dt.date(2026, 11, 15)     # Sunday, and it does not
MONDAY = dt.date(2026, 11, 9)           # normal session
BALIPRATIPADA = dt.date(2026, 11, 10)   # Tuesday, shut, absent from the engine
JUNE_HOLIDAY = dt.date(2026, 6, 26)     # a holiday the engine called open
DUSSEHRA = dt.date(2026, 10, 20)        # equities shut, MCX EVENING from 17:00
BEYOND = dt.date(2027, 3, 2)            # outside the calendar's data

#: The broker's published window for equity F&O, which is the whole universe.
NSE_WINDOW = (dt.time(14, 20), dt.time(15, 40))
MCX_WINDOW = (dt.time(14, 20), dt.time(15, 30))


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


# ===================================================== the calendar itself
def test_the_muhurat_sunday_is_a_trading_day():
    assert MUHURAT.weekday() == 6
    assert tc.session_kind(MUHURAT, "NSE") == tc.MUHURAT
    assert tc.session_kind(MUHURAT, "MCX") == tc.MUHURAT
    assert tc.anything_trades(MUHURAT) is True


def test_two_sundays_one_shut_one_open():
    """The comparison the old code could not make."""
    assert DEAD_SUNDAY.weekday() == MUHURAT.weekday() == 6
    assert tc.session_kind(DEAD_SUNDAY, "NSE") == tc.CLOSED
    assert tc.session_kind(MUHURAT, "NSE") == tc.MUHURAT


def test_the_published_windows_are_what_the_broker_said():
    assert tc.session_window(MUHURAT, "NSE") == NSE_WINDOW
    assert tc.session_window(MUHURAT, "MCX") == MCX_WINDOW


def test_an_ordinary_day_has_no_special_window():
    """None means "the usual hours", NOT "shut" - the hours live in the
    engine's session manager and this file does not duplicate them."""
    assert tc.session_window(MONDAY, "NSE") is None
    assert tc.special_session(MONDAY) is None
    assert tc.segment_shut(MONDAY, "NSE") is False


def test_muhurat_is_an_afternoon_session_not_an_evening_one():
    """MCX's 17:00 evening start belongs to equity holidays. Reusing it here
    would hunt a market that shut at 15:30."""
    assert MCX_WINDOW[1] < tc.EVENING_SESSION_START
    assert tc.session_kind(MUHURAT, "MCX") != tc.EVENING


def test_the_widest_span_covers_both_leagues():
    assert tc.session_span(MUHURAT) == (dt.time(14, 20), dt.time(15, 40))
    assert tc.session_span(DEAD_SUNDAY) is None


def test_the_description_says_which_hours():
    line = tc.describe(MUHURAT)
    assert "SPECIAL SESSION" in line
    assert "14:20-15:40" in line
    assert "Muhurat" in line


# ====================================== the five senders come back to life
@pytest.mark.parametrize("segment", ["NSE", "MCX"])
def test_nothing_is_suppressed_on_a_special_session(segment):
    assert tc.nothing_trades(MUHURAT) is False
    assert tc.segment_shut(MUHURAT, segment) is False


def test_the_weekend_rule_does_not_get_to_answer_first():
    """THE RAIL. Every one of those senders asks this one function, so the
    order of these two checks inside it is the difference between a noisy
    Sunday and a silent live session."""
    src = (_repo_root() / "src" / "hokage" / "memory"
           / "trading_calendar.py").read_text(encoding="utf-8")
    body = src.split("def session_kind")[1].split("\ndef ")[0]
    special_at = body.index("_SPECIAL_SESSIONS.get(day)")
    weekend_at = body.index("day.weekday() >= 5")
    assert special_at < weekend_at, (
        "the weekend short-circuit is back in front of the special-session "
        "table, which silences every sender through a Muhurat session")


# ====================================== the watchdog follows the real hours
@pytest.mark.parametrize("when,expected", [
    (dt.datetime(2026, 11, 8, 9, 0), False),      # the ordinary window start
    (dt.datetime(2026, 11, 8, 14, 19), False),
    (dt.datetime(2026, 11, 8, 14, 20), True),     # the session opens
    (dt.datetime(2026, 11, 8, 15, 39), True),
    (dt.datetime(2026, 11, 8, 15, 40), False),    # and closes
    (dt.datetime(2026, 11, 8, 22, 0), False),
    (dt.datetime(2026, 11, 15, 14, 30), False),   # a dead Sunday, same clock
    (dt.datetime(2026, 11, 9, 10, 0), True),      # an ordinary Monday
])
def test_the_staleness_alarm_arms_only_inside_the_session(when, expected):
    from shared.watchdog.watchdog import Watchdog

    assert Watchdog.feed_expected_now(when) is expected


# ============================================== the engine's session status
def _status(day: dt.date, hhmm: str, exchange_name: str) -> str:
    from integrations.brokers.session_manager import TradingSessionManager
    from integrations.data.models import Exchange

    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    hour, minute = (int(x) for x in hhmm.split(":"))
    when = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ist)
    return TradingSessionManager().get_exchange_status(
        getattr(Exchange, exchange_name), when.astimezone(dt.timezone.utc))


@pytest.mark.parametrize("hhmm,expected", [
    ("09:00", "CLOSED"),        # the ordinary open is not this session
    ("14:04", "CLOSED"),
    ("14:05", "PRE_OPEN"),      # the published 15-minute pre-open
    ("14:20", "OPEN"),
    ("15:39", "OPEN"),
    ("15:40", "CLOSED"),
])
def test_the_engine_is_awake_for_the_muhurat_session(hhmm, expected):
    """Asleep here means no scan, no quote and NO ARCHIVED CANDLES for a real
    session - the hole in the tape is the part that cannot be repaired later."""
    assert _status(MUHURAT, hhmm, "NSE") == expected


def test_the_two_leagues_close_at_their_own_times():
    """MCX stops at 15:30, equity F&O runs to 15:40. One shared answer would
    have to be wrong about one of them."""
    assert _status(MUHURAT, "15:35", "NSE") == "OPEN"
    assert _status(MUHURAT, "15:35", "MCX") == "CLOSED"


def test_the_engine_sleeps_on_a_dead_sunday():
    assert _status(DEAD_SUNDAY, "14:30", "NSE") == "CLOSED"


def test_an_ordinary_session_still_keeps_its_published_hours():
    """The special-session branch must not become a third place that
    09:15-15:30 is written down."""
    assert _status(MONDAY, "09:05", "NSE") == "PRE_OPEN"
    assert _status(MONDAY, "10:00", "NSE") == "OPEN"
    assert _status(MONDAY, "15:45", "NSE") == "POST_CLOSE"
    assert _status(MONDAY, "18:00", "NSE") == "CLOSED"


@pytest.mark.parametrize("day", [BALIPRATIPADA, JUNE_HOLIDAY])
def test_holidays_missing_from_the_engines_own_list_are_now_shut(day):
    """Both of these were absent from `indian_holidays`, so the engine would
    have scanned them and priced decisions off whatever last quote it had.
    2026-06-26 is confirmed shut by an absence of NIFTY candles in the
    archive; a test in this repo asserted it was open."""
    assert tc.session_kind(day, "NSE") == tc.CLOSED
    assert _status(day, "10:00", "NSE") == "CLOSED"


def test_dussehra_keeps_mcx_shut_until_the_evening():
    assert _status(DUSSEHRA, "10:00", "MCX") == "CLOSED"
    assert _status(DUSSEHRA, "18:00", "MCX") == "OPEN"
    assert _status(DUSSEHRA, "11:00", "NSE") == "CLOSED"


def test_an_unknown_date_changes_nothing_in_the_engine():
    """Outside the calendar's span the engine falls back to its own rules
    exactly as before. An unmaintained calendar must not quietly shut the
    market down."""
    assert tc.session_kind(BEYOND, "NSE") is None
    assert _status(BEYOND, "10:00", "NSE") == "OPEN"


# ============================================= nothing here may be invented
def test_every_special_session_carries_its_source():
    """These dates are exchange announcements, not inferences. The project's
    rule is that nothing in this file is guessed, and a window with no stated
    source is a guess whatever it says."""
    table = tc._SPECIAL_SESSIONS
    assert table, "the table must not be empty while a dated session exists"
    for day, record in table.items():
        assert isinstance(day, dt.date)
        assert record.get("name"), f"{day} has no name"
        assert record.get("source"), f"{day} has no source"
        assert record.get("windows"), f"{day} has no windows"
        for segment, window in record["windows"].items():
            assert segment in ("NSE", "MCX"), f"{day}: unknown segment {segment}"
            start, end = window
            assert start < end, f"{day} {segment}: window ends before it starts"


def test_a_special_session_sits_inside_the_calendars_span():
    """A date outside the span is unreachable - session_kind returns None
    before it ever looks at the table."""
    for day in tc._SPECIAL_SESSIONS:
        assert tc._KNOWN_FROM <= day <= tc._KNOWN_TO
        assert tc.session_kind(day, "NSE") is not None


# ====================================== the backstop for an unfed table
def _archive(tmp_path, days: list[str]):
    import sqlite3

    root = tmp_path / "brain"
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "candles.db")
    con.execute("CREATE TABLE candles (symbol TEXT, ts TEXT, close REAL)")
    con.executemany(
        "INSERT INTO candles VALUES ('NIFTY', ?, 100.0)",
        [(f"{d} 10:00:00",) for d in days])
    con.commit()
    con.close()
    return root


def test_a_traded_weekend_already_in_the_table_is_not_reported(tmp_path,
                                                              monkeypatch):
    """2026-11-08 traded and the table says so. Nothing to flag."""
    root = _archive(tmp_path, ["2026-11-06", "2026-11-08", "2026-11-09"])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    assert tc.unlisted_sessions_from_archive() == []


def test_a_traded_weekend_missing_from_the_table_is_flagged(tmp_path,
                                                            monkeypatch):
    """THE BACKSTOP. This is the only part of the calendar that can notice
    its own gap, and it notices in the dangerous direction: a day that traded
    while every rule here called it shut."""
    root = _archive(tmp_path, ["2026-11-09", "2027-11-07", "2027-11-14"])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    found = tc.unlisted_sessions_from_archive()
    assert found == [dt.date(2027, 11, 7), dt.date(2027, 11, 14)]


def test_an_absent_archive_asserts_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "nothing-here"))
    assert tc.unlisted_sessions_from_archive() == []


def test_the_backstop_never_writes_itself_into_the_table():
    """It REPORTS a gap; it does not fill one. A table that learned its own
    dates from the tape would be inferred data presented as an exchange
    announcement, and it still could not anticipate - the tape exists only
    after the session it was needed for."""
    src = (_repo_root() / "src" / "hokage" / "memory"
           / "trading_calendar.py").read_text(encoding="utf-8")
    reader = src.split("def unlisted_sessions_from_archive")[1].split(
        "def confirmed_holidays_from_archive")[0]
    assert "_SPECIAL_SESSIONS[" not in reader
    assert ".update(" not in reader
    assert "_SPECIAL_SESSIONS" in reader          # it reads the table
    # and nothing anywhere mutates it
    for marker in ("_SPECIAL_SESSIONS[", "_SPECIAL_SESSIONS.update",
                   "_SPECIAL_SESSIONS.setdefault", "_SPECIAL_SESSIONS.pop"):
        assert marker not in src, f"the table is being mutated: {marker}"


def test_boot_names_the_day_and_warns_about_a_missing_session():
    """Six gates decide what to do from the weekday. One line at boot makes
    the day's real hours readable without a log dive."""
    import pathlib

    src = (_repo_root() / "src" / "bots" / "autonomous"
           / "autonomous_bot.py").read_text(encoding="utf-8")
    boot = src.split("# WHAT DAY IS IT.")[1][:1200]
    assert 'logger.info("Session calendar: %s", self._describe_today())' in boot
    assert "unlisted_sessions_from_archive()" in boot
    assert "logger.warning" in boot


def test_the_morning_checklist_names_the_real_open():
    """"Awaiting 09:00 Open" is a fabricated line on a day that opens at
    14:20, and a message that states a falsehood is this project's most
    expensive recurring defect."""
    src = (_repo_root() / "src" / "bots" / "autonomous"
           / "cron_reset.py").read_text(encoding="utf-8")
    assert "trading_calendar.session_window(" in src
    assert "'Awaiting 09:00 Open.'" not in src
    assert "Awaiting {open_at} Open." in src
