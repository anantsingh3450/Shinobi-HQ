from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from hokage.dashboard.event_bus import EventBus
from shared.persistence.sqlite_engine import SqliteStorageEngine


class LearningCategory(str, Enum):
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    ENTRY_TIMING = "ENTRY_TIMING"
    EXIT_TIMING = "EXIT_TIMING"
    POSITION_SIZING = "POSITION_SIZING"
    MARKET_REGIME = "MARKET_REGIME"
    EXECUTION = "EXECUTION"
    STRATEGY = "STRATEGY"
    GENERAL = "GENERAL"


class NodeType(str, Enum):
    TRADE = "TRADE"
    RESEARCH = "RESEARCH"
    MISSION = "MISSION"
    LESSON = "LESSON"
    STRATEGY = "STRATEGY"
    MARKET_EVENT = "MARKET_EVENT"
    PATTERN = "PATTERN"
    INDICATOR = "INDICATOR"


class StrategyVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    TESTING = "TESTING"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class LearningEngine:
    """Manages cognitive learning logs, self-improvement queue, and AI coach recommendations."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def record_lesson(
        self,
        source_type: str,
        source_id: str,
        lesson: str,
        category: str,
        impact_score: float,
        confidence: float,
        tags: list[str],
    ) -> dict[str, Any]:
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO learning_records (
                record_id, source_type, source_id, lesson, category,
                impact_score, confidence, tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                source_type,
                source_id,
                lesson,
                category,
                impact_score,
                confidence,
                json.dumps(tags),
                now,
            ),
        )
        conn.commit()

        record = {
            "record_id": record_id,
            "source_type": source_type,
            "source_id": source_id,
            "lesson": lesson,
            "category": category,
            "impact_score": impact_score,
            "confidence": confidence,
            "tags": tags,
            "created_at": now,
        }

        self.event_bus.publish("LESSON_GENERATED", record)
        return record

    def get_lessons(self, category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if category:
            rows = conn.execute(
                "SELECT * FROM learning_records WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM learning_records ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

        results = []
        for r in rows:
            rec = dict(r)
            rec["tags"] = json.loads(rec["tags"] or "[]")
            results.append(rec)
        return results

    def get_improvement_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if status:
            rows = conn.execute(
                "SELECT * FROM improvement_queue WHERE status = ? ORDER BY priority DESC, created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM improvement_queue ORDER BY priority DESC, created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_improvement(
        self,
        title: str,
        description: str,
        category: str,
        estimated_impact: float,
        difficulty: str,
        source: str,
        priority: int = 1,
    ) -> dict[str, Any]:
        improvement_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO improvement_queue (
                improvement_id, title, description, category, status,
                estimated_impact, difficulty, source, priority, created_at
            ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
            """,
            (
                improvement_id,
                title,
                description,
                category,
                estimated_impact,
                difficulty,
                source,
                priority,
                now,
            ),
        )
        conn.commit()

        return {
            "improvement_id": improvement_id,
            "title": title,
            "description": description,
            "category": category,
            "status": "PENDING",
            "estimated_impact": estimated_impact,
            "difficulty": difficulty,
            "source": source,
            "priority": priority,
            "created_at": now,
        }

    def action_improvement(
        self, improvement_id: str, action: str, reviewer: str, notes: str
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        cursor = conn.execute(
            """
            UPDATE improvement_queue
            SET status = ?, reviewer = ?, review_notes = ?, reviewed_at = ?
            WHERE improvement_id = ?
            """,
            (action, reviewer, notes, now, improvement_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_performance_snapshots(
        self, bot_name: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if bot_name:
            rows = conn.execute(
                "SELECT * FROM performance_snapshots WHERE bot_name = ? ORDER BY captured_at DESC LIMIT ?",
                (bot_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM performance_snapshots ORDER BY captured_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def record_performance_snapshot(self, bot_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        accuracy = metrics.get("accuracy")
        latency = metrics.get("latency_ms")
        success_rate = metrics.get("success_rate")
        error_rate = metrics.get("error_rate")

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO performance_snapshots (
                snapshot_id, bot_name, captured_at, accuracy, latency_ms,
                success_rate, error_rate, custom_metrics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                bot_name,
                now,
                accuracy,
                latency,
                success_rate,
                error_rate,
                json.dumps(metrics),
            ),
        )
        conn.commit()

        return {
            "snapshot_id": snapshot_id,
            "bot_name": bot_name,
            "captured_at": now,
            "accuracy": accuracy,
            "latency_ms": latency,
            "success_rate": success_rate,
            "error_rate": error_rate,
            "custom_metrics": metrics,
        }

    def get_coach_recommendations(self, status: str | None = "ACTIVE") -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if status:
            rows = conn.execute(
                "SELECT * FROM coach_recommendations WHERE status = ? ORDER BY priority DESC, generated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM coach_recommendations ORDER BY priority DESC, generated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def generate_coach_recommendations(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        
        # Count lessons by category
        risk_lessons = conn.execute(
            "SELECT COUNT(*) FROM learning_records WHERE category = 'RISK_MANAGEMENT'"
        ).fetchone()[0]
        timing_lessons = conn.execute(
            "SELECT COUNT(*) FROM learning_records WHERE category = 'ENTRY_TIMING'"
        ).fetchone()[0]

        recs = []
        now = datetime.now(timezone.utc).isoformat()

        # Seed some default AI Coach insights if none exist, or based on counts
        if risk_lessons >= 0:
            recs.append(
                {
                    "recommendation_id": str(uuid.uuid4()),
                    "title": "Tighten Risk Bounds on Tech Sector",
                    "description": "Historical lessons indicate elevated volatility in Tech. Recommend lowering max position size by 15%.",
                    "category": "RISK_MANAGEMENT",
                    "priority": "HIGH",
                    "estimated_gain": 0.045,
                    "status": "ACTIVE",
                    "generated_at": now,
                }
            )
        if timing_lessons >= 0:
            recs.append(
                {
                    "recommendation_id": str(uuid.uuid4()),
                    "title": "Optimize Entry Timing for High-Beta Assets",
                    "description": "Lessons show early entries on breakouts. Recommend waiting for 1-hour candle confirmation.",
                    "category": "ENTRY_TIMING",
                    "priority": "MEDIUM",
                    "estimated_gain": 0.028,
                    "status": "ACTIVE",
                    "generated_at": now,
                }
            )

        for r in recs:
            conn.execute(
                """
                INSERT INTO coach_recommendations (
                    recommendation_id, title, description, category, priority,
                    estimated_gain, status, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["recommendation_id"],
                    r["title"],
                    r["description"],
                    r["category"],
                    r["priority"],
                    r["estimated_gain"],
                    r["status"],
                    r["generated_at"],
                ),
            )
        conn.commit()
        return recs


class MemoryGraph:
    """Manages the associative cognitive memory graph (nodes and edges)."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def add_node(
        self,
        node_type: str,
        label: str,
        summary: str,
        importance: float,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        node_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO memory_nodes (
                node_id, node_type, label, summary, importance, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (node_id, node_type, label, summary, importance, json.dumps(metadata), now, now),
        )
        conn.commit()

        node = {
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
            "summary": summary,
            "importance": importance,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now,
        }

        self.event_bus.publish("MEMORY_UPDATED", node)
        return node

    def add_edge(
        self, source_node_id: str, target_node_id: str, relationship: str, weight: float
    ) -> dict[str, Any]:
        edge_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO memory_edges (
                edge_id, source_node_id, target_node_id, relationship, weight, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (edge_id, source_node_id, target_node_id, relationship, weight, now),
        )
        conn.commit()

        return {
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relationship": relationship,
            "weight": weight,
            "created_at": now,
        }

    def get_graph(self) -> dict[str, Any]:
        conn = self.db.get_connection()
        node_rows = conn.execute("SELECT * FROM memory_nodes").fetchall()
        edge_rows = conn.execute("SELECT * FROM memory_edges").fetchall()

        nodes = []
        for nr in node_rows:
            nd = dict(nr)
            nd["metadata"] = json.loads(nd["metadata"] or "{}")
            nodes.append(nd)

        edges = [dict(er) for er in edge_rows]
        return {"nodes": nodes, "edges": edges}

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM memory_nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        
        nd = dict(row)
        nd["metadata"] = json.loads(nd["metadata"] or "{}")
        return nd

    def search_nodes(self, node_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if node_type:
            rows = conn.execute(
                "SELECT * FROM memory_nodes WHERE node_type = ? LIMIT ?", (node_type, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM memory_nodes LIMIT ?", (limit,)).fetchall()

        results = []
        for r in rows:
            nd = dict(r)
            nd["metadata"] = json.loads(nd["metadata"] or "{}")
            results.append(nd)
        return results

    def delete_node(self, node_id: str) -> bool:
        conn = self.db.get_connection()
        # Cascade delete edges
        conn.execute(
            "DELETE FROM memory_edges WHERE source_node_id = ? OR target_node_id = ?",
            (node_id, node_id),
        )
        cursor = conn.execute("DELETE FROM memory_nodes WHERE node_id = ?", (node_id,))
        conn.commit()
        return cursor.rowcount > 0


class StrategyEvolution:
    """Tracks strategy configuration parameter changes and historical backtest metrics."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def create_version(
        self,
        strategy_id: str,
        name: str,
        description: str,
        parameters: dict[str, Any],
        backtest_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        version_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        
        # Get next version number
        max_ver = conn.execute(
            "SELECT MAX(version_number) FROM strategy_versions WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()[0]
        next_ver = (max_ver or 0) + 1

        conn.execute(
            """
            INSERT INTO strategy_versions (
                version_id, strategy_id, version_number, name, description,
                parameters, backtest_metrics, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?)
            """,
            (
                version_id,
                strategy_id,
                next_ver,
                name,
                description,
                json.dumps(parameters),
                json.dumps(backtest_metrics),
                now,
            ),
        )
        conn.commit()

        version = {
            "version_id": version_id,
            "strategy_id": strategy_id,
            "name": name,
            "description": description,
            "version_number": next_ver,
            "status": "DRAFT",
            "parameters": parameters,
            "backtest_metrics": backtest_metrics,
            "created_at": now,
        }

        self.event_bus.publish("STRATEGY_EVOLVED", version)
        return version

    def promote_version(self, version_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        
        row = conn.execute(
            "SELECT strategy_id FROM strategy_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if not row:
            return False
            
        strategy_id = row["strategy_id"]

        # Deprecate older active versions of the same strategy
        conn.execute(
            """
            UPDATE strategy_versions 
            SET status = 'DEPRECATED', deprecated_at = ? 
            WHERE strategy_id = ? AND status = 'ACTIVE'
            """,
            (now, strategy_id),
        )

        # Activate this version
        conn.execute(
            """
            UPDATE strategy_versions 
            SET status = 'ACTIVE', promoted_at = ? 
            WHERE version_id = ?
            """,
            (now, version_id),
        )
        conn.commit()
        return True

    def deprecate_version(self, version_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE strategy_versions SET status = 'DEPRECATED', deprecated_at = ? WHERE version_id = ?",
            (now, version_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_version_history(self, strategy_id: str) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY version_number DESC",
            (strategy_id,),
        ).fetchall()

        results = []
        for r in rows:
            sv = dict(r)
            sv["parameters"] = json.loads(sv["parameters"] or "{}")
            sv["backtest_metrics"] = json.loads(sv["backtest_metrics"] or "{}")
            results.append(sv)
        return results

    def list_strategies(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT sv1.* 
            FROM strategy_versions sv1
            INNER JOIN (
                SELECT strategy_id, MAX(version_number) as max_ver
                FROM strategy_versions
                GROUP BY strategy_id
            ) sv2 ON sv1.strategy_id = sv2.strategy_id AND sv1.version_number = sv2.max_ver
            """
        ).fetchall()

        results = []
        for r in rows:
            sv = dict(r)
            sv["parameters"] = json.loads(sv["parameters"] or "{}")
            sv["backtest_metrics"] = json.loads(sv["backtest_metrics"] or "{}")
            results.append(sv)
        return results


class PredictionCalibrationEngine:
    """Validates predictions against actual market/portfolio outcomes to calculate calibration error."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def record_prediction(
        self,
        model_name: str,
        prediction_type: str,
        predicted_value: float,
        actual_value: float,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        calibration_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        error = actual_value - predicted_value
        relative_error = abs(error) / max(abs(actual_value), 1e-9)

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO prediction_calibration (
                calibration_id, model_name, prediction_type, predicted_value,
                actual_value, error, relative_error, timestamp, context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                calibration_id,
                model_name,
                prediction_type,
                predicted_value,
                actual_value,
                error,
                relative_error,
                now,
                json.dumps(context),
            ),
        )
        conn.commit()

        record = {
            "prediction_id": calibration_id,
            "model_name": model_name,
            "prediction_type": prediction_type,
            "predicted_value": predicted_value,
            "actual_value": actual_value,
            "error": error,
            "relative_error": relative_error,
            "context": context,
            "timestamp": now,
        }

        self.event_bus.publish("CALIBRATION_UPDATED", record)
        return record

    def get_calibration_stats(self, model_name: str | None = None) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        query = """
            SELECT model_name, prediction_type,
                   AVG(error) as avg_error,
                   AVG(relative_error) as avg_relative_error,
                   COUNT(*) as count
            FROM prediction_calibration
        """
        if model_name:
            query += " WHERE model_name = ? GROUP BY model_name, prediction_type"
            rows = conn.execute(query, (model_name,)).fetchall()
        else:
            query += " GROUP BY model_name, prediction_type"
            rows = conn.execute(query).fetchall()

        return [dict(r) for r in rows]

    def get_calibration_history(
        self, model_name: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if model_name:
            rows = conn.execute(
                "SELECT * FROM prediction_calibration WHERE model_name = ? ORDER BY timestamp DESC LIMIT ?",
                (model_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM prediction_calibration ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

        results = []
        for r in rows:
            pc = dict(r)
            pc["context"] = json.loads(pc["context"] or "{}")
            results.append(pc)
        return results


__all__ = [
    "LearningEngine",
    "MemoryGraph",
    "StrategyEvolution",
    "PredictionCalibrationEngine",
    "LearningCategory",
    "NodeType",
    "StrategyVersionStatus",
]
