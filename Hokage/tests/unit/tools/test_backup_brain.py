"""The brain had one copy, and `backups/` had always been empty.

124 MB on one laptop disk: the chests, 412 positions of track record, 45,800
candles, 1,173 premium marks, the journal, the reviews. Nothing anywhere else.
Deferred 2026-10-22, approved 2026-11-04 alongside the dead man's switch.

These tests hold the two decisions that make the tool a backup rather than a
file copy:

  * DATABASES GO THROUGH `VACUUM INTO`, not shutil. hokage.db runs in WAL with
    a live writer and a 4 MB -wal beside it; copying .db and -wal as separate
    files snapshots two different instants and can produce an archive that
    opens cleanly while missing the last committed transactions.
  * THE ARCHIVE IS OPENED BEFORE THE RUN IS CALLED A SUCCESS. Every database
    is extracted from the finished zip, integrity-checked and counted. This
    project's recurring wound is a check that answered plausibly from the
    wrong place -- "Health Score 100/100" while he was dead for 3h39m, a
    watcher reporting "no trade" for four days on a path bug, a venue
    reporting CONNECTED with no network call. An unverified backup is the same
    shape, and it fails on the one day there is no second chance.

Nothing here touches the real brain: every test builds its own under tmp_path.
"""
from __future__ import annotations

import sqlite3
import zipfile

import pytest

from tools.ops import backup_brain as bb


