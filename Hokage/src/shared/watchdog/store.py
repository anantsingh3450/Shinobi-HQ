from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from hokage.memory.resolver import PathResolver
from shared.persistence.sqlite_engine import SqliteStorageEngine
from shared.watchdog.heartbeat import Heartbeat
from shared.watchdog.incident import Incident


class WatchdogStore:
    """Handles persistence for watchdog heartbeats and immutable incidents in SQLite or JSON fallback."""

    _json_lock = threading.RLock()

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver
        self.brain_root = resolver.resolve_brain_root()
        
        # Fallback file paths
        self._heartbeats_file = self.brain_root / "watchdog_heartbeats.json"
        self._incidents_file = self.brain_root / "watchdog_incidents.jsonl"
        
        if SqliteStorageEngine.is_active(resolver):
            self.engine = SqliteStorageEngine(resolver)
            self._use_sqlite = True
        else:
            self.engine = None
            self._use_sqlite = False

    # ------------------------------------------------------------------
    # Heartbeat Persistence
    # ------------------------------------------------------------------

    def save_heartbeat(self, hb: Heartbeat) -> None:
        """Persist or update a subsystem heartbeat."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO watchdog_heartbeats (
                            subsystem, timestamp, status, uptime, last_successful_cycle, 
                            execution_latency, memory_usage, cpu_usage
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        hb.subsystem,
                        hb.timestamp.isoformat(),
                        hb.status,
                        hb.uptime,
                        hb.last_successful_cycle.isoformat(),
                        hb.execution_latency,
                        hb.memory_usage,
                        hb.cpu_usage
                    ))
            except Exception:
                pass
        else:
            # JSON Fallback
            with self._json_lock:
                self.brain_root.mkdir(parents=True, exist_ok=True)
                data = self._load_heartbeats_json()
                data[hb.subsystem] = hb.to_dict()
                self._save_heartbeats_json(data)

    def load_heartbeats(self) -> dict[str, Heartbeat]:
        """Load the latest heartbeats for all subsystems."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM watchdog_heartbeats;")
                hbs = {}
                for row in cursor.fetchall():
                    hbs[row["subsystem"]] = Heartbeat(
                        subsystem=row["subsystem"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        status=row["status"],
                        uptime=row["uptime"],
                        last_successful_cycle=datetime.fromisoformat(row["last_successful_cycle"]),
                        execution_latency=row["execution_latency"],
                        memory_usage=row["memory_usage"],
                        cpu_usage=row["cpu_usage"]
                    )
                return hbs
            except Exception:
                return {}
        else:
            with self._json_lock:
                data = self._load_heartbeats_json()
                return {k: Heartbeat.from_dict(v) for k, v in data.items()}

    def _load_heartbeats_json(self) -> dict[str, Any]:
        if not self._heartbeats_file.exists():
            return {}
        try:
            with self._heartbeats_file.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save_heartbeats_json(self, data: dict) -> None:
        try:
            with self._heartbeats_file.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Incident Persistence (Immutable Journal)
    # ------------------------------------------------------------------

    def save_incident(self, incident: Incident) -> None:
        """Persist a new incident record. Never deletes or overwrites existing records."""
        try:
            from hokage.dashboard.event_bus import EventBus
            EventBus().publish("WATCHDOG_ALERT", incident.to_dict())
        except Exception:
            pass

        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO watchdog_incidents (
                            incident_id, timestamp, severity, subsystem, root_cause, 
                            detected_by, automatic_actions, recommended_actions, 
                            commander_acknowledgement, resolution, duration
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        incident.incident_id,
                        incident.timestamp.isoformat(),
                        incident.severity,
                        incident.subsystem,
                        incident.root_cause,
                        incident.detected_by,
                        incident.automatic_actions,
                        incident.recommended_actions,
                        1 if incident.commander_acknowledgement else 0,
                        incident.resolution,
                        incident.duration
                    ))
            except Exception:
                pass
        else:
            # JSON Fallback (append-only JSONL for immutability)
            with self._json_lock:
                self.brain_root.mkdir(parents=True, exist_ok=True)
                # If modifying an existing incident in fallback, we must write a new file or rewrite the journal.
                # Since we want to load the latest state, we can rewrite the journal if modifying,
                # or append if it's a new incident. For simplicity and robustness, we can load all,
                # update the matching one or append, and rewrite the JSONL file.
                incidents = self.load_incidents()
                # Remove if exists to update, then append
                incidents = [i for i in incidents if i.incident_id != incident.incident_id]
                incidents.append(incident)
                self._write_incidents_jsonl(incidents)

    def load_incidents(self) -> list[Incident]:
        """Load all historical incident records."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM watchdog_incidents ORDER BY timestamp DESC;")
                incidents = []
                for row in cursor.fetchall():
                    incidents.append(
                        Incident(
                            incident_id=row["incident_id"],
                            timestamp=datetime.fromisoformat(row["timestamp"]),
                            severity=row["severity"],
                            subsystem=row["subsystem"],
                            root_cause=row["root_cause"],
                            detected_by=row["detected_by"],
                            automatic_actions=row["automatic_actions"],
                            recommended_actions=row["recommended_actions"],
                            commander_acknowledgement=bool(row["commander_acknowledgement"]),
                            resolution=row["resolution"],
                            duration=row["duration"]
                        )
                    )
                return incidents
            except Exception:
                return []
        else:
            with self._json_lock:
                if not self._incidents_file.exists():
                    return []
                incidents = []
                try:
                    with self._incidents_file.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            if line.strip():
                                incidents.append(Incident.from_dict(json.loads(line.strip())))
                    # Return sorted by newest first
                    incidents.sort(key=lambda x: x.timestamp, reverse=True)
                    return incidents
                except Exception:
                    return []

    #: Severities that mean "something went wrong", as opposed to a warning.
    #: CRITICAL is included although nothing writes it today: the health panel
    #: counted ONLY CRITICAL, and because every real incident is written HIGH
    #: or WARNING, its "errors today" figure was structurally pinned to 0.
    ERROR_SEVERITIES = ("CRITICAL", "HIGH")

    def count_incidents_for_day(self, day: str) -> dict[str, int]:
        """How many incidents of each severity were raised on `day` (YYYY-MM-DD).

        COUNTING IN SQL, NOT IN PYTHON. The dashboard's health publisher used
        to call load_incidents() TWICE every five seconds and filter the result
        with list comprehensions, to arrive at two integers. Measured
        2026-10-13 with 47,675 rows in the table: 343 ms per call, so 687 ms of
        every 5 s - 13.7% of a core, burned forever, for two numbers. This
        query is 35 ms, and with the index below it is near zero.

        It also fixes what the old count MEANT. Filtering on severity alone
        counted the whole history: the panel reported 47,548 "warnings today"
        when the true figure for that day was 214. A number whose label says
        "today" and whose value says "since the beginning" is worse than no
        number, because it looks like a measurement.

        Returns {} rather than guessing if the store cannot answer - missing
        must stay distinguishable from zero.
        """
        if not (self._use_sqlite and self.engine):
            # JSONL fallback: still cheaper than building every Incident.
            try:
                if not self._incidents_file.exists():
                    return {}
                counts: dict[str, int] = {}
                with self._json_lock, self._incidents_file.open(
                    "r", encoding="utf-8"
                ) as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        rec = json.loads(line)
                        if str(rec.get("timestamp", ""))[:10] != day:
                            continue
                        sev = str(rec.get("severity", "UNKNOWN"))
                        counts[sev] = counts.get(sev, 0) + 1
                return counts
            except Exception:
                return {}
        try:
            conn = self.engine.get_connection()
            rows = conn.execute(
                "SELECT severity, COUNT(*) FROM watchdog_incidents "
                "WHERE substr(timestamp, 1, 10) = ? GROUP BY severity;",
                (day,),
            ).fetchall()
            return {str(r[0]): int(r[1]) for r in rows}
        except Exception:
            return {}

    def _write_incidents_jsonl(self, incidents: list[Incident]) -> None:
        try:
            with self._incidents_file.open("w", encoding="utf-8") as fh:
                for inc in incidents:
                    fh.write(json.dumps(inc.to_dict()) + "\n")
        except Exception:
            pass

    def acknowledge_incident(self, incident_id: str) -> bool:
        """Set commander_acknowledgement to True for the specified incident."""
        incidents = self.load_incidents()
        target = None
        for inc in incidents:
            if inc.incident_id == incident_id:
                target = inc
                break
        
        if not target:
            return False
            
        target.commander_acknowledgement = True
        self.save_incident(target)
        return True

    def resolve_incident(self, incident_id: str, resolution: str) -> bool:
        """Mark an incident as resolved and compute duration."""
        incidents = self.load_incidents()
        target = None
        for inc in incidents:
            if inc.incident_id == incident_id:
                target = inc
                break
        
        if not target:
            return False
            
        now = datetime.now(timezone.utc)
        duration_sec = (now - target.timestamp).total_seconds()
        
        target.resolution = resolution
        target.duration = duration_sec
        self.save_incident(target)
        return True
