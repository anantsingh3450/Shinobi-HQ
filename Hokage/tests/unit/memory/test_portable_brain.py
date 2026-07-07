from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from hokage.memory.models import BrainMetadata
from hokage.memory.resolver import PathResolver
from hokage.memory.bootstrap import BrainBootstrapper
from hokage.memory.fingerprint import BrainFingerprinter


def test_brain_metadata_serialization():
    meta = BrainMetadata(
        brain_id=UUID("12345678-1234-5678-1234-567812345678"),
        brain_name="Test_Brain",
        owner_name="Anant",
        display_name="Tester",
        brain_role="PRIMARY",
        brain_type="EXPERIMENTAL",
        parent_brain_id=UUID("87654321-4321-8765-4321-876543210987")
    )
    
    serialized = meta.to_dict()
    assert serialized["brain_name"] == "Test_Brain"
    assert serialized["brain_type"] == "EXPERIMENTAL"
    assert serialized["parent_brain_id"] == "87654321-4321-8765-4321-876543210987"
    
    deserialized = BrainMetadata.from_dict(serialized)
    assert deserialized.brain_id == meta.brain_id
    assert deserialized.parent_brain_id == meta.parent_brain_id
    assert deserialized.brain_type == "EXPERIMENTAL"


def test_path_resolution(tmp_path: Path):
    resolver = PathResolver(tmp_path)
    assert resolver.resolve_brain_root() == tmp_path
    assert resolver.resolve_config_dir() == tmp_path / "config"
    assert resolver.resolve_portfolio_dir() == tmp_path / "portfolio"
    assert resolver.resolve_trades_dir() == tmp_path / "trades"
    assert resolver.resolve_tax_dir() == tmp_path / "tax"
    assert resolver.resolve_vault_dir() == tmp_path / "vault"
    assert resolver.resolve_evolution_dir() == tmp_path / "evolution"
    assert resolver.resolve_genomes_dir() == tmp_path / "evolution" / "genomes"


def test_brain_bootstrap(tmp_path: Path):
    resolver = PathResolver(tmp_path)
    bootstrapper = BrainBootstrapper(resolver)
    
    assert not bootstrapper.is_brain_bootstrapped()
    
    bootstrapper.bootstrap()
    
    assert bootstrapper.is_brain_bootstrapped()
    
    # Check that brain.json is valid
    brain_json_path = tmp_path / "brain.json"
    assert brain_json_path.exists()
    with open(brain_json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["brain_name"] == "Elder_Primary"
    assert meta["brain_type"] == "PRIMARY"
    
    # Check config/venues.json is valid
    venues_json_path = tmp_path / "config" / "venues.json"
    assert venues_json_path.exists()
    with open(venues_json_path, "r", encoding="utf-8") as f:
        venues = json.load(f)
    assert len(venues["venues"]) == 1
    assert venues["venues"][0]["venue_id"] == "paper_main"


def test_brain_fingerprint_deterministic(tmp_path: Path):
    resolver = PathResolver(tmp_path)
    bootstrapper = BrainBootstrapper(resolver)
    bootstrapper.bootstrap()
    
    fingerprinter = BrainFingerprinter(tmp_path)
    fp1 = fingerprinter.compute_fingerprint()
    
    # Create some dummy files in trades and portfolio
    with open(tmp_path / "trades" / "trades.jsonl", "w") as f:
        f.write("trade-line-1\n")
    with open(tmp_path / "portfolio" / "account_paper.json", "w") as f:
        f.write("{}\n")
        
    fp2 = fingerprinter.compute_fingerprint()
    assert fp1 != fp2
    
    # Verify deterministic output
    fp3 = fingerprinter.compute_fingerprint()
    assert fp2 == fp3
