"""The bot health panel reported numbers nobody measured.

`bot_health_metrics` was created in pipeline.py as a dict literal of invented
values -- health_score 100, cpu 0.5, memory 45.0, latency 0.05, current_task
"IDLE" -- with `heartbeat` stamped at construction and never written again.
/commander/status recomputed health_score and current_task from the real
watchdog heartbeats and served the rest of that literal untouched beside them.

Measured live on 2026-10-12 at 09:23 IST, one payload carried:

    current_task : ACTIVE                        <- correct, recomputed
    health_score : 100                           <- correct, recomputed
    heartbeat    : 2026-10-12T03:41:01+00:00     <- the BOOT time, 12 min old
    cpu          : 0.5                           <- never a measurement

for subsystems whose real heartbeats were four to seven seconds fresh. The one
field a human reads to answer "when did this last run" was the one telling the
oldest lie, sitting next to two that were true.

A fabricated number is worse than a missing one: it cannot be distinguished
from a reading. Everything without a live source is None now, and these tests
exist to keep it that way -- the failure they guard against is silent and
reassuring, which is the dangerous combination.
"""
from __future__ import annotations

import ast
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from hokage.dashboard.api import create_dashboard_api
from hokage.memory.resolver import PathResolver
from shared.persistence.sqlite_engine import SqliteStorageEngine

#: Every bot the dashboard shows, and the watchdog subsystem that really beats
#: for it. Verified against the live heartbeat table on 2026-10-12.
BOT_SUBSYSTEM = {
    "research_bot": "research_engine",
    "strategy_bot": "strategy_engine",
    "risk_bot": "risk_engine",
    "execution_bot": "execution_engine",
    "portfolio_bot": "portfolio_engine",
    "improvement_bot": "improvement_engine",
    "shadow_bot": "shadow_engine",
    "market_intelligence": "surveillance_loop",
    "voice_commander": "voice_commander",
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A dashboard on a throwaway brain, with the SQLite backend active."""
    monkeypatch.setattr(SqliteStorageEngine, "is_active",
                        staticmethod(lambda resolver: True))
    brain_root = tmp_path / "brain"
    app = create_dashboard_api(brain_root=brain_root)
    SqliteStorageEngine(PathResolver(brain_root=brain_root)).run_migrations()
    return app, brain_root


def _beat(brain_root, subsystem, *, age_seconds=2.0, status="HEALTHY",
          cpu=11.5, memory=22.5, latency=0.33):
    """Put a real heartbeat in the store, `age_seconds` in the past."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    conn = sqlite3.connect(brain_root / "hokage.db")
    conn.execute(
        "INSERT OR REPLACE INTO watchdog_heartbeats "
        "(subsystem, timestamp, status, uptime, last_successful_cycle, "
        " execution_latency, memory_usage, cpu_usage) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (subsystem, ts.isoformat(), status, 1.0, ts.isoformat(),
         latency, memory, cpu),
    )
    conn.commit()
    conn.close()
    return ts


def _bots(app):
    with app.test_client() as client:
        resp = client.get("/api/v1/commander/status")
        assert resp.status_code == 200, resp.data[:300]
        return resp.json["bots"]


# ------------------------------------------- the timestamp must be the real one
def test_the_heartbeat_shown_is_the_one_from_the_store(api):
    """THE bug. The displayed timestamp was the process start time forever."""
    app, brain_root = api
    ts = _beat(brain_root, "research_engine", age_seconds=3.0)

    bot = _bots(app)["research_bot"]
    assert bot["heartbeat"] is not None
    shown = datetime.fromisoformat(bot["heartbeat"])
    assert abs((shown - ts).total_seconds()) < 1.0, (
        f"shown {shown} is not the stored heartbeat {ts}"
    )
    assert bot["current_task"] == "ACTIVE"
    assert bot["health_score"] == 100


def test_the_age_is_reported_so_staleness_is_visible_without_arithmetic(api):
    app, brain_root = api
    _beat(brain_root, "risk_engine", age_seconds=4.0)
    bot = _bots(app)["risk_bot"]
    assert bot["heartbeat_age_seconds"] == pytest.approx(4.0, abs=2.0)


def test_cpu_memory_and_latency_come_from_the_heartbeat(api):
    """These were 0.5 / 45.0 / 0.05 for every bot, forever."""
    app, brain_root = api
    _beat(brain_root, "execution_engine", cpu=77.25, memory=66.5, latency=1.75)
    bot = _bots(app)["execution_bot"]
    assert bot["cpu"] == pytest.approx(77.25)
    assert bot["memory"] == pytest.approx(66.5)
    assert bot["latency"] == pytest.approx(1.75)


