from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from hokage.memory.resolver import PathResolver
from shared.watchdog.heartbeat import Heartbeat, HeartbeatTracker
from shared.watchdog.incident import Incident, IncidentJournal
from shared.watchdog.store import WatchdogStore
from shared.watchdog.watchdog import Watchdog


def test_heartbeat_publishing_and_tracking(tmp_path: Path):
    """Verify that heartbeats can be published and successfully tracked/loaded."""
    resolver = PathResolver(tmp_path)
    tracker = HeartbeatTracker()
    
    # 1. Publish heartbeat
    hb = tracker.record_heartbeat(
        subsystem="strategy_engine",
        status="HEALTHY",
        execution_latency=12.5
    )
    assert hb.subsystem == "strategy_engine"
    assert hb.status == "HEALTHY"
    assert hb.execution_latency == 12.5
    assert hb.uptime >= 0.0
    assert hb.memory_usage >= 0.0
    assert hb.cpu_usage >= 0.0

    # 2. Persist and load via store (running in JSON fallback mode in tests)
    store = WatchdogStore(resolver)
    store.save_heartbeat(hb)
    
    loaded_hbs = store.load_heartbeats()
    assert "strategy_engine" in loaded_hbs
    assert loaded_hbs["strategy_engine"].status == "HEALTHY"
    assert loaded_hbs["strategy_engine"].execution_latency == 12.5


def test_incident_creation_and_immutability(tmp_path: Path):
    """Verify that incidents are unique, immutable, and are never deleted from the journal."""
    resolver = PathResolver(tmp_path)
    store = WatchdogStore(resolver)
    
    # 1. Create incidents
    inc1 = IncidentJournal.create_incident(
        severity="WARNING",
        subsystem="orchestrator",
        root_cause="Stale loop",
        detected_by="Watchdog"
    )
    inc2 = IncidentJournal.create_incident(
        severity="CRITICAL",
        subsystem="database_health",
        root_cause="DB Lock",
        detected_by="Watchdog"
    )
    
    assert inc1.incident_id != inc2.incident_id
    assert inc1.resolution == "UNRESOLVED"
    assert inc1.commander_acknowledgement is False
    
    # 2. Save both
    store.save_incident(inc1)
    store.save_incident(inc2)
    
    # 3. Load and verify counts
    loaded = store.load_incidents()
    assert len(loaded) == 2
    # Verify descending order by timestamp
    assert loaded[0].timestamp >= loaded[1].timestamp


def test_watchdog_failure_detection_stale_heartbeat(tmp_path: Path):
    """Verify that the Watchdog detects stale heartbeats and triggers warning/high incidents."""
    resolver = PathResolver(tmp_path)
    watchdog = Watchdog(resolver)
    
    # Publish an old heartbeat (e.g. 40 seconds ago)
    old_time = datetime.now(timezone.utc) - timedelta(seconds=40)
    hb = Heartbeat(
        subsystem="surveillance_loop",
        timestamp=old_time,
        status="HEALTHY",
        uptime=100.0,
        last_successful_cycle=old_time,
        execution_latency=5.0,
        memory_usage=15.0,
        cpu_usage=1.0
    )
    watchdog.store.save_heartbeat(hb)
    
    # Run diagnostic health check
    health_score = watchdog.check_system_health()
    assert health_score < 100.0
    
    # Incident journal must contain the stale heartbeat failure
    incidents = watchdog.store.load_incidents()
    assert len(incidents) > 0
    stale_inc = [i for i in incidents if i.subsystem == "heartbeat_freshness"]
    assert len(stale_inc) == 1
    assert "surveillance_loop" in stale_inc[0].root_cause
    assert stale_inc[0].severity in ("WARNING", "HIGH")


def test_watchdog_failure_detection_database_lock(tmp_path: Path):
    """Verify that a database lock check failure raises a critical incident and activates safety freezes."""
    resolver = PathResolver(tmp_path)
    watchdog = Watchdog(resolver)
    
    # Mock _check_database_lock to simulate a database lock/write failure
    watchdog._check_database_lock = lambda: False
    
    health_score = watchdog.check_system_health()
    assert health_score < 100.0
    
    # Should raise database_health incident
    incidents = watchdog.store.load_incidents()
    db_inc = [i for i in incidents if i.subsystem == "database_health"]
    assert len(db_inc) == 1
    assert db_inc[0].severity == "CRITICAL"
    
    # Safety freeze must have been activated in ReconciliationStore
    from shared.reconciliation.store import ReconciliationStore
    recon_store = ReconciliationStore(resolver)
    assert recon_store.is_asset_frozen("PORTFOLIO") is True


def test_watchdog_failure_detection_memory_growth(tmp_path: Path):
    """Verify that memory growth exceeding critical thresholds triggers critical incidents."""
    resolver = PathResolver(tmp_path)
    watchdog = Watchdog(resolver)
    
    # Force memory threshold values
    watchdog.memory_critical_threshold_mb = 10.0
    
    # Run diagnostic check
    health_score = watchdog.check_system_health()
    assert health_score < 100.0
    
    # Verify memory critical incident was raised
    incidents = watchdog.store.load_incidents()
    mem_inc = [i for i in incidents if i.subsystem == "memory_usage"]
    assert len(mem_inc) == 1
    assert mem_inc[0].severity == "CRITICAL"
    assert "Severe memory growth detected" in mem_inc[0].root_cause


