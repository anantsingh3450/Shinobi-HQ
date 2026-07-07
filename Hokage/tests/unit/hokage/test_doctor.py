"""Unit tests for Hokage Doctor diagnostic engine."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from hokage.router.doctor import HokageDoctor
from hokage.router.command_router import CommandRouter


@pytest.fixture
def temp_brain_root() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create required directories
        (root / "intelligence").mkdir(parents=True)
        (root / "journal").mkdir(parents=True)
        (root / "reports").mkdir(parents=True)
        (root / "reviews").mkdir(parents=True)
        
        # Create a mock profile.json
        profile_data = {
            "commander_name": "Test",
            "commander_title": "Sir",
            "environment": {"mode": "PAPER", "base_currency": "INR"},
            "portfolio": {"starting_capital": 500000.0},
            "risk": {"capital_preservation": True, "risk_mode": "BALANCED"},
            "horizon": {"phase": "ALPHA", "mode": "FOCUSED", "active_universe": ["CRUDE_OIL"]},
            "tax": {"tax_aware": True}
        }
        with (root / "profile.json").open("w", encoding="utf-8") as fh:
            import json
            json.dump(profile_data, fh)
            
        yield root


def test_doctor_diagnostics_pass(temp_brain_root):
    doc = HokageDoctor(temp_brain_root)
    diag = doc.run_diagnostics()
    
    assert "overall_health_score" in diag
    assert diag["overall_health_score"] > 0
    assert diag["environment"]["supported_python_version"] is True
    assert diag["dependencies"]["all_dependencies_satisfied"] is True
    assert diag["configuration"]["profile_exists"] is True
    assert diag["configuration"]["profile_valid_json"] is True


@patch("hokage.router.doctor.HokageDoctor.run_diagnostics")
def test_command_router_doctor_integration(mock_run, temp_brain_root):
    mock_run.return_value = {
        "overall_health_score": 95.0,
        "environment": {
            "python_version": "3.11.0",
            "os_platform": "Windows",
            "supported_python_version": True
        },
        "dependencies": {
            "all_dependencies_satisfied": True,
            "missing_packages": []
        },
        "configuration": {
            "profile_valid_json": True,
            "has_hardcoded_secrets": False
        },
        "database": {
            "database_exists": True,
            "integrity_check_passed": True,
            "schema_version": 2,
            "database_tables": ["schema_version"]
        },
        "filesystem_and_cache": {
            "directory_status": {"intelligence": {"writable": True}},
            "cache_file_status": {"portfolio_intelligence.json": {"valid_json": True}}
        },
        "routing": {
            "registered_cli_subcommands": ["status"],
            "registered_api_routes": []
        },
        "performance": {
            "startup_latency_ms": 50.0,
            "memory_usage_mb": 100.0,
            "disk_read_latency_ms": 1.0,
            "disk_write_latency_ms": 2.0
        },
        "security_and_logging": {
            "logging_configured": True,
            "security_passed": True,
            "security_scan_unsafe_findings": []
        }
    }
    
    orch = MagicMock()
    orch.resolver.resolve_brain_root.return_value = temp_brain_root
    router = CommandRouter(orch)
    
    res = router.handle_command("hokage doctor")
    assert "HOKAGE SYSTEM DOCTOR" in res
    assert "OVERALL HEALTH SCORE: 95.0/100" in res
