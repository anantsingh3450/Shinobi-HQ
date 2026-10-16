"""99.7% of the incident table was one sentence, repeated.

47,675 incidents, of which 47,519 were byte-for-byte:

    WARNING / heartbeat_freshness
    "Stale heartbeats detected for: market_data"

The market_data heartbeat can only be published by a quote that actually came
back, so it goes stale whenever the feed is quiet - including every night and
every weekend. Until the feed window shipped on 2026-10-12, the watchdog
raised that warning around the clock.

    2026-10-10   9,927
    2026-10-11  12,814
    2026-10-12   2,033   <- feed window scoped to 09:00-23:30 IST
    2026-10-13     214   <- and all 214 fall in 14:00-15:18 IST, which is
                            exactly the DNS outage that day

So the writer is honest now; what it still records is a real outage. That is
why this is a cleanup and not a silencing: the measurement came first, and if
the rate had still been 12,000 a day the answer would have been to fix the
writer, not to empty the table.

AGE IS THE WRONG RULE, which is the trap these tests mostly guard. A rolling
7-day window keeps 26,269 of them because the two worst days are inside it.
The noise is bounded by when the WRITER was fixed.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "prune_watchdog_incidents", ROOT / "tools" / "ops" / "prune_watchdog_incidents.py"
)
tool = importlib.util.module_from_spec(_spec)
sys.modules["prune_watchdog_incidents"] = tool
_spec.loader.exec_module(tool)

DDL = """
CREATE TABLE watchdog_incidents (
    incident_id TEXT PRIMARY KEY, timestamp TEXT, severity TEXT, subsystem TEXT,
    root_cause TEXT, detected_by TEXT, automatic_actions TEXT,
    recommended_actions TEXT, commander_acknowledgement INTEGER,
    resolution TEXT, duration REAL
);
"""
NOISE = tool.NOISE_ROOT_CAUSE


def _row(i, day, severity, root_cause, subsystem="heartbeat_freshness"):
    return (f"inc-{i}", f"{day}T10:00:0{i % 10}+00:00", severity, subsystem,
            root_cause, "watchdog", "", "", 0, "UNRESOLVED", 0.0)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "hokage.db"
    con = sqlite3.connect(path)
    con.executescript(DDL)
    rows = [
        # the repeated noise, before the cut
        _row(1, "2026-10-10", "WARNING", NOISE),
        _row(2, "2026-10-11", "WARNING", NOISE),
        # the same sentence, ON the cut date and after - kept
        _row(3, "2026-10-12", "WARNING", NOISE),
        _row(4, "2026-10-13", "WARNING", NOISE),
        # a real multi-subsystem incident, before the cut - kept, it is HIGH
        _row(5, "2026-10-10", "HIGH", "Stale heartbeats detected for: strategy_engine, market_data"),
        # a different warning, before the cut - kept, not this sentence
        _row(6, "2026-10-10", "WARNING", "Stale heartbeats detected for: improvement_engine"),
        # right sentence, wrong subsystem - kept
        _row(7, "2026-10-10", "WARNING", NOISE, subsystem="something_else"),
        # a CRITICAL - kept whatever else is true
        _row(8, "2026-10-01", "CRITICAL", NOISE),
    ]
    con.executemany("INSERT INTO watchdog_incidents VALUES (" + ",".join("?" * 11) + ");", rows)
    con.commit()
    con.close()

    monkeypatch.setattr(tool, "DB", path)
    monkeypatch.setattr(tool, "ARCHIVE_DIR", tmp_path / "archive")
    return path


def _ids(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT incident_id FROM watchdog_incidents;")}
    finally:
        con.close()


def _prune(path, cut=tool.DEFAULT_CUT):
    con = sqlite3.connect(path)
    try:
        return tool.prune(con, cut)
    finally:
        con.close()


# ------------------------------------------------- only the repeated sentence
def test_the_repeated_warning_before_the_cut_is_archived(db):
    assert _prune(db) == 0
    assert "inc-1" not in _ids(db)
    assert "inc-2" not in _ids(db)


def test_a_high_incident_is_never_touched(db):
    """127 of these exist and they are the real ones: several subsystems
    stale at once. Losing them to a cleanup of warnings would be the actual
    disaster here."""
    _prune(db)
    assert "inc-5" in _ids(db)


def test_a_critical_incident_is_never_touched(db):
    _prune(db)
    assert "inc-8" in _ids(db)


def test_a_different_warning_is_never_touched(db):
    """156 warnings name other subsystems. They are rare, which is exactly
    what makes them worth reading."""
    _prune(db)
    assert "inc-6" in _ids(db)


def test_the_same_sentence_from_another_subsystem_is_not_touched(db):
    _prune(db)
    assert "inc-7" in _ids(db)


def test_the_root_cause_is_matched_in_full_not_by_pattern():
    """A LIKE '%market_data%' would eventually swallow a different incident
    that deserved reading."""
    assert "LIKE" not in tool._WHERE.upper()
    assert "root_cause = ?" in tool._WHERE


# --------------------------------------------------- the cut is a date, not an age
def test_rows_on_the_cut_date_are_kept(db):
    """The cut is 'before', not 'on or before'. The fix landed during
    2026-10-12, so that day's rows are kept conservatively."""
    _prune(db)
    assert "inc-3" in _ids(db)


