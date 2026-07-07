from __future__ import annotations

import queue
import threading
from typing import Any


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
        """Publish an event to all active subscribers."""
        payload = {"event": event_type, "data": data}

        # Persist to SQLite audit trail
        try:
            from hokage.memory.resolver import PathResolver
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            import json
            from datetime import datetime, timezone
            
            resolver = PathResolver()
            db = SqliteStorageEngine(resolver)
            conn = db.get_connection()
            
            timestamp = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO audit_trail (event_type, timestamp, data) VALUES (?, ?, ?);",
                (event_type, timestamp, json.dumps(data))
            )
            conn.commit()
        except Exception:
            pass

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
