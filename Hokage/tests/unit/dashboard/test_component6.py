from __future__ import annotations

import json
from pathlib import Path

from hokage.dashboard.api import create_dashboard_api
from hokage.memory.resolver import PathResolver
from hokage.orchestrator.learning_engine import (
    PredictionCalibrationEngine,
    LearningCategory,
    LearningEngine,
    MemoryGraph,
    NodeType,
    StrategyEvolution,
    StrategyVersionStatus,
)
from shared.persistence.sqlite_engine import SqliteStorageEngine


def test_component6_learning_and_evolution(tmp_path: Path) -> None:
    # Bypass pytest sqlite safeguard
    original_is_active = SqliteStorageEngine.is_active
    SqliteStorageEngine.is_active = staticmethod(lambda resolver: True)

    try:
        brain_root = tmp_path / "comp6_brain"
        app = create_dashboard_api(brain_root=brain_root)
        resolver = PathResolver(brain_root=brain_root)
        
        db = SqliteStorageEngine(resolver)
        db.run_migrations()

        le = LearningEngine(db)
        mg = MemoryGraph(db)
        se = StrategyEvolution(db)
        ce = PredictionCalibrationEngine(db)

        # 1. Test Python Classes Directly
        # A. LearningEngine lessons
        lesson = le.record_lesson(
            source_type="TRADE",
            source_id="trade_123",
            lesson="Avoid trading low liquidity assets during market open",
            category=LearningCategory.RISK_MANAGEMENT.value,
            impact_score=0.8,
            confidence=0.9,
            tags=["liquidity", "open"],
        )
        assert lesson["source_id"] == "trade_123"
        lessons = le.get_lessons()
        assert len(lessons) == 1
        assert lessons[0]["category"] == LearningCategory.RISK_MANAGEMENT.value

        # B. LearningEngine improvements
        imp = le.add_improvement(
            title="Update Risk Weights",
            description="Lessen max weight of high-beta tech assets",
            category=LearningCategory.RISK_MANAGEMENT.value,
            estimated_impact=0.04,
            difficulty="EASY",
            source="Lesson #1",
        )
        assert imp["status"] == "PENDING"
        ok = le.action_improvement(imp["improvement_id"], "APPROVED", "Commander", "Looks good")
        assert ok is True
        imps = le.get_improvement_queue(status="APPROVED")
        assert len(imps) == 1
        assert imps[0]["reviewer"] == "Commander"

        # C. LearningEngine performance snapshots
        snap = le.record_performance_snapshot(
            bot_name="research_bot",
            metrics={"accuracy": 0.85, "latency_ms": 120.0, "success_rate": 0.95, "error_rate": 0.05},
        )
        assert snap["bot_name"] == "research_bot"
        assert snap["accuracy"] == 0.85

        # D. MemoryGraph nodes & edges
        n1 = mg.add_node(
            node_type=NodeType.TRADE.value,
            label="Long AAPL",
            summary="Bought breakout",
            importance=0.7,
            metadata={"price": 175.0},
        )
        n2 = mg.add_node(
            node_type=NodeType.LESSON.value,
            label="Patience lesson",
            summary="AAPL lesson",
            importance=0.8,
            metadata={},
        )
        edge = mg.add_edge(
            source_node_id=n1["node_id"],
            target_node_id=n2["node_id"],
            relationship="PRODUCED",
            weight=0.9,
        )
        assert edge["relationship"] == "PRODUCED"
        graph = mg.get_graph()
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1

        # E. StrategyEvolution
        sv = se.create_version(
            strategy_id="strat_trend",
            name="Trend Follower v2",
            description="Added MACD filter",
            parameters={"macd_fast": 12, "macd_slow": 26},
            backtest_metrics={"sharpe": 1.45},
        )
        assert sv["version_number"] == 1
        assert sv["status"] == "DRAFT"
        
        se.promote_version(sv["version_id"])
        history = se.get_version_history("strat_trend")
        assert history[0]["status"] == "ACTIVE"

        # F. CalibrationEngine
        pred = ce.record_prediction(
            model_name="alpha_predictor",
            prediction_type="price_direction",
            predicted_value=1.0,
            actual_value=1.2,
            context={"market": "BTC/USD"},
        )
        assert pred["error"] == 1.2 - 1.0

        # 2. Test REST API Endpoints
        with app.test_client() as client:
            # A. Get Memory Graph
            resp = client.get("/api/v1/memory/graph")
            assert resp.status_code == 200
            assert "nodes" in resp.json

            # B. Get Learning History
            resp = client.get("/api/v1/learning/history")
            assert resp.status_code == 200
            assert len(resp.json["lessons"]) >= 1

            # C. Get Strategy Evolution
            resp = client.get("/api/v1/strategy/evolution")
            assert resp.status_code == 200
            assert "strategies" in resp.json

            # D. Performance Lab
            resp = client.get("/api/v1/performance/laboratory")
            assert resp.status_code == 200
            assert len(resp.json["snapshots"]) >= 1

            # E. AI Coach recommendations
            resp = client.get("/api/v1/coach")
            assert resp.status_code == 200
            assert "recommendations" in resp.json
            assert len(resp.json["recommendations"]) >= 2

            # F. Calibration stats
            resp = client.get("/api/v1/calibration")
            assert resp.status_code == 200
            assert "stats" in resp.json

            # G. Improvements queue
            resp = client.get("/api/v1/improvements")
            assert resp.status_code == 200
            assert len(resp.json["improvements"]) >= 1

            # H. Action an improvement via API
            resp = client.post(
                f"/api/v1/improvements/{imp['improvement_id']}/reject",
                json={"reviewer": "Commander", "notes": "No longer needed"},
            )
            assert resp.status_code == 200
            assert resp.json["success"] is True

    finally:
        SqliteStorageEngine.is_active = original_is_active
