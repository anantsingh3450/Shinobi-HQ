"""A holiday that closes NSE does not close MCX, and six evenings proved it.

2026-11-11. The question was whether the new MCX stand-down journaling had
written its first row. It had — two rows, exactly as designed, at 22:30 the
night before. The rest of that day's record was empty, and that is what
mattered:

    Session calendar: 2026-11-10: Diwali Balipratipada - everything closed

MCX ran its full 17:00-23:30 evening session that day. His own archive holds
27 fifteen-minute bars for each of the four commodities. "Everything closed"
was half right, and the wrong half stood both live assets down through the
entire 17:00-22:30 entry window while Hokage was awake for all of it.

THE CHAIN, each link verified:

    _MCX_EVENING_ON_EQUITY_HOLIDAY     2026-11-10 missing
    session_kind(day, "MCX")           -> CLOSED
    _indian_session_status             -> "CLOSED"
    session_manager.is_tradable        -> False
    the MCX scan loop                  -> bare `continue`, no row, no log

THE BACKSTOP THAT EXISTS FOR THIS COULD NOT SEE IT, for two independent
reasons that both had to be fixed. `unlisted_sessions_from_archive` tested
`day.weekday() >= 5`, so a WEEKDAY holiday that traded was invisible; and it
probed NIFTY, which has no MCX candles with which to disagree. Six evenings
had stacked up unnoticed since March.

Measured, from the tape rather than from a holiday website:

    2026-03-03  Holi                  17:00-23:45
    2026-03-26  exchange holiday      17:00-23:15
    2026-03-31  exchange holiday      17:00-23:15
    2026-05-28  exchange holiday      17:00-23:15
    2026-06-26  exchange holiday      17:00-23:15
    2026-11-10  Diwali Balipratipada  17:00-23:30

Only the last one cost anything: `no_trade_decisions` starts 2026-07-14, so
the other five are evidence about the exchange, not about him.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3

import pytest

from hokage.memory import trading_calendar as tc

BALIPRATIPADA = dt.date(2026, 11, 10)

#: Every date the tape positively contradicted. Named here as DATES, and
#: asserted through the public `session_kind` rather than the private set,
#: because what matters is the answer the engine gets.
MEASURED_EVENINGS = [
    dt.date(2026, 3, 3),
    dt.date(2026, 3, 26),
    dt.date(2026, 3, 31),
    dt.date(2026, 5, 28),
    dt.date(2026, 6, 26),
    dt.date(2026, 11, 10),
]

#: Equity holidays the archive says NOTHING about. They must stay shut.
UNMEASURED = [dt.date(2026, 4, 3), dt.date(2026, 12, 25)]


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


# ===================================================== the day itself
def test_balipratipada_closes_equities_and_opens_the_mcx_evening():
    """THE DEFECT, in one assertion pair."""
    assert tc.session_kind(BALIPRATIPADA, "NSE") == tc.CLOSED
    assert tc.session_kind(BALIPRATIPADA, "MCX") == tc.EVENING


def test_the_senders_no_longer_go_silent_through_that_evening():
    """`nothing_trades` is what four senders ask before suppressing
    themselves. It answered True for a day MCX traded for six hours."""
    assert tc.nothing_trades(BALIPRATIPADA) is False
    assert tc.segment_shut(BALIPRATIPADA, "NSE") is True
    assert tc.segment_shut(BALIPRATIPADA, "MCX") is False


def test_the_one_line_at_boot_names_the_evening():
    """"everything closed" is the sentence that was in the log. A reason that
    is wrong about half the system is worse than no reason, because it reads
    as an explanation."""
    said = tc.describe(BALIPRATIPADA)
    assert "everything closed" not in said
    assert "MCX" in said and "17:00" in said


@pytest.mark.parametrize("day", MEASURED_EVENINGS)
def test_every_measured_evening_is_now_open_for_mcx(day):
    assert tc.session_kind(day, "MCX") == tc.EVENING
    # and the equity side of each is untouched
    assert tc.session_kind(day, "NSE") == tc.CLOSED


@pytest.mark.parametrize("day", UNMEASURED)
def test_an_unmeasured_holiday_stays_shut(day):
    """ABSENT IS NOT FALSE, and it is not true either.

    The archive has no candles for Good Friday (he was switched off) or for
    Christmas (it has not happened). Guessing either one open is precisely
    the error this file exists to prevent — "a guessed holiday is worse than
    no holiday". They wait for the tape, which is now watched per league.
    """
    assert tc.session_kind(day, "MCX") == tc.CLOSED


def test_an_ordinary_day_and_a_weekend_are_unchanged():
    """The fix must not have widened anything except the six measured days."""
    assert tc.session_kind(dt.date(2026, 11, 9), "MCX") == tc.FULL     # Monday
    assert tc.session_kind(dt.date(2026, 11, 14), "MCX") == tc.CLOSED  # Saturday
    assert tc.session_kind(dt.date(2026, 11, 8), "MCX") == tc.MUHURAT  # Sunday


# ============================================ the backstop that missed it
def _archive(tmp_path, rows: list[tuple[str, str]]):
    """rows is [(symbol, 'YYYY-MM-DD'), ...]."""
    root = tmp_path / "brain"
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "candles.db")
    con.execute("CREATE TABLE candles (symbol TEXT, ts TEXT, close REAL)")
    con.executemany("INSERT INTO candles VALUES (?, ?, 100.0)",
                    [(s, f"{d} 18:00:00") for s, d in rows])
    con.commit()
    con.close()
    return root


def test_a_weekday_holiday_that_traded_is_flagged(tmp_path, monkeypatch):
    """THE HALF THAT WAS BLIND. 2026-12-25 is a Friday and an equity holiday,
    so the old `day.weekday() >= 5` test skipped it entirely — which is how
    six MCX evenings went unreported for eight months."""
    root = _archive(tmp_path, [("GOLDM", "2026-12-25")])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    assert tc.unlisted_sessions_from_archive("GOLDM", "MCX") == [
        dt.date(2026, 12, 25)]


def test_the_backstop_is_asked_per_segment(tmp_path, monkeypatch):
    """THE OTHER HALF. The same archive, asked about the other league, must
    report nothing — a GOLDM evening is not an NSE session, and conflating
    them would turn this backstop into a noise generator."""
    root = _archive(tmp_path, [("GOLDM", "2026-12-25")])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    assert tc.unlisted_sessions_from_archive("NIFTY", "NSE") == []
    assert tc.unlisted_sessions_by_segment() == {"MCX": [dt.date(2026, 12, 25)]}


def test_an_index_holiday_that_traded_is_flagged_too(tmp_path, monkeypatch):
    """The weekday-holiday half is not MCX-specific. A listed equity holiday
    with NIFTY candles in it means the holiday itself is wrong."""
    root = _archive(tmp_path, [("NIFTY", "2026-12-25")])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    assert tc.unlisted_sessions_by_segment() == {"NSE": [dt.date(2026, 12, 25)]}


def test_a_listed_evening_is_not_flagged(tmp_path, monkeypatch):
    """2026-11-10 is now in the table. Having fixed it, the backstop must go
    quiet about it — otherwise the warning becomes permanent furniture."""
    root = _archive(tmp_path, [("GOLDM", "2026-11-10"),
                               ("NATURALGAS", "2026-11-10")])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    assert tc.unlisted_sessions_by_segment() == {}


def test_an_uncovered_weekend_is_still_flagged(tmp_path, monkeypatch):
    """THE REGRESSION THIS FIX NEARLY SHIPPED.

    Asking `session_kind` alone would have been cleaner and would have
    switched the backstop off outside the entered years, because it answers
    None there. The table runs out on 2026-12-31 — 51 days after this was
    written — and a backstop that stops working exactly when the table
    expires is worse than none, because its silence reads as a clean report.

    An uncovered weekend with candles in it is still a session that happened,
    so the exchange's own weekend rule is kept separately.
    """
    root = _archive(tmp_path, [("NIFTY", "2027-11-07"),   # Sunday, uncovered
                               ("NIFTY", "2027-11-09")])  # Tuesday, unknowable
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    assert tc.covers(dt.date(2027, 11, 7)) is False
    assert tc.unlisted_sessions_from_archive("NIFTY", "NSE") == [
        dt.date(2027, 11, 7)]


def test_an_absent_archive_asserts_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "nothing-here"))
    assert tc.unlisted_sessions_by_segment() == {}


def test_both_leagues_have_probe_symbols():
    """A segment with no probe symbol is a segment nobody is checking, which
    is the state MCX was in. A rail on the fact, not on the list."""
    for segment in ("NSE", "MCX"):
        assert tc._SEGMENT_PROBES.get(segment), f"{segment} has no probe"
    # More than one each: a probe that depends on a single symbol being
    # present in the archive is blind whenever it is not.
    for segment, symbols in tc._SEGMENT_PROBES.items():
        assert len(symbols) >= 2, f"{segment} rests on one symbol"


def test_the_backstop_still_only_reports(tmp_path, monkeypatch):
    """It REPORTS a gap; it must never fill one. A table that learned its own
    dates from the tape would be inferred data presented as an exchange
    announcement — and it still could not anticipate, because the tape only
    exists after the session it was needed for."""
    root = _archive(tmp_path, [("GOLDM", "2026-12-25")])
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(root))
    before = set(tc._MCX_EVENING_ON_EQUITY_HOLIDAY)
    tc.unlisted_sessions_by_segment()
    assert set(tc._MCX_EVENING_ON_EQUITY_HOLIDAY) == before
    assert tc.session_kind(dt.date(2026, 12, 25), "MCX") == tc.CLOSED

    src = (_repo_root() / "src" / "hokage" / "memory"
           / "trading_calendar.py").read_text(encoding="utf-8")
    for marker in ("_MCX_EVENING_ON_EQUITY_HOLIDAY.add",
                   "_MCX_EVENING_ON_EQUITY_HOLIDAY.update",
                   "_MCX_EVENING_ON_EQUITY_HOLIDAY.discard",
                   "_MCX_EVENING_ON_EQUITY_HOLIDAY.remove"):
        assert marker not in src, f"the table is being mutated: {marker}"


def test_boot_asks_about_both_leagues():
    """The call site is the whole fix. Asking one league is how the other
    league's missing sessions stay missing, and for six months the boot
    audit asked only the NSE default."""
    src = (_repo_root() / "src" / "bots" / "autonomous"
           / "autonomous_bot.py").read_text(encoding="utf-8")
    boot = src.split("# WHAT DAY IS IT.")[1].split("def _cleanup")[0]
    assert "unlisted_sessions_by_segment()" in boot
    assert "logger.warning" in boot
    # The per-league form, not the single-segment default that was blind.
    assert "unlisted_sessions_from_archive()" not in boot
