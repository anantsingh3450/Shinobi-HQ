"""Intelligence Cache Manager for the Hokage Two-Speed Brain.

Handles isolated file reads and writes for Layer 2 Deep Intelligence outputs,
enabling Layer 1 Fast Trading Brain to retrieve precomputed parameters instantly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.IntelligenceCache")


class IntelligenceCache:
    """Manages reading and writing precomputed files in hokage_brain/intelligence/."""

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize IntelligenceCache."""
        self._resolver = PathResolver(brain_root)
        self._intel_dir = self._resolver.resolve_brain_root() / "intelligence"
        self._intel_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_file_path(self, filename: str) -> Path:
        """Return absolute path for cache file."""
        return self._intel_dir / filename

    def write_intelligence(self, filename: str, data: dict[str, Any]) -> None:
        """Write precomputed JSON dictionary back to intelligence cache folder atomically."""
        file_path = self.get_cache_file_path(filename)
        try:
            # Inject update timestamp if not already present
            if isinstance(data, dict) and "updated_at" not in data and "timestamp" not in data:
                from datetime import datetime, timezone
                data["updated_at"] = datetime.now(timezone.utc).isoformat()

            temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
            with temp_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.flush()
                import os
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            try:
                temp_path.replace(file_path)
            except PermissionError as pe:
                logger.warning(f"File locked, could not replace cache for {filename}: {pe}")
            logger.debug(f"Wrote precomputed intelligence to cache: {filename}")
        except Exception as exc:
            logger.error(f"Failed to write intelligence cache '{filename}': {exc}")

    def read_intelligence(
        self,
        filename: str,
        default: dict[str, Any] | None = None,
        max_age_seconds: int | None = None
    ) -> dict[str, Any]:
        """Read precomputed JSON dictionary from cache, falling back to defaults, validating freshness."""
        file_path = self.get_cache_file_path(filename)
        if not file_path.exists():
            return default or {}
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)

            if max_age_seconds is not None:
                ts_str = data.get("updated_at") or data.get("timestamp")
                if ts_str:
                    from datetime import datetime, timezone
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        age = (datetime.now(timezone.utc) - ts).total_seconds()
                        if age > max_age_seconds:
                            logger.warning(f"Cache file '{filename}' is stale (age: {age:.1f}s > {max_age_seconds}s). Ignoring.")
                            return default or {}
                    except Exception as ts_exc:
                        logger.error(f"Failed to parse timestamp in cache '{filename}': {ts_exc}")
                        return default or {}
                else:
                    logger.warning(f"Cache file '{filename}' lacks timestamp and max_age_seconds was requested. Ignoring.")
                    return default or {}

            return data
        except Exception as exc:
            logger.error(f"Failed to read intelligence cache '{filename}': {exc}")
            return default or {}
