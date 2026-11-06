"""The other side had one price, so the experiment could never be settled.

The commander's hypothesis of 2026-10-23 - "every time it takes a call, take a
put" - has fired in lockstep with its originals for a fortnight and has never
traded, which is the design: a mirror carries its original's confidence, every
scan ties, and a mirror loses a tie to a non-mirror. 0 wins in 54 firings
since the 2026-10-28 tie-break fix.

It therefore has to be scored from the archive, and the archive could not do
it. 2026-11-06 is the whole problem in four rows:

    10:30:31  RangeFade  CALL 280 @ 14.55  WON, filled  -> 83 marks, +2,625
              FadeRange  PUT  280 @ 15.25  lost         -> 1 number, ever
    16:15:23  RangeFade  CALL 285 @ 13.90  WON, filled  -> 32 marks
              FadeRange  PUT  285 @ 16.00  lost         -> 1 number, ever

One number is not a round trip. And the underlying cannot stand in for it: a
mirror fires on the same bar with the opposite direction, so its edge there is
exactly minus its original's and the flip creates no information. The question
asked - wrong about DIRECTION or wrong about MOVEMENT - only separates in
premium, because both sides BUY and both pay theta.

So the loser is now priced on the same tick as the winner, for as long as the
winner is open.

WHAT THIS FILE PINS: that the pair is stored on ONE row and not in two tables
to align; that these rows never enter `position_marks`, which `trail_arm_lab`
reads as a list of positions held; that a leg nobody could price is absent
rather than zero; and that none of it can cost the held position its own mark.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import mirror_path as mp
from hokage.memory import premium_path as pp
from hokage.memory import signal_archive as sa

IST = ZoneInfo("Asia/Kolkata")
T0 = dt.datetime(2026, 11, 6, 16, 15, 23, tzinfo=IST)

#: The real 16:15 gas pair.
HELD = "NATURALGAS26NOV285CE"
HELD_ENTRY = 13.90
MIRROR = "NATURALGAS26NOV285PE"
MIRROR_ENTRY = 16.00


class _Sig:
    def __init__(self, fired, direction=None, confidence=None, reason=""):
        self.should_enter = fired
        self.direction = direction
        self.confidence = confidence
        self.reason = reason


ORIGINAL = ("strat-rangefade-mcx-v1", "entry-rangefade-mcx-v1",
            _Sig(True, "long", 54.75, "RangeFade: fading the band."))
OPPOSITE = ("strat-faderange-mcx-v1", "entry-faderange-mcx-v1",
            _Sig(True, "short", 54.75, "MIRROR of LONG - by commander hypothesis."))
ASIDE = ("strat-eiareaction-mcx-v1", "entry-eiareaction-mcx-v1",
         _Sig(False, reason="not a Thursday."))

PRICED = {"long": (HELD, HELD_ENTRY), "short": (MIRROR, MIRROR_ENTRY)}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return mp


@pytest.fixture
def scanned(archive):
    """One recorded scan: the original won, the mirror lost, both priced."""
    sa.remember_scan("NATURALGAS", [ORIGINAL, OPPOSITE, ASIDE],
                     winner_strategy_id=ORIGINAL[0], underlying=282.90,
                     when=T0, premiums=PRICED)
    return T0.isoformat()


# ================================================ the pair is one observation
def test_a_mark_carries_both_sides_at_the_same_instant(archive):
    """The question is always a difference between the two. A lab that had to
    align two paths on a timestamp would be one rounding rule away from
    comparing 16:15:01 with 16:15:16 and calling it a spread."""
    assert archive.remember(
        MIRROR, 15.60, MIRROR_ENTRY, held_symbol=HELD,
        held_premium=14.65, held_entry=HELD_ENTRY, when=T0) is True

    row = archive.path_for(HELD)[0]
    assert row["symbol"] == MIRROR
    assert row["premium"] == 15.60 and row["entry"] == MIRROR_ENTRY
    assert row["held_premium"] == 14.65 and row["held_entry"] == HELD_ENTRY


def test_the_path_is_read_by_the_contract_that_was_held(archive):
    """What a reader has is a round trip in the ledger, asking what the other
    side would have done."""
    for i, (mirror_prem, held_prem) in enumerate(
            [(16.00, 13.90), (15.60, 14.45), (15.10, 14.65)]):
        archive.remember(MIRROR, mirror_prem, MIRROR_ENTRY, held_symbol=HELD,
                         held_premium=held_prem, held_entry=HELD_ENTRY,
                         when=T0 + dt.timedelta(minutes=i))

    path = archive.path_for(HELD)
    assert [r["premium"] for r in path] == [16.00, 15.60, 15.10]
    assert [r["held_premium"] for r in path] == [13.90, 14.45, 14.65]


def test_the_two_sides_moved_opposite_ways_which_is_the_point(archive):
    """The measured shape of the 16:15 trade: the call gained while the put
    bled. A direction column cannot show this, because on the underlying the
    mirror's edge is exactly minus the original's."""
    archive.remember(MIRROR, 15.10, MIRROR_ENTRY, held_symbol=HELD,
                     held_premium=14.65, held_entry=HELD_ENTRY, when=T0)
    row = archive.path_for(HELD)[0]
    held_pct = (row["held_premium"] - row["held_entry"]) / row["held_entry"]
    mirror_pct = (row["premium"] - row["entry"]) / row["entry"]
    assert held_pct > 0 > mirror_pct


def test_a_day_narrows_the_path(archive):
    """The same option symbol is traded on several days and each is its own
    pair."""
    archive.remember(MIRROR, 15.10, MIRROR_ENTRY, held_symbol=HELD,
                     held_premium=14.65, held_entry=HELD_ENTRY, when=T0)
    archive.remember(MIRROR, 12.00, MIRROR_ENTRY, held_symbol=HELD,
                     held_premium=15.00, held_entry=HELD_ENTRY,
                     when=T0 + dt.timedelta(days=1))
    assert len(archive.path_for(HELD, day="2026-11-06")) == 1
    assert len(archive.path_for(HELD)) == 2


# ============================================ it refuses rather than guesses
@pytest.mark.parametrize("premium,entry", [(0, 16.0), (-1, 16.0), (15.6, 0)])
def test_a_bad_print_is_refused(archive, premium, entry):
    """A premium at or below zero is a dead quote, never a free option; an
    entry at or below zero makes every percentage meaningless."""
    assert archive.remember(MIRROR, premium, entry, held_symbol=HELD) is False
    assert archive.path_for(HELD) == []


def test_a_mark_with_no_winner_to_pair_it_with_is_refused(archive):
    """Unpaired, it is an observation of nothing."""
    assert archive.remember(MIRROR, 15.60, MIRROR_ENTRY, held_symbol="") is False


def test_an_unrecorded_held_premium_stays_missing(archive):
    """None reads as 'not recorded'; 0.0 is a price the venue might really
    have quoted."""
    archive.remember(MIRROR, 15.60, MIRROR_ENTRY, held_symbol=HELD, when=T0)
    assert archive.path_for(HELD)[0]["held_premium"] is None


def test_an_instant_is_never_overwritten(archive):
    archive.remember(MIRROR, 15.60, MIRROR_ENTRY, held_symbol=HELD, when=T0)
    archive.remember(MIRROR, 99.99, MIRROR_ENTRY, held_symbol=HELD, when=T0)
    assert [r["premium"] for r in archive.path_for(HELD)] == [15.60]


def test_reading_an_archive_that_does_not_exist_is_empty_not_an_error(archive):
    assert archive.path_for(HELD) == []
    assert archive.coverage() == {
        "rows": 0, "pairs": 0, "first_day": None, "last_day": None}


def test_coverage_counts_pairs_so_a_study_can_state_its_n(archive):
    for i in range(3):
        archive.remember(MIRROR, 15.0 + i, MIRROR_ENTRY, held_symbol=HELD,
                         when=T0 + dt.timedelta(minutes=i))
    archive.remember("NATURALGAS26NOV280PE", 15.25, 15.25,
                     held_symbol="NATURALGAS26NOV280CE", when=T0)
    cov = archive.coverage()
    assert cov["rows"] == 4 and cov["pairs"] == 2
    assert cov["first_day"] == cov["last_day"] == "2026-11-06"


# =================================== it must not contaminate the trail study
def test_a_mirror_mark_never_enters_position_marks(archive):
    """THE RAIL. trail_arm_lab does SELECT DISTINCT symbol, day FROM
    position_marks and treats each one as a position that was HELD. A path for
    a contract nobody bought would enter that study as a trade."""
    archive.remember(MIRROR, 15.60, MIRROR_ENTRY, held_symbol=HELD,
                     held_premium=14.65, held_entry=HELD_ENTRY, when=T0)
    pp.remember(HELD, 14.65, HELD_ENTRY, when=T0)

    held_paths = {r["symbol"] for r in pp.path_for(HELD)}
    assert held_paths == {HELD}
    con = sqlite3.connect(archive.db_path())
    try:
        symbols = {r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM position_marks")}
    finally:
        con.close()
    assert MIRROR not in symbols


def test_both_archives_share_the_one_history_store(archive):
    """candles.db, not hokage.db - which reached 1.5 GB on telemetry and has
    to be prunable."""
    assert archive.db_path() == pp.db_path()
    assert archive.db_path().name == "candles.db"


# ======================================= which leg is the opposing one
def test_the_opposing_leg_is_the_contract_that_did_not_fill(scanned):
    leg = sa.opposing_leg("NATURALGAS", scanned, HELD)
    assert leg["option_symbol"] == MIRROR
    assert leg["option_premium"] == MIRROR_ENTRY
    assert leg["module_id"] == "entry-faderange-mcx-v1"
    assert leg["direction"] == "short"


def test_the_winner_is_never_returned_as_its_own_opposite(scanned):
    """Pricing the held contract twice would make the experiment compare a
    trade with itself."""
    leg = sa.opposing_leg("NATURALGAS", scanned, HELD)
    assert leg["option_symbol"] != HELD


def test_a_stand_aside_is_not_a_leg(archive):
    """It proposed no direction, so it has no contract. Pricing one would be
    inventing a trade nobody suggested."""
    sa.remember_scan("NATURALGAS", [ORIGINAL, ASIDE],
                     winner_strategy_id=ORIGINAL[0], underlying=282.90,
                     when=T0, premiums=PRICED)
    assert sa.opposing_leg("NATURALGAS", T0.isoformat(), HELD) is None


def test_an_unpriceable_loser_has_no_leg(archive):
    """A thin chain or a dead feed. Absent is not zero: a leg with no entry
    premium cannot start a path."""
    sa.remember_scan("NATURALGAS", [ORIGINAL, OPPOSITE],
                     winner_strategy_id=ORIGINAL[0], underlying=282.90,
                     when=T0, premiums={"long": (HELD, HELD_ENTRY)})
    assert sa.opposing_leg("NATURALGAS", T0.isoformat(), HELD) is None


def test_no_scan_means_no_leg(archive):
    assert sa.opposing_leg("NATURALGAS", T0.isoformat(), HELD) is None
    assert sa.opposing_leg("NATURALGAS", "", HELD) is None


# ============================================ what the bot stores and reads
@pytest.fixture
def bot():
    """A bare bot: _opposing_leg_for and _archive_mirror_mark read nothing
    off the engine except orchestrator.price_source."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
    return Bot.__new__(Bot)