def test_each_bot_names_the_subsystem_it_is_actually_reading(api):
    app, brain_root = api
    for subsystem in set(BOT_SUBSYSTEM.values()):
        _beat(brain_root, subsystem)
    bots = _bots(app)
    for bot_name, subsystem in BOT_SUBSYSTEM.items():
        assert bots[bot_name]["subsystem"] == subsystem


# -------------------------------------------- absence must look like absence
def test_a_bot_with_no_heartbeat_reports_nothing_rather_than_defaults(api):
    """Nothing was seeded, so nothing has ever beaten. The old literal would
    have answered 100 / IDLE / cpu 0.5 to every one of these."""
    app, _ = api
    for bot_name, bot in _bots(app).items():
        assert bot["heartbeat"] is None, bot_name
        assert bot["last_execution"] is None, bot_name
        assert bot["cpu"] is None, bot_name
        assert bot["memory"] is None, bot_name
        assert bot["latency"] is None, bot_name
        assert bot["health_score"] == 0, bot_name
        assert bot["current_task"] == "OFFLINE", bot_name


def test_a_stale_heartbeat_goes_OFFLINE_but_still_shows_its_timestamp(api):
    """Hiding the timestamp on a stale beat would remove the one fact that
    says HOW stale -- which is what the reader needs most."""
    app, brain_root = api
    ts = _beat(brain_root, "shadow_engine", age_seconds=600.0)
    bot = _bots(app)["shadow_bot"]
    assert bot["current_task"] == "OFFLINE"
    assert bot["health_score"] == 0
    assert bot["heartbeat"] is not None
    assert abs((datetime.fromisoformat(bot["heartbeat"]) - ts).total_seconds()) < 1.0
    assert bot["heartbeat_age_seconds"] > 500


def test_an_unhealthy_but_fresh_beat_is_degraded_not_dead(api):
    app, brain_root = api
    _beat(brain_root, "portfolio_engine", age_seconds=1.0, status="DEGRADED")
    assert _bots(app)["portfolio_bot"]["health_score"] == 50


# --------------------------------------- the topology view uses the same source
def test_the_nodes_view_agrees_with_the_status_view(api):
    """/orchestrator/nodes served the boot-time literal verbatim, so the two
    views disagreed about the same bot at the same instant."""
    app, brain_root = api
    _beat(brain_root, "research_engine", age_seconds=2.0)

    with app.test_client() as client:
        status = client.get("/api/v1/commander/status").json["bots"]
        nodes = client.get("/api/v1/orchestrator/nodes").json

    node_metrics = {n["id"]: n["metrics"] for n in nodes["nodes"]}
    assert node_metrics["research_bot"]["heartbeat"] == status["research_bot"]["heartbeat"]
    assert node_metrics["research_bot"]["health_score"] == status["research_bot"]["health_score"]


# ------------------------------------- nothing may ship an invented number
def _assigned_constants(path: pathlib.Path, keys: set[str]) -> dict:
    """Literal numbers assigned to `keys` in dict displays in EXECUTABLE code.

    AST, not text: a comment explaining the old constants must not trip this,
    which a raw scan did three times in one day.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value in keys
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, (int, float))
                    and not isinstance(v.value, bool)):
                found[k.value] = v.value
    return found


def test_the_pipeline_ships_no_invented_telemetry():
    """pipeline.py held the original literal: health_score 100, cpu 0.5,
    memory 45.0, latency 0.05, for nine bots."""
    found = _assigned_constants(
        pathlib.Path("src/hokage/orchestrator/pipeline.py"),
        {"health_score", "cpu", "memory", "latency", "average_runtime"},
    )
    assert not found, f"fabricated bot telemetry is back: {found}"


def test_the_dashboard_ships_no_invented_latencies():
    """broker_latency 45.0, market_data_latency 12.0, sse_latency 5.0,
    api_latency 8.0 and average_decision_time 1.25 were constants on the
    health panel. Nothing measures them."""
    found = _assigned_constants(
        pathlib.Path("src/hokage/dashboard/api.py"),
        {"broker_latency", "market_data_latency", "sse_latency",
         "api_latency", "average_decision_time"},
    )
    assert not found, f"fabricated latencies are back: {found}"


def test_the_health_panel_measures_cpu_rather_than_asserting_it():
    """The SSE publisher sent cpu 12.5 / ram 45.2 / disk 28.5 every five
    seconds, fixed, however loaded the machine actually was."""
    src = pathlib.Path("src/hokage/dashboard/api.py").read_text(encoding="utf-8")
    assert "_psutil.cpu_percent()" in src
    assert "_psutil.virtual_memory().percent" in src
    found = _assigned_constants(pathlib.Path("src/hokage/dashboard/api.py"),
                                {"ram", "disk"})
    assert not found, f"invented system telemetry is back: {found}"
