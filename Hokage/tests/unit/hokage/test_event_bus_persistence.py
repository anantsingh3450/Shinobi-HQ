"""The audit trail filled the disk with dashboard refresh ticks.

By 2026-10-09 `audit_trail` held 3,808,221 rows in 1.5 GB. The breakdown:

    2,602,468  HEARTBEAT       SSE health loop, one per bot, every 5s
      872,875  SHINOBI_LOG     every INFO log line Hokage emitted
      289,164  SYSTEM_HEALTH   same 5s loop
    -----------
    3,764,507  98.9% of the table

The forensic record the table exists for - trades, rejections, no-trade days,
state changes - was 43,714 rows. There was no retention path anywhere in the
codebase, so this only ever grew.

WHAT THESE TESTS PIN:

  1. Transient telemetry is NEVER written to disk, however often it is
     published. This is the leak itself.

  2. Transient telemetry IS still delivered to subscribers. The live dashboard
     reads from those queues; fixing the disk leak must not blank the UI.

  3. Real decision events ARE still persisted. The cheap wrong fix is to stop
     persisting everything, which would silently empty the audit trail.

  4. The prune tool purges exactly what the bus declines to write. If those two
     lists drift apart, the tool starts deleting records the bus considers
     worth keeping.

  5. One engine for the process. A new SqliteStorageEngine per publish re-ran
     the schema check and LOGGED it, through a `Hokage.*` logger, straight back
     into publish() - which is why boot logs showed "schema is at version 8"
     six times running.
"""
from __future__ import annotations

import sqlite3

import pytest

from hokage.dashboard import event_bus as eb