class _Quote:
    def __init__(self, price):
        self.price = price


class _Source:
    def __init__(self, prices):
        self.prices = prices
        self.asked: list[str] = []

    def get_quote(self, symbol):
        self.asked.append(symbol)
        if symbol not in self.prices:
            raise KeyError(symbol)
        return _Quote(self.prices[symbol])


class _Orchestrator:
    def __init__(self, source):
        self.price_source = source


def test_the_leg_the_bot_stores_survives_a_json_round_trip(bot, scanned):
    """active_positions.json is rewritten on every tick. A datetime in this
    dict is what truncated that file 168 times on 2026-10-28."""
    leg = bot._opposing_leg_for("NATURALGAS", scanned, HELD)
    assert leg["symbol"] == MIRROR and leg["entry"] == MIRROR_ENTRY
    assert json.loads(json.dumps(leg)) == leg


def test_the_bot_writes_a_paired_mark_from_a_live_quote(bot, scanned, archive):
    bot.orchestrator = _Orchestrator(_Source({MIRROR: 15.10}))
    tracking = {"mirror_leg": bot._opposing_leg_for("NATURALGAS", scanned, HELD),
                "decision_id": "mcx-20261106161530"}

    bot._archive_mirror_mark(HELD, HELD_ENTRY, 14.65, tracking, T0)

    row = archive.path_for(HELD)[0]
    assert row["premium"] == 15.10 and row["held_premium"] == 14.65
    assert row["decision_id"] == "mcx-20261106161530"
    assert row["scanned_at"] == scanned


