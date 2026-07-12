"""Reconciliation Store — persists freezes, reports, and status to SQLite or JSON.

Maintains complete backward compatibility by falling back to JSON files if SQLite is inactive.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from hokage.memory.resolver import PathResolver
from shared.persistence.sqlite_engine import SqliteStorageEngine
from shared.reconciliation.report import ReconciliationReport


class ReconciliationStore:
    """Handles read/write persistence for all reconciliation-related data."""

    _json_lock = threading.RLock()

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver
        self.brain_root = resolver.resolve_brain_root()
        
        # Paths for JSON fallback mode
        self._freezes_file = self.brain_root / "reconciliation_freezes.json"
        self._reports_file = self.brain_root / "reconciliation_reports.jsonl"
        self._status_file = self.brain_root / "reconciliation_status.json"
        
        # Check if SQLite is active
        if SqliteStorageEngine.is_active(resolver):
            self.engine = SqliteStorageEngine(resolver)
            self._use_sqlite = True
        else:
            self.engine = None
            self._use_sqlite = False

    # ------------------------------------------------------------------
    # Strategy / Asset Freezes
    # ------------------------------------------------------------------

    def freeze_asset(self, asset: str, reason: str) -> None:
        """Freeze an asset to prevent any execution orders from being routed."""
        key = f"asset:{asset.upper()}"
        frozen_at = datetime.now(timezone.utc).isoformat()

        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO reconciliation_freezes (frozen_key, reason, frozen_at)
                        VALUES (?, ?, ?);
                    """, (key, reason, frozen_at))
            except Exception:
                # Safe fallback if write fails
                pass
        else:
            # JSON Fallback
            with self._json_lock:
                self.brain_root.mkdir(parents=True, exist_ok=True)
                data = self._load_freezes_json()
                data[key] = {"reason": reason, "frozen_at": frozen_at}
                self._save_freezes_json(data)

    def unfreeze_asset(self, asset: str) -> None:
        """Unfreeze an asset to resume standard executions."""
        key = f"asset:{asset.upper()}"

        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM reconciliation_freezes WHERE frozen_key = ?;", (key,))
            except Exception:
                pass
        else:
            # JSON Fallback
            with self._json_lock:
                data = self._load_freezes_json()
                if key in data:
                    del data[key]
                    self._save_freezes_json(data)

    def is_asset_frozen(self, asset: str) -> bool:
        """Check if an asset is currently frozen."""
        key = f"asset:{asset.upper()}"

        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM reconciliation_freezes WHERE frozen_key = ?;", (key,))
                count = cursor.fetchone()[0]
                return count > 0
            except Exception:
                return False
        else:
            data = self._load_freezes_json()
            return key in data

    def list_freezes(self) -> dict[str, dict[str, str]]:
        """Return all active freezes with their details."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM reconciliation_freezes;")
                freezes = {}
                for row in cursor.fetchall():
                    freezes[row["frozen_key"]] = {
                        "reason": row["reason"],
                        "frozen_at": row["frozen_at"]
                    }
                return freezes
            except Exception:
                return {}
        else:
            return self._load_freezes_json()

    def _load_freezes_json(self) -> dict[str, dict[str, str]]:
        with self._json_lock:
            if not self._freezes_file.exists():
                return {}
            try:
                with self._freezes_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                return {}

    def _save_freezes_json(self, data: dict) -> None:
        with self._json_lock:
            try:
                with self._freezes_file.open("w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Reconciliation Reports
    # ------------------------------------------------------------------

    def save_report(self, report: ReconciliationReport) -> None:
        """Persist a reconciliation report."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO reconciliation_reports (
                            report_id, timestamp, health_score, discrepancies, risk_estimate, status, is_critical
                        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (
                        report.report_id,
                        report.timestamp.isoformat(),
                        report.health_score,
                        json.dumps([d.to_dict() for d in report.discrepancies]),
                        report.risk_estimate,
                        "PENDING_APPROVAL" if report.requires_action else "RESOLVED",
                        1 if report.is_critical else 0
                    ))
            except Exception:
                pass
        else:
            # JSON Fallback (append-only JSONL)
            with self._json_lock:
                self.brain_root.mkdir(parents=True, exist_ok=True)
                try:
                    with self._reports_file.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(report.to_dict()) + "\n")
                except Exception:
                    pass

    def load_reports(self) -> list[ReconciliationReport]:
        """Load all historical reconciliation reports."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM reconciliation_reports ORDER BY timestamp DESC;")
                reports = []
                for row in cursor.fetchall():
                    disc_list = json.loads(row["discrepancies"])
                    from shared.reconciliation.classifier import Discrepancy
                    discrepancies = [Discrepancy.from_dict(d) for d in disc_list]
                    reports.append(
                        ReconciliationReport(
                            report_id=row["report_id"],
                            timestamp=datetime.fromisoformat(row["timestamp"]),
                            health_score=row["health_score"],
                            discrepancies=discrepancies,
                            risk_estimate=row["risk_estimate"],
                            frozen_assets=[d.asset for d in discrepancies if d.requires_freeze],
                            is_critical=bool(row["is_critical"]),
                            requires_action=any(d.severity in ("HIGH", "CRITICAL") for d in discrepancies)
                        )
                    )
                return reports
            except Exception:
                return []
        else:
            with self._json_lock:
                if not self._reports_file.exists():
                    return []
                reports = []
                try:
                    with self._reports_file.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            if line.strip():
                                reports.append(ReconciliationReport.from_dict(json.loads(line.strip())))
                    reports.reverse()  # Newest first
                    return reports
                except Exception:
                    return []

    # ------------------------------------------------------------------
    # Real-Time Reconciliation Status
    # ------------------------------------------------------------------

    def save_status(
        self,
        health_score: float,
        last_time: datetime,
        outstanding_cnt: int,
        critical_cnt: int,
        details: dict
    ) -> None:
        """Save the latest status summary for quick dashboard/UI checks."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO reconciliation_status (
                            key, health_score, last_reconciliation_time, outstanding_discrepancies_count, critical_alerts_count, details
                        ) VALUES (?, ?, ?, ?, ?, ?);
                    """, (
                        "latest",
                        health_score,
                        last_time.isoformat(),
                        outstanding_cnt,
                        critical_cnt,
                        json.dumps(details)
                    ))
            except Exception:
                pass
        else:
            # JSON Fallback
            with self._json_lock:
                self.brain_root.mkdir(parents=True, exist_ok=True)
                status_data = {
                    "health_score": health_score,
                    "last_reconciliation_time": last_time.isoformat(),
                    "outstanding_discrepancies_count": outstanding_cnt,
                    "critical_alerts_count": critical_cnt,
                    "details": details
                }
                try:
                    with self._status_file.open("w", encoding="utf-8") as fh:
                        json.dump(status_data, fh, indent=2)
                except Exception:
                    pass

    def load_status(self) -> dict[str, Any] | None:
        """Load the latest status summary."""
        if self._use_sqlite and self.engine:
            conn = self.engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM reconciliation_status WHERE key = ?;", ("latest",))
                row = cursor.fetchone()
                if row:
                    return {
                        "health_score": row["health_score"],
                        "last_reconciliation_time": row["last_reconciliation_time"],
                        "outstanding_discrepancies_count": row["outstanding_discrepancies_count"],
                        "critical_alerts_count": row["critical_alerts_count"],
                        "details": json.loads(row["details"])
                    }
                return None
            except Exception:
                return None
        else:
            with self._json_lock:
                if not self._status_file.exists():
                    return None
                try:
                    with self._status_file.open("r", encoding="utf-8") as fh:
                        return json.load(fh)
                except Exception:
                    return None
