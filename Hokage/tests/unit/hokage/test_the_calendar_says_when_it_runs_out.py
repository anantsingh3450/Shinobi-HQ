"""The calendar expires on 2026-12-31 and nothing would have said so.

`trading_calendar` answers None for a year nobody has entered, and every
caller handles None correctly. That is the problem. Nothing errors, nothing
goes red, and SIX behaviours revert at midnight on New Year's Eve:

    the 08:45 checklist goes back to red-flagging every Saturday
    the blind-feed alarm goes back to nagging for a login on a holiday
    both EOD reports go back to reporting "no trades" about a shut market
    the watchdog's staleness window goes back to expecting a dead feed
    the option archive goes back to storing a chain nobody traded
    and a holiday with an MCX evening in it gets written off entirely

That is 2026-10-20 and 2026-11-07 arriving together, on a date known a year
in advance, with nothing on fire to notice it by.

SO THE FILE SAYS HOW LONG IT HAS LEFT. These tests pin the countdown, the
escalation past the date, and the two places the warning reaches him. They
also pin the fail-safe direction twice over: an uncovered year is unknown
rather than open, and a year LISTED WITH NO DATES IN IT is also unknown -
a half-typed year must not read as a year with no holidays in it, because
that calls Republic Day a normal session.

ONE TEST HERE IS A DEADLINE. `test_the_calendar_covers_today` fails the day
the data runs out, by design: an unmaintained calendar must become loud,
never quiet, and a red suite is the loudest thing this project has.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from hokage.memory import trading_calendar as cal


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src").is_dir() and (parent / "tests").is_dir():
            return parent
    raise AssertionError("could not find the repository root")


def _code_only(src: str) -> str:
    """Source with its comment lines removed.

    A text rail that reads prose fires on the comment EXPLAINING the trap it
    guards - that happened four times on 2026-11-09. The assertions below
    must see code.
    """
    return "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))


# ------------------------------------------------------------- the deadline
def test_the_calendar_covers_today():
    """THE ALARM, AND IT IS MEANT TO GO OFF.

    When this fails the fix is one block of dates in
    src/hokage/memory/trading_calendar.py, taken from the NSE circular -
    never from a holiday website, six of which disagreed with each other
    when this was checked.
    """
    today = dt.date.today()
    assert cal.covers(today), (
        f"the trading calendar has no data for {today.year}: "
        f"{cal.coverage_warning(today)}")


def test_the_shipped_tables_do_not_contradict_each_other():
    assert cal.coverage_problems() == []


# -------------------------------------------------- unknown, never open
def test_an_uncovered_year_is_unknown_rather_than_open():
    """Every shape of day, so that no single rule leaks an answer: a plain
    weekday, a weekend, and a date that IS a holiday but in a year nobody
    typed."""
    for day in (dt.date(2027, 3, 15),      # Monday
                dt.date(2027, 3, 20),      # Saturday
                dt.date(2027, 1, 26)):     # Republic Day, every year
        assert cal.session_kind(day, "NSE") is None
        assert cal.session_kind(day, "MCX") is None
        assert cal.anything_trades(day) is None
        assert cal.nothing_trades(day) is False      # unknown is not shut
        assert cal.segment_shut(day, "NSE") is False
        assert cal.holiday_name(day) is None


def test_a_year_listed_with_no_dates_in_it_is_not_coverage(monkeypatch):
    """THE FAIL-SAFE DIRECTION. A year opened and not finished must answer
    like a year nobody touched. Reading an empty table as "no holidays this
    year" calls Republic Day a normal session, which is the exact failure
    this file was written for, with the authority of a typed year."""
    monkeypatch.setitem(cal._EQUITY_HOLIDAYS, 2027, {})
    assert 2027 not in cal.covered_years()
    assert cal.covers(dt.date(2027, 1, 26)) is False
    assert cal.session_kind(dt.date(2027, 1, 26), "NSE") is None
    assert cal.session_kind(dt.date(2027, 3, 15), "NSE") is None
    problems = cal.coverage_problems()
    assert any("2027" in p and "no holidays" in p for p in problems), problems


def test_a_date_entered_under_the_wrong_year_is_reported(monkeypatch):
    """A 2028 date in the 2027 block is unreachable - session_kind looks it
    up in its own year's table and finds nothing, so the holiday reads as a
    normal session."""
    monkeypatch.setitem(cal._EQUITY_HOLIDAYS, 2027,
                        {dt.date(2028, 1, 26): "Republic Day"})
    problems = cal.coverage_problems()
    assert any("2028-01-26" in p for p in problems), problems


# ------------------------------------------------------------- the countdown
def test_the_countdown_reaches_zero_on_the_last_covered_day():
    assert cal.covered_until(dt.date(2026, 11, 10)) == dt.date(2026, 12, 31)
    assert cal.days_of_coverage(dt.date(2026, 12, 31)) == 0
    assert cal.days_of_coverage(dt.date(2026, 12, 30)) == 1
    assert cal.days_of_coverage(dt.date(2027, 1, 1)) is None
    assert cal.covered_until(dt.date(2027, 1, 1)) is None


def test_nothing_is_said_while_there_is_time():
    """A warning that runs all year is a warning nobody reads."""
    assert cal.coverage_warning(dt.date(2026, 1, 2)) is None
    assert cal.coverage_warning(dt.date(2026, 9, 1)) is None


def test_the_warning_starts_exactly_at_the_window():
    last = cal.covered_until(dt.date(2026, 6, 1))
    assert last is not None
    opens = last - dt.timedelta(days=cal.COVERAGE_WARNING_DAYS)
    assert cal.coverage_warning(opens - dt.timedelta(days=1)) is None
    assert cal.coverage_warning(opens) is not None


def test_the_window_is_long_enough_to_act_on():
    """NSE publishes the next year's list in December. A window that opens
    after the circular is a window that can only report the cliff, not
    prevent it."""
    assert cal.COVERAGE_WARNING_DAYS >= 40


def test_the_warning_names_the_year_and_the_source():
    text = cal.coverage_warning(dt.date(2026, 11, 10))
    assert text is not None
    assert "2027" in text                       # the year to enter
    assert "2026-12-31" in text                 # the date it runs out
    assert "nseindia" in text                   # where the dates come from
    assert "src/hokage/memory/" in text         # which file to put them in
    assert "51" in text                         # days left, on that date


def test_the_warning_escalates_once_the_date_has_passed():
    before = cal.coverage_warning(dt.date(2026, 12, 20))
    after = cal.coverage_warning(dt.date(2027, 1, 3))
    assert before is not None and after is not None
    assert "runs out" in before
    assert "EXPIRED" in after
    assert "3 days ago" in after
    assert "2027" in after and "nseindia" in after


def test_the_expired_warning_says_what_has_already_broken():
    """He needs to know what is now wrong, not only that a file is stale."""
    text = cal.coverage_warning(dt.date(2027, 2, 1))
    assert text is not None
    for consequence in ("08:45", "Saturday", "login", "EOD", "MCX"):
        assert consequence in text, consequence


def test_one_day_is_not_pluralised():
    text = cal.coverage_warning(dt.date(2026, 12, 30))
    assert text is not None and "1 day," in text
    gone = cal.coverage_warning(dt.date(2027, 1, 1))
    assert gone is not None and "1 day ago" in gone


def test_the_last_day_says_today():
    text = cal.coverage_warning(dt.date(2026, 12, 31))
    assert text is not None
    assert "TODAY" in text
    assert "in 0 days" not in text


def test_the_warning_carries_no_markdown_control_characters():
    """These go out over legacy Telegram Markdown, where ONE unpaired
    control character used to eat the entire message. A file path with an
    underscore in it is exactly how that happens, so the warning names the
    directory instead."""
    texts = [cal.coverage_warning(d) for d in (dt.date(2026, 11, 10),
                                               dt.date(2026, 12, 31),
                                               dt.date(2027, 1, 1),
                                               dt.date(2027, 6, 1))]
    for text in texts:
        assert text is not None
        for char in ("_", "*", "[", "`", "\\"):
            assert char not in text, f"{char!r} in: {text}"


def test_a_gap_year_is_a_cliff_like_any_other(monkeypatch):
    """With 2027 missing and 2028 entered, coverage still ends on
    2026-12-31. Reporting the furthest year in the table would hide a hole
    in the middle of it."""
    monkeypatch.setitem(cal._EQUITY_HOLIDAYS, 2028,
                        {dt.date(2028, 1, 26): "Republic Day"})
    assert cal.covered_until(dt.date(2026, 11, 10)) == dt.date(2026, 12, 31)
    text = cal.coverage_warning(dt.date(2026, 11, 10))
    assert text is not None and "Enter 2027" in text


def test_a_run_of_years_extends_the_coverage(monkeypatch):
    monkeypatch.setitem(cal._EQUITY_HOLIDAYS, 2027,
                        {dt.date(2027, 1, 26): "Republic Day"})
    assert cal.covered_until(dt.date(2026, 11, 10)) == dt.date(2027, 12, 31)
    assert cal.coverage_warning(dt.date(2026, 11, 10)) is None
    assert cal.session_kind(dt.date(2027, 1, 26), "NSE") == cal.CLOSED
    assert cal.session_kind(dt.date(2027, 1, 25), "NSE") == cal.FULL


def test_a_day_before_the_data_starts_is_not_an_expiry():
    """2025 is uncovered too, and it is not a stale calendar - saying
    "EXPIRED 400 days ago" about it would send him to fix the wrong year."""
    text = cal.coverage_warning(dt.date(2025, 6, 1))
    assert text is not None
    assert "EXPIRED" not in text
    assert "does not cover today" in text
    assert "2026" in text


# ---------------------------------------------------- an unreachable evening
def test_an_mcx_evening_without_an_equity_holiday_is_reported(monkeypatch):
    """The evening table is read ONLY for a day that is already an equity
    holiday, so a date listed there and nowhere else never fires - it is a
    tradeable MCX evening written off by a typo."""
    monkeypatch.setattr(
        cal, "_MCX_EVENING_ON_EQUITY_HOLIDAY",
        cal._MCX_EVENING_ON_EQUITY_HOLIDAY | {dt.date(2026, 7, 7)})
    problems = cal.coverage_problems()
    assert any("2026-07-07" in p for p in problems), problems


def test_a_special_session_in_an_uncovered_year_is_reported(monkeypatch):
    """A Muhurat date entered for a year whose holidays were never typed is
    unreachable, and every calendar-gated sender goes silent through a live
    afternoon - 2026-11-08 exactly."""
    monkeypatch.setitem(cal._SPECIAL_SESSIONS, dt.date(2027, 10, 29),
                        {"name": "Diwali Muhurat", "windows": {}, "source": "x"})
    problems = cal.coverage_problems()
    assert any("2027-10-29" in p for p in problems), problems


# ------------------------------------------------------ describe, and copies
def test_describe_an_uncovered_day_names_the_years_it_has():
    text = cal.describe(dt.date(2027, 3, 15))
    assert "unknown" in text
    assert "not the same as open" in text
    assert "2026" in text
    assert "nseindia" in text


def test_the_holiday_accessor_hands_out_a_copy():
    """Three tests used to read the private dict. A reader that mutates what
    it is given must not be able to edit the calendar."""
    got = cal.holidays(2026)
    got.clear()
    assert cal.holidays(2026), "the accessor handed out the real table"
    assert cal.holidays(2099) == {}
    assert cal.holiday_name(dt.date(2026, 10, 20)) == "Dussehra"


def test_rubbish_input_is_uncovered_not_a_crash():
    assert cal.covers("tuesday") is False       # type: ignore[arg-type]
    assert cal.covers(None) is False            # type: ignore[arg-type]
    assert cal.holiday_name("tuesday") is None  # type: ignore[arg-type]


# --------------------------------------------------- where it reaches him
def test_boot_logs_the_coverage_warning():
    src = _code_only((_repo_root() / "src" / "bots" / "autonomous"
                      / "autonomous_bot.py").read_text(encoding="utf-8"))
    boot = src.split('logger.info("Session calendar: %s"')[1][:1500]
    assert "trading_calendar.coverage_warning()" in boot
    assert "coverage_problems()" in boot
    assert "logging.ERROR" in boot, "an expired calendar is not a warning"


def test_the_morning_checklist_carries_the_warning():
    """THE CHANNEL THAT ARRIVES EVERY DAY. A log line at boot is read when
    something else has already gone wrong; this message is read at 08:45."""
    src = _code_only((_repo_root() / "src" / "bots" / "autonomous"
                      / "cron_reset.py").read_text(encoding="utf-8"))
    assert "trading_calendar.coverage_warning()" in src
    assert "coverage_problems()" in src
    assert "{calendar_line}" in src, "built but never put in the message"


def test_the_checklist_does_not_go_red_on_a_stale_calendar():
    """Deliberate: the fix is a commit, not an action before the open, and a
    red that cannot be cleared before 09:00 is a red he learns to ignore."""
    src = _code_only((_repo_root() / "src" / "bots" / "autonomous"
                      / "cron_reset.py").read_text(encoding="utf-8"))
    block = src.split("calendar_line = \"\"")[1].split("msg = (")[0]
    assert "checklist_passed = False" not in block