def test_rows_after_the_cut_are_kept(db):
    _prune(db)
    assert "inc-4" in _ids(db)


def test_the_default_cut_is_the_day_the_writer_was_fixed():
    """A rolling window is the wrong rule: a 7-day one keeps 26,269 of these
    because the two worst days are inside it."""
    assert tool.DEFAULT_CUT == "2026-10-12"


def test_a_later_cut_takes_more(db):
    """The cut is a parameter, and moving it forward must widen the
    selection rather than do something surprising."""
    assert _prune(db, "2026-10-14") == 0
    left = _ids(db)
    for noise_id in ("inc-1", "inc-2", "inc-3", "inc-4"):
        assert noise_id not in left
    assert {"inc-5", "inc-6", "inc-7", "inc-8"} <= left


def test_a_malformed_cut_is_refused(monkeypatch, db, capsys):
    monkeypatch.setattr(sys, "argv", ["x", "--prune", "--before", "last tuesday"])
    assert tool.main() == 1
    assert "YYYY-MM-DD" in capsys.readouterr().out


# ------------------------------------------- archive before anything is deleted
def test_every_archived_row_is_readable_back(db):
    _prune(db)
    archive = next((tool.ARCHIVE_DIR).glob("watchdog_incidents_*.jsonl.gz"))
    with gzip.open(archive, "rt", encoding="utf-8") as fh:
        lines = [json.loads(l) for l in fh]
    header, rows = lines[0], lines[1:]
    assert {r["incident_id"] for r in rows} == {"inc-1", "inc-2"}
    assert header["_cut_before"] == tool.DEFAULT_CUT
    assert "CREATE TABLE watchdog_incidents" in header["_schema"]
    assert header["_reason"]


def test_nothing_is_deleted_if_the_archive_is_short(db, monkeypatch):
    """THE RAIL. A half-written archive plus a completed delete is
    unrecoverable."""
    real_open = gzip.open

    def truncating_open(path, mode="rb", **kw):
        if "w" in mode:
            class _Swallow:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    with real_open(path, "wt", encoding="utf-8") as fh:
                        fh.write("")
                    return False

                def write(self_inner, _):
                    return None

            return _Swallow()
        return real_open(path, mode, **kw)

    monkeypatch.setattr(tool.gzip, "open", truncating_open)
    before = _ids(db)
    assert _prune(db) == 1
    assert _ids(db) == before


def test_pruning_twice_is_harmless(db):
    _prune(db)
    after_first = _ids(db)
    assert _prune(db) == 0
    assert _ids(db) == after_first


# ------------------------------------------------------- report changes nothing
def test_report_is_read_only(db, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x", "--report"])
    before = _ids(db)
    assert tool.main() == 0
    assert _ids(db) == before
    out = capsys.readouterr().out
    assert "selected" in out and "kept" in out


def test_report_shows_what_survives_by_severity(db, monkeypatch, capsys):
    """Whoever runs this must be able to see that the HIGH incidents are
    staying before they let it delete 45,000 rows."""
    monkeypatch.setattr(sys, "argv", ["x", "--report"])
    tool.main()
    out = capsys.readouterr().out
    assert "HIGH" in out
    assert "CRITICAL" in out


# --------------------------------------------- the WAL lesson is not duplicated
def test_the_vacuum_is_imported_not_copied():
    """A VACUUM in WAL mode grows the file instead of shrinking it. That cost
    a day to find on 2026-10-09; a second copy of the fix is a second thing to
    get wrong."""
    src = (ROOT / "tools" / "ops" / "prune_watchdog_incidents.py").read_text(
        encoding="utf-8"
    )
    assert "from prune_audit_trail import" in src
    assert "journal_mode=DELETE" not in src, "the WAL dance is duplicated here"
    assert tool.vacuum.__module__ == "prune_audit_trail"
