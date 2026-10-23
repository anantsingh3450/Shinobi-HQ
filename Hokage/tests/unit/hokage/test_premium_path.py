"""A held position's premium path, or the trail stays an opinion forever.

2026-10-22 gave nine round trips whose exits sorted cleanly:

    TARGET_HIT      3   +10,526    every winner
    TRAIL_LOCK      3       -62    every scratch
    Hard Backstop   2    -3,643    both big losses
    Thesis Stop     1    -1,125

Three trades armed the trail, had the protective floor ratcheted to exactly
the entry price, and finished at a rounding error after peaking +5.4%, +5.1%
and +8.2%. A fourth armed, kept ratcheting and ran to target for +4,050. One
armed trade in four paid — and whether breakeven-at-arm costs more than it
saves COULD NOT BE ANSWERED, because the data did not exist.

Every log on disk held 33 exit-ladder lines across 8 positions, oldest
2026-09-22, and logs rotate. None of the brain's fifty-three tables stored a
premium over time: `positions.current_price` is one mark, and one mark is not
a path. The ladder computed the whole thing every tick and discarded it.

Fourth time this lesson has been paid for — candles (a futures roll deleted
three months of tape), the option chain (premium dies with the contract),
India VIX (a gate read a number stored nowhere), now this. The difference:
this data was already in memory. It was simply never written down.

WHAT THIS FILE PINS: that it records, that it refuses bad prints rather than
storing them, that missing stays missing, and that it can never take a
position down with it.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import premium_path as pp

IST = ZoneInfo("Asia/Kolkata")
T0 = dt.datetime(2026, 10, 22, 17, 1, 0, tzinfo=IST)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return pp


def _mark(archive, premium, *, when=T0, entry=1468.50, **kw):
    return archive.remember("GOLDM26OCT142500PE", premium, entry,
                            when=when, **kw)


# ------------------------------------------------------------- it records
def test_a_mark_is_stored_and_reads_back(archive):
    assert _mark(archive, 1468.50, peak=1468.50, floor=0.0, target=1719.28)
    rows = archive.path_for("GOLDM26OCT142500PE")
    assert len(rows) == 1
    assert rows[0]["premium"] == 1468.50
    assert rows[0]["entry"] == 1468.50
    assert rows[0]["target"] == 1719.28


def test_the_path_comes_back_in_time_order(archive):
    """A path out of order is not a path. Written deliberately shuffled."""
    for offset, premium in ((120, 1462.50), (0, 1468.50), (240, 1537.50)):
        _mark(archive, premium, when=T0 + dt.timedelta(seconds=offset))
    got = [r["premium"] for r in archive.path_for("GOLDM26OCT142500PE")]
    assert got == [1468.50, 1462.50, 1537.50]


def test_the_real_2026_10_22_gold_path_reconstructs(archive):
    """The trade this archive exists because of: entered 1468.50, peaked
    1547.50 (+5.4%), floor ratcheted to entry when the trail armed, exited
    1462.50 for -60. Every one of those numbers is now recoverable."""
    steps = [
        (0,   1468.50, 1468.50, 0.00),
        (60,  1458.50, 1468.50, 1395.08),
        (180, 1537.50, 1537.50, 1395.08),
        (240, 1547.50, 1547.50, 1468.50),      # trail ARMED, floor = entry
        (480, 1462.50, 1547.50, 1468.50),      # floor taken out
    ]
    for secs, premium, peak, floor in steps:
        _mark(archive, premium, when=T0 + dt.timedelta(seconds=secs),
              peak=peak, floor=floor)
    rows = archive.path_for("GOLDM26OCT142500PE")
    assert len(rows) == 5
    assert max(r["peak"] for r in rows) == 1547.50
    # The question that could not be asked before: where was the floor when
    # the position was at its best, and what did price do afterwards?
    at_peak = next(r for r in rows if r["premium"] == 1547.50)
    assert at_peak["floor"] == at_peak["entry"], "breakeven lock, recorded"
    assert rows[-1]["premium"] < at_peak["floor"]


# -------------------------------------------------- it refuses, not guesses
def test_a_zero_premium_is_refused(archive):
    """A dead quote is not a free option — the chain archive's rule, and the
    reason a 0.00 in a path would read as a total loss that never happened."""
    assert not _mark(archive, 0.0)
    assert archive.coverage()["marks"] == 0


def test_a_negative_premium_is_refused(archive):
    assert not _mark(archive, -5.0)


def test_a_zero_entry_is_refused_because_every_percentage_dies_with_it(archive):
    assert not archive.remember("X", 100.0, 0.0, when=T0)


def test_a_mark_already_stored_for_that_instant_is_never_overwritten(archive):
    """INSERT OR IGNORE, like the candles, the VIX and the chain. What a
    position was worth at an instant is the record of that instant."""
    assert _mark(archive, 1468.50)
    assert not _mark(archive, 9999.00)
    assert archive.path_for("GOLDM26OCT142500PE")[0]["premium"] == 1468.50


def test_a_missing_floor_stays_missing_rather_than_becoming_zero(archive):
    """A floor of 0.00 means NO PROTECTION. A floor of None means NOT
    RECORDED. A study that cannot tell them apart concludes the wrong
    thing."""
    _mark(archive, 1468.50, floor=None, target=None, peak=None)
    row = archive.path_for("GOLDM26OCT142500PE")[0]
    assert row["floor"] is None and row["target"] is None and row["peak"] is None


def test_an_explicit_zero_floor_is_kept_as_zero(archive):
    """The other half of the same rule: before the trail arms the floor
    genuinely IS zero, and that is a fact worth storing."""
    _mark(archive, 1468.50, floor=0.0)
    assert archive.path_for("GOLDM26OCT142500PE")[0]["floor"] == 0.0


# ------------------------------------------------------- days are separate
def test_the_same_option_on_two_days_is_two_paths(archive):
    """SILVERM26OCT205000PE was entered three separate times on 2026-10-22
    alone. Across days the symbol repeats, and pooling them would splice
    unrelated trades into one curve."""
    _mark(archive, 1468.50, when=T0)
    _mark(archive, 1500.00, when=T0 + dt.timedelta(days=1))
    assert len(archive.path_for("GOLDM26OCT142500PE")) == 2
    assert len(archive.path_for("GOLDM26OCT142500PE", day=T0.date())) == 1


# ------------------------------------------------------------- the plumbing
def test_it_lives_with_the_candles_not_in_hokage_db(archive, tmp_path):
    """hokage.db reached 1.5 GB on telemetry and was pruned on 2026-10-09. An
    archive meant to be read in three months must not sit in the store that
    gets pruned."""
    assert archive.db_path().name == "candles.db"


def test_moving_the_brain_moves_the_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "one"))
    first = pp.db_path()
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "two"))
    assert pp.db_path() != first, "the path must resolve late, not at import"


def test_an_empty_archive_reads_as_empty_not_as_an_error(archive):
    assert archive.coverage() == {"marks": 0, "positions": 0, "days": 0,
                                  "first": None, "last": None}
    assert archive.path_for("ANYTHING") == []


def test_coverage_counts_positions_not_just_rows(archive):
    for i in range(4):
        _mark(archive, 1468.50 + i, when=T0 + dt.timedelta(seconds=15 * i))
    archive.remember("SILVERM26OCT205000PE", 2716.50, 2716.50, when=T0)
    cover = archive.coverage()
    assert cover["marks"] == 5
    assert cover["positions"] == 2
    assert cover["days"] == 1


def test_a_broken_archive_never_takes_a_position_down_with_it(archive, monkeypatch):
    """This runs inside the exit path. A position that cannot be closed
    because its history could not be written would be far worse than a
    missing row."""
    import sqlite3

    def boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(pp, "connect", boom)
    assert _mark(archive, 1468.50) is False          # refused, not raised


# ------------------------------------------- the rate limit, and why it exists
def test_the_marks_are_rate_limited_finer_than_any_study_needs():
    """Not a per-tick dump: 74% of 2026-08-27's log was one sentence repeated
    and it buried 135 real errors. But 15s is sixty times finer than the
    15-minute bars every study here runs on, so nothing is limited by it."""
    assert 0 < pp.MIN_SECONDS_BETWEEN_MARKS <= 60
    assert pp.MIN_SECONDS_BETWEEN_MARKS * 60 <= 15 * 60


def test_the_rate_limit_is_enforced_by_the_caller_not_the_store(archive):
    """The store writes what it is given; two marks a second apart are both
    legitimate records if something asked for them. The throttle belongs
    where the tick loop is."""
    assert _mark(archive, 1468.50, when=T0)
    assert _mark(archive, 1469.00, when=T0 + dt.timedelta(seconds=1))
    assert archive.coverage()["marks"] == 2


# ============================================ the wiring, inside the exit path
# `_trace_ladder` returns early when nothing changed, and those skipped ticks
# are exactly the marks a floor study needs — a path recorded only at its
# corners says nothing about the edges. So the archive call sits BESIDE it,
# not inside it.
from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot   # noqa: E402


def _bot():
    return object.__new__(Bot)


def test_the_ladder_archives_a_mark(archive):
    tracking: dict = {"stop_price": 1395.08, "target_price": 1719.28,
                      "decision_id": "DEC-1"}
    _bot()._archive_mark("GOLDM26OCT142500PE", 1468.50, 1458.50, 1468.50, tracking)
    rows = archive.path_for("GOLDM26OCT142500PE")
    assert len(rows) == 1
    assert rows[0]["premium"] == 1458.50
    assert rows[0]["floor"] == 1395.08
    assert rows[0]["decision_id"] == "DEC-1"


def test_a_second_mark_within_the_window_is_skipped(archive):
    bot, tracking = _bot(), {}
    bot._archive_mark("X26OCT100CE", 100.0, 100.0, 100.0, tracking)
    bot._archive_mark("X26OCT100CE", 100.0, 101.0, 101.0, tracking)
    assert archive.coverage()["marks"] == 1, "the throttle is what keeps this sane"


def test_the_throttle_releases_once_the_window_has_passed(archive):
    bot = _bot()
    tracking = {"_archived_at": pp.now_ist()
                - dt.timedelta(seconds=pp.MIN_SECONDS_BETWEEN_MARKS + 1)}
    bot._archive_mark("X26OCT100CE", 100.0, 101.0, 101.0, tracking)
    assert archive.coverage()["marks"] == 1


def test_each_position_is_throttled_separately(archive):
    """The stamp lives on that position's own tracking dict, so a busy
    position cannot starve a quiet one of its marks."""
    bot = _bot()
    bot._archive_mark("A26OCT100CE", 100.0, 100.0, 100.0, {})
    bot._archive_mark("B26OCT200CE", 200.0, 200.0, 200.0, {})
    assert archive.coverage()["positions"] == 2


def test_a_stale_stamp_of_the_wrong_type_does_not_raise(archive):
    """Tracking dicts are long-lived and have carried junk before."""
    bot = _bot()
    bot._archive_mark("X26OCT100CE", 100.0, 100.0, 100.0, {"_archived_at": "yesterday"})
    assert archive.coverage()["marks"] == 1


def test_the_archive_failing_never_reaches_the_exit_path(archive, monkeypatch):
    """If this raises, a position cannot be closed. It must not raise."""
    def boom(*a, **k):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(pp, "remember", boom)
    _bot()._archive_mark("X26OCT100CE", 100.0, 100.0, 100.0, {})   # must not raise
