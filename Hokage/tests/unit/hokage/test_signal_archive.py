"""Every module's signal, so the auction's loser can be scored.

2026-10-26. The mirror experiment put RiderTrend in the arena beside
TrendRider — identical logic, opposite option, same asset. Both fired on both
evening gas scans:

    19:00   TrendRider: LONG (conf 60)  |  RiderTrend: SHORT (conf 60)
    19:30   TrendRider: LONG (conf 60)  |  RiderTrend: SHORT (conf 60)

TrendRider took both. The arena is WINNER-TAKE-ASSET, and a mirror carries
its original's confidence by deliberate design — there is a test pinning
that, so it cannot steal the asset by inflating itself. The consequence is an
exact tie on every scan and a tie-break that picks the same side forever:
RiderTrend will never place an order while its original is live on gas.

Filling both would put two opposite positions on one asset, which breaks the
one-bet-per-asset rule the correlation cap exists to enforce. So the losing
side is SCORED rather than traded, and this archive is what makes that
possible. Commander-approved 2026-10-27.

STRICTLY MORE EVIDENCE, NOT A CONSOLATION PRIZE. An auction winner is a
biased sample — the signal that happened to out-bid the others that scan.
Recording every verdict measures each module on its OWN firing condition,
which is what entry_module_lab always wanted and could previously only get
by re-deriving signals from a copy of the production rules. A copy drifts.
These rows come from the live evaluate() call.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import signal_archive as sa

IST = ZoneInfo("Asia/Kolkata")
T0 = dt.datetime(2026, 10, 26, 19, 0, 0, tzinfo=IST)


class _Sig:
    def __init__(self, fired, direction=None, confidence=None, reason=""):
        self.should_enter = fired
        self.direction = direction
        self.confidence = confidence
        self.reason = reason


#: The real 19:00 gas field.
TREND = ("strat-trendrider-mcx-v1", "entry-trendrider-mcx-v1",
         _Sig(True, "long", 60.0, "confirmed uptrend ... joining the continuation."))
MIRROR = ("strat-ridertrend-mcx-v1", "entry-ridertrend-mcx-v1",
          _Sig(True, "short", 60.0, "MIRROR of LONG — confirmed uptrend ..."))
ASIDE = ("strat-eiareaction-mcx-v1", "entry-eiareaction-mcx-v1",
         _Sig(False, reason="not a Thursday — the storage report prints once a week."))


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return sa


# ------------------------------------------------- the loser is recorded
def test_the_losing_side_of_the_mirror_is_kept(archive):
    """The whole point. TrendRider won; RiderTrend's signal still exists."""
    archive.remember_scan("NATURALGAS", [TREND, MIRROR, ASIDE],
                          winner_strategy_id=TREND[0], underlying=241.70, when=T0)
    loser = archive.signals_for("strat-ridertrend-mcx-v1")
    assert len(loser) == 1
    assert loser[0]["direction"] == "short"
    assert loser[0]["confidence"] == 60.0
    assert loser[0]["won"] == 0
    assert loser[0]["underlying"] == 241.70


def test_the_winner_is_flagged_as_such(archive):
    archive.remember_scan("NATURALGAS", [TREND, MIRROR],
                          winner_strategy_id=TREND[0], when=T0)
    won = [r for r in archive.signals_for("strat-trendrider-mcx-v1")]
    assert won[0]["won"] == 1


def test_both_sides_of_one_tie_are_stored_separately(archive):
    """Identical confidence, opposite directions, one scan. If these collided
    on the primary key the experiment would record only one of them."""
    archive.remember_scan("NATURALGAS", [TREND, MIRROR],
                          winner_strategy_id=TREND[0], when=T0)
    cover = archive.coverage()
    assert cover["rows"] == 2 and cover["scans"] == 1 and cover["fired"] == 2


# ------------------------------------------- winning is not filling
def test_a_winner_that_never_filled_is_not_counted_as_a_trade(archive):
    """On 2026-10-26 the gas winner was blocked by the bias veto AFTER
    winning. A study that treats every winner as a trade measures a system
    nobody is running."""
    archive.remember_scan("NATURALGAS", [TREND, MIRROR],
                          winner_strategy_id=TREND[0], when=T0)
    row = archive.signals_for("strat-trendrider-mcx-v1")[0]
    assert row["won"] == 1
    assert row["filled"] is None, "unknown until something says otherwise"


