"""Hokage burned a quarter of a core computing a panel nobody was watching.

Measured 2026-10-13, after 337 minutes of uptime:

    working set   174 MB          <- memory was never the problem
    CPU           4,583 seconds = 22.7% of a core, continuously
    one thread    4,431s of it = 95.6%, started 21ms after STARTING_DASHBOARD
    HTTP traffic  1.9 requests/minute

Sampled in 5-second windows it never dropped to zero: 6.9%-33.4% forever. So
not scan bursts - something running constantly.

It was sse_health_publisher, a thread that gathers a full system snapshot
every 5 seconds to push over SSE to an open dashboard. Two faults compounded:

  1. IT RAN WITH NO SUBSCRIBERS. There is no browser open on a headless host,
     ever, and the planned Oracle VPS has one or two cores.

  2. IT COUNTED INCIDENTS IN PYTHON. Two calls to get_watchdog_incidents()
     per tick, each loading all 47,675 rows and building a dict per row, then
     filtering with list comprehensions to produce two integers. Measured:
     343 ms per call, 687 ms of every 5 s = 13.7% of a core. The same two
     comprehensions sat in /system/health, so one HTTP request there read the
     whole table twice.

AND THE TWO NUMBERS WERE WRONG, which is the part that matters more than the
CPU. The filter was on severity alone with no date, so "warnings_today" showed
47,548 - the whole history - when the day's true figure was 214. And it
matched only CRITICAL, a severity nothing writes (every incident is HIGH or
WARNING), pinning "errors_today" to 0 permanently. A number labelled "today"
whose value means "since the beginning" is worse than no number: it reads as
a measurement.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path("src/hokage/dashboard/api.py")


# ------------------------------------------- nobody watching, nothing computed
def test_the_publisher_checks_for_subscribers_before_working():
    """THE REGRESSION. Without this the thread works forever on a headless
    host for a reader that cannot exist."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "sse_health_publisher"
    )
    dumped = ast.dump(fn)
    assert "listener_count" in dumped, (
        "sse_health_publisher must skip its tick when nothing is subscribed"
    )


def test_the_subscriber_check_comes_before_the_expensive_calls():
    """A check after the snapshot is gathered saves nothing at all.

    WALKS THE AST, NOT THE TEXT. The first version of this scanned for the
    first occurrence of each name and failed on the comment above the gate,
    which mentions _refresh_bot_health while explaining why skipping it is
    safe. Text cannot tell a rule from a description of one.
    """
    tree = ast.parse(API.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "sse_health_publisher"
    )
    loop = next(n for n in ast.walk(fn) if isinstance(n, ast.While))

    gate_at = next(
        (i for i, stmt in enumerate(loop.body)
         if isinstance(stmt, ast.If) and "listener_count" in ast.dump(stmt)),
        None,
    )
    assert gate_at is not None, "no subscriber check in the loop body"

    for expensive in ("check_system_health", "load_heartbeats", "_refresh_bot_health"):
        at = next(
            (i for i, stmt in enumerate(loop.body) if expensive in ast.dump(stmt)),
            None,
        )
        assert at is not None, f"{expensive} is no longer called at all"
        assert gate_at < at, f"{expensive} runs before the subscriber check"


