from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from hokage.dashboard.event_bus import EventBus
from shared.persistence.sqlite_engine import SqliteStorageEngine


class AgentRole(str, Enum):
    COMMANDER = "COMMANDER"
    CHIEF_RESEARCH_OFFICER = "CHIEF_RESEARCH_OFFICER"
    CHIEF_STRATEGY_OFFICER = "CHIEF_STRATEGY_OFFICER"
    CHIEF_RISK_OFFICER = "CHIEF_RISK_OFFICER"
    CHIEF_EXECUTION_OFFICER = "CHIEF_EXECUTION_OFFICER"
    CHIEF_PORTFOLIO_OFFICER = "CHIEF_PORTFOLIO_OFFICER"
    CHIEF_LEARNING_OFFICER = "CHIEF_LEARNING_OFFICER"
    CHIEF_INTELLIGENCE_OFFICER = "CHIEF_INTELLIGENCE_OFFICER"


class AgentStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class VotingModel(str, Enum):
    MAJORITY = "MAJORITY"
    WEIGHTED = "WEIGHTED"
    UNANIMOUS = "UNANIMOUS"
    CONSENSUS = "CONSENSUS"


class ConsensusStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class AgentRegistry:
    """Manages agent registration, health, and availability status."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()
        self._seed_default_agents()

    def _seed_default_agents(self) -> None:
        conn = self.db.get_connection()
        count = conn.execute("SELECT COUNT(*) FROM agent_registry").fetchone()[0]
        if count > 0:
            return

        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            (
                "agent_commander",
                AgentRole.COMMANDER.value,
                "Voice Commander",
                AgentStatus.IDLE.value,
                json.dumps(["voice_control", "override"]),
            ),
            (
                "agent_researcher",
                AgentRole.CHIEF_RESEARCH_OFFICER.value,
                "Jiraiya",
                AgentStatus.IDLE.value,
                json.dumps(["market_research", "nlp_sentiment"]),
            ),
            (
                "agent_strategist",
                AgentRole.CHIEF_STRATEGY_OFFICER.value,
                "Shikamaru",
                AgentStatus.IDLE.value,
                json.dumps(["signal_generation", "alpha_modeling"]),
            ),
            (
                "agent_risk",
                AgentRole.CHIEF_RISK_OFFICER.value,
                "Kakashi",
                AgentStatus.IDLE.value,
                json.dumps(["exposure_check", "stress_test"]),
            ),
            (
                "agent_executor",
                AgentRole.CHIEF_EXECUTION_OFFICER.value,
                "Minato",
                AgentStatus.IDLE.value,
                json.dumps(["order_routing", "slippage_mgmt"]),
            ),
            (
                "agent_portfolio",
                AgentRole.CHIEF_PORTFOLIO_OFFICER.value,
                "Tsunade",
                AgentStatus.IDLE.value,
                json.dumps(["rebalancing", "pnl_attribution"]),
            ),
            (
                "agent_learner",
                AgentRole.CHIEF_LEARNING_OFFICER.value,
                "Might Guy",
                AgentStatus.IDLE.value,
                json.dumps(["model_calibration", "strategy_evolution"]),
            ),
            (
                "agent_intelligence",
                AgentRole.CHIEF_INTELLIGENCE_OFFICER.value,
                "Neji",
                AgentStatus.IDLE.value,
                json.dumps(["universe_scanning", "macro_analysis"]),
            ),
        ]

        for aid, role, name, status, caps in defaults:
            conn.execute(
                """
                INSERT INTO agent_registry (
                    agent_id, role, name, status, capabilities, health_score, workload, last_heartbeat, created_at
                ) VALUES (?, ?, ?, ?, ?, 1.0, 0, ?, ?)
                """,
                (aid, role, name, status, caps, now, now),
            )
        conn.commit()

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM agent_registry WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_agents(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute("SELECT * FROM agent_registry").fetchall()
        return [dict(r) for r in rows]

    def update_agent_status(
        self, agent_id: str, status: AgentStatus, workload: int | None = None
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        
        if workload is not None:
            conn.execute(
                """
                UPDATE agent_registry 
                SET status = ?, workload = ?, last_heartbeat = ? 
                WHERE agent_id = ?
                """,
                (status.value, workload, now, agent_id),
            )
        else:
            conn.execute(
                """
                UPDATE agent_registry 
                SET status = ?, last_heartbeat = ? 
                WHERE agent_id = ?
                """,
                (status.value, now, agent_id),
            )
            
        conn.commit()

        agent = self.get_agent(agent_id)
        if agent:
            self.event_bus.publish("AGENT_REGISTERED", agent)
            return True
        return False

    def update_agent_heartbeat(self, agent_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE agent_registry SET last_heartbeat = ? WHERE agent_id = ?", (now, agent_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_available_agents(self, capability: str | None = None) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM agent_registry WHERE status IN ('IDLE', 'RUNNING')"
        ).fetchall()
        
        agents = []
        for r in rows:
            a = dict(r)
            caps = json.loads(a["capabilities"] or "[]")
            if capability is None or capability in caps:
                agents.append(a)
        return agents


class DelegationEngine:
    """Orchestrates work assignments to specialist bots."""

    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self.db = registry.db
        self.event_bus = EventBus()

    def assign_task(
        self, task_description: str, required_capability: str, priority: int = 1
    ) -> dict[str, Any] | None:
        available = self.registry.get_available_agents(capability=required_capability)
        if not available:
            return None

        # Sort by workload ascending to balance load
        available.sort(key=lambda a: a["workload"] or 0)
        chosen = available[0]

        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Update workload
        new_workload = (chosen["workload"] or 0) + 1
        self.registry.update_agent_status(
            chosen["agent_id"], AgentStatus.RUNNING, workload=new_workload
        )

        assignment = {
            "task_id": task_id,
            "agent_id": chosen["agent_id"],
            "agent_name": chosen["name"],
            "task_description": task_description,
            "priority": priority,
            "assigned_at": now,
        }

        self.event_bus.publish("TASK_ASSIGNED", assignment)
        return assignment

    def complete_task(self, agent_id: str, task_id: str, success: bool = True) -> bool:
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return False

        # Decrement workload
        new_workload = max(0, (agent["workload"] or 0) - 1)
        next_status = AgentStatus.IDLE if new_workload == 0 else AgentStatus.RUNNING
        self.registry.update_agent_status(agent_id, next_status, workload=new_workload)

        event_type = "TASK_COMPLETED" if success else "TASK_FAILED"
        self.event_bus.publish(
            event_type, {"task_id": task_id, "agent_id": agent_id, "success": success}
        )
        return True

    def get_workload_summary(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT name, role, workload, status FROM agent_registry ORDER BY workload DESC"
        ).fetchall()
        return [dict(r) for r in rows]


class AgentCommunicationBus:
    """Message passing channel between autonomous agents."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db

    def send_message(
        self,
        sender_agent_id: str,
        recipient_agent_id: str | None,
        message_type: str,
        subject: str,
        body: str,
        priority: int = 1,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO agent_messages (
                message_id, sender_agent_id, recipient_agent_id, message_type,
                subject, body, priority, status, reply_to_message_id, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'UNREAD', ?, ?)
            """,
            (
                message_id,
                sender_agent_id,
                recipient_agent_id,
                message_type,
                subject,
                body,
                priority,
                reply_to,
                now,
            ),
        )
        conn.commit()

        return {
            "message_id": message_id,
            "sender_agent_id": sender_agent_id,
            "recipient_agent_id": recipient_agent_id,
            "message_type": message_type,
            "subject": subject,
            "body": body,
            "priority": priority,
            "status": "UNREAD",
            "reply_to_message_id": reply_to,
            "sent_at": now,
        }

    def get_messages(self, agent_id: str, unread_only: bool = False) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if unread_only:
            rows = conn.execute(
                """
                SELECT * FROM agent_messages 
                WHERE (recipient_agent_id = ? OR recipient_agent_id IS NULL) AND status = 'UNREAD'
                ORDER BY sent_at DESC
                """,
                (agent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM agent_messages 
                WHERE recipient_agent_id = ? OR recipient_agent_id IS NULL
                ORDER BY sent_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, message_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE agent_messages SET status = 'READ', read_at = ? WHERE message_id = ?",
            (now, message_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def broadcast(self, sender_agent_id: str, message_type: str, subject: str, body: str) -> dict[str, Any]:
        return self.send_message(
            sender_agent_id=sender_agent_id,
            recipient_agent_id=None,
            message_type=message_type,
            subject=subject,
            body=body,
        )


class GovernanceEngine:
    """Enforces policy constraints and seeds default governance rules."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self._seed_default_policies()

    def _seed_default_policies(self) -> None:
        conn = self.db.get_connection()
        count = conn.execute("SELECT COUNT(*) FROM governance_policies").fetchone()[0]
        if count > 0:
            return

        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            (
                "MAX_POSITION_SIZE",
                "Maximum allocation size per asset as a percentage of total portfolio.",
                "RISK",
                json.dumps({"max_pct": 0.15}),
            ),
            (
                "DAILY_LOSS_LIMIT",
                "Maximum allowed drawdown in a single trading day.",
                "RISK",
                json.dumps({"max_drawdown_pct": 0.05}),
            ),
            (
                "CONSENSUS_REQUIRED_FOR_LIVE",
                "Consensus model required before transitioning paper to live.",
                "TRADING",
                json.dumps({"required_votes": 3}),
            ),
            (
                "MAX_CONCURRENT_MISSIONS",
                "Limit the number of simultaneous active missions.",
                "OPERATIONS",
                json.dumps({"limit": 5}),
            ),
            (
                "EMERGENCY_STOP_THRESHOLD",
                "Max consecutive error counts before triggering system pause.",
                "SAFETY",
                json.dumps({"max_errors": 3}),
            ),
        ]

        for name, desc, cat, params in defaults:
            policy_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO governance_policies (
                    policy_id, name, description, category, is_active, parameters, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (policy_id, name, desc, cat, params, now, now),
            )
        conn.commit()

    def list_policies(self) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute("SELECT * FROM governance_policies").fetchall()
        return [dict(r) for r in rows]

    def get_policy(self, policy_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM governance_policies WHERE policy_id = ?", (policy_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_policy(
        self, policy_id: str, is_active: bool | None = None, parameters: dict[str, Any] | None = None
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        updates = {"updated_at": now}
        
        if is_active is not None:
            updates["is_active"] = 1 if is_active else 0
        if parameters is not None:
            updates["parameters"] = json.dumps(parameters)

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        params = list(updates.values()) + [policy_id]

        conn = self.db.get_connection()
        cursor = conn.execute(
            f"UPDATE governance_policies SET {set_clause} WHERE policy_id = ?", params
        )
        conn.commit()
        return cursor.rowcount > 0

    def create_policy(
        self, name: str, description: str, category: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        policy_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO governance_policies (
                policy_id, name, description, category, is_active, parameters, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (policy_id, name, description, category, json.dumps(parameters), now, now),
        )
        conn.commit()

        return {
            "policy_id": policy_id,
            "name": name,
            "description": description,
            "category": category,
            "is_active": True,
            "parameters": parameters,
            "created_at": now,
            "updated_at": now,
        }

    def enforce_check(self, policy_name: str, check_value: float) -> tuple[bool, str]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM governance_policies WHERE name = ? AND is_active = 1", (policy_name,)
        ).fetchone()
        if not row:
            return True, f"Policy '{policy_name}' not found or inactive."

        params = json.loads(row["parameters"] or "{}")

        if policy_name == "MAX_POSITION_SIZE":
            max_pct = params.get("max_pct", 0.15)
            if check_value > max_pct:
                return False, f"Value {check_value} exceeds max position limit of {max_pct}."
        elif policy_name == "DAILY_LOSS_LIMIT":
            max_drawdown = params.get("max_drawdown_pct", 0.05)
            if check_value > max_drawdown:
                return False, f"Drawdown {check_value} exceeds daily limit of {max_drawdown}."
        elif policy_name == "MAX_CONCURRENT_MISSIONS":
            limit = params.get("limit", 5)
            if check_value > limit:
                return False, f"Active missions count {check_value} exceeds limit of {limit}."
        elif policy_name == "EMERGENCY_STOP_THRESHOLD":
            max_errors = params.get("max_errors", 3)
            if check_value >= max_errors:
                return False, f"Errors count {check_value} reached emergency threshold of {max_errors}."

        return True, "Policy check passed."


class ConsensusEngine:
    """Enforces decentralized consensus decisions across specialist bots."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def start_consensus(
        self, topic: str, description: str, voting_model: VotingModel, threshold: float = 0.51
    ) -> dict[str, Any]:
        consensus_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO consensus_records (
                consensus_id, topic, description, voting_model, status, votes, threshold, created_at
            ) VALUES (?, ?, ?, ?, 'OPEN', '{}', ?, ?)
            """,
            (consensus_id, topic, description, voting_model.value, threshold, now),
        )
        conn.commit()

        return {
            "consensus_id": consensus_id,
            "topic": topic,
            "description": description,
            "voting_model": voting_model.value,
            "threshold": threshold,
            "status": "OPEN",
            "votes": {},
            "created_at": now,
        }

    def cast_vote(
        self, consensus_id: str, agent_id: str, vote: str, rationale: str = ""
    ) -> bool:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT votes, status FROM consensus_records WHERE consensus_id = ?", (consensus_id,)
        ).fetchone()
        if not row or row["status"] != "OPEN":
            return False

        votes = json.loads(row["votes"] or "{}")
        votes[agent_id] = {"vote": vote, "rationale": rationale, "timestamp": datetime.now(timezone.utc).isoformat()}

        conn.execute(
            "UPDATE consensus_records SET votes = ? WHERE consensus_id = ?",
            (json.dumps(votes), consensus_id),
        )
        conn.commit()

        self._check_consensus(consensus_id)
        return True

    def _check_consensus(self, consensus_id: str) -> bool:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM consensus_records WHERE consensus_id = ?", (consensus_id,)
        ).fetchone()
        if not row or row["status"] != "OPEN":
            return False

        votes = json.loads(row["votes"] or "{}")
        voting_model = row["voting_model"]
        threshold = row["threshold"]

        # Number of active bots to vote
        total_voters = 8  
        votes_cast = len(votes)

        if votes_cast < 3:  # Wait for at least 3 votes
            return False

        yes_votes = sum(1 for v in votes.values() if v["vote"] == "YES")
        no_votes = sum(1 for v in votes.values() if v["vote"] == "NO")

        resolved = False
        result = None

        if voting_model == VotingModel.MAJORITY.value:
            if yes_votes / votes_cast >= threshold:
                resolved = True
                result = "YES"
            elif no_votes / votes_cast >= threshold:
                resolved = True
                result = "NO"
        elif voting_model == VotingModel.UNANIMOUS.value:
            if yes_votes == total_voters:
                resolved = True
                result = "YES"
            elif no_votes > 0:
                resolved = True
                result = "NO"

        if resolved:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE consensus_records 
                SET status = 'RESOLVED', result = ?, resolved_at = ?
                WHERE consensus_id = ?
                """,
                (result, now, consensus_id),
            )
            conn.commit()
            self.event_bus.publish(
                "CONSENSUS_REACHED",
                {"consensus_id": consensus_id, "topic": row["topic"], "result": result},
            )
            return True

        return False

    def get_consensus_records(self, status: str | None = None) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        if status:
            rows = conn.execute(
                "SELECT * FROM consensus_records WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM consensus_records ORDER BY created_at DESC").fetchall()

        results = []
        for r in rows:
            rec = dict(r)
            rec["votes"] = json.loads(rec["votes"] or "{}")
            results.append(rec)
        return results


class ResourceManager:
    """Monitors system CPU, memory, and API limits."""

    def __init__(self, db: SqliteStorageEngine) -> None:
        self.db = db
        self.event_bus = EventBus()

    def record_snapshot(self) -> dict[str, Any]:
        metric_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Fallback values
        cpu_pct = 15.0
        ram_mb = 1200.0

        try:
            import psutil
            cpu_pct = psutil.cpu_percent()
            ram_mb = psutil.virtual_memory().used / (1024 * 1024)
        except ImportError:
            pass

        # Increment tokens and API calls from previous or use mock values
        conn = self.db.get_connection()
        prev = conn.execute(
            "SELECT llm_tokens_used, api_calls_used FROM resource_metrics ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()

        tokens_used = (prev["llm_tokens_used"] if prev else 150000) + 1200
        api_used = (prev["api_calls_used"] if prev else 2400) + 5

        # Cap or reset occasionally
        if tokens_used > 1000000:
            tokens_used = 1200
        if api_used > 10000:
            api_used = 5

        conn.execute(
            """
            INSERT INTO resource_metrics (
                captured_at, cpu_pct, ram_mb, llm_tokens_used,
                llm_tokens_limit, api_calls_used, api_calls_limit
            ) VALUES (?, ?, ?, ?, 1000000, ?, 10000)
            """,
            (now, cpu_pct, ram_mb, tokens_used, api_used),
        )
        conn.commit()

        if cpu_pct > 80.0:
            self.event_bus.publish(
                "RESOURCE_WARNING", {"message": f"High CPU utilization: {cpu_pct:.1f}%"}
            )
        if ram_mb > 4096.0:
            self.event_bus.publish(
                "RESOURCE_WARNING", {"message": f"High RAM usage: {ram_mb:.1f} MB"}
            )

        return {
            "metric_id": metric_id,
            "timestamp": now,
            "cpu_pct": cpu_pct,
            "ram_mb": ram_mb,
            "llm_tokens_used": tokens_used,
            "llm_tokens_limit": 1000000,
            "api_calls_used": api_used,
            "api_calls_limit": 10000,
        }

    def get_latest(self) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM resource_metrics ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM resource_metrics ORDER BY captured_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self) -> dict[str, Any]:
        latest = self.get_latest()
        if not latest:
            latest = self.record_snapshot()
        return latest


__all__ = [
    "AgentRegistry",
    "DelegationEngine",
    "AgentCommunicationBus",
    "GovernanceEngine",
    "ConsensusEngine",
    "ResourceManager",
    "AgentRole",
    "AgentStatus",
    "VotingModel",
    "ConsensusStatus",
]
