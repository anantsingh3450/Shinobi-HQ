from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from hokage.dashboard.api import create_dashboard_api
from shared.persistence.sqlite_engine import SqliteStorageEngine
from hokage.memory.resolver import PathResolver


def test_component3_endpoints(tmp_path: Path) -> None:
    # Save original is_active to prevent test pollution
    original_is_active = SqliteStorageEngine.is_active
    SqliteStorageEngine.is_active = staticmethod(lambda resolver: True)

    try:
        # 1. Setup temporary brain root
        brain_root = tmp_path / "dash_brain"

        # 2. Create the Flask app
        app = create_dashboard_api(brain_root=brain_root)

        # Initialize SQLite database and run migrations
        resolver = PathResolver(brain_root=brain_root)
        db = SqliteStorageEngine(resolver)
        db.run_migrations()

        # 3. Test client requests
        with app.test_client() as client:
            # A. Test Replay Events endpoint (initially empty)
            resp = client.get("/api/v1/replay/events?date=2026-06-28")
            assert resp.status_code == 200
            assert resp.json == []

            # B. Test Commander Notes POST & GET
            note_data = {
                "target_id": "RELIANCE_LONG_001",
                "note": "Excellent breakout trade with high volume support."
            }
            resp = client.post("/api/v1/commander/notes", json=note_data)
            assert resp.status_code == 200
            assert resp.json["success"] is True
            assert resp.json["target_id"] == "RELIANCE_LONG_001"
            assert resp.json["note"] == "Excellent breakout trade with high volume support."

            # Get notes
            resp = client.get("/api/v1/commander/notes?target_id=RELIANCE_LONG_001")
            assert resp.status_code == 200
            assert len(resp.json) == 1
            assert resp.json[0]["note"] == "Excellent breakout trade with high volume support."

            # C. Test Global Search
            # Search for 'reliance'
            resp = client.get("/api/v1/search?q=reliance")
            assert resp.status_code == 200
            search_data = resp.json
            assert "positions" in search_data
            assert "decisions" in search_data
            assert "notes" in search_data
            assert len(search_data["notes"]) == 1
            assert search_data["notes"][0]["target_id"] == "RELIANCE_LONG_001"

            # D. Test Research Reports (initially empty)
            resp = client.get("/api/v1/research/reports")
            assert resp.status_code == 200
            assert resp.json == []

            # E. Test Portfolio History
            resp = client.get("/api/v1/portfolio/history?account_id=paper")
            assert resp.status_code == 200
            history_data = resp.json
            assert len(history_data) >= 1
            assert history_data[0]["equity"] == 10000.0
            assert history_data[0]["cash"] == 10000.0
    finally:
        # Restore original is_active
        SqliteStorageEngine.is_active = original_is_active