def test_a_fill_can_be_stamped_against_its_scan(archive):
    archive.remember_scan("NATURALGAS", [TREND, MIRROR],
                          winner_strategy_id=TREND[0], when=T0)
    assert archive.mark_filled("NATURALGAS", TREND[0], T0.isoformat(), True)
    assert archive.signals_for("strat-trendrider-mcx-v1")[0]["filled"] == 1


def test_stamping_a_scan_that_does_not_exist_changes_nothing(archive):
    assert not archive.mark_filled("NATURALGAS", TREND[0], T0.isoformat(), True)


# ------------------------------------------- refusals are the denominator
def test_a_stand_aside_is_recorded_with_its_reason(archive):
    """A module that fires once in a hundred scans has a different character
    from one that fires constantly, and a table of only the fires cannot tell
    them apart."""
    archive.remember_scan("NATURALGAS", [ASIDE], winner_strategy_id=None, when=T0)
    rows = archive.signals_for("strat-eiareaction-mcx-v1", fired_only=False)
    assert len(rows) == 1
    assert rows[0]["fired"] == 0
    assert "not a Thursday" in rows[0]["reason"]


def test_a_refusal_carries_no_direction_or_confidence(archive):
    """MISSING IS NOT ZERO. A confidence of 0.0 would read as 'scored zero';
    None reads as 'never scored', and only one of those is true."""
    archive.remember_scan("NATURALGAS", [ASIDE], when=T0)
    row = archive.signals_for("strat-eiareaction-mcx-v1", fired_only=False)[0]
    assert row["direction"] is None and row["confidence"] is None


def test_fired_only_is_the_default_view(archive):
    archive.remember_scan("NATURALGAS", [TREND, ASIDE],
                          winner_strategy_id=TREND[0], when=T0)
    assert archive.signals_for("strat-eiareaction-mcx-v1") == []
    assert len(archive.signals_for("strat-eiareaction-mcx-v1", fired_only=False)) == 1


# -------------------------------------------------------- not fragile
def test_rescanning_the_same_instant_never_overwrites(archive):
    archive.remember_scan("NATURALGAS", [TREND], winner_strategy_id=TREND[0], when=T0)
    archive.remember_scan("NATURALGAS", [MIRROR], winner_strategy_id=None, when=T0)
    # Different strategies at one instant are different rows; a repeat of the
    # same cell at the same instant is ignored, like every other archive here.
    again = archive.remember_scan("NATURALGAS", [TREND], winner_strategy_id=TREND[0], when=T0)
    assert again == 0
    assert archive.coverage()["rows"] == 2


def test_a_malformed_verdict_is_skipped_not_fatal(archive):
    assert archive.remember_scan("NATURALGAS", [TREND, ("x",), None, MIRROR],
                                 winner_strategy_id=TREND[0], when=T0) == 2


def test_an_empty_scan_writes_nothing_and_does_not_raise(archive):
    assert archive.remember_scan("NATURALGAS", [], when=T0) == 0
    assert archive.coverage()["rows"] == 0


def test_a_broken_archive_never_reaches_the_scan_loop(archive, monkeypatch):
    """This runs inside the scan. A scan that died because a row could not be
    written would be far worse than a missing row."""
    import sqlite3

    def boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sa, "connect", boom)
    assert archive.remember_scan("NATURALGAS", [TREND], when=T0) == 0
    assert archive.mark_filled("NATURALGAS", TREND[0], T0.isoformat(), True) is False


def test_it_lives_with_the_candles_not_in_hokage_db(archive):
    """hokage.db reached 1.5 GB on telemetry and was pruned on 2026-10-09."""
    assert archive.db_path().name == "candles.db"


def test_an_empty_archive_reads_as_empty(archive):
    assert archive.coverage()["rows"] == 0
    assert archive.signals_for("anything") == []


def test_coverage_separates_scans_from_rows_and_fires(archive):
    archive.remember_scan("NATURALGAS", [TREND, MIRROR, ASIDE],
                          winner_strategy_id=TREND[0], when=T0)
    archive.remember_scan("GOLDM", [TREND],
                          winner_strategy_id=TREND[0],
                          when=T0 + dt.timedelta(minutes=30))
    c = archive.coverage()
    assert c["rows"] == 4 and c["scans"] == 2 and c["fired"] == 3
    # A CELL IS (strategy, asset), which is the whole reason this archive and
    # the demoter both count them that way: TrendRider on gas and TrendRider
    # on gold are two different bets. So 4, not 3 - trendrider/NATURALGAS,
    # trendrider/GOLDM, ridertrend/NATURALGAS, eiareaction/NATURALGAS.
    assert c["cells"] == 4
