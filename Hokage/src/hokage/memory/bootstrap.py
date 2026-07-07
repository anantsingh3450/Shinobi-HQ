from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from hokage.memory.models import BrainMetadata
from hokage.memory.resolver import PathResolver


class BrainBootstrapper:
    """Detects missing brain directory structure and bootstraps default settings/metadata."""

    def __init__(self, resolver: PathResolver) -> None:
        self._resolver = resolver

    def is_brain_bootstrapped(self) -> bool:
        """Check if brain.json exists under the brain root."""
        root = self._resolver.resolve_brain_root()
        return (root / "brain.json").exists()

    def bootstrap(self) -> None:
        """Create directory structure and initialize default brain.json & venues.json."""
        dirs = [
            self._resolver.resolve_brain_root(),
            self._resolver.resolve_config_dir(),
            self._resolver.resolve_portfolio_dir(),
            self._resolver.resolve_trades_dir(),
            self._resolver.resolve_tax_dir(),
            self._resolver.resolve_vault_dir(),
            self._resolver.resolve_predictions_dir(),
            self._resolver.resolve_genomes_dir(),
            self._resolver.resolve_species_dir(),
            self._resolver.resolve_extinction_registry_dir(),
            self._resolver.resolve_lineage_dir(),
            self._resolver.resolve_mutation_logs_dir(),
            self._resolver.resolve_regime_history_dir(),
            self._resolver.resolve_champions_dir(),
            self._resolver.resolve_knowledge_dir(),
        ]
        
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # 1. Write default brain.json if missing
        brain_json_path = self._resolver.resolve_brain_root() / "brain.json"
        if not brain_json_path.exists():
            meta = BrainMetadata(
                brain_id=uuid4(),
                brain_name="Elder_Primary",
                owner_name="Anant",
                display_name="Village Elder",
                brain_role="PRIMARY",
                brain_type="PRIMARY",
                parent_brain_id=None
            )
            with open(brain_json_path, "w", encoding="utf-8") as f:
                json.dump(meta.to_dict(), f, indent=2)

        # 2. Write default config/venues.json if missing (NO SECRETS)
        venues_json_path = self._resolver.resolve_config_dir() / "venues.json"
        if not venues_json_path.exists():
            default_venues = {
                "venues": [
                    {
                        "venue_id": "paper_main",
                        "venue_name": "Paper Default",
                        "venue_category": "sandbox",
                        "account_id": "paper",
                        "is_active": True,
                        "metadata": {}
                    }
                ]
            }
            with open(venues_json_path, "w", encoding="utf-8") as f:
                json.dump(default_venues, f, indent=2)

        # 3. Write default config/commander_profile.json if missing
        profile_path = self._resolver.resolve_profile_path()
        if not profile_path.exists():
            default_profile = {
                "commander_name": "Anant",
                "commander_title": "Elder",
                "environment": {
                    "mode": "PAPER",
                    "base_currency": "INR"
                },
                "horizon": {
                    "phase": "ALPHA",
                    "mode": "FOCUSED",
                    "active_universe": [
                        "CRUDE_OIL"
                    ]
                },
                "risk": {
                    "risk_mode": "DEFENSIVE",
                    "capital_preservation": True,
                    "max_positions": 1
                },
                "portfolio": {
                    "starting_capital": 500000
                },
                "tax": {
                    "tax_aware": True
                }
            }
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(default_profile, f, indent=2)

