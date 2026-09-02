"""The test suite must NEVER touch the production brain.

Regression guard for the 2026-07-13 incident: tests that built default
orchestrators/stores resolved PathResolver's CWD-relative "hokage_brain"
default and wrote trades, ghost positions, and audit rows into the LIVE
production database — which the running bot then acted on (it spent an
evening trying to square off a GBP/USD position a test had planted).

conftest.py points HOKAGE_BRAIN_ROOT at a session-scoped temp directory;
PathResolver honors it whenever no explicit root is passed.
"""
from __future__ import annotations

import os
from pathlib import Path

from hokage.memory.resolver import PathResolver

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCTION_BRAIN = (_REPO_ROOT / "hokage_brain").resolve()


def test_suite_brain_root_is_sandboxed():
    env_root = os.environ.get("HOKAGE_BRAIN_ROOT", "")
    assert env_root, "conftest must set HOKAGE_BRAIN_ROOT for the whole suite"
    assert "hokage_test_brain_" in env_root


def test_default_path_resolver_never_resolves_production_brain():
    resolved = PathResolver().resolve_brain_root()
    assert resolved != _PRODUCTION_BRAIN, (
        "Default PathResolver points at the production brain during tests — "
        "any store built on it would pollute live trading state."
    )


def test_explicit_brain_root_still_wins_over_env(tmp_path: Path):
    explicit = PathResolver(tmp_path).resolve_brain_root()
    assert explicit == tmp_path.resolve()


def test_new_paper_account_uses_commander_profile_capital(tmp_path: Path):
    """Profile starting_capital must win over the hardcoded 10k default.

    A 500k commander profile silently booting a 10k paper account starved
    every entry of cash ("Insufficient account cash balance")."""
    import json

    from bots.portfolio.store import JsonPortfolioStore

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "commander_profile.json").write_text(
        json.dumps({"portfolio": {"starting_capital": 500000}}), encoding="utf-8"
    )

    store = JsonPortfolioStore(tmp_path / "portfolio")
    account = store.load_account("paper")
    assert account.cash == 500000.0
    assert account.initial_balance == 500000.0


# --------------------------------------------------------------------------
# The suite must not litter the WORKING TREE either.
#
# The guards above stop tests writing into the production brain. They did not
# stop tests creating directories elsewhere in the repo, and two had been
# quietly accumulating on every run:
#
#     MagicMock/mock.resolver.resolve_brain_root()/2185934233552/intelligence
#     dummy/
#
# Both came from constructors with filesystem side effects — IntelligenceCache
# and TradeDNAEngine each did `mkdir(parents=True)` in `__init__`, so merely
# BUILDING one created folders, and a test handing in a MagicMock produced a
# real directory named after the mock's repr. `MagicMock/` had been added to
# .gitignore rather than fixed, which hid the symptom and kept the cause.
#
# Both now create their directory when something is actually written.
# --------------------------------------------------------------------------
def test_building_the_intelligence_cache_creates_nothing(tmp_path: Path):
    """A constructor must not touch the filesystem."""
    from bots.autonomous.cache import IntelligenceCache

    root = tmp_path / "brain"
    IntelligenceCache(root)
    assert not root.exists(), "constructing the cache created directories"


def test_writing_through_the_cache_does_create_it(tmp_path: Path):
    """Laziness must not become breakage — the write path still works."""
    from bots.autonomous.cache import IntelligenceCache

    cache = IntelligenceCache(tmp_path / "brain")
    cache.write_intelligence("probe.json", {"ok": True})
    assert cache.read_intelligence("probe.json").get("ok") is True


def test_building_the_trade_dna_engine_creates_nothing(tmp_path: Path):
    from bots.autonomous.trade_dna import TradeDNAEngine

    root = tmp_path / "brain"
    TradeDNAEngine(root)
    assert not root.exists(), "constructing the DNA engine created directories"


def test_a_mock_brain_root_cannot_create_a_real_directory(tmp_path, monkeypatch):
    """The exact shape of the litter: a MagicMock passed where a path belongs.

    Building the object must stay inert even then — the repr of a mock must
    never become a folder in the working tree."""
    from unittest.mock import MagicMock

    from bots.autonomous.cache import IntelligenceCache

    monkeypatch.chdir(tmp_path)
    IntelligenceCache(MagicMock())
    assert list(tmp_path.iterdir()) == [], sorted(p.name for p in tmp_path.iterdir())


def test_the_repo_has_no_mock_shaped_directories():
    """Belt and braces: if either constructor regains a mkdir, this catches the
    artifact itself rather than the mechanism."""
    for junk in ("MagicMock", "dummy"):
        assert not (_REPO_ROOT / junk).exists(), (
            f"'{junk}/' is back in the repo — a test is writing to the working "
            f"tree again. Find the constructor that mkdirs and make it lazy."
        )