def test_a_position_with_no_opposing_leg_writes_nothing(bot, archive):
    """Absent is not false: no leg means no row, not a fabricated one."""
    bot.orchestrator = _Orchestrator(_Source({MIRROR: 15.10}))
    bot._archive_mirror_mark(HELD, HELD_ENTRY, 14.65, {}, T0)
    assert archive.path_for(HELD) == []


def test_a_dead_quote_on_the_leg_is_silent(bot, scanned, archive):
    """The experiment must never take a held position down with it, nor store
    a zero as if the venue had quoted it."""
    bot.orchestrator = _Orchestrator(_Source({MIRROR: 0.0}))
    tracking = {"mirror_leg": bot._opposing_leg_for("NATURALGAS", scanned, HELD)}
    bot._archive_mirror_mark(HELD, HELD_ENTRY, 14.65, tracking, T0)
    assert archive.path_for(HELD) == []


def test_an_unquotable_leg_does_not_raise(bot, scanned, archive):
    bot.orchestrator = _Orchestrator(_Source({}))
    tracking = {"mirror_leg": bot._opposing_leg_for("NATURALGAS", scanned, HELD)}
    bot._archive_mirror_mark(HELD, HELD_ENTRY, 14.65, tracking, T0)
    assert archive.path_for(HELD) == []


def test_it_costs_exactly_one_quote_per_mark(bot, scanned, archive):
    """A scan prices at most one CE and one PE however many modules fired, and
    the leg is fixed at entry, so this cannot fan out."""
    source = _Source({MIRROR: 15.10})
    bot.orchestrator = _Orchestrator(source)
    tracking = {"mirror_leg": bot._opposing_leg_for("NATURALGAS", scanned, HELD)}
    bot._archive_mirror_mark(HELD, HELD_ENTRY, 14.65, tracking, T0)
    assert source.asked == [MIRROR]


def test_the_held_mark_is_written_before_the_experiment_is_attempted():
    """Ordering, at source: the trail study needs the held path, and an
    experiment must not be able to cost it a row."""
    import inspect
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
    src = inspect.getsource(Bot._archive_mark)
    assert src.index("premium_path.remember(") < src.index(
        "self._archive_mirror_mark(")
