"""A spread cannot be backtested, because option history dies with the contract.

2026-10-19: the mandate changed to allow defined-risk short-premium spreads —
the one effect this system has ever confirmed on both halves, and the one with
the strongest independent literature. It cannot be measured, and the reason is
data rather than caution. Checked the same day against the live venue:

    NIFTY26NOV22900CE    37 daily bars, listed 2026-08-26
    NIFTY26DEC22900CE    13 daily bars, listed 2026-09-30

A contract carries history only from its listing, and an expired one is
DELISTED along with its token. Options expire weekly, so the premium history
of the past does not exist and never will. The futures-roll wound, in its
worst form.

So the only corpus that can ever exist is the one that starts now. That is the
same lesson as the candles (2026-08-27) and India VIX (2026-10-16), learned a
third time. The first snapshot was taken 2026-10-19 at 15:58 IST: 168
contracts across NIFTY and SENSEX.

TWO THINGS THIS FILE PROTECTS.

  1. A SNAPSHOT IS STAMPED WITH WHEN IT WAS TAKEN. One captured at 11:00 is an
     intraday mark, not a close, and a close-to-close study built on a mix of
     the two would be measuring the clock. The archive does not decide what a
     row means; it records when the row was taken.

  2. NOTHING IS MODELLED. A premium derived from a pricing formula is a
     synthetic price, which the data doctrine forbids outright. Every row here
     is what the venue quoted.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import option_archive as oa

IST = ZoneInfo("Asia/Kolkata")
AFTER_CLOSE = dt.datetime(2026, 10, 19, 15, 58, tzinfo=IST)
DURING = dt.datetime(2026, 10, 19, 11, 0, tzinfo=IST)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return oa


def _row(strike=22900.0, option_type="CE", price=150.0, symbol="NIFTY",
         expiry=dt.date(2026, 11, 23)):
    return {"symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "last_price": price,
            "oi": 1000.0, "volume": 50.0, "spot": 22888.95}


# ------------------------------------------- a mark is not a close
def test_a_snapshot_records_when_it_was_taken(archive):
    archive.remember([_row()], when=DURING)
    rows = archive.closing_snapshots()
    assert rows == [], "an 11:00 mark must not read as a close"


def test_a_snapshot_after_the_bell_is_a_close(archive):
    archive.remember([_row()], when=AFTER_CLOSE)
    rows = archive.closing_snapshots()
    assert len(rows) == 1
    assert rows[0]["last_price"] == 150.0


def test_the_session_end_is_the_exchange_bell():
    assert oa.SESSION_END == dt.time(15, 30)
    assert oa.is_after_close(AFTER_CLOSE)
    assert not oa.is_after_close(DURING)


def test_the_clock_is_IST_not_the_host(archive):
    """A VPS in UTC would call 15:58 IST "10:28" and stamp a settled close as
    an intraday mark for the rest of time."""
    assert oa.IST == ZoneInfo("Asia/Kolkata")


# -------------------------------------------------- nothing is overwritten
def test_a_contract_already_recorded_today_is_not_rewritten(archive):
    assert archive.remember([_row(price=150.0)], when=AFTER_CLOSE) == 1
    assert archive.remember([_row(price=999.0)], when=AFTER_CLOSE) == 0
    assert archive.closing_snapshots()[0]["last_price"] == 150.0


def test_the_same_strike_on_a_later_day_is_a_new_row(archive):
    archive.remember([_row()], when=AFTER_CLOSE)
    # +2, not +1: the day after AFTER_CLOSE is 2026-10-20, an equity holiday,
    # and the holiday guard added below correctly refuses it. The claim under
    # test is about a LATER DAY, not about which day, so it moves to the next
    # one the market was actually open.
    later = AFTER_CLOSE + dt.timedelta(days=2)
    assert archive.remember([_row(price=160.0)], when=later) == 1
    assert len(archive.closing_snapshots()) == 2


def test_calls_and_puts_at_one_strike_are_separate_rows(archive):
    added = archive.remember([_row(option_type="CE"), _row(option_type="PE")],
                             when=AFTER_CLOSE)
    assert added == 2


# ------------------------------------------------------ missing is not zero
def test_a_zero_premium_is_refused(archive):
    """A zero would read as a free option and make every spread look like
    free money."""
    assert archive.remember([_row(price=0.0)], when=AFTER_CLOSE) == 0
    assert archive.remember([_row(price=-5.0)], when=AFTER_CLOSE) == 0
    assert archive.closing_snapshots() == []


def test_a_row_with_no_price_is_dropped_rather_than_defaulted(archive):
    bad = _row()
    bad["last_price"] = None
    assert archive.remember([bad], when=AFTER_CLOSE) == 0


def test_one_bad_row_does_not_lose_the_good_ones(archive):
    rows = [_row(strike=22800.0), {"symbol": "NIFTY"}, _row(strike=23000.0)]
    assert archive.remember(rows, when=AFTER_CLOSE) == 2


def test_an_unknown_option_type_is_refused(archive):
    assert archive.remember([_row(option_type="XX")], when=AFTER_CLOSE) == 0


def test_an_empty_archive_reads_as_empty_not_as_an_error(archive):
    assert archive.closing_snapshots() == []
    assert archive.coverage() == {"rows": 0, "days": 0, "first": None,
                                  "last": None, "symbols": []}


def test_nothing_at_all_is_not_an_error(archive):
    assert archive.remember([], when=AFTER_CLOSE) == 0
    assert archive.remember(None, when=AFTER_CLOSE) == 0


# ------------------------------------------------------- the strikes kept
def test_the_strikes_kept_are_the_ones_around_the_money():
    strikes = [22000.0 + 50 * i for i in range(40)]
    kept = oa.atm_strikes(strikes, 22888.95, each_side=2)
    assert kept == [22800.0, 22850.0, 22900.0, 22950.0, 23000.0]


def test_it_never_invents_a_strike_the_exchange_does_not_list():
    """Reading the dump rather than computing a ladder is the whole point:
    a fabricated contract is a fabricated price."""
    strikes = [22900.0, 23000.0]
    kept = oa.atm_strikes(strikes, 22888.95, each_side=10)
    assert kept == [22900.0, 23000.0]


def test_an_edge_of_the_chain_returns_fewer_rather_than_padding():
    strikes = [22900.0 + 50 * i for i in range(5)]
    kept = oa.atm_strikes(strikes, 22900.0, each_side=10)
    assert kept == strikes


def test_no_spot_means_no_strikes_rather_than_a_guess():
    assert oa.atm_strikes([22900.0], 0.0) == []
    assert oa.atm_strikes([], 22888.95) == []


def test_enough_strikes_are_kept_to_build_a_spread():
    """A vertical needs two legs a few strikes apart; the wings are where
    quotes go stale and spreads go wide."""
    assert oa.STRIKES_EACH_SIDE >= 5


# ----------------------------------------------------------- the doctrine
def test_no_premium_is_modelled_anywhere():
    """A Black-Scholes premium would be a synthetic price. Every row here is
    what the venue quoted."""
    import pathlib

    src = pathlib.Path(oa.__file__).read_text(encoding="utf-8").lower()
    for banned in ("black_scholes", "blackscholes", "norm.cdf", "def price("):
        assert banned not in src, f"a pricing model crept in: {banned}"


def test_it_lives_with_the_rest_of_the_market_history(archive):
    assert oa.db_path().name == "candles.db"


def test_moving_the_brain_moves_the_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "one"))
    first = oa.db_path()
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "two"))
    assert oa.db_path() != first


def test_the_daily_job_takes_the_snapshot():
    """Hokage does not capture this himself — he has no reason to read a
    whole chain — so the scheduled job is the only writer."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    ps = (root / "Sync-Candles.ps1").read_text(encoding="utf-8-sig")
    assert "archive_options.py" in ps


