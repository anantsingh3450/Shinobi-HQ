"""The brain exists once, on a laptop, and `backups/` has always been empty.

C:\\Hokage\\hokage_brain holds everything that is not in git: the portfolio
state and both leagues' chests, 412 positions of track record, the candle
archive, the option-chain archive, the journal, the reviews, the retirement
stamps. 124 MB, one copy, one disk. The repository is in OneDrive and the
brain is NOT -- it sits outside it, deliberately, because 1.5 GB of audit
telemetry once accumulated in there and a sync client is a poor place for a
database that grows on every dashboard tick.

So the brain has never been copied anywhere. Deferred 2026-10-22, raised again
with the dead man's switch, approved 2026-11-04.

WHY NOT A FILE COPY. hokage.db runs in WAL mode with a live writer; at the
moment of writing this it had a 4 MB -wal beside it. Copying those three files
with the shell gives a snapshot of a moving target -- the .db from one instant,
the -wal from another -- and the result can open cleanly and still be missing
the last committed transactions, which is the worst kind of backup: one that
looks fine. So every database goes through `VACUUM INTO`, which asks SQLite
itself for a consistent snapshot of the committed state. Measured on the real
file: 0.5s, integrity_check ok, 412 positions, matching live.

WHAT IS LEFT OUT, AND WHY IT MATTERS THAT IT IS.
  * logs/ -- 50 MB of the 124, half the archive, and DISPOSABLE. It is also
    the one place credentials have ever leaked: his request_token sat in 18
    log files because werkzeug logs the callback URL. A backup that carries
    the logs to a cloud folder would re-export the exact thing that was
    cleaned up on 2026-11-03. The logs stay on this machine.
  * *.db-wal / *.db-shm -- sidecars of a snapshot already taken. Copying them
    beside a VACUUMed database would invite a future restore to apply a WAL
    to a file it does not belong to.
  * __pycache__ -- regenerated.

VERIFICATION IS PART OF THE BACKUP, NOT A SEPARATE CHORE. Every database is
re-opened FROM INSIDE THE FINISHED ZIP, integrity-checked, and its key tables
counted against the live file. A backup nobody has opened is a hope. This
whole project's recurring wound is a check that returned a plausible answer
from the wrong place -- "Health Score 100/100" while he was dead for 3h39m, a
watcher reporting "no trade" for four days on a path bug, a venue reporting
CONNECTED without a network call. An unverified backup is the same shape, and
the day it matters is the day there is no second chance.

RESTORING. Stop Hokage first -- a running Hokage overwrites portfolio JSON
from memory, so restoring under a live process loses the restore. Then unzip
over `C:\\Hokage\\hokage_brain`. The databases inside are plain SQLite files
with no sidecars; SQLite recreates the WAL on first open.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

BRAIN = Path(r"C:\Hokage\hokage_brain")

#: Off this machine, as far as this machine can arrange on its own. OneDrive
#: replicates it; it is not a substitute for a real second location, and the
#: summary says so out loud every run.
DEFAULT_DEST = Path(r"C:\Users\anant\OneDrive\Hokage Brain Backups")

#: Directories never copied. `logs` is the credential-leak vector and half the
#: bytes; see the module docstring.
SKIP_DIRS = {"logs", "__pycache__", ".pytest_cache"}

#: Suffixes never copied: WAL/SHM sidecars belong to a snapshot already taken.
SKIP_SUFFIXES = {".db-wal", ".db-shm", ".db-journal"}

#: Tables whose row counts are compared against the live file after the zip is
#: written. `positions` is the real ledger (`trades` has never held an entry),
#: and `candles` is the archive that a futures roll once deleted three months
#: of. If either came back short, the backup is not trustworthy.
VERIFY_TABLES = {
    "hokage.db": ("positions", "audit_trail"),
    "candles.db": ("candles", "position_marks"),
}

KEEP_DEFAULT = 7


def _live_counts(db: Path) -> dict[str, int]:
    """Row counts from the LIVE database, read-only, before the snapshot."""
    out: dict[str, int] = {}
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        for table in VERIFY_TABLES.get(db.name, ()):
            try:
                out[table] = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.OperationalError:
                out[table] = -1          # table absent; reported, not guessed
    finally:
        conn.close()
    return out


def _snapshot_db(db: Path, into: Path) -> None:
    """A consistent copy of the committed state, via SQLite itself."""
    target = into / db.name
    target.unlink(missing_ok=True)
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()


def _stage(staging: Path) -> tuple[list[Path], dict[str, dict[str, int]]]:
    """Build the tree to be zipped. Returns (files, live counts per db)."""
    counts: dict[str, dict[str, int]] = {}
    for db in sorted(BRAIN.glob("*.db")):
        counts[db.name] = _live_counts(db)
        _snapshot_db(db, staging)

    for path in sorted(BRAIN.rglob("*")):
        rel = path.relative_to(BRAIN)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.is_dir():
            continue
        if path.suffix in SKIP_SUFFIXES or path.suffix == ".db":
            continue
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    return sorted(p for p in staging.rglob("*") if p.is_file()), counts


def _verify(archive: Path, counts: dict[str, dict[str, int]]) -> list[str]:
    """Open every database FROM INSIDE the finished zip. Returns problems."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
            for db_name, expected in counts.items():
                if db_name not in names:
                    problems.append(f"{db_name} is missing from the archive")
                    continue
                # A database damaged badly enough does not answer PRAGMA at
                # all -- it raises. That has to come back as a PROBLEM, not as
                # a traceback: this runs unattended from a scheduled task, and
                # the difference is between a report that says the archive is
                # untrustworthy and a crash that says nothing about why.
                conn = None
                try:
                    zf.extract(db_name, tmpdir)
                    extracted = tmpdir / db_name
                    conn = sqlite3.connect(
                        f"{extracted.as_uri()}?mode=ro", uri=True)
                    verdict = conn.execute(
                        "PRAGMA integrity_check").fetchone()[0]
                    if verdict != "ok":
                        problems.append(f"{db_name} integrity_check: {verdict}")
                    for table, live in expected.items():
                        if live < 0:
                            continue
                        got = conn.execute(
                            f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        # Live keeps writing while the zip is built, so the
                        # copy may be BEHIND. It must never be ahead, and it
                        # must not be short of what was there at snapshot.
                        if got < live:
                            problems.append(
                                f"{db_name}:{table} has {got} rows, live had "
                                f"{live} before the snapshot")
                except Exception as exc:
                    problems.append(
                        f"{db_name} could not be read back from the archive: "
                        f"{type(exc).__name__}: {str(exc)[:120]}")
                finally:
                    if conn is not None:
                        conn.close()
    return problems


def _rotate(dest: Path, keep: int) -> list[Path]:
    archives = sorted(dest.glob("hokage_brain_*.zip"))
    removed = []
    while len(archives) > keep:
        victim = archives.pop(0)
        victim.unlink()
        removed.append(victim)
    return removed


def run(dest: Path, keep: int, dry_run: bool = False) -> int:
    if not BRAIN.exists():
        print(f"the brain is not at {BRAIN}")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = dest / f"hokage_brain_{stamp}.zip"
    print(f"brain   {BRAIN}")
    print(f"archive {archive}")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "brain"
        staging.mkdir(parents=True)
        files, counts = _stage(staging)
        raw = sum(f.stat().st_size for f in files)
        print(f"staged  {len(files)} files, {raw / 1048576:.1f} MB "
              f"(logs excluded on purpose)")
        for db_name, expected in counts.items():
            shown = ", ".join(f"{t}={n:,}" for t, n in expected.items()
                              if n >= 0)
            print(f"  live {db_name}: {shown}")

        if dry_run:
            print("dry run, nothing written")
            return 0

        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
                archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in files:
                zf.write(f, f.relative_to(staging).as_posix())

    size = archive.stat().st_size
    print(f"written {size / 1048576:.1f} MB "
          f"({100 * size / raw:.0f}% of staged)")

    problems = _verify(archive, counts)
    if problems:
        print("VERIFICATION FAILED - this archive is NOT trustworthy:")
        for p in problems:
            print("  ", p)
        return 1
    print("verified: every database re-opened from inside the zip, "
          "integrity ok, key tables present")

    for gone in _rotate(dest, keep):
        print(f"rotated out {gone.name}")
    held = sorted(dest.glob("hokage_brain_*.zip"))
    print(f"holding {len(held)} archive(s), oldest {held[0].name}")
    print("NOTE: OneDrive replicates this; it is still one account and one "
          "machine's view. A copy somewhere else entirely is a separate job.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Back up the Hokage brain.")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--keep", type=int, default=KEEP_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return run(args.dest, max(1, args.keep), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
