"""The dashboard's live event transport — and, by accident, what filled the disk.

THE BUG THIS FILE IS SHAPED AROUND

`publish()` persisted EVERY event to the permanent `audit_trail` table. Three
publishers are pure UI telemetry:

    SYSTEM_HEALTH   the SSE health publisher, every 5 seconds, forever
    HEARTBEAT       the same loop, one row per bot, every 5 seconds, forever
    SHINOBI_LOG     EventBusLogHandler — every INFO log line Hokage emits

By 2026-10-09 `audit_trail` held 3,808,221 rows across 1.5 GB, of which
3,764,507 (98.9%) were those three types. The forensic record the table exists
for — trades, rejections, no-trade days, state changes — was 43,714 rows, about
17 MB. Nothing pruned it; there was no retention path anywhere in the codebase.

It was also expensive per event. Each publish built a NEW SqliteStorageEngine,
whose constructor re-ran the schema check and LOGGED that it had — through a
`Hokage.*` logger, straight back into this function. That is why boot logs show
"schema is at version 8" six times in a row, and why every log line cost a
connection open plus an fsync.

THE RULE NOW: transient telemetry reaches subscribers and never touches disk.
The live dashboard is unaffected — it reads from the subscriber queues, which
are unchanged. Only the permanent record gets smaller, and truer.
"""
from __future__ import annotations

import queue
import threading
from typing import Any

#: Event types that are live UI telemetry, not forensic record. These are
#: delivered to subscribers and NEVER persisted.
#:
#: They are named explicitly rather than inferred, because a denylist that
#: guesses is a denylist that eventually persists something at 5-second
#: cadence again. If a new high-frequency publisher appears, it belongs here —
#: and `tools/ops/prune_audit_trail.py --report` will show it growing.
TRANSIENT_EVENTS = frozenset({
    "HEARTBEAT",
    "SYSTEM_HEALTH",
    "SHINOBI_LOG",
})

#: One engine for the whole process. Its connections are already thread-local
#: and cached; building a new engine per publish threw that away and re-ran the
#: schema check every time.
_engine = None
_engine_lock = threading.Lock()

#: Re-entry guard. Persistence code paths log, and SHINOBI_LOG turns log records
#: back into publishes. Without this, an error inside the INSERT can recurse.
_persisting = threading.local()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from hokage.memory.resolver import PathResolver
                from shared.persistence.sqlite_engine import SqliteStorageEngine

                _engine = SqliteStorageEngine(PathResolver())
    return _engine


def _reset_engine_for_tests() -> None:
    """Test seam. Never called in production."""
    global _engine
    _engine = None


class EventBus:
    """Thread-safe event bus for real-time dashboard updates."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> EventBus:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._listeners = []
                cls._instance._listener_lock = threading.Lock()
        return cls._instance

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        """Subscribe a new client queue to the event bus."""
        q = queue.Queue(maxsize=100)
        with self._listener_lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        """Unsubscribe a client queue from the event bus."""
        with self._listener_lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event to all active subscribers.

        Persists the event to `audit_trail` unless it is transient telemetry.
        Delivery to subscribers happens either way, so the live dashboard sees
        exactly what it saw before.
        """
        payload = {"event": event_type, "data": data}

        if event_type not in TRANSIENT_EVENTS:
            self._persist(event_type, data)

        with self._listener_lock:
            for q in self._listeners:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    # Drop old events if queue is full to prevent blocking
                    try:
                        q.get_nowait()
                        q.put_nowait(payload)
                    except Exception:
                        pass

    def _persist(self, event_type: str, data: dict[str, Any]) -> None:
        if getattr(_persisting, "active", False):
            return
        _persisting.active = True
        try:
            import json
            from datetime import datetime, timezone

            conn = _get_engine().get_connection()
            timestamp = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO audit_trail (event_type, timestamp, data) VALUES (?, ?, ?);",
                (event_type, timestamp, json.dumps(data)),
            )
            conn.commit()
        except Exception:
            # An audit write must never take down a trading decision. The
            # growth report in tools/ops/prune_audit_trail.py is how a silently
            # broken audit path becomes visible.
            pass
        finally:
            _persisting.active = False
