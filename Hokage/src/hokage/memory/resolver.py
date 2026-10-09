from __future__ import annotations

import os
from pathlib import Path


#: Environment variable that relocates the brain. The bot's entry point loads
#: `.env` before importing anything that resolves a path; everything else
#: relies on the CONSULT_DOTENV fallback below.
BRAIN_ROOT_ENV = "HOKAGE_BRAIN_ROOT"

#: Used when the variable is unset. Relative, so it follows the CWD.
DEFAULT_BRAIN_DIRNAME = "hokage_brain"

#: Whether brain_root() may fall back to reading `.env` when the environment
#: does not carry HOKAGE_BRAIN_ROOT.
#:
#: True in production, because the liveness probe, the prune tool, the candle
#: archive and the weekly audit are launched by PowerShell and cron rather than
#: through the bot's entry point, so nothing has loaded `.env` for them.
#:
#: `tests/conftest.py` sets this to False, so a test run can never pick up the
#: production brain from `.env`. It is a CONFIG SEAM, which is the point:
#: src must never detect the test environment for itself, and
#: tests/test_no_mock_sniffing_in_src.py enforces that.
CONSULT_DOTENV = True


def _brain_root_from_dotenv() -> str:
    """Read HOKAGE_BRAIN_ROOT — and ONLY that key — from the project `.env`.

    WHY THIS IS HERE. `start.py` calls load_dotenv() before importing anything,
    so Hokage himself sees the variable. Nothing else does. The liveness probe,
    the prune tool, the candle archive and the weekly audit are launched
    directly by PowerShell and cron, and none of them loads `.env`.

    Measured on 2026-10-09, minutes after the brain was moved to C:/Hokage:
    `Start-Hokage.ps1` asked the probe whether a deliberate stop was in force,
    the probe found HOKAGE_BRAIN_ROOT unset, fell back to the repo-relative
    default, and read the stale marker still sitting in OneDrive. Deleting the
    real marker changed nothing. That is the split brain this whole module
    exists to prevent, reproduced inside the fix for it — and the candle
    archive would have gone on appending to the abandoned candles.db nightly.

    ONLY ONE KEY IS READ. Resolving a filesystem path must not have the side
    effect of injecting a file full of credentials into the environment, so
    this parses the single line it needs and ignores everything else. It also
    never writes to os.environ.
    """
    if not CONSULT_DOTENV:
        return ""
    try:
        env_file = Path(__file__).resolve().parents[3] / ".env"
        if not env_file.exists():
            return ""
        return _parse_brain_root(env_file.read_text(encoding="utf-8-sig"))
    except Exception:
        # A malformed .env must not stop a path from resolving. The fallback is
        # the repo-relative default, which is wrong but visible — a traceback
        # here would take down the watchdog as well as the bot.
        return ""


def _parse_brain_root(text: str) -> str:
    """Pull HOKAGE_BRAIN_ROOT out of `.env` text.

    Split out so the parsing is testable without CONSULT_DOTENV standing in
    the way, and without a real credentials file anywhere near a test."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == BRAIN_ROOT_ENV:
            return value.strip().strip('"').strip("'")
    return ""


def brain_root() -> Path:
    """The active brain root, for code that has no PathResolver to hand.

    THE POINT OF THIS FUNCTION. Nine places used to compute
    `Path(__file__).parents[N] / "hokage_brain"` for themselves: the liveness
    probe's stop marker, the candle archive, the weekly audit, the sweep and
    hold-out labs, the affordability check, the review regrader, and two
    modules inside src. PathResolver honoured HOKAGE_BRAIN_ROOT; none of those
    did.

    So on 2026-10-09, moving the brain out of OneDrive would have given Hokage
    a brain at the new path while every tool kept reading and WRITING the old
    one — two divergent brains, silently, which is exactly what MIGRATION.md
    step 1 exists to prevent. The candle archive would have gone on appending
    to a candles.db nobody read, and `Start-Hokage.ps1` would have checked for
    a stop marker in a directory `Stop-Hokage.ps1` no longer wrote to,
    re-breaking that guard hours after it shipped.

    One function, one answer. `tests/unit/hokage/test_brain_root_is_single.py`
    fails the build if a new hardcoded path appears.
    """
    configured = (os.environ.get(BRAIN_ROOT_ENV) or "").strip()
    if not configured:
        # The environment wins; .env is the fallback, for entry points that
        # never ran start.py. See _brain_root_from_dotenv.
        configured = _brain_root_from_dotenv()
    return Path(configured).resolve() if configured else Path(DEFAULT_BRAIN_DIRNAME).resolve()


#: Alias for use inside PathResolver, whose `brain_root` parameter shadows the
#: function above.
_active_brain_root = brain_root


class PathResolver:
    """Resolves directory paths for persistence layers under a specific brain root.

    When no explicit root is given, the HOKAGE_BRAIN_ROOT environment variable
    wins over the CWD-relative default. This is the seam that relocates the
    brain (portable deployments, isolated test sandboxes); without it, any
    process started from the repo root — including the test suite — writes
    into the production brain.
    """

    def __init__(self, brain_root: Path | None = None) -> None:
        if brain_root is None:
            self._brain_root = _active_brain_root()
        else:
            self._brain_root = Path(brain_root).resolve()

    def resolve_brain_root(self) -> Path:
        return self._brain_root

    def resolve_config_dir(self) -> Path:
        return self._brain_root / "config"

    def resolve_portfolio_dir(self) -> Path:
        return self._brain_root / "portfolio"

    def resolve_trades_dir(self) -> Path:
        return self._brain_root / "trades"

    def resolve_tax_dir(self) -> Path:
        return self._brain_root / "tax"

    def resolve_vault_dir(self) -> Path:
        return self._brain_root / "vault"

    def resolve_predictions_dir(self) -> Path:
        return self._brain_root / "predictions"

    def resolve_evolution_dir(self) -> Path:
        return self._brain_root / "evolution"

    def resolve_genomes_dir(self) -> Path:
        return self.resolve_evolution_dir() / "genomes"

    def resolve_species_dir(self) -> Path:
        return self.resolve_evolution_dir() / "species"

    def resolve_extinction_registry_dir(self) -> Path:
        return self.resolve_evolution_dir() / "extinction_registry"

    def resolve_lineage_dir(self) -> Path:
        return self.resolve_evolution_dir() / "lineage"

    def resolve_mutation_logs_dir(self) -> Path:
        return self.resolve_evolution_dir() / "mutation_logs"

    def resolve_regime_history_dir(self) -> Path:
        return self.resolve_evolution_dir() / "regime_history"

    def resolve_champions_dir(self) -> Path:
        return self.resolve_evolution_dir() / "champions"

    def resolve_knowledge_dir(self) -> Path:
        return self._brain_root / "knowledge"

    def resolve_profile_path(self) -> Path:
        return self.resolve_config_dir() / "commander_profile.json"
