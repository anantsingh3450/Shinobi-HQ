"""A dropped cache write used to log "Wrote".

2026-10-13 06:23:21, from Hokage's own boot log:

    [WARNING] Hokage.IntelligenceCache: File locked, could not replace cache
    for portfolio_health.json: [WinError 5] Access is denied:
    '...portfolio_health.json.tmp' -> '...portfolio_health.json'

Three things were wrong with how that was handled:

  1. The PermissionError was caught and execution fell straight through to
     logger.debug("Wrote precomputed intelligence to cache") - so the log
     claimed a write that had not happened.
  2. write_intelligence returned None whether it worked or not, so no caller
     could ever know.
  3. The .tmp was left on disk, which makes the next failure indistinguishable
     from this one and accumulates in silence.

WHY IT MATTERS MORE THAN A MISSING FILE. The write being dropped does not
leave a gap; it leaves the PREVIOUS file, and the reader shows that old health
score as the current one. A stale number nothing can distinguish from a fresh
one is the same defect as a fabricated number - which is why the health panel
reports None for things nothing measures rather than a plausible constant.

The lock itself is ordinary Windows behaviour: os.replace fails with WinError 5
while anything holds the target open for a moment, and the lock is gone again
milliseconds later. So retry, and if it still will not go, say so loudly.
"""
from __future__ import annotations

import json
import logging
import pathlib

import pytest

from bots.autonomous.cache import IntelligenceCache

PAYLOAD = {"health_score": 87, "grade": "A"}


@pytest.fixture
def cache(tmp_path: pathlib.Path) -> IntelligenceCache:
    return IntelligenceCache(brain_root=tmp_path)


def flaky_replace(failures: int):
    """A Path.replace that refuses the first `failures` attempts.

    A plain function, not a callable object: an instance assigned to a class
    attribute is not a descriptor, so `self` never binds and the real call
    arrives one argument short.
    """
    real = pathlib.Path.replace
    calls = {"n": 0}

    def replace(this, target):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise PermissionError(
                22, "Access is denied", str(this), 5, str(target)
            )
        return real(this, target)

    replace.calls = calls
    return replace


# ------------------------------------------------------- the happy path
def test_a_successful_write_says_so_and_lands_on_disk(cache):
    assert cache.write_intelligence("portfolio_health.json", dict(PAYLOAD)) is True
    written = json.loads(
        cache.get_cache_file_path("portfolio_health.json").read_text(encoding="utf-8")
    )
    assert written["health_score"] == 87


def test_a_successful_write_leaves_no_tmp_behind(cache):
    cache.write_intelligence("portfolio_health.json", dict(PAYLOAD))
    assert not list(cache.get_cache_file_path("x").parent.glob("*.tmp"))


# ------------------------------------------------ a lock that lets go
def test_a_transient_lock_is_retried_and_succeeds(cache, monkeypatch):
    """The actual observed failure: a scanner holding the fresh .tmp for a few
    milliseconds. One attempt turned that into a lost write."""
    flaky = flaky_replace(failures=2)
    monkeypatch.setattr(pathlib.Path, "replace", flaky)

    assert cache.write_intelligence("portfolio_health.json", dict(PAYLOAD)) is True
    assert flaky.calls["n"] == 3
    written = json.loads(
        cache.get_cache_file_path("portfolio_health.json").read_text(encoding="utf-8")
    )
    assert written["grade"] == "A"


def test_the_retry_gives_up_rather_than_spinning(cache, monkeypatch):
    """A write path that blocks forever on a stuck lock stalls the loop that
    called it."""
    flaky = flaky_replace(failures=99)
    monkeypatch.setattr(pathlib.Path, "replace", flaky)

    cache.write_intelligence("portfolio_health.json", dict(PAYLOAD))
    assert flaky.calls["n"] == IntelligenceCache._REPLACE_ATTEMPTS


# --------------------------------------------- a lock that does not
def test_a_permanent_lock_reports_failure(cache, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace(failures=99))
    assert cache.write_intelligence("portfolio_health.json", dict(PAYLOAD)) is False


def test_a_dropped_write_never_claims_to_have_written(cache, monkeypatch, caplog):
    """THE REGRESSION. The log said "Wrote precomputed intelligence to cache"
    for a write that was dropped."""
    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace(failures=99))
    with caplog.at_level(logging.DEBUG, logger="Hokage.IntelligenceCache"):
        cache.write_intelligence("portfolio_health.json", dict(PAYLOAD))
    assert "Wrote precomputed intelligence" not in caplog.text


def test_a_dropped_write_is_an_error_and_names_the_consequence(cache, monkeypatch, caplog):
    """WARNING was too quiet for "the panel is now showing an old number as
    the current one"."""
    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace(failures=99))
    with caplog.at_level(logging.DEBUG, logger="Hokage.IntelligenceCache"):
        cache.write_intelligence("portfolio_health.json", dict(PAYLOAD))
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a dropped write must be an ERROR"
    assert "STALE" in errors[0].getMessage()
    assert "portfolio_health.json" in errors[0].getMessage()


def test_a_dropped_write_leaves_no_orphaned_tmp(cache, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace(failures=99))
    cache.write_intelligence("portfolio_health.json", dict(PAYLOAD))
    leftovers = list(cache.get_cache_file_path("x").parent.glob("*.tmp"))
    assert not leftovers, f"orphaned temp files: {leftovers}"


def test_a_dropped_write_does_not_corrupt_what_was_already_there(cache, monkeypatch):
    """Losing the new value is survivable. Losing the old one too is not."""
    assert cache.write_intelligence("portfolio_health.json", {"health_score": 70}) is True
    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace(failures=99))
    cache.write_intelligence("portfolio_health.json", {"health_score": 99})

    still_there = json.loads(
        cache.get_cache_file_path("portfolio_health.json").read_text(encoding="utf-8")
    )
    assert still_there["health_score"] == 70


# ------------------------------------------------------- never raises
def test_an_unexpected_failure_returns_false_instead_of_raising(cache, monkeypatch):
    """Callers are deep inside the trading loop. A cache write must not be
    able to take it down."""
    def boom(this, target):
        raise OSError("disk went away")

    monkeypatch.setattr(pathlib.Path, "replace", boom)
    assert cache.write_intelligence("portfolio_health.json", dict(PAYLOAD)) is False
