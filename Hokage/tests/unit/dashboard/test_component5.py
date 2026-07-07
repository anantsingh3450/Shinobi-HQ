from __future__ import annotations

import json
from pathlib import Path

from hokage.dashboard.api import create_dashboard_api
from hokage.memory.resolver import PathResolver
from hokage.orchestrator.mission_control import (
    AutonomousPlanner,
    MissionControl,
    MissionScheduler,
    MissionStatus,
    TriggerType,
    WorkflowEngine,
)
from shared.persistence.sqlite_engine import SqliteStorageEngine


def test_component5_mission_control_and_workflows(tmp_path: Path) -> None:
    # Bypass pytest sqlite safeguard
    original_is_active = SqliteStorageEngine.is_active
    SqliteStorageEngine.is_active = staticmethod(lambda resolver: True)

    try:
        brain_root = tmp_path / "comp5_brain"
        app = create_dashboard_api(brain_root=brain_root)
        resolver = PathResolver(brain_root=brain_root)
        
        db = SqliteStorageEngine(resolver)
        db.run_migrations()

        mc = MissionControl(db)
        scheduler = MissionScheduler(mc)
        planner = AutonomousPlanner(mc)
        we = WorkflowEngine(db)

        # 1. Test Python Classes Directly
        # A. Create a mission
        m = mc.create_mission(
            name="Test Mission",
            objective="Verify MC works",
            description="Direct creation test",
            priority=1,
            trigger_type=TriggerType.MANUAL.value,
            assigned_bots=["research_bot"],
            tags=["test"],
        )
        assert m["name"] == "Test Mission"
        assert m["status"] == MissionStatus.PENDING.value
        
        # B. Get mission
        retrieved = mc.get_mission(m["mission_id"])
        assert retrieved is not None
        assert retrieved["name"] == "Test Mission"
        assert "research_bot" in retrieved["assigned_bots"]

        # C. Update status
        ok = mc.update_mission_status(
            m["mission_id"],
            MissionStatus.RUNNING,
            progress_pct=25.0,
            message="Moving along",
        )
        assert ok is True
        updated = mc.get_mission(m["mission_id"])
        assert updated["status"] == MissionStatus.RUNNING.value
        assert updated["progress_pct"] == 25.0

        # D. Log event
        mc.log_event(m["mission_id"], "INFO", "Custom progress log")
        history = mc.get_history(m["mission_id"])
        assert len(history) >= 3  # Created, RUNNING, INFO

        # E. Scheduler
        scheduler.schedule_mission(m["mission_id"], TriggerType.CRON_DAILY)
        queue = scheduler.get_queue()
        assert len(queue) >= 1
        dq = scheduler.dequeue_next()
        assert dq is not None
        assert dq["mission_id"] == m["mission_id"]

        # F. AutonomousPlanner
        daily_missions = planner.generate_daily_missions()
        assert len(daily_missions) == 3
        weekly_missions = planner.generate_weekly_missions()
        assert len(weekly_missions) == 2

        # G. WorkflowEngine
        wf = we.create_workflow(
            name="Visual Alpha Workflow",
            description="Macro to Execution",
            nodes=[
                {"node_type": "MARKET_INTELLIGENCE", "label": "Surveillance", "position_x": 100, "position_y": 100},
                {"node_type": "STRATEGY", "label": "Signal Gen", "position_x": 300, "position_y": 100},
            ],
            edges=[
                {"source_node_id": "Surveillance", "target_node_id": "Signal Gen"},
            ],
        )
        assert wf["name"] == "Visual Alpha Workflow"
        wf_details = we.get_workflow(wf["workflow_id"])
        assert len(wf_details["nodes"]) == 2
        assert len(wf_details["edges"]) == 1

        # 2. Test REST API Endpoints via client
        with app.test_client() as client:
            # A. List missions
            resp = client.get("/api/v1/missions")
            assert resp.status_code == 200
            assert "missions" in resp.json
            assert len(resp.json["missions"]) >= 6  # Created + Daily + Weekly

            # B. Create mission via REST
            resp = client.post(
                "/api/v1/missions",
                json={
                    "name": "API Mission",
                    "objective": "API Test",
                    "description": "Via Client",
                    "priority": 2,
                    "trigger_type": "MANUAL",
                },
            )
            assert resp.status_code == 201
            api_mission_id = resp.json["mission_id"]

            # C. Update mission via REST
            resp = client.patch(
                f"/api/v1/missions/{api_mission_id}",
                json={"status": "COMPLETED", "progress_pct": 100.0, "message": "Done!"},
            )
            assert resp.status_code == 200
            assert resp.json["success"] is True

            # D. Delete mission via REST
            resp = client.delete(f"/api/v1/missions/{api_mission_id}")
            assert resp.status_code == 200
            assert resp.json["success"] is True

            # E. Get KPIs
            resp = client.get("/api/v1/missions/kpis")
            assert resp.status_code == 200
            assert "success_rate_pct" in resp.json

            # F. List Workflows
            resp = client.get("/api/v1/workflows")
            assert resp.status_code == 200
            assert len(resp.json["workflows"]) >= 1

            # G. Create Workflow via REST
            resp = client.post(
                "/api/v1/workflows",
                json={
                    "name": "API Workflow",
                    "description": "Created via API",
                    "nodes": [],
                    "edges": [],
                },
            )
            assert resp.status_code == 201
            api_wf_id = resp.json["workflow_id"]

            # H. Get Workflow via REST
            resp = client.get(f"/api/v1/workflows/{api_wf_id}")
            assert resp.status_code == 200
            assert resp.json["name"] == "API Workflow"

    finally:
        SqliteStorageEngine.is_active = original_is_active
