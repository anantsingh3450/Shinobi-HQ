"""Notice when Hokage stops learning, and never cry wolf about a holiday.

2026-10-12: the weekly audit's scheduled task reported LastTaskResult = 1 for
the Friday run. No log, no Telegram, nothing. The only reason a 2026-10-09
snapshot exists is that the audit was run by hand that evening; otherwise the
newest measurement would have been 2026-09-22 and nobody would have known.

The liveness probe watches whether Hokage is ALIVE. This watches whether he is
still LEARNING. A dead bot stops answering; a bot that has stopped learning
answers perfectly while its evidence rots, which is the quieter failure.

THE TWO WAYS THIS CAN BE USELESS, and both are tested here:

  1. CRYING WOLF. India's exchange holidays fall on weekdays. A watch that
     alarms on a long weekend teaches the commander to ignore it, and then it
     is worse than nothing — the same reasoning that put CRUDEOIL in
     PARKED_ASSETS instead of letting the orphan audit scream every boot.

  2. STAYING QUIET. An unreadable archive must NEVER read as "fresh". The
     first version of this queried MAX(date) on a table whose column is `ts`;
     the query raised and the function reported UNREADABLE. That was the
     correct outcome from a wrong query, and only because None means UNKNOWN
     here rather than "today".
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
from datetime import date

import pytest


def _load():
    path = pathlib.Path("tools/ops/job_watch.py")
    spec = importlib.util.spec_from_file_location("job_watch_probe", path)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["job_watch_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


jw = _load()


# ------------------------------------------------- weekdays, not calendar days
@pytest.mark.parametrize("start,end,expected", [
    (date(2026, 10, 9), date(2026, 10, 12), 1),    # Fri -> Mon: ONE trading day
    (date(2026, 10, 9), date(2026, 10, 9), 0),
    (date(2026, 10, 9), date(2026, 10, 10), 0),    # Sat
    (date(2026, 10, 9), date(2026, 10, 11), 0),    # Sun
    (date(2026, 10, 9), date(2026, 10, 13), 2),
    (date(2026, 10, 9), date(2026, 10, 16), 5),
    (date(2026, 10, 12), date(2026, 10, 9), 0),    # end before start
])
def test_only_weekdays_count(start, end, expected):
    """Calendar days would score a normal weekend as two days of breakage,
    which is how a watch starts crying every Monday."""
    assert jw.weekdays_between(start, end) == expected


# ------------------------------------------------------------- no false alarms
def test_a_normal_weekend_is_silent():
    """Friday's tape, read on Monday, is CURRENT."""
    assert jw.assess(date(2026, 10, 12), date(2026, 10, 9), date(2026, 10, 9)) == []


@pytest.mark.parametrize("gap", [1, 2, 3, 4])
def test_a_holiday_run_is_silent(gap):
    """One missed weekday is an exchange holiday, two is a long weekend, and
    the Diwali cluster can reach three. None of those is breakage."""
    today = date(2026, 10, 16)           # a Friday
    candle = today
    for _ in range(gap):                  # walk back `gap` weekdays
        candle -= jw.timedelta(days=1)
        while candle.weekday() >= 5:
            candle -= jw.timedelta(days=1)
    assert jw.weekdays_between(candle, today) == gap
    assert jw.assess(today, candle, today) == [], f"alarmed on a {gap}-day gap"


def test_a_snapshot_inside_the_weekly_cadence_is_silent():
    """The audit runs weekly. Ten days allows one slipped run."""
    assert jw.assess(date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 5)) == []


# ------------------------------------------------------------- real breakage
def test_a_tape_that_stopped_growing_is_reported():
    problems = jw.assess(date(2026, 10, 16), date(2026, 10, 8), date(2026, 10, 16))
    assert len(problems) == 1
    assert "not learning" in problems[0].lower()


def test_a_missed_audit_is_reported():
    """Twenty days is what it would have been on 2026-10-12 without the
    hand-run on the 9th."""
    problems = jw.assess(date(2026, 10, 12), date(2026, 10, 12), date(2026, 9, 22))
    assert len(problems) == 1
    assert "not evolving" in problems[0].lower()
    assert "20 days" in problems[0]


def test_both_can_be_wrong_at_once():
    problems = jw.assess(date(2026, 10, 30), date(2026, 10, 8), date(2026, 9, 22))
    assert len(problems) == 2


# ----------------------------------------------- unknown is never "healthy"
def test_an_unreadable_archive_alarms_rather_than_passing():
    """THE trap. A watch that reads a broken database as fresh is worse than
    no watch, because it actively reassures."""
    problems = jw.assess(date(2026, 10, 12), None, date(2026, 10, 12))
    assert len(problems) == 1
    assert "cannot be read" in problems[0]


