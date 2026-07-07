from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from hokage.dashboard.event_bus import EventBus
from shared.persistence.sqlite_engine import SqliteStorageEngine


class MissionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SCHEDULED = "SCHEDULED"


class MissionStage(str, Enum):
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    MACRO_ANALYSIS = "MACRO_ANALYSIS"
    UNIVERSE_SCAN = "UNIVERSE_SCAN"
    STRATEGY_COMMITTEE = "STRATEGY_COMMITTEE"
    INVESTMENT_COMMITTEE = "INVESTMENT_COMMITTEE"
    RISK_COMMITTEE = "RISK_COMMITTEE"
    EXECUTION = "EXECUTION"
    PORTFOLIO_UPDATE = "PORTFOLIO_UPDATE"
    SHADOW_ANALYTICS = "SHADOW_ANALYTICS"
    LEARNING = "LEARNING"
    CUSTOM = "CUSTOM"


class TriggerType(str, Enum):
    MANUAL = "MANUAL"
    CRON_DAILY = "CRON_DAILY"
    CRON_WEEKLY = "CRON_WEEKLY"
    MARKET_OPEN = "MARKET_OPEN"
    MARKET_CLOSE = "MARKET_CLOSE"
    EVENT_BASED = "EVENT_BASED"
    DEPENDENCY = "DEPENDENCY"