# ===================================================== a brain to back up
@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A miniature brain, with the two traps the real one has: a WAL-mode
    database with a live connection still open, and a fat logs directory."""
    root = tmp_path / "hokage_brain"
    (root / "portfolio").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "state").mkdir()

    (root / "portfolio" / "strategy_portfolio.json").write_text(
        '{"strategies": {"a": {"capital": 100000}}}', encoding="utf-8")
    (root / "state" / "marker.json").write_text("{}", encoding="utf-8")
    # 50 MB of the real 124 is logs, and it is where his request_token leaked.
    (root / "logs" / "hokage.log").write_text(
        "request_token=SHOULD_NEVER_BE_COPIED", encoding="utf-8")
    (root / "logs" / "hokage.log.1").write_text("old", encoding="utf-8")

    db = root / "hokage.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE positions (position_id TEXT, market TEXT)")
    conn.execute("CREATE TABLE audit_trail (id INTEGER)")
    conn.executemany("INSERT INTO positions VALUES (?,?)",
                     [(str(i), f"SYM{i}") for i in range(7)])
    conn.executemany("INSERT INTO audit_trail VALUES (?)",
                     [(i,) for i in range(11)])
    conn.commit()

    candles = root / "candles.db"
    c2 = sqlite3.connect(candles)
    c2.execute("CREATE TABLE candles (ts TEXT)")
    c2.execute("CREATE TABLE position_marks (symbol TEXT)")
    c2.executemany("INSERT INTO candles VALUES (?)", [(str(i),) for i in range(5)])
    c2.commit()
    c2.close()

    monkeypatch.setattr(bb, "BRAIN", root)
    yield root
    # The writer stays open for the duration of the test on purpose: a backup
    # that needs Hokage stopped is a backup that will not get taken.
    conn.close()


# ===================================================== the happy path
def test_a_backup_is_written_and_verifies(brain, tmp_path, capsys):
    assert bb.run(tmp_path / "dest", keep=7) == 0
    out = capsys.readouterr().out
    assert "verified" in out
    archives = list((tmp_path / "dest").glob("hokage_brain_*.zip"))
    assert len(archives) == 1


def test_the_databases_survive_a_round_trip_with_a_live_writer(brain, tmp_path):
    """The whole reason for VACUUM INTO. The fixture's connection is still
    open and in WAL mode while this runs."""
    assert bb.run(tmp_path / "dest", keep=7) == 0
    archive = next((tmp_path / "dest").glob("*.zip"))
    with zipfile.ZipFile(archive) as zf:
        zf.extract("hokage.db", tmp_path / "x")
    conn = sqlite3.connect(tmp_path / "x" / "hokage.db")
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 7
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_trail").fetchone()[0] == 11
    finally:
        conn.close()


def test_the_chests_are_in_there(brain, tmp_path):
    bb.run(tmp_path / "dest", keep=7)
    with zipfile.ZipFile(next((tmp_path / "dest").glob("*.zip"))) as zf:
        assert "portfolio/strategy_portfolio.json" in zf.namelist()
        assert "state/marker.json" in zf.namelist()


# ===================================================== what must be left out
def test_the_logs_are_not_copied(brain, tmp_path):
    """50 MB of the 124, disposable, and the one place credentials have ever
    leaked -- his request_token sat in 18 log files because werkzeug logs the
    callback URL. Carrying them to a cloud folder would re-export exactly what
    was cleaned up on 2026-11-03."""
    bb.run(tmp_path / "dest", keep=7)
    with zipfile.ZipFile(next((tmp_path / "dest").glob("*.zip"))) as zf:
        names = zf.namelist()
        assert not [n for n in names if n.startswith("logs/")]
        blob = b"".join(zf.read(n) for n in names if not n.endswith(".db"))
        assert b"SHOULD_NEVER_BE_COPIED" not in blob


def test_the_wal_sidecars_are_not_copied(brain, tmp_path):
    """They belong to a snapshot already taken. Shipping them beside a
    VACUUMed database invites a restore to apply a WAL to the wrong file."""
    assert (brain / "hokage.db-wal").exists(), "fixture is not in WAL mode"
    bb.run(tmp_path / "dest", keep=7)
    with zipfile.ZipFile(next((tmp_path / "dest").glob("*.zip"))) as zf:
        assert not [n for n in zf.namelist() if n.endswith(("-wal", "-shm"))]


# ===================================================== the verification bites
def test_a_corrupted_archive_is_reported_as_failure(brain, tmp_path, capsys):
    """Proof the check is load-bearing: truncate the database inside the zip
    and the run must refuse to call it a backup."""
    dest = tmp_path / "dest"
    bb.run(dest, keep=7)
    archive = next(dest.glob("*.zip"))

    good = {}
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            good[name] = zf.read(name)
    good["hokage.db"] = good["hokage.db"][:512] + b"\x00" * 512
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in good.items():
            zf.writestr(name, data)

    counts = {"hokage.db": {"positions": 7, "audit_trail": 11},
              "candles.db": {"candles": 5, "position_marks": 0}}
    problems = bb._verify(archive, counts)
    assert problems, "a truncated database passed verification"


def test_a_short_table_is_reported(brain, tmp_path):
    """The copy may lag the live file while the zip is built. It must never be
    SHORT of what was counted at snapshot time."""
    dest = tmp_path / "dest"
    bb.run(dest, keep=7)
    archive = next(dest.glob("*.zip"))
    inflated = {"hokage.db": {"positions": 9_999}}
    problems = bb._verify(archive, inflated)
    assert any("positions" in p for p in problems)


def test_a_missing_database_is_reported(brain, tmp_path):
    dest = tmp_path / "dest"
    bb.run(dest, keep=7)
    archive = next(dest.glob("*.zip"))
    problems = bb._verify(archive, {"not_there.db": {"x": 1}})
    assert any("missing" in p for p in problems)


# ===================================================== housekeeping
def test_rotation_keeps_the_newest(brain, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    for stamp in ("20260101_000000", "20260102_000000", "20260103_000000"):
        (dest / f"hokage_brain_{stamp}.zip").write_bytes(b"old")
    assert bb.run(dest, keep=2) == 0
    held = sorted(p.name for p in dest.glob("hokage_brain_*.zip"))
    assert len(held) == 2
    assert held[0] == "hokage_brain_20260103_000000.zip", \
        "rotation dropped a newer archive than it kept"


def test_a_dry_run_writes_nothing(brain, tmp_path, capsys):
    dest = tmp_path / "dest"
    assert bb.run(dest, keep=7, dry_run=True) == 0
    assert "dry run" in capsys.readouterr().out
    assert not dest.exists() or not list(dest.glob("*.zip"))


def test_a_missing_brain_is_an_error_not_an_empty_backup(tmp_path, monkeypatch):
    """An empty archive written without complaint is worse than no archive."""
    monkeypatch.setattr(bb, "BRAIN", tmp_path / "nope")
    assert bb.run(tmp_path / "dest", keep=7) == 2
