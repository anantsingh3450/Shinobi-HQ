"""Shared datetime utilities for Hokage."""
from __future__ import annotations
from datetime import UTC, datetime

def utc_now() -> datetime:
    """Return the current UTC timestamp with UTC timezone."""
    return datetime.now(UTC)
