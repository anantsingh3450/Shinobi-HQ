from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import logging

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger("Hokage.Watchdog.Heartbeat")


@dataclass
class Heartbeat:
    """The canonical heartbeat record published by a subsystem."""
    subsystem: str
    timestamp: datetime
    status: str
    uptime: float  # in seconds
    last_successful_cycle: datetime
    execution_latency: float  # in milliseconds
    memory_usage: float  # in MB
    cpu_usage: float  # in %

    def to_dict(self) -> dict[str, any]:
        """Convert Heartbeat instance to a serializable dictionary."""
        return {
            "subsystem": self.subsystem,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "uptime": self.uptime,
            "last_successful_cycle": self.last_successful_cycle.isoformat(),
            "execution_latency": self.execution_latency,
            "memory_usage": self.memory_usage,
            "cpu_usage": self.cpu_usage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, any]) -> Heartbeat:
        """Construct Heartbeat instance from a dictionary."""
        return cls(
            subsystem=data["subsystem"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            status=data["status"],
            uptime=float(data["uptime"]),
            last_successful_cycle=datetime.fromisoformat(data["last_successful_cycle"]),
            execution_latency=float(data["execution_latency"]),
            memory_usage=float(data["memory_usage"]),
            cpu_usage=float(data["cpu_usage"]),
        )


class HeartbeatTracker:
    """A thread-safe tracker for capturing and recording heartbeats from Hokage subsystems."""

    def __init__(self) -> None:
        self._start_times: dict[str, datetime] = {}
        self._last_heartbeats: dict[str, Heartbeat] = {}

    def register_subsystem(self, subsystem: str) -> None:
        """Register the boot/start time of a subsystem to compute uptime."""
        if subsystem not in self._start_times:
            self._start_times[subsystem] = datetime.now(timezone.utc)

    def record_heartbeat(
        self,
        subsystem: str,
        status: str = "HEALTHY",
        last_successful_cycle: datetime | None = None,
        execution_latency: float = 0.0,
    ) -> Heartbeat:
        """Create and return a fresh heartbeat for the given subsystem."""
        self.register_subsystem(subsystem)
        
        now = datetime.now(timezone.utc)
        start_time = self._start_times[subsystem]
        uptime_sec = (now - start_time).total_seconds()
        
        # Get memory and CPU metrics
        memory_mb = 0.0
        cpu_pct = 0.0
        
        if psutil:
            try:
                process = psutil.Process(os.getpid())
                memory_mb = process.memory_info().rss / (1024 * 1024)
                cpu_pct = process.cpu_percent(interval=None)
            except Exception as e:
                logger.debug(f"Failed to fetch system metrics via psutil: {e}")

        hb = Heartbeat(
            subsystem=subsystem,
            timestamp=now,
            status=status,
            uptime=uptime_sec,
            last_successful_cycle=last_successful_cycle or now,
            execution_latency=execution_latency,
            memory_usage=memory_mb,
            cpu_usage=cpu_pct,
        )
        self._last_heartbeats[subsystem] = hb
        return hb

    def get_last_heartbeat(self, subsystem: str) -> Heartbeat | None:
        """Retrieve the last recorded heartbeat for a subsystem."""
        return self._last_heartbeats.get(subsystem)

    def get_all_last_heartbeats(self) -> dict[str, Heartbeat]:
        """Retrieve the last recorded heartbeats for all subsystems."""
        return dict(self._last_heartbeats)