@pytest.fixture
def bus_with_db(monkeypatch):
    """A real sqlite audit_trail behind the bus, in memory."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE audit_trail (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type TEXT NOT NULL, timestamp TEXT NOT NULL, data TEXT NOT NULL)"
    )

    class _Engine:
        def get_connection(self):
            return conn

    engine = _Engine()
    monkeypatch.setattr(eb, "_get_engine", lambda: engine)

    bus = eb.EventBus()
    # The bus is a singleton; drop listeners left behind by other tests.
    monkeypatch.setattr(bus, "_listeners", [])
    return bus, conn


def _rows(conn, event_type=None):
    if event_type:
        return conn.execute(
            "SELECT COUNT(*) FROM audit_trail WHERE event_type = ?", (event_type,)
        ).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM audit_trail").fetchone()[0]


# ------------------------------------------------------------ the leak itself
@pytest.mark.parametrize("event_type", sorted(eb.TRANSIENT_EVENTS))
def test_transient_telemetry_is_never_persisted(bus_with_db, event_type):
    bus, conn = bus_with_db
    for _ in range(200):
        bus.publish(event_type, {"anything": 1})
    assert _rows(conn) == 0, f"{event_type} reached the permanent audit trail"


def test_the_three_known_offenders_are_all_covered():
    """Named explicitly, because these are the ones that filled 1.5 GB."""
    assert {"HEARTBEAT", "SYSTEM_HEALTH", "SHINOBI_LOG"} <= eb.TRANSIENT_EVENTS


# ---------------------------------------- the UI must not go dark as a result
@pytest.mark.parametrize("event_type", sorted(eb.TRANSIENT_EVENTS))
def test_transient_telemetry_still_reaches_subscribers(bus_with_db, event_type):
    """The live dashboard reads these queues. Not persisting them must not
    stop them being published."""
    bus, _ = bus_with_db
    q = bus.subscribe()
    try:
        bus.publish(event_type, {"health_score": 100})
        payload = q.get_nowait()
        assert payload["event"] == event_type
        assert payload["data"] == {"health_score": 100}
    finally:
        bus.unsubscribe(q)


# ------------------------------------- the forensic record must still be kept
@pytest.mark.parametrize("event_type", [
    "OPPORTUNITY_REJECTED", "NO_TRADE_DAY", "PORTFOLIO_UPDATED",
    "state_change", "WATCHDOG_ALERT", "TRADE_EXECUTED",
])
def test_real_decision_events_are_still_persisted(bus_with_db, event_type):
    """The cheap wrong fix - persist nothing - would empty the audit trail."""
    bus, conn = bus_with_db
    bus.publish(event_type, {"symbol": "NIFTY", "reason": "volume"})
    assert _rows(conn, event_type) == 1


def test_a_persisted_event_keeps_its_payload_and_timestamp(bus_with_db):
    bus, conn = bus_with_db
    bus.publish("NO_TRADE_DAY",
                {"symbol": "GOLDM", "timestamp": "2026-10-09T13:00:00+00:00"})
    row = conn.execute(
        "SELECT timestamp, data FROM audit_trail WHERE event_type = 'NO_TRADE_DAY'"
    ).fetchone()
    assert row[0] == "2026-10-09T13:00:00+00:00"
    assert "GOLDM" in row[1]


def test_an_event_without_a_timestamp_still_gets_one(bus_with_db):
    bus, conn = bus_with_db
    bus.publish("NO_TRADE_DAY", {"symbol": "GOLDM"})
    stamp = conn.execute(
        "SELECT timestamp FROM audit_trail WHERE event_type = 'NO_TRADE_DAY'"
    ).fetchone()[0]
    assert stamp and stamp.startswith("20")


# --------------------------------------------- tool and bus must not drift
def _load_prune_tool():
    import importlib.util
    import pathlib

    path = pathlib.Path("tools/ops/prune_audit_trail.py")
    spec = importlib.util.spec_from_file_location("prune_audit_trail", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_prune_tool_purges_exactly_what_the_bus_declines_to_write():
    """Two lists, one meaning. If they drift, the tool deletes rows the bus
    still considers worth recording - a silent hole in the audit trail."""
    assert set(_load_prune_tool().PURGEABLE) == set(eb.TRANSIENT_EVENTS)


def test_the_prune_tool_archives_before_it_deletes():
    """Data doctrine: a purge is an archive-move, never a deletion. The DELETE
    must be guarded by a completeness check on the archive."""
    import ast
    import pathlib

    src = pathlib.Path("tools/ops/prune_audit_trail.py").read_text(encoding="utf-8")
    assert "gzip" in src, "purged rows must be archived"
    assert "written != selected" in src, "a short archive write must abort the delete"

    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "prune")

    def line_of(needle):
        return min(n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.Constant)
                   and isinstance(n.value, str) and needle in n.value)

    assert line_of("Archiving") < line_of("ABORT") < line_of("DELETE FROM audit_trail"), (
        "the archive and its completeness check must both precede the DELETE"
    )


def test_the_prune_tool_refuses_to_vacuum_without_the_disk_for_it():
    """VACUUM rebuilds the file beside the original. Starting it with less free
    space than the database is how a 1.5 GB ledger gets truncated."""
    import pathlib

    src = pathlib.Path("tools/ops/prune_audit_trail.py").read_text(encoding="utf-8")
    assert "disk_usage" in src and "SKIPPING VACUUM" in src


# --------------------------------------------------- one engine, not per-event
def test_the_engine_is_built_once_not_per_publish(monkeypatch):
    """A new SqliteStorageEngine per publish re-ran the schema check and logged
    it back through a Hokage logger, into publish() again."""
    eb._reset_engine_for_tests()
    builds = []

    class _Engine:
        def get_connection(self):
            raise RuntimeError("deliberate - this test only counts constructions")

    def _factory(*_a, **_k):
        builds.append(1)
        return _Engine()

    monkeypatch.setattr("hokage.memory.resolver.PathResolver", lambda *a, **k: object())
    monkeypatch.setattr("shared.persistence.sqlite_engine.SqliteStorageEngine", _factory)

    bus = eb.EventBus()
    monkeypatch.setattr(bus, "_listeners", [])
    try:
        for _ in range(50):
            bus.publish("NO_TRADE_DAY", {"n": 1})
        assert len(builds) == 1, (
            f"built the engine {len(builds)} times for 50 publishes"
        )
    finally:
        eb._reset_engine_for_tests()


# ------------------------------------------------------------ failure safety
def test_a_broken_audit_write_does_not_break_the_publish(monkeypatch):
    """An audit failure must never take down a trading decision."""
    eb._reset_engine_for_tests()

    class _Broken:
        def get_connection(self):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(eb, "_get_engine", lambda: _Broken())
    bus = eb.EventBus()
    monkeypatch.setattr(bus, "_listeners", [])
    q = bus.subscribe()
    try:
        bus.publish("NO_TRADE_DAY", {"symbol": "NIFTY"})   # must not raise
        assert q.get_nowait()["event"] == "NO_TRADE_DAY"
    finally:
        bus.unsubscribe(q)
        eb._reset_engine_for_tests()


def test_persistence_refuses_to_re_enter_itself(bus_with_db):
    """SHINOBI_LOG turns log records into publishes, and the persistence path
    logs. Without the guard, an error inside the INSERT recurses."""
    bus, conn = bus_with_db

    # Drive _persist directly, with the guard already raised, exactly as it
    # would be during a nested publish.
    eb._persisting.active = True
    try:
        bus._persist("NO_TRADE_DAY", {"symbol": "NIFTY"})
        assert _rows(conn) == 0, "re-entered persistence while already persisting"
    finally:
        eb._persisting.active = False

    # Guard lowered, the same call writes normally.
    bus._persist("NO_TRADE_DAY", {"symbol": "NIFTY"})
    assert _rows(conn) == 1


def test_the_guard_is_lowered_again_after_a_failed_write(monkeypatch):
    """A guard left raised by an exception would silence the audit trail for
    the rest of the process - the worst kind of quiet."""
    eb._reset_engine_for_tests()

    class _Broken:
        def get_connection(self):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(eb, "_get_engine", lambda: _Broken())
    bus = eb.EventBus()
    monkeypatch.setattr(bus, "_listeners", [])
    try:
        bus.publish("NO_TRADE_DAY", {"symbol": "NIFTY"})
        assert not getattr(eb._persisting, "active", False)
    finally:
        eb._reset_engine_for_tests()


# ------------------------------------- the vacuum has to shrink the real file
def test_the_vacuum_drops_wal_journalling_so_the_file_actually_shrinks():
    """A VACUUM in WAL mode does not shrink hokage.db.

    Measured 2026-10-09: the database reported 30.5 MB of live pages while the
    file was still 1,507,266,560 bytes with a 616 MB WAL beside it. The prune
    had used MORE disk than it freed, and the tool announced "freed 1.4 GB"
    because it was reporting page_count instead of the filesystem.
    """
    import pathlib

    src = pathlib.Path("tools/ops/prune_audit_trail.py").read_text(encoding="utf-8")
    assert "journal_mode=DELETE" in src, (
        "VACUUM in WAL mode leaves the main file at its old size"
    )
    assert "journal_mode=WAL" in src, "WAL must be restored afterwards"
    assert src.index("journal_mode=DELETE") < src.index('conn.execute("VACUUM")') \
        < src.index("journal_mode=WAL"), "DELETE -> VACUUM -> WAL, in that order"


def test_sizes_are_measured_from_the_filesystem_not_page_count():
    """page_count * page_size is what made the first version of this tool lie."""
    import pathlib

    src = pathlib.Path("tools/ops/prune_audit_trail.py").read_text(encoding="utf-8")
    assert "_files_on_disk" in src
    assert "-wal" in src and "-shm" in src, "the WAL counts toward disk used"


# --------------------------------- a deliberate stop must survive the schedule
def test_the_launcher_refuses_to_start_over_a_deliberate_stop():
    """2026-10-09 18:36: Hokage was stopped on purpose to prune the audit
    table. The weekday task relaunched him 43 seconds later, and the liveness
    probe then cleared the marker because it saw him up — so the restart left
    no trace.

    The two mechanisms made each other worse: the marker exists to MUTE the
    "HOKAGE IS NOT TRADING" alarm, so the only thing that would have reported
    the unwanted restart had been silenced by the stop itself.
    """
    import pathlib
    import re

    src = pathlib.Path("Start-Hokage.ps1").read_text(encoding="utf-8")

    assert "Get-DeliberateStop" in src, "the launcher must read the stop marker"

    unattended = src.index("if ($Unattended)")
    body = src[unattended:src.index("Clear-Host")]

    guard = body.index("Get-DeliberateStop")
    first_start = min(
        (m.start() for m in re.finditer(r"Start-Hokage\b", body)
         if m.start() > 0),
        default=len(body),
    )
    assert guard < first_start, (
        "the scheduled-task path checks the marker before it starts anything"
    )
    assert "exit 0" in body[guard:guard + 400], (
        "a marked stop must end the unattended run, not fall through"
    )


def test_a_human_override_clears_the_marker_rather_than_obeying_it():
    """Running the shortcut by hand IS the intent to start. The asymmetry is
    the point: triggers obey the marker, the commander overrides it."""
    import pathlib

    src = pathlib.Path("Start-Hokage.ps1").read_text(encoding="utf-8")
    interactive = src[src.index("Clear-Host"):]
    assert "Clear-DeliberateStop" in interactive, (
        "the interactive path must clear the marker it overrides"
    )
    assert "Starting anyway" in interactive, "and say that it is overriding one"


def test_powershell_never_builds_the_brain_path_itself():
    """The brain is relocatable (it moved off OneDrive on 2026-10-09). A
    launcher that looks for the stop marker under a hardcoded
    $Root\\hokage_brain while Stop-Hokage.ps1 writes to HOKAGE_BRAIN_ROOT is a
    guard that has silently stopped guarding. liveness_probe.py owns the path.
    """
    import pathlib

    for name in ("Start-Hokage.ps1", "Stop-Hokage.ps1"):
        src = pathlib.Path(name).read_text(encoding="utf-8")
        offenders = [
            line for line in src.splitlines()
            if "hokage_brain" in line and not line.strip().startswith("#")
        ]
        assert not offenders, f"{name} hardcodes a brain path: {offenders}"


# -------------------------------------- a no-op that announced itself 72 times
def test_schema_version_constant_matches_the_migrations():
    """LATEST_SCHEMA_VERSION must equal the highest upgrade branch.

    If a schema 9 is added and the constant is not bumped, run_migrations()
    logs "nothing to upgrade" while it upgrades - losing the one line that
    reports a real migration.
    """
    import ast
    import pathlib
    import re

    from shared.persistence.sqlite_engine import LATEST_SCHEMA_VERSION

    src = pathlib.Path("src/shared/persistence/sqlite_engine.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_migrations")
    branches = {
        n.comparators[0].value
        for n in ast.walk(fn)
        if isinstance(n, ast.Compare)
        and isinstance(n.ops[0], ast.Lt)
        and getattr(n.left, "id", None) == "current_version"
        and isinstance(n.comparators[0], ast.Constant)
        and isinstance(n.comparators[0].value, int)
    }
    assert branches, "no `if current_version < N` branches found"
    assert LATEST_SCHEMA_VERSION == max(branches), (
        f"LATEST_SCHEMA_VERSION is {LATEST_SCHEMA_VERSION} but migrations go "
        f"up to {max(branches)}"
    )


def test_a_current_schema_does_not_log_at_info():
    """72 copies of "Applying any missing upgrades" in three minutes of boot,
    for a database that needed no upgrade. run_migrations() is called from six
    places plus a ~60-second loop, and until the event-bus fix every one of
    those lines also became a permanent audit_trail row."""
    import ast
    import pathlib

    src = pathlib.Path("src/shared/persistence/sqlite_engine.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_migrations")

    # Find the version check and confirm the no-op branch logs at debug.
    guard = next(
        (n for n in ast.walk(fn)
         if isinstance(n, ast.If)
         and isinstance(n.test, ast.Compare)
         and isinstance(n.test.ops[0], ast.Lt)
         and getattr(n.test.left, "id", None) == "current_version"
         and getattr(n.test.comparators[0], "id", None) == "LATEST_SCHEMA_VERSION"),
        None,
    )
    assert guard is not None, (
        "run_migrations must branch on current_version < LATEST_SCHEMA_VERSION"
    )

    def levels(body):
        return {n.func.attr for n in ast.walk(ast.Module(body=body, type_ignores=[]))
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and getattr(n.func.value, "id", None) == "logger"}

    assert "info" in levels(guard.body), "a real upgrade must still be announced"
    assert levels(guard.orelse) == {"debug"}, (
        "an already-current schema must not log at INFO"
    )
