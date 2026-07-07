from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from hokage.dashboard.api import create_dashboard_api
from shared.persistence.sqlite_engine import SqliteStorageEngine
from hokage.memory.resolver import PathResolver
from hokage.orchestrator.command_queue import Command, CommandType, Role


def test_component4_orchestration_and_apis(tmp_path: Path) -> None:
    # Bypass pytest sqlite safeguard to test actual database features
    original_is_active = SqliteStorageEngine.is_active
    SqliteStorageEngine.is_active = staticmethod(lambda resolver: True)

    try:
        # 1. Setup temporary brain root
        brain_root = tmp_path / "dash_brain"

        # 2. Create the Flask app
        app = create_dashboard_api(brain_root=brain_root)
        resolver = PathResolver(brain_root=brain_root)
        
        # Initialize SQLite database and run migrations (which creates version 3 tables)
        db = SqliteStorageEngine(resolver)
        db.run_migrations()

        app.orchestrator.sqlite_engine = db

        # 3. Test Command Queue Permissions Validation
        with app.app_context():
            # Get the orchestrator instance
            # In api.py, it's created locally inside create_dashboard_api, but we can access it
            # via app's endpoints or by mocking. Let's test via client requests!
            pass

        with app.test_client() as client:
            # A. Test Permission: Observer trying to run SCAN (should be rejected)
            obs_scan_data = {
                "action": "RUN_SCAN",
                "role": "OBSERVER",
                "commander": "ObserverBot",
                "parameters": {}
            }
            resp = client.post("/api/v1/commander/mode", json=obs_scan_data)
            assert resp.status_code == 403
            assert resp.json["status"] == "REJECTED"
            assert "permission" in resp.json["error"]

            # B. Test Permission: Commander running SCAN (should be approved/enqueued)
            cmd_scan_data = {
                "action": "RUN_SCAN",
                "role": "COMMANDER",
                "commander": "LordHokage",
                "parameters": {}
            }
            resp = client.post("/api/v1/commander/mode", json=cmd_scan_data)
            assert resp.status_code == 200
            assert resp.json["status"] in ("PENDING", "RUNNING", "COMPLETED")
            assert resp.json["commander"] == "LordHokage"

            # C. Test Command History Audit Log
            resp = client.get("/api/v1/command/history")
            assert resp.status_code == 200
            history = resp.json
            assert len(history) >= 2
            # Order is newest first
            assert history[0]["commander"] == "LordHokage"
            assert history[1]["commander"] == "ObserverBot"

            # D. Test Bot Status Endpoint & Health Scoring
            resp = client.get("/api/v1/commander/status")
            assert resp.status_code == 200
            status_data = resp.json
            assert "hokage_health_score" in status_data
            assert "bots" in status_data
            assert "research_bot" in status_data["bots"]
            assert status_data["bots"]["research_bot"]["health_score"] == 0  # No heartbeat published yet

            # E. Test System Health Endpoint
            resp = client.get("/api/v1/system/health")
            assert resp.status_code == 200
            health_data = resp.json
            assert "cpu" in health_data
            assert "ram" in health_data
            assert "database_status" in health_data
            assert health_data["database_status"] == "OK"

            # F. Test Automation Settings Get & Post
            settings_payload = {
                "capital_limit": 500000,
                "daily_loss_limit": 1.5,
                "max_open_positions": 3
            }
            resp = client.post("/api/v1/automation/settings", json=settings_payload)
            assert resp.status_code == 200
            assert resp.json["success"] is True

            # Get settings back
            resp = client.get("/api/v1/automation/settings")
            assert resp.status_code == 200
            assert resp.json["capital_limit"] == 500000
            assert resp.json["daily_loss_limit"] == 1.5

            # G. Test Alert Center lifecycle
            # Create a test alert directly in SQLite
            conn = db.get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO system_alerts (source, severity, message, timestamp)
                    VALUES (?, ?, ?, ?);
                """, ("RISK", "CRITICAL", "Risk limit exceeded!", datetime.now(timezone.utc).isoformat()))

            # Fetch alerts
            resp = client.get("/api/v1/alerts")
            assert resp.status_code == 200
            alerts = resp.json
            assert len(alerts) == 1
            assert alerts[0]["source"] == "RISK"
            assert alerts[0]["severity"] == "CRITICAL"
            assert alerts[0]["resolved"] is False

            alert_id = alerts[0]["alert_id"]

            # Resolve alert
            resp = client.post(f"/api/v1/alerts/{alert_id}/resolve")
            assert resp.status_code == 200
            assert resp.json["success"] is True

            # Verify alert is resolved
            resp = client.get("/api/v1/alerts?resolved=false")
            assert resp.status_code == 200
            assert len(resp.json) == 0

    finally:
        SqliteStorageEngine.is_active = original_is_active
