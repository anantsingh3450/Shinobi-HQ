from __future__ import annotations

from pathlib import Path

from hokage.dashboard.api import create_dashboard_api


def test_create_dashboard_api_with_brain_root(tmp_path: Path) -> None:
    # 1. Setup temporary brain root
    brain_root = tmp_path / "dash_brain"

    # 2. Create the Flask app
    app = create_dashboard_api(brain_root=brain_root)
    
    # Verify that the bootstrapper was triggered and folders exist
    assert (brain_root / "brain.json").exists()
    assert (brain_root / "config" / "venues.json").exists()

    # 3. Test client requests
    with app.test_client() as client:
        # Verify health check endpoint works
        health_resp = client.get("/api/v1/health")
        assert health_resp.status_code == 200
        assert health_resp.json == {"status": "healthy"}

        # Verify portfolio overview works and loads default balance
        portfolio_resp = client.get("/api/v1/portfolio/paper/overview")
        assert portfolio_resp.status_code == 200
        
        data = portfolio_resp.json
        assert data["account_id"] == "paper"
        assert data["initial_balance"] == 10000.0
        assert data["cash"] == 10000.0
        assert data["open_positions_count"] == 0

        # Verify index page loads html
        index_resp = client.get("/")
        assert index_resp.status_code == 200
        assert b"Hokage Commander War Room" in index_resp.data

        # Verify chat POST endpoint routes natural queries
        chat_resp = client.post("/api/v1/chat", json={"message": "What is our status?"})
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json
        assert chat_data["query"] == "What is our status?"
        assert chat_data["mapped_command"] == "hokage status"
        assert "=== Hokage System Status ===" in chat_data["response_text"]

        # Verify unmapped chat mapping returns instructions
        chat_unmapped = client.post("/api/v1/chat", json={"message": "random gibberish message"})
        assert chat_unmapped.status_code == 200
        unmapped_data = chat_unmapped.json
        assert unmapped_data["mapped_command"] == "unmapped"
        assert "couldn't map your request" in unmapped_data["response_text"]

        # Verify summary dashboard endpoint compiles stats
        summary_resp = client.get("/api/v1/dashboard/summary")
        assert summary_resp.status_code == 200
        summary_data = summary_resp.json
        assert "equity" in summary_data
        assert "cash" in summary_data
        assert "status" in summary_data
        assert summary_data["status"]["execution_mode"] == "PAPER"
        assert "horizon" in summary_data
        assert "opportunities" in summary_data
        assert "tax_intelligence" in summary_data
        assert "learning" in summary_data
        assert summary_data["horizon"]["progression_phase"] == "ALPHA"
        assert summary_data["tax_intelligence"]["paper"]["post_tax_return_pct"] == 8.75

        # Verify profile endpoint works
        profile_resp = client.get("/api/v1/profile")
        assert profile_resp.status_code == 200
        profile_data = profile_resp.json
        assert profile_data["commander_name"] == "Anant"
        assert profile_data["commander_title"] == "Elder"
        assert profile_data["environment"]["mode"] == "PAPER"
        assert profile_data["horizon"]["phase"] == "ALPHA"

        # Verify shadow diagnostics endpoint works
        diag_resp = client.get("/api/v1/shadow/diagnostics")
        assert diag_resp.status_code == 200
        diag_data = diag_resp.json
        assert "status" in diag_data
        assert "ljung_box" in diag_data
        assert "jarque_bera" in diag_data
        assert "kupiec" in diag_data