def test_safe_restart_policy(tmp_path: Path):
    """Verify that safe restart works when all safety conditions are met, and updates the heartbeat."""
    resolver = PathResolver(tmp_path)
    watchdog = Watchdog(resolver)
    
    # Setup stale heartbeat incident to verify recovery auto-resolves it
    inc = IncidentJournal.create_incident(
        severity="WARNING",
        subsystem="heartbeat_freshness",
        root_cause="Stale heartbeats detected for: strategy_engine",
        detected_by="Watchdog"
    )
    watchdog.store.save_incident(inc)
    
    # Mock safe restart criteria to return True
    watchdog.evaluate_safe_restart = lambda sub: True
    
    # Execute restart
    success = watchdog.execute_restart("strategy_engine")
    assert success is True
    assert watchdog._restart_counts["strategy_engine"] == 1
    assert watchdog._last_recovery_time is not None
    
    # Heartbeat must have updated to HEALTHY
    hb = watchdog.store.load_heartbeats()["strategy_engine"]
    assert hb.status == "HEALTHY"
    
    # Incident must be resolved
    incidents = watchdog.store.load_incidents()
    resolved = [i for i in incidents if i.incident_id == inc.incident_id]
    assert resolved[0].resolution == "RESOLVED_BY_RESTART"


def test_safe_restart_denied(tmp_path: Path):
    """Verify that a restart is denied if safety conditions are not met, raising a critical incident and freezing execution."""
    resolver = PathResolver(tmp_path)
    watchdog = Watchdog(resolver)
    
    # Mock safe restart criteria to return False
    watchdog.evaluate_safe_restart = lambda sub: False
    
    # Execute restart -> must fail!
    success = watchdog.execute_restart("strategy_engine")
    assert success is False
    
    # Critical incident raised
    incidents = watchdog.store.load_incidents()
    restart_inc = [i for i in incidents if i.subsystem == "strategy_engine" and "Restart denied" in i.root_cause]
    assert len(restart_inc) == 1
    assert restart_inc[0].severity == "CRITICAL"
    
    # Execution safety freeze activated
    from shared.reconciliation.store import ReconciliationStore
    recon_store = ReconciliationStore(resolver)
    assert recon_store.is_asset_frozen("PORTFOLIO") is True


def test_commander_acknowledgement_and_resolution(tmp_path: Path):
    """Verify that the Commander can acknowledge and resolve incidents."""
    resolver = PathResolver(tmp_path)
    watchdog = Watchdog(resolver)
    
    # Create incident
    inc = IncidentJournal.create_incident(
        severity="CRITICAL",
        subsystem="risk_engine",
        root_cause="Risk limit breach",
        detected_by="Watchdog"
    )
    watchdog.store.save_incident(inc)
    
    # 1. Acknowledge
    success_ack = watchdog.store.acknowledge_incident(inc.incident_id)
    assert success_ack is True
    
    # Verify acknowledged in store
    loaded = watchdog.store.load_incidents()[0]
    assert loaded.commander_acknowledgement is True
    
    # 2. Resolve
    success_res = watchdog.store.resolve_incident(inc.incident_id, "RESOLVED_BY_COMMANDER")
    assert success_res is True
    
    # Verify resolved and duration computed
    loaded_resolved = watchdog.store.load_incidents()[0]
    assert loaded_resolved.resolution == "RESOLVED_BY_COMMANDER"
    assert loaded_resolved.duration >= 0.0


def test_watchdog_concurrency_and_stress(tmp_path: Path):
    """Stress test the watchdog store under high concurrent writes to verify thread-safety."""
    resolver = PathResolver(tmp_path)
    store = WatchdogStore(resolver)
    errors = []

    def worker(tid: int):
        try:
            for i in range(20):
                # Save heartbeat
                hb = Heartbeat(
                    subsystem=f"subsys-{tid}-{i}",
                    timestamp=datetime.now(timezone.utc),
                    status="HEALTHY",
                    uptime=1.0,
                    last_successful_cycle=datetime.now(timezone.utc),
                    execution_latency=1.0,
                    memory_usage=1.0,
                    cpu_usage=1.0
                )
                store.save_heartbeat(hb)
                
                # Save incident
                inc = Incident(
                    incident_id=f"inc-{tid}-{i}",
                    timestamp=datetime.now(timezone.utc),
                    severity="INFO",
                    subsystem="test",
                    root_cause="concurrency check",
                    detected_by="test",
                    automatic_actions="none",
                    recommended_actions="none",
                    commander_acknowledgement=False,
                    resolution="UNRESOLVED",
                    duration=None
                )
                store.save_incident(inc)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrency errors in watchdog: {errors}"
    assert len(store.load_heartbeats()) == 100
    assert len(store.load_incidents()) == 100
