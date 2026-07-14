from __future__ import annotations

import os
from pathlib import Path


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
            env_root = os.environ.get("HOKAGE_BRAIN_ROOT", "").strip()
            self._brain_root = Path(env_root).resolve() if env_root else Path("hokage_brain").resolve()
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