def test_no_snapshots_at_all_alarms():
    problems = jw.assess(date(2026, 10, 12), date(2026, 10, 12), None)
    assert len(problems) == 1
    assert "no audit snapshots" in problems[0].lower()


def test_a_missing_database_reads_as_unknown_not_fresh(tmp_path):
    assert jw.newest_candle_date(tmp_path / "nope.db") is None


def test_a_database_without_the_table_reads_as_unknown(tmp_path):
    db = tmp_path / "candles.db"
    sqlite3.connect(db).execute("CREATE TABLE unrelated (x INT)").connection.commit()
    assert jw.newest_candle_date(db) is None


# ------------------------------------- the column is `ts`, and that was a bug
def _executable_strings(path: pathlib.Path) -> list[str]:
    """String literals that actually run, excluding docstrings.

    Comments never reach the AST at all, which is the point: a first version
    of this check scanned raw text and failed on the explanatory comment
    describing the bug it forbids. Scanning text cannot tell a rule from a
    description of one -- the same lesson as test_grounded_chat.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_the_archive_is_read_by_its_REAL_column_name():
    """The first version queried MAX(date). The candles table has no `date`
    column -- it is `ts` -- so every run reported UNREADABLE for an archive
    that opens perfectly well."""
    strings = _executable_strings(pathlib.Path("tools/ops/job_watch.py"))
    assert any("MAX(ts)" in s for s in strings)
    assert not any("MAX(date)" in s for s in strings), (
        "a query against a column the candles table does not have"
    )


def test_it_reads_a_real_archive(tmp_path):
    db = tmp_path / "candles.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE candles (symbol TEXT, ts TEXT, close REAL)")
    conn.executemany("INSERT INTO candles VALUES (?,?,?)", [
        ("GOLDM", "2026-10-08 23:15", 1.0),
        ("GOLDM", "2026-10-09 23:15", 2.0),
        ("NIFTY", "2026-10-09 15:15", 3.0),
    ])
    conn.commit()
    conn.close()
    assert jw.newest_candle_date(db) == date(2026, 10, 9)


def test_the_archive_is_opened_READ_ONLY():
    """A watch must not be able to damage the thing it watches."""
    src = pathlib.Path("tools/ops/job_watch.py").read_text(encoding="utf-8")
    assert "mode=ro" in src
    assert "as_uri()" in src, (
        'f"file:{path}" mangles a Windows drive letter; as_uri() does not'
    )


# --------------------------------------------- snapshots are dated by NAME
def test_snapshots_are_dated_by_filename_not_mtime(tmp_path):
    """mtime moves when a file is copied, and the whole brain was copied to a
    new disk on 2026-10-09. The filename is the measurement date."""
    d = tmp_path / "snapshots"
    d.mkdir()
    for name in ("2026-09-22.json", "2026-10-09.json", "notes.json"):
        (d / name).write_text("{}", encoding="utf-8")
    assert jw.newest_snapshot_date(d) == date(2026, 10, 9)


def test_an_unparseable_snapshot_name_is_skipped_not_fatal(tmp_path):
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / "backup-old.json").write_text("{}", encoding="utf-8")
    (d / "2026-10-09.json").write_text("{}", encoding="utf-8")
    assert jw.newest_snapshot_date(d) == date(2026, 10, 9)


def test_an_empty_snapshot_dir_reads_as_none(tmp_path):
    d = tmp_path / "snapshots"
    d.mkdir()
    assert jw.newest_snapshot_date(d) is None


# ------------------------------------------------------ alarm once, then rearm
def test_state_round_trips(tmp_path):
    p = tmp_path / "job_watch.json"
    jw.State(alerted=True, last_reason="because").save(p)
    back = jw.State.load(p)
    assert back.alerted is True
    assert back.last_reason == "because"


def test_a_corrupt_state_file_does_not_stop_the_watch(tmp_path):
    """A monitor that crashes on its own state file is worse than no monitor."""
    p = tmp_path / "job_watch.json"
    p.write_text("{not json", encoding="utf-8")
    s = jw.State.load(p)
    assert s.alerted is False


def test_a_missing_state_file_starts_clean(tmp_path):
    assert jw.State.load(tmp_path / "absent.json").alerted is False


# ------------------------------------------------------------- the thresholds
def test_the_bars_are_where_the_docstring_says():
    """Changing these silently is how the watch becomes noise or becomes
    blind. Both numbers are argued for in the module docstring."""
    assert jw.MAX_CANDLE_WEEKDAYS_STALE == 4
    assert jw.MAX_SNAPSHOT_DAYS_STALE == 10
