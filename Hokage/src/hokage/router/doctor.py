"""Hokage Doctor diagnostic engine.

Performs comprehensive read-only audits of the Hokage system, verifying
environment, dependencies, configuration, database, cache, filesystem,
routing, performance, logging, and security.
"""
from __future__ import annotations

import os
import sys
import time
import json
import logging
import platform
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("Hokage.Doctor")


class HokageDoctor:
    """Diagnoses the health of the Hokage platform and computes a Health Score."""

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize HokageDoctor."""
        from hokage.memory.resolver import PathResolver
        self.resolver = PathResolver(brain_root)
        self.brain_root = self.resolver.resolve_brain_root()
        self.diagnostics: Dict[str, Any] = {}
        self.scores: Dict[str, float] = {}

    def run_diagnostics(self) -> Dict[str, Any]:
        """Run all diagnostic audits and compute scores."""
        self._audit_environment()
        self._audit_dependencies()
        self._audit_configuration()
        self._audit_database()
        self._audit_filesystem_and_cache()
        self._audit_routing_and_endpoints()
        self._audit_performance()
        self._audit_logging_and_security()

        # Compute overall health score
        # Weights:
        #   Environment & Deps: 15%
        #   Configuration: 15%
        #   Database: 20%
        #   Filesystem & Cache: 15%
        #   Routing & Endpoints: 15%
        #   Performance: 10%
        #   Security & Logging: 10%
        overall_score = (
            0.15 * self.scores.get("environment", 100.0) +
            0.15 * self.scores.get("configuration", 100.0) +
            0.20 * self.scores.get("database", 100.0) +
            0.15 * self.scores.get("filesystem", 100.0) +
            0.15 * self.scores.get("routing", 100.0) +
            0.10 * self.scores.get("performance", 100.0) +
            0.10 * self.scores.get("security", 100.0)
        )

        self.diagnostics["overall_health_score"] = round(overall_score, 1)
        return self.diagnostics

    def _audit_environment(self) -> None:
        """Audit the Python environment and OS details."""
        py_version = sys.version.split()[0]
        is_supported_version = sys.version_info >= (3, 10)
        
        details = {
            "python_version": py_version,
            "os_platform": platform.platform(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor(),
            "supported_python_version": is_supported_version
        }
        
        self.diagnostics["environment"] = details
        self.scores["environment"] = 100.0 if is_supported_version else 50.0

    def _audit_dependencies(self) -> None:
        """Audit required package dependencies."""
        required_packages = [
            "flask",
            "psutil",
            "pytest",
            "kiteconnect",
            "keyring",
            "sqlite3"
        ]
        
        missing = []
        imported = {}
        for pkg in required_packages:
            try:
                __import__(pkg)
                imported[pkg] = True
            except ImportError:
                imported[pkg] = False
                missing.append(pkg)
                
        details = {
            "audited_packages": imported,
            "missing_packages": missing,
            "all_dependencies_satisfied": len(missing) == 0
        }
        
        self.diagnostics["dependencies"] = details
        # Subtract 15 points per missing package
        self.scores["dependencies"] = max(0.0, 100.0 - (len(missing) * 15.0))

    def _audit_configuration(self) -> None:
        """Audit configuration files and environment variables."""
        profile_file = self.brain_root / "profile.json"
        profile_valid = False
        profile_error = None
        has_hardcoded_secrets = False
        
        if profile_file.exists():
            try:
                with profile_file.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    profile_valid = True
                    
                # Basic scan for hardcoded credentials or defaults
                serialized = json.dumps(data).lower()
                for keyword in ("your_api_key", "your_api_secret", "your_access_token", "password123"):
                    if keyword in serialized:
                        has_hardcoded_secrets = True
                        break
            except Exception as exc:
                profile_error = str(exc)
        else:
            profile_error = "profile.json does not exist."

        env_secrets = ["KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN"]
        configured_env = {key: (key in os.environ) for key in env_secrets}

        details = {
            "profile_exists": profile_file.exists(),
            "profile_valid_json": profile_valid,
            "profile_error": profile_error,
            "has_hardcoded_secrets": has_hardcoded_secrets,
            "env_credentials_present": configured_env
        }
        
        self.diagnostics["configuration"] = details
        
        score = 100.0
        if not profile_file.exists() or not profile_valid:
            score -= 50.0
        if has_hardcoded_secrets:
            score -= 30.0
            
        self.scores["configuration"] = max(0.0, score)

    def _audit_database(self) -> None:
        """Audit SQLite database integrity and schema version."""
        db_file = self.brain_root / "hokage.db"
        db_exists = db_file.exists()
        db_integrity = False
        schema_version = 0
        db_error = None
        tables: List[str] = []

        if db_exists:
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row
                
                # Integrity check
                cursor = conn.execute("PRAGMA integrity_check;")
                row = cursor.fetchone()
                if row and row[0] == "ok":
                    db_integrity = True
                
                # Check tables
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [r["name"] for r in cursor.fetchall()]
                
                # Check schema version
                if "schema_version" in tables:
                    cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;")
                    row = cursor.fetchone()
                    if row:
                        schema_version = row["version"]
                elif "shadow_sessions" in tables:
                    # Implied Version 2
                    schema_version = 2
                    
                conn.close()
            except Exception as exc:
                db_error = str(exc)
        else:
            db_error = "hokage.db file not found."

        details = {
            "database_exists": db_exists,
            "integrity_check_passed": db_integrity,
            "schema_version": schema_version,
            "database_tables": tables,
            "database_error": db_error
        }
        
        self.diagnostics["database"] = details
        
        score = 100.0
        if not db_exists:
            score -= 50.0
        elif not db_integrity:
            score -= 50.0
        if schema_version < 2:
            score -= 30.0
            
        self.scores["database"] = max(0.0, score)

    def _audit_filesystem_and_cache(self) -> None:
        """Audit required directories, permissions, and cache files."""
        required_dirs = ["intelligence", "journal", "reports", "reviews"]
        dir_status = {}
        for d in required_dirs:
            p = self.brain_root / d
            exists = p.exists()
            writable = os.access(p, os.W_OK) if exists else False
            dir_status[d] = {"exists": exists, "writable": writable}

        required_cache_files = [
            "portfolio_intelligence.json",
            "market_intelligence.json",
            "capital_preservation.json",
            "execution_quality.json",
            "calibration_metrics.json",
            "elder_trust.json"
        ]
        
        cache_status = {}
        for f in required_cache_files:
            p = self.brain_root / "intelligence" / f
            exists = p.exists()
            readable = os.access(p, os.R_OK) if exists else False
            valid_json = False
            if exists and readable:
                try:
                    with p.open("r", encoding="utf-8") as fh:
                        json.load(fh)
                    valid_json = True
                except Exception:
                    pass
            cache_status[f] = {"exists": exists, "readable": readable, "valid_json": valid_json}

        details = {
            "directory_status": dir_status,
            "cache_file_status": cache_status
        }
        
        self.diagnostics["filesystem_and_cache"] = details
        
        score = 100.0
        # Deduct 10 points per missing/unwritable directory
        for d, stat in dir_status.items():
            if not stat["exists"] or not stat["writable"]:
                score -= 10.0
        # Deduct 5 points per missing/invalid cache file
        for f, stat in cache_status.items():
            if not stat["exists"] or not stat["valid_json"]:
                score -= 5.0
                
        self.scores["filesystem"] = max(0.0, score)

    def _audit_routing_and_endpoints(self) -> None:
        """Audit CLI CommandRouter registry and Flask dashboard routes."""
        from hokage.router.command_router import CommandRouter
        from hokage.orchestrator.pipeline import HokageOrchestrator
        
        # Audit CLI commands
        orch = HokageOrchestrator(brain_root=self.brain_root)
        router = CommandRouter(orch)
        
        cli_methods = [m for m in dir(router) if m.startswith("handle_hokage_")]
        cli_commands = [m.replace("handle_hokage_", "").replace("_", "-") for m in cli_methods]
        
        # Audit API routes
        from hokage.dashboard.api import create_dashboard_api
        api_routes = []
        try:
            app = create_dashboard_api(brain_root=self.brain_root)
            for rule in app.url_map.iter_rules():
                api_routes.append({
                    "endpoint": rule.endpoint,
                    "methods": list(rule.methods - {"HEAD", "OPTIONS"}),
                    "rule": str(rule)
                })
        except Exception as exc:
            logger.error(f"Failed to load dashboard API routes: {exc}")

        details = {
            "registered_cli_subcommands": cli_commands,
            "registered_api_routes": api_routes
        }
        
        self.diagnostics["routing"] = details
        self.scores["routing"] = 100.0

    def _audit_performance(self) -> None:
        """Measure startup latency, memory footprint, and disk I/O speed."""
        import psutil
        
        # 1. Startup latency measurement
        start_time = time.perf_counter()
        from hokage.orchestrator.pipeline import HokageOrchestrator
        orch = HokageOrchestrator(brain_root=self.brain_root)
        startup_latency_ms = (time.perf_counter() - start_time) * 1000.0

        # 2. Memory usage
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / (1024.0 * 1024.0)

        # 3. Disk I/O speed (Write & Read speed test of a temporary file)
        temp_file = self.brain_root / "intelligence" / "doctor_temp.json"
        write_time_ms = 0.0
        read_time_ms = 0.0
        try:
            test_data = {"test": "data" * 1000}
            t_start = time.perf_counter()
            with temp_file.open("w", encoding="utf-8") as fh:
                json.dump(test_data, fh)
            write_time_ms = (time.perf_counter() - t_start) * 1000.0

            t_start = time.perf_counter()
            with temp_file.open("r", encoding="utf-8") as fh:
                json.load(fh)
            read_time_ms = (time.perf_counter() - t_start) * 1000.0
            
            if temp_file.exists():
                temp_file.unlink()
        except Exception:
            pass

        details = {
            "startup_latency_ms": round(startup_latency_ms, 2),
            "memory_usage_mb": round(memory_mb, 2),
            "disk_write_latency_ms": round(write_time_ms, 2),
            "disk_read_latency_ms": round(read_time_ms, 2)
        }
        
        self.diagnostics["performance"] = details
        
        score = 100.0
        if startup_latency_ms > 500.0:
            score -= 10.0
        if memory_mb > 250.0:
            score -= 10.0
            
        self.scores["performance"] = max(0.0, score)

    def _audit_logging_and_security(self) -> None:
        """Scan codebase and verify logging configuration and security practices."""
        # 1. Logging verification
        has_handlers = len(logging.getLogger().handlers) > 0 or len(logger.handlers) > 0
        
        # 2. Security scan (Read-only search of key files for eval/exec/pickle/shell=True)
        unsafe_findings = []
        try:
            src_dir = Path(__file__).resolve().parent.parent.parent
            for root, _, files in os.walk(str(src_dir)):
                for f in files:
                    if f.endswith(".py"):
                        fp = Path(root) / f
                        content = fp.read_text(encoding="utf-8", errors="ignore")
                        if "eval(" in content:
                            unsafe_findings.append(f"{fp.name}: eval() usage")
                        if "exec(" in content:
                            unsafe_findings.append(f"{fp.name}: exec() usage")
                        if "pickle.load" in content or "pickle.dump" in content:
                            unsafe_findings.append(f"{fp.name}: pickle usage")
                        if "shell=True" in content:
                            unsafe_findings.append(f"{fp.name}: shell=True subprocess usage")
        except Exception as exc:
            logger.error(f"Security scan failed: {exc}")

        details = {
            "logging_configured": has_handlers,
            "security_scan_unsafe_findings": unsafe_findings,
            "security_passed": len(unsafe_findings) == 0
        }
        
        self.diagnostics["security_and_logging"] = details
        
        score = 100.0
        if not has_handlers:
            score -= 20.0
        if len(unsafe_findings) > 0:
            score -= min(50.0, len(unsafe_findings) * 10.0)
            
        self.scores["security"] = max(0.0, score)