class MissionControl:
    """Manages long-running autonomous missions and their execution tracking."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def create_mission(
        self,
        name: str,
        objective: str,
        description: str,
        priority: int,
        trigger_type: str,
        assigned_bots: list[str],
        tags: list[str],
        template_id: str | None = None,
    ) -> dict[str, Any]:
        mission_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        status = MissionStatus.PENDING.value
        progress_pct = 0.0

        meta = {}
        if template_id:
            meta["template_id"] = template_id

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO missions (
                mission_id, name, objective, description, status,
                priority, trigger_type, assigned_bots, tags,
                current_stage, progress_pct, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                name,
                objective,
                description,
                status,
                priority,
                trigger_type,
                json.dumps(assigned_bots),
                json.dumps(tags),
                MissionStage.MARKET_INTELLIGENCE.value,
                progress_pct,
                now,
                now,
                json.dumps(meta),
            ),
        )
        conn.commit()

        mission = {
            "mission_id": mission_id,
            "template_id": template_id,
            "name": name,
            "objective": objective,
            "description": description,
            "status": status,
            "current_stage": MissionStage.MARKET_INTELLIGENCE.value,
            "progress_pct": progress_pct,
            "priority": priority,
            "trigger_type": trigger_type,
            "assigned_bots": assigned_bots,
            "tags": tags,
            "created_at": now,
            "updated_at": now,
        }

        self.event_bus.publish("MISSION_CREATED", mission)
        self.log_event(
            mission_id=mission_id,
            event_type="CREATED",
            message=f"Mission '{name}' initialized.",
            stage=MissionStage.MARKET_INTELLIGENCE.value,
        )
        return mission

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if not row:
            return None
        
        m = dict(row)
        m["assigned_bots"] = json.loads(m["assigned_bots"] or "[]")
        m["tags"] = json.loads(m["tags"] or "[]")
        
        meta = json.loads(m.get("metadata") or "{}")
        m["template_id"] = meta.get("template_id")
        return m

    def list_missions(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if status:
            rows = conn.execute(
                "SELECT * FROM missions WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM missions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

        results = []
        for r in rows:
            m = dict(r)
            m["assigned_bots"] = json.loads(m["assigned_bots"] or "[]")
            m["tags"] = json.loads(m["tags"] or "[]")
            meta = json.loads(m.get("metadata") or "{}")
            m["template_id"] = meta.get("template_id")
            results.append(m)
        return results

    def update_mission_status(
        self,
        mission_id: str,
        status: MissionStatus,
        stage: MissionStage | None = None,
        progress_pct: float | None = None,
        message: str = "",
    ) -> bool:
        mission = self.get_mission(mission_id)
        if not mission:
            return False

        now = datetime.now(timezone.utc).isoformat()
        updates = {"updated_at": now, "status": status.value}
        
        if stage:
            updates["current_stage"] = stage.value
        if progress_pct is not None:
            updates["progress_pct"] = progress_pct

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        params = list(updates.values()) + [mission_id]

        conn = self.db.get_connection()
        conn.execute(f"UPDATE missions SET {set_clause} WHERE mission_id = ?", params)
        
        if status == MissionStatus.COMPLETED:
            conn.execute(
                "UPDATE missions SET completed_at = ? WHERE mission_id = ?",
                (now, mission_id),
            )
        conn.commit()

        # Publish SSE Event
        event_type = f"MISSION_{status.value}"
        self.event_bus.publish(
            event_type,
            {
                "mission_id": mission_id,
                "mission_name": mission["name"],
                "status": status.value,
                "stage": stage.value if stage else mission["current_stage"],
                "progress_pct": progress_pct if progress_pct is not None else mission["progress_pct"],
                "message": message,
            },
        )

        self.log_event(
            mission_id=mission_id,
            event_type=status.value,
            message=message or f"Mission status updated to {status.value}.",
            stage=stage.value if stage else mission["current_stage"],
        )
        return True

    def log_event(
        self,
        mission_id: str,
        event_type: str,
        message: str,
        stage: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO mission_events (
                event_id, mission_id, stage, event_type, message, data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                mission_id,
                stage,
                event_type,
                message,
                json.dumps(data) if data else '{}',
                now,
            ),
        )
        conn.commit()

    def delete_mission(self, mission_id: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.execute("DELETE FROM missions WHERE mission_id = ?", (mission_id,))
        conn.commit()
        return cursor.rowcount > 0

    def get_kpis(self) -> dict[str, Any]:
        conn = self.db.get_connection()
        
        total = conn.execute("SELECT COUNT(*) FROM missions").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status IN ('RUNNING', 'PENDING', 'PAUSED')"
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'COMPLETED'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'FAILED'"
        ).fetchone()[0]

        success_rate = 0.0
        if completed + failed > 0:
            success_rate = (completed / (completed + failed)) * 100.0

        # Calculate average completion time in seconds
        durations = conn.execute(
            """
            SELECT strftime('%s', completed_at) - strftime('%s', created_at)
            FROM missions 
            WHERE status = 'COMPLETED' AND completed_at IS NOT NULL AND created_at IS NOT NULL
            """
        ).fetchall()

        avg_time = None
        if durations:
            valid_durs = [d[0] for d in durations if d[0] is not None]
            if valid_durs:
                avg_time = sum(valid_durs) / len(valid_durs)

        return {
            "total": total,
            "active": active,
            "completed": completed,
            "failed": failed,
            "success_rate_pct": success_rate,
            "avg_completion_seconds": avg_time,
        }

    def get_history(self, mission_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if mission_id:
            rows = conn.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY timestamp DESC LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mission_events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

        results = []
        for r in rows:
            ev = dict(r)
            ev["data"] = json.loads(ev["data"]) if ev["data"] else None
            results.append(ev)
        return results


class MissionScheduler:
    """Schedules autonomous missions to execute based on time or events."""

    def __init__(self, mission_control: MissionControl) -> None:
        self.mission_control = mission_control
        self.db = mission_control.db

    def schedule_mission(
        self,
        mission_id: str,
        trigger_type: TriggerType,
        cron_expr: str | None = None,
        scheduled_at: str | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        
        # Get priority of the mission
        mission = self.mission_control.get_mission(mission_id)
        priority = mission["priority"] if mission else 1

        conn.execute(
            """
            INSERT INTO mission_queue (
                mission_id, priority, scheduled_at, enqueued_at
            ) VALUES (?, ?, ?, ?)
            """,
            (mission_id, priority, scheduled_at or now, now),
        )
        
        conn.execute(
            "UPDATE missions SET status = ? WHERE mission_id = ?",
            (MissionStatus.SCHEDULED.value, mission_id),
        )
        conn.commit()
        return True

    def get_queue(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT mq.*, m.name, m.priority 
            FROM mission_queue mq
            JOIN missions m ON mq.mission_id = m.mission_id
            ORDER BY mq.priority ASC, mq.scheduled_at ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def dequeue_next(self) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            """
            SELECT mq.*, m.name, m.priority 
            FROM mission_queue mq
            JOIN missions m ON mq.mission_id = m.mission_id
            ORDER BY mq.priority ASC, mq.scheduled_at ASC
            LIMIT 1
            """
        ).fetchone()
        
        if not row:
            return None

        dq = dict(row)
        # Delete or update
        conn.execute(
            "DELETE FROM mission_queue WHERE queue_id = ?",
            (dq["queue_id"],),
        )
        conn.commit()
        return dq


class AutonomousPlanner:
    """Generates recommended routine missions for Hokage."""

    def __init__(self, mission_control: MissionControl) -> None:
        self.mission_control = mission_control

    def generate_daily_missions(self) -> list[dict[str, Any]]:
        missions = [
            self.mission_control.create_mission(
                name="Daily Market Intelligence",
                objective="Perform comprehensive market surveillance and news sentiment parsing.",
                description="Aggregates global macro feeds, scans universe for anomalies, and flags key events.",
                priority=1,
                trigger_type=TriggerType.CRON_DAILY.value,
                assigned_bots=["market_intelligence", "research_bot"],
                tags=["daily", "surveillance"],
            ),
            self.mission_control.create_mission(
                name="Portfolio Health Check",
                objective="Evaluate current risk metrics, VaR, and sector allocations.",
                description="Checks active portfolio exposure against governance bounds and runs stress tests.",
                priority=1,
                trigger_type=TriggerType.CRON_DAILY.value,
                assigned_bots=["risk_bot", "portfolio_bot"],
                tags=["daily", "risk"],
            ),
            self.mission_control.create_mission(
                name="Shadow Analytics Review",
                objective="Calibrate shadow models and compare paper vs shadow performance.",
                description="Validates strategy versions currently in dry-run/shadow mode.",
                priority=2,
                trigger_type=TriggerType.CRON_DAILY.value,
                assigned_bots=["shadow_bot", "improvement_bot"],
                tags=["daily", "shadow"],
            ),
        ]
        return missions

    def generate_weekly_missions(self) -> list[dict[str, Any]]:
        missions = [
            self.mission_control.create_mission(
                name="Weekly Portfolio Rebalancing",
                objective="Formulate strategy committee decisions and recommend allocations.",
                description="Aggregates weekly performance logs and triggers consensus on portfolio weights.",
                priority=1,
                trigger_type=TriggerType.CRON_WEEKLY.value,
                assigned_bots=["strategy_bot", "portfolio_bot", "risk_bot"],
                tags=["weekly", "rebalance"],
            ),
            self.mission_control.create_mission(
                name="Sector Rotation Analysis",
                objective="Identify shifting capital flows across sectors.",
                description="Macro scans of sector strength and correlation analysis.",
                priority=2,
                trigger_type=TriggerType.CRON_WEEKLY.value,
                assigned_bots=["research_bot", "strategy_bot"],
                tags=["weekly", "macro"],
            ),
        ]
        return missions


class WorkflowEngine:
    """Manages visual multi-step workflow graphs."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db

    def create_workflow(
        self, name: str, description: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any]:
        workflow_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO workflow_definitions (workflow_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (workflow_id, name, description, now, now),
        )

        for node in nodes:
            node_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO workflow_nodes (node_id, workflow_id, node_type, label, position_x, position_y, config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    workflow_id,
                    node["node_type"],
                    node["label"],
                    node.get("position_x", 0.0),
                    node.get("position_y", 0.0),
                    json.dumps(node.get("config", {})),
                ),
            )

        for edge in edges:
            edge_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO workflow_edges (edge_id, workflow_id, source_node_id, target_node_id, condition)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    edge_id,
                    workflow_id,
                    edge["source_node_id"],
                    edge["target_node_id"],
                    edge.get("condition"),
                ),
            )

        conn.commit()
        return {"workflow_id": workflow_id, "name": name, "description": description}

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM workflow_definitions WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        if not row:
            return None

        wf = dict(row)
        node_rows = conn.execute(
            "SELECT * FROM workflow_nodes WHERE workflow_id = ?", (workflow_id,)
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT * FROM workflow_edges WHERE workflow_id = ?", (workflow_id,)
        ).fetchall()

        wf["nodes"] = []
        for nr in node_rows:
            nd = dict(nr)
            nd["config"] = json.loads(nd["config"] or "{}")
            wf["nodes"].append(nd)

        wf["edges"] = [dict(er) for er in edge_rows]
        return wf

    def list_workflows(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute("SELECT * FROM workflow_definitions ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]

    def delete_workflow(self, workflow_id: str) -> bool:
        conn = self.db.get_connection()
        conn.execute("DELETE FROM workflow_edges WHERE workflow_id = ?", (workflow_id,))
        conn.execute("DELETE FROM workflow_nodes WHERE workflow_id = ?", (workflow_id,))
        cursor = conn.execute(
            "DELETE FROM workflow_definitions WHERE workflow_id = ?", (workflow_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def execute_workflow(self, workflow_id: str, mission_id: str) -> bool:
        wf = self.get_workflow(workflow_id)
        if not wf:
            return False

        # Log start of visual workflow execution
        mc = MissionControl(self.db)
        mc.log_event(
            mission_id=mission_id,
            event_type="WORKFLOW_START",
            message=f"Visual workflow '{wf['name']}' execution triggered.",
            data={"workflow_id": workflow_id},
        )
        return True


__all__ = [
    "MissionControl",
    "MissionScheduler",
    "AutonomousPlanner",
    "WorkflowEngine",
    "MissionStatus",
    "MissionStage",
    "TriggerType",
]