def test_the_skip_is_a_continue_and_nothing_else():
    """A gate that did work before continuing, or that returned, would either
    save nothing or kill the publisher for the rest of the process's life."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "sse_health_publisher"
    )
    loop = next(n for n in ast.walk(fn) if isinstance(n, ast.While))
    gate = next(
        stmt for stmt in loop.body
        if isinstance(stmt, ast.If) and "listener_count" in ast.dump(stmt)
    )
    assert len(gate.body) == 1 and isinstance(gate.body[0], ast.Continue), (
        "the subscriber gate must do nothing but continue the loop"
    )


def test_the_event_bus_can_be_asked():
    from hokage.dashboard.event_bus import EventBus

    bus = EventBus()
    before = bus.listener_count()
    q = bus.subscribe()
    try:
        assert bus.listener_count() == before + 1
    finally:
        bus.unsubscribe(q)
    assert bus.listener_count() == before


def test_the_tick_still_runs_for_a_real_subscriber():
    """Gating must not switch the live dashboard off. An open browser gets
    exactly what it got before."""
    src = API.read_text(encoding="utf-8")
    body = src[src.index("def sse_health_publisher"):]
    body = body[: body.index("threading.Thread")]
    assert "continue" in body, "the skip must continue the loop, not exit it"
    assert "while True" in body, "the publisher must keep looping"
    assert 'bus.publish("SYSTEM_HEALTH"' in body


# --------------------------------------------- counted in SQL, scoped to a day
def test_no_reader_counts_incidents_in_python_any_more():
    """Each of those comprehensions loaded 47,675 rows to produce one integer."""
    src = API.read_text(encoding="utf-8")
    assert "get_watchdog_incidents() if i" not in src, (
        "a full-table load is back in a health reader"
    )


def test_both_readers_share_one_definition():
    """The same wrong filter existed in two places, which is how a wrong
    number survives being noticed in one of them."""
    src = API.read_text(encoding="utf-8")
    assert src.count("def _incident_counts(") == 1
    assert src.count("_incident_counts()") >= 2


def test_the_http_endpoint_counts_once_per_request():
    """_incident_counts()[0] and [1] would run the query twice."""
    src = API.read_text(encoding="utf-8")
    assert "_incident_counts()[0]" not in src
    assert "_incident_counts()[1]" not in src


# ----------------------------------------------------- the numbers are right
def test_the_count_is_scoped_to_the_day_asked_for(tmp_path):
    from shared.watchdog.store import WatchdogStore

    store = object.__new__(WatchdogStore)
    store._use_sqlite = False
    store.engine = None
    store._incidents_file = tmp_path / "incidents.jsonl"
    import threading

    store._json_lock = threading.Lock()
    store._incidents_file.write_text(
        '{"timestamp": "2026-10-13T10:00:00+00:00", "severity": "WARNING"}\n'
        '{"timestamp": "2026-10-13T11:00:00+00:00", "severity": "WARNING"}\n'
        '{"timestamp": "2026-10-13T12:00:00+00:00", "severity": "HIGH"}\n'
        '{"timestamp": "2026-09-21T10:00:00+00:00", "severity": "WARNING"}\n',
        encoding="utf-8",
    )
    counts = store.count_incidents_for_day("2026-10-13")
    assert counts == {"WARNING": 2, "HIGH": 1}, (
        f"yesterday's rows leaked into today: {counts}"
    )


def test_a_day_with_nothing_is_empty_not_a_guess(tmp_path):
    import threading

    from shared.watchdog.store import WatchdogStore

    store = object.__new__(WatchdogStore)
    store._use_sqlite = False
    store.engine = None
    store._incidents_file = tmp_path / "missing.jsonl"
    store._json_lock = threading.Lock()
    assert store.count_incidents_for_day("2026-10-13") == {}


def test_error_severities_include_what_is_actually_written():
    """THE PINNED ZERO. The old count matched only CRITICAL. Nothing writes
    CRITICAL - the 47,675 real rows are HIGH and WARNING - so "errors today"
    could never be anything but 0, however badly the day had gone."""
    from shared.watchdog.store import WatchdogStore

    assert "HIGH" in WatchdogStore.ERROR_SEVERITIES
    assert "CRITICAL" in WatchdogStore.ERROR_SEVERITIES
    assert "WARNING" not in WatchdogStore.ERROR_SEVERITIES, (
        "a warning is not an error; counting it as one makes the figure useless"
    )


def test_the_counts_are_summed_over_every_error_severity():
    src = API.read_text(encoding="utf-8")
    body = src[src.index("def _incident_counts("):]
    body = body[: body.index("def sse_health_publisher")]
    assert "ERROR_SEVERITIES" in body, (
        "the error count must consult the store's severity list, not a literal"
    )
    assert 'counts.get("WARNING", 0)' in body


def test_a_failure_to_count_is_not_reported_as_zero_incidents_silently():
    """It returns (0, 0) on error, which is a deliberate choice for a panel
    field - but it must be wrapped, never allowed to take the thread down."""
    src = API.read_text(encoding="utf-8")
    body = src[src.index("def _incident_counts("):]
    body = body[: body.index("def sse_health_publisher")]
    assert "except Exception" in body


# ------------------------------------------------------------- it stays fast
def test_the_incident_table_is_indexed_for_this_query():
    """The table only grows. Without an index the count scans every row, so a
    query that is fast today gets slower every week."""
    src = pathlib.Path("src/shared/persistence/sqlite_engine.py").read_text(
        encoding="utf-8"
    )
    assert "idx_watchdog_incidents_day" in src
    assert "CREATE INDEX IF NOT EXISTS" in src, "the migration must be idempotent"


def test_the_expensive_loader_warns_about_itself():
    """It still exists for callers that need the records. The next person
    reaching for it should know what it costs."""
    from hokage.orchestrator.pipeline import HokageOrchestrator

    doc = HokageOrchestrator.get_watchdog_incidents.__doc__ or ""
    assert "EXPENSIVE" in doc
