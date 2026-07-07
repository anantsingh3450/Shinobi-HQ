"""Memory Manager for Hokage permanent market memory subsystem.

Maintains a long-term historical database stored as a JSON lines file
inside the portable brain root.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.MemoryManager")


class MemoryManager:
    """Manages reading and writing market event logs to JSON lines file."""

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize MemoryManager."""
        self._resolver = PathResolver(brain_root)
        self._memory_dir = self._resolver.resolve_brain_root() / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._memory_file = self._memory_dir / "market_events.jsonl"

    def record_event(self, event_data: dict[str, Any]) -> None:
        """Write a single event record line to market_events.jsonl."""
        try:
            with self._memory_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event_data, sort_keys=True) + "\n")
            logger.info(f"Recorded market event in memory: {event_data.get('event_id', 'unknown')}")
        except Exception as exc:
            logger.error(f"Failed to write market event record: {exc}")

    def load_all_events(self) -> list[dict[str, Any]]:
        """Load and return all recorded event logs from file."""
        events = []
        if not self._memory_file.exists():
            return events

        try:
            with self._memory_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_str = line.strip()
                    if line_str:
                        events.append(json.loads(line_str))
        except Exception as exc:
            logger.error(f"Failed to read market event records: {exc}")
        return events
