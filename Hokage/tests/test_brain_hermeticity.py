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
