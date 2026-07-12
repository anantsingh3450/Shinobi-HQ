from __future__ import annotations

from pathlib import Path

from hokage.dashboard.api import create_dashboard_api
from hokage.memory.resolver import PathResolver
from hokage.orchestrator.governance import (
    AgentCommunicationBus,
    AgentRegistry,
    AgentStatus,
    ConsensusEngine,
    DelegationEngine,
    GovernanceEngine,
    ResourceManager,
    VotingModel,
)
from shared.persistence.sqlite_engine import SqliteStorageEngine


def test_component7_governance_and_collaboration(tmp_path: Path) -> None:
    # Bypass pytest sqlite safeguard
    original_is_active = SqliteStorageEngine.is_active
    SqliteStorageEngine.is_active = staticmethod(lambda resolver: True)

    try:
        brain_root = tmp_path / "comp7_brain"
        app = create_dashboard_api(brain_root=brain_root)
        resolver = PathResolver(brain_root=brain_root)
        
        db = SqliteStorageEngine(resolver)
        db.run_migrations()

        reg = AgentRegistry(db)
        delegation = DelegationEngine(reg)
        bus = AgentCommunicationBus(db)
        gov = GovernanceEngine(db)
        consensus = ConsensusEngine(db)
        resources = ResourceManager(db)

        # 1. Test Python Classes Directly
        # A. AgentRegistry seeding
        agents = reg.list_agents()
        assert len(agents) == 8  # 8 default agents seeded
        assert agents[0]["health_score"] == 1.0

        # B. DelegationEngine task assignment
        task = delegation.assign_task(
            task_description="Scan energy sector",
            required_capability="universe_scanning",
        )
        assert task is not None
        assert task["agent_id"] == "agent_intelligence"
        
        agent_after = reg.get_agent("agent_intelligence")
        assert agent_after["workload"] == 1
        assert agent_after["status"] == AgentStatus.RUNNING.value

        delegation.complete_task("agent_intelligence", task["task_id"], success=True)
        agent_final = reg.get_agent("agent_intelligence")
        assert agent_final["workload"] == 0

        # C. AgentCommunicationBus messaging
        msg = bus.send_message(
            sender_agent_id="agent_researcher",
            recipient_agent_id="agent_strategist",
            message_type="DATA_ALERT",
            subject="AAPL Breakout",
            body="AAPL crossed 180 resistance",
        )
        assert msg["status"] == "UNREAD"
        msgs = bus.get_messages("agent_strategist", unread_only=True)
        assert len(msgs) == 1
        assert msgs[0]["subject"] == "AAPL Breakout"

        bus.mark_read(msg["message_id"])
        assert len(bus.get_messages("agent_strategist", unread_only=True)) == 0

        # D. GovernanceEngine policy checks
        policies = gov.list_policies()
        assert len(policies) == 5  # 5 default policies seeded
        
        passed, reason = gov.enforce_check("MAX_POSITION_SIZE", 0.10)
        assert passed is True
        
        passed, reason = gov.enforce_check("MAX_POSITION_SIZE", 0.25)
        assert passed is False
        assert "exceeds" in reason

        # E. ConsensusEngine voting
        con = consensus.start_consensus(
            topic="Deploy Trend Follower v2 to Live",
            description="Promotion vote",
            voting_model=VotingModel.MAJORITY,
        )
        assert con["status"] == "OPEN"
        
        # Cast votes
        consensus.cast_vote(con["consensus_id"], "agent_commander", "YES")
        consensus.cast_vote(con["consensus_id"], "agent_risk", "YES")
        consensus.cast_vote(con["consensus_id"], "agent_strategist", "YES")

        records = consensus.get_consensus_records()
        assert records[0]["status"] == "RESOLVED"
        assert records[0]["result"] == "YES"

        # F. ResourceManager snapshots
        snap = resources.record_snapshot()
        assert "cpu_pct" in snap
        assert snap["llm_tokens_limit"] == 1000000

        # 2. Test REST API Endpoints
        with app.test_client() as client:
            # A. List agents
            resp = client.get("/api/v1/organization/agents")
            assert resp.status_code == 200
            assert len(resp.json["agents"]) == 8

            # B. List governance policies
            resp = client.get("/api/v1/organization/governance/policies")
            assert resp.status_code == 200
            assert len(resp.json["policies"]) == 5

            # C. Update policy parameter
            resp = client.post(
                "/api/v1/organization/governance/policies",
                json={
                    "policy_id": policies[0]["policy_id"],
                    "is_active": True,
                    "parameters": {"max_pct": 0.20},
                },
            )
            assert resp.status_code == 200
            assert resp.json["success"] is True

            # D. List consensus records
            resp = client.get("/api/v1/organization/consensus")
            assert resp.status_code == 200
            assert len(resp.json["records"]) >= 1

            # E. Start consensus session via API
            resp = client.post(
                "/api/v1/organization/consensus",
                json={
                    "topic": "API Consensus",
                    "description": "API Test",
                    "voting_model": "MAJORITY",
                },
            )
            assert resp.status_code == 201
            api_consensus_id = resp.json["consensus_id"]

            # F. Cast vote via API
            resp = client.post(
                f"/api/v1/organization/consensus/{api_consensus_id}/vote",
                json={"agent_id": "agent_commander", "vote": "YES", "rationale": "Approve"},
            )
            assert resp.status_code == 200
            assert resp.json["success"] is True

            # G. Organization resources
            resp = client.get("/api/v1/organization/resources")
            assert resp.status_code == 200
            assert "cpu_pct" in resp.json

    finally:
        SqliteStorageEngine.is_active = original_is_active