# ------------------------------- a quote is not evidence the market was open
# 2026-10-20 was an equity holiday. NIFTY and SENSEX did not trade. The
# archiver ran on schedule, Kite answered every quote with MONDAY's last
# print, and 168 rows went in stamped day='2026-10-20'. Nothing in a row says
# so: a reader three months from now sees closes like any other and measures
# a zero-change session that never existed.
#
# Same family as the rest of this file. A mark is not a close; missing is not
# zero; and a quote coming back is not evidence that the market was open.
HOLIDAY = dt.datetime(2026, 10, 20, 15, 58, tzinfo=IST)     # Dussehra
TRADING_DAY = dt.datetime(2026, 10, 21, 15, 58, tzinfo=IST)


def test_a_holiday_snapshot_is_refused_at_the_point_of_writing(archive):
    assert archive.remember([_row()], when=HOLIDAY) == 0
    assert archive.coverage()["rows"] == 0


def test_the_next_trading_day_still_writes(archive):
    """The guard must refuse a holiday, not the week around it."""
    assert archive.remember([_row()], when=TRADING_DAY) == 1


def test_mcx_trades_the_evening_of_an_equity_holiday(archive):
    """Commodity options follow a different calendar, and on 2026-10-20 MCX
    ran its evening session. Refusing them would be the same error pointed
    the other way."""
    assert archive.market_was_open("NATURALGAS", HOLIDAY.date()) is True
    assert archive.market_was_open("NIFTY", HOLIDAY.date()) is False


def test_a_day_the_calendar_cannot_speak_to_is_written_not_dropped(archive):
    """UNKNOWN IS NOT SHUT, and this direction is deliberate. The calendar
    covers 2026. Refusing on silence would make the archive stop writing on
    2027-01-01 with no error anywhere — the silent-stop failure this project
    has now paid for with a dead token, a blind watcher and a dead bot."""
    beyond = dt.datetime(2027, 3, 1, 15, 58, tzinfo=IST)
    assert archive.market_was_open("NIFTY", beyond.date()) is None
    assert archive.remember([_row()], when=beyond) == 1


def test_a_holiday_row_already_in_the_table_never_reaches_a_measurement(archive):
    """The 168 rows from 2026-10-20 predate the guard. They are NOT deleted —
    they are the record of what happened — but no study may read them."""
    import sqlite3
    archive.remember([_row()], when=TRADING_DAY)
    # Write the bad row the way it got in: straight past the guard.
    with archive.connect() as conn:
        conn.execute(
            "INSERT INTO option_chain (symbol, day, expiry, strike, "
            "option_type, captured_at, last_price) VALUES (?,?,?,?,?,?,?)",
            ("NIFTY", "2026-10-20", "2026-11-23", 22900.0, "CE",
             HOLIDAY.isoformat(), 150.0))
    assert archive.coverage()["rows"] == 2, "the row stays in the table"
    days = {r["day"] for r in archive.closing_snapshots()}
    assert days == {"2026-10-21"}, "a shut day must not read as a close"


def test_the_status_line_separates_what_is_stored_from_what_is_usable(archive):
    """A corpus count that includes unusable days overstates the corpus, and
    this one is being built precisely so a spread can be measured later."""
    archive.remember([_row()], when=TRADING_DAY)
    archive.remember([_row(strike=23000.0)], when=DURING)   # intraday mark
    cover = archive.coverage()
    assert cover["days"] == 2
    assert cover["usable_days"] == 1
