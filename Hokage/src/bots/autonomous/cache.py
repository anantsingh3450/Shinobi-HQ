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
        """Initialize IntelligenceCache.

        CONSTRUCTING THIS MUST NOT TOUCH THE FILESYSTEM. It used to mkdir the
        intelligence directory here, which meant merely BUILDING the object
        created directories — and a test handing it a MagicMock produced a real
        folder named after the mock's repr:

            MagicMock/mock.resolver.resolve_brain_root()/2185934233552/intelligence

        That litter reappeared on every test run and had been papered over with
        a .gitignore entry rather than fixed. The directory is now created when
        something is actually WRITTEN, which is the only moment it is needed.
        """
        self._resolver = PathResolver(brain_root)
        self._intel_dir = self._resolver.resolve_brain_root() / "intelligence"

    def get_cache_file_path(self, filename: str) -> Path:
        """Return absolute path for cache file."""
        return self._intel_dir / filename

    #: Attempts at the final rename before giving up. On Windows os.replace
    #: fails with WinError 5 while anything holds the target open for even a
    #: moment - an indexer or a scanner reading the freshly written .tmp is
    #: enough - and the lock is gone again milliseconds later.
    _REPLACE_ATTEMPTS = 5
    _REPLACE_BACKOFF_SECONDS = 0.05

    def write_intelligence(self, filename: str, data: dict[str, Any]) -> bool:
        """Write a precomputed JSON dictionary into the intelligence cache.

        Returns True only if the file on disk now holds this data.

        IT USED TO SAY "Wrote precomputed intelligence to cache" ON THE PATH
        WHERE THE WRITE HAD BEEN DROPPED. A PermissionError from the final
        rename was caught, logged at WARNING, and execution fell straight
        through to the success line - so the log claimed a write that had not
        happened, the orphaned .tmp was left on disk, and every caller was told
        nothing at all because this returned None either way.

        Seen 9 times, most recently 2026-10-13 06:23:21 on
        portfolio_health.json. The consequence is not a missing panel: the
        reader finds the PREVIOUS file and shows an old health score as the
        current one. A stale number that cannot be told apart from a fresh one
        is the same failure as a fabricated one.
        """
        file_path = self.get_cache_file_path(filename)
        try:
            # Created here, at the moment it is genuinely needed, rather than in
            # the constructor — see __init__.
            self._intel_dir.mkdir(parents=True, exist_ok=True)

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
            import time
            last_error: Exception | None = None
            for attempt in range(self._REPLACE_ATTEMPTS):
                try:
                    temp_path.replace(file_path)
                    logger.debug(f"Wrote precomputed intelligence to cache: {filename}")
                    return True
                except PermissionError as pe:
                    last_error = pe
                    if attempt + 1 < self._REPLACE_ATTEMPTS:
                        time.sleep(self._REPLACE_BACKOFF_SECONDS * (attempt + 1))

            # ERROR, not WARNING. The cache now holds data of an unknown age
            # that its reader will present as current.
            logger.error(
                f"Could not replace cache for {filename} after "
                f"{self._REPLACE_ATTEMPTS} attempts - the file on disk is now "
                f"STALE and whatever reads it will show an old value as "
                f"current: {last_error}"
            )
            # Never leave the .tmp behind: an orphan makes the next failure
            # look like this one and accumulates silently.
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False
        except Exception as exc:
            logger.error(f"Failed to write intelligence cache '{filename}': {exc}")
            return False

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
