"""Unit tests for Hokage Read-Only Command Interface (Phase 5A.2)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import pytest

from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


def seed_test_data(brain_root: Path) -> None:
    """Helper to seed mock data in the temporary brain directory."""
    (brain_root / "portfolio").mkdir(parents=True, exist_ok=True)
    (brain_root / "journal").mkdir(parents=True, exist_ok=True)
    (brain_root / "reviews").mkdir(parents=True, exist_ok=True)
    (brain_root / "intelligence").mkdir(parents=True, exist_ok=True)

    # account_paper.json
    account_data = {
        "account_id": "paper",
        "initial_balance": 500000.0,
        "cash": 490000.0,
        "currency": "INR",
        "realized_pnl": 500.0,
        "positions": {
            "p001": {
                "position_id": "p001",
                "market": "TCS",
                "direction": "LONG",
                "quantity": 10.0,
                "entry_price": 3000.0,
                "current_price": 3100.0,
                "unrealized_pnl": 1000.0,
                "realized_pnl": 0.0,
                "status": "OPEN",
                "opened_at": "2026-06-23T12:00:00+00:00",
                "closed_at": None
            }
        },
        "equity_history": []
    }
    with (brain_root / "portfolio" / "account_paper.json").open("w", encoding="utf-8") as f:
        json.dump(account_data, f)

    # decision_journal.jsonl (seeded with today's local date dynamically)
    today_str = date.today().strftime("%Y-%m-%d")
    tcs_entry = {
        "symbol": "TCS",
        "decision": "ACCEPTED",
        "conviction": 86,
        "timestamp": f"{today_str}T12:00:00.000000+00:00",
        "decision_id": "p001",
        "decision_reason": "Authorized deployment of 2% capital.",
        "reasoning_chain": [
            {"gate": "CapitalPreservation", "decision": "NORMAL", "reason": "Safe conditions"},
            {"gate": "PortfolioHealth", "decision": "STRONG", "reason": "No drawdown"},
            {"gate": "ConvictionScore", "decision": 86, "reason": "High score"},
            {"gate": "ConfidenceCalibration", "decision": 86, "reason": "Calibrated"},
            {"gate": "NoTradeDecisionEngine", "decision": "BUY", "reason": "Trade approved"},
            {"gate": "PositionAllocation", "decision": "2.00%", "reason": "Allocated"},
            {"gate": "RiskBot", "decision": "APPROVED", "reason": "Risk checks passed"},
            {"gate": "Execute", "decision": "ACCEPTED", "reason": "Executed trade"}
        ]
    }
    infy_entry = {
        "symbol": "INFY",
        "decision": "REJECTED",
        "conviction": 40,
        "timestamp": f"{today_str}T12:05:00.000000+00:00",
        "decision_id": "p002",
        "veto_source": "RiskBot",
        "reason": "Exceeded maximum position size."
    }
    with (brain_root / "journal" / "decision_journal.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(tcs_entry) + "\n")
        f.write(json.dumps(infy_entry) + "\n")

    # trade_performance_history.jsonl
    perf_entry = {
        "timestamp": f"{today_str}T12:10:00.000000+00:00",
        "decision_id": "p001",
        "symbol": "TCS",
        "sector": "it",
        "market_regime": "BULL_RISK-ON",
        "conviction_score": 86,
        "conviction_grade": "ELITE",
        "holding_period_days": 1,
        "pnl": 1000.0,
        "return_pct": 0.033,
        "is_win": True,
        "volatility_level": 12.5,
        "asset_class": "EQUITY",
        "entry_price": 3000.0,
        "exit_price": 3100.0
    }
    with (brain_root / "portfolio" / "trade_performance_history.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(perf_entry) + "\n")

    # position_reviews.jsonl
    review_entry = {
        "decision_id": "p001",
        "symbol": "TCS",
        "entry_quality": "EXCELLENT",
        "exit_quality": "ON_TARGET",
        "sizing_quality": "CORRECT",
        "stop_quality": "CORRECT",
        "risk_reward_achieved": 2.0,
        "pnl": 1000.0,
        "return_pct": 0.033,
        "holding_days": 1,
        "lesson": "Excellent R:R achieved: 2.0 — replicate strategy.",
        "timestamp": f"{today_str}T12:15:00.000000+00:00"
    }
    with (brain_root / "reviews" / "position_reviews.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(review_entry) + "\n")

    # trade_dna.jsonl
    dna_entry = {
        "decision_id": "p001",
        "symbol": "TCS",
        "market_regime": "BULL_RISK-ON",
        "sector": "it",
        "conviction_grade": "ELITE",
        "holding_period_days": 1,
        "result": "WIN",
        "return_pct": 0.033,
        "conviction_score": 86,
        "pnl": 1000.0,
        "entry_price": 3000.0,
        "exit_price": 3100.0,
        "exit_reason": "Take Profit",
        "vix_level": 12.5,
        "personality_mode": "BALANCED",
        "sector_flow": "N/A",
        "timestamp": f"{today_str}T12:00:00.000000+00:00"
    }
    with (brain_root / "intelligence" / "trade_dna.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(dna_entry) + "\n")

    # morning_briefing.json
    briefing_data = {
        "markdown": "TEST MORNING BRIEFING MARKDOWN CONTENT"
    }
    with (brain_root / "intelligence" / "morning_briefing.json").open("w", encoding="utf-8") as f:
        json.dump(briefing_data, f)

    # elder_trust.json
    trust_data = {
        "trust_score": 95,
        "grade": "A",
        "metrics": {
            "risk_compliance": 98.5
        }
    }
    with (brain_root / "intelligence" / "elder_trust.json").open("w", encoding="utf-8") as f:
        json.dump(trust_data, f)

    # portfolio_health.json
    health_data = {
        "health_score": 90,
        "grade": "STRONG"
    }
    with (brain_root / "intelligence" / "portfolio_health.json").open("w", encoding="utf-8") as f:
        json.dump(health_data, f)

    # capital_preservation.json
    pres_data = {
        "mode": "NORMAL"
    }
    with (brain_root / "intelligence" / "capital_preservation.json").open("w", encoding="utf-8") as f:
        json.dump(pres_data, f)


@pytest.fixture
def orchestrator(tmp_path: Path) -> HokageOrchestrator:
    """Fixture for HokageOrchestrator using tmp_path."""
    seed_test_data(tmp_path)
    return HokageOrchestrator(brain_root=tmp_path)


@pytest.fixture
def router(orchestrator: HokageOrchestrator) -> CommandRouter:
    """Fixture for CommandRouter."""
    return CommandRouter(orchestrator)


def test_command_hokage_help(router: CommandRouter) -> None:
    """Test 'hokage' without subcommands displays help."""
    res = router.handle_command("hokage")
    assert "Usage: hokage <subcommand>" in res
    assert "hokage status" in res


def test_command_hokage_status(router: CommandRouter) -> None:
    """Test 'hokage status' parsing and output."""
    res = router.handle_command("hokage status")
    assert "=== Hokage System Status ===" in res
    assert "Execution Mode:" in res
    assert "Elder Trust Score:          95/100 (Grade: A)" in res
    assert "Portfolio Health:           90/100 (Grade: STRONG)" in res
    assert "Paper Account Balance:      ₹500,000.00" in res
    assert "Current Cash:               ₹490,000.00" in res
    assert "Open Positions:             1" in res


def test_command_hokage_portfolio(router: CommandRouter) -> None:
    """Test 'hokage portfolio' output."""
    res = router.handle_command("hokage portfolio")
    assert "=== Hokage Paper Portfolio ===" in res
    assert "Initial Balance:    ₹500,000.00" in res
    assert "Current Cash:       ₹490,000.00" in res
    assert "Realized P&L:       ₹500.00" in res
    assert "Unrealized P&L:     ₹1,000.00" in res
    assert "Total Equity:       ₹521,000.00" in res


def test_command_hokage_portfolio_intelligence(router: CommandRouter) -> None:
    """Test 'hokage portfolio-intelligence' output."""
    res = router.handle_command("hokage portfolio-intelligence")
    assert "=== Hokage Portfolio Intelligence ===" in res
    assert "Total Assets:" in res
    assert "Portfolio Volatility:" in res
    assert "Portfolio Budgets & Limits" in res
    assert "[ASSET_CLASS]" in res
    assert "equity" in res


def test_command_hokage_positions(router: CommandRouter) -> None:
    """Test 'hokage positions' output."""
    res = router.handle_command("hokage positions")
    assert "=== Hokage Open Positions ===" in res
    assert "TCS" in res
    assert "LONG" in res
    assert "10.00" in res
    assert "₹3,000.00" in res
    assert "₹3,100.00" in res
    assert "₹1,000.00" in res


def test_command_hokage_decisions_today(router: CommandRouter) -> None:
    """Test 'hokage decisions today' output."""
    res = router.handle_command("hokage decisions today")
    today_str = date.today().strftime("%Y-%m-%d")
    assert f"=== Hokage Decisions Today ({today_str}) ===" in res
    assert "TCS | ACCEPTED | Conviction: 86 (ELITE)" in res
    assert "Reason: Authorized deployment of 2% capital." in res
    assert "INFY | REJECTED | Conviction: 40 (WATCH)" in res
    assert "Veto Gate: RiskBot | Reason: Exceeded maximum position size." in res


def test_command_hokage_why(router: CommandRouter) -> None:
    """Test 'hokage why <symbol>' details."""
    # TCS has a valid reasoning chain
    res = router.handle_command("hokage why TCS")
    assert "=== Hokage Decision Audit: TCS ===" in res
    assert "Verdict: NORMAL" in res
    assert "Gate: CapitalPreservation" in res
    assert "Verdict: APPROVED" in res
    assert "Gate: RiskBot" in res

    # INFY is rejected and has no reasoning chain
    res2 = router.handle_command("hokage why INFY")
    assert "No reasoning chain logged" in res2

    # Unknown symbol
    res3 = router.handle_command("hokage why RELIANCE")
    assert "No decision journal entry found" in res3


def test_command_hokage_performance(router: CommandRouter) -> None:
    """Test 'hokage performance' metrics."""
    res = router.handle_command("hokage performance")
    assert "=== Hokage Trading Performance ===" in res
    assert "Total Trades:    1" in res
    assert "Win Rate:        100.00%" in res
    assert "Expectancy:      ₹1,000.00" in res


def test_command_hokage_lessons(router: CommandRouter) -> None:
    """Test 'hokage lessons' retrieval."""
    res = router.handle_command("hokage lessons")
    assert "=== Hokage Lessons Learned (Recent) ===" in res
    assert "TCS (PnL: ₹1,000.00):" in res
    assert "Excellent R:R achieved: 2.0" in res


def test_command_hokage_dna(router: CommandRouter) -> None:
    """Test 'hokage dna' output."""
    res = router.handle_command("hokage dna")
    assert "=== Hokage Trade DNA Analysis ===" in res
    assert "Total DNA Records: 1" in res
    assert "By Conviction Grade:" in res
    assert "- ELITE: 1 trades (1 Wins, 0 Losses, 0 Breakeven) | Win Rate: 100.00%" in res


def test_command_hokage_briefing(router: CommandRouter) -> None:
    """Test 'hokage briefing' output."""
    res = router.handle_command("hokage briefing")
    assert "TEST MORNING BRIEFING MARKDOWN CONTENT" in res


def test_command_hokage_review(router: CommandRouter) -> None:
    """Test 'hokage review' template pre-population."""
    res = router.handle_command("hokage review")
    assert "# HOKAGE Alpha EOD Daily Review" in res
    assert "**Daily PnL** | ₹1,000.00" in res
    assert "**Account Equity** | ₹521,000.00" in res
    assert "**Win Rate** | 100.00%" in res
    assert "Elder Trust Score:** `95/100`" in res
    assert "Required Sizing Scale:** `1.00x`" in res


def test_command_hokage_knowledge(router: CommandRouter) -> None:
    """Test 'hokage knowledge <topic>' search."""
    res = router.handle_command("hokage knowledge safety")
    assert "No knowledge matches found" in res


def test_command_hokage_opportunities(router: CommandRouter) -> None:
    """Test 'hokage opportunities' command output."""
    res = router.handle_command("hokage opportunities")
    assert "=== Hokage Global Opportunity Radar ===" in res
    assert "Active Horizon Mode: FOCUSED" in res
    assert "BTC" in res
    assert "ETH" in res
    assert "Gold" in res
    assert "Crude Oil" in res
    assert "Bank Nifty" in res
    assert "USD/INR" in res
    assert "Reliance" in res
    assert "Nasdaq ETF" in res


def test_command_hokage_profile(router: CommandRouter) -> None:
    """Test 'hokage profile' command output."""
    res = router.handle_command("hokage profile")
    assert "=== Hokage Commander Profile ===" in res
    assert "Commander:             Elder Anant" in res
    assert "Risk Mode:             DEFENSIVE" in res
    assert "Execution Mode:        PAPER" in res


def test_command_hokage_horizon(router: CommandRouter) -> None:
    """Test 'hokage horizon' command output."""
    res = router.handle_command("hokage horizon")
    assert "=== Hokage Horizon State ===" in res
    assert "Progression Phase:     ALPHA" in res
    assert "Active Horizon Mode:   FOCUSED" in res
    assert "Universe Size:         1" in res


def test_command_hokage_universe(router: CommandRouter) -> None:
    """Test 'hokage universe' command output."""
    res = router.handle_command("hokage universe")
    assert "=== Hokage Active Monitor Universe ===" in res
    assert "Assets (1):" in res
    assert "  - CRUDE_OIL" in res


def test_committee_cli_commands(router: CommandRouter) -> None:
    """Test committee subcommands (vetoes, stats, votes, why)."""
    # 1. vetoes
    vetoes_res = router.handle_command("hokage committee vetoes")
    assert "=== Hokage Committee Veto Powers ===" in vetoes_res
    assert "Risk Committee" in vetoes_res
    assert "Capital Preservation" in vetoes_res

    # Seed committee ledger dummy decision
    from bots.autonomous.committee import CommitteeLedger, CommitteeDecision, Vote
    ledger = CommitteeLedger(router.orchestrator.resolver)
    mock_votes = {
        "Risk": Vote("APPROVE", 100.0, "Risk check passed", {}, 0.0, veto_status=True),
        "Trend": Vote("REJECT", 80.0, "Regime down", {}, 0.2),
    }
    dec = CommitteeDecision("REJECTED", mock_votes, 50.0, 80.0, True, ["Trend"], ["Risk"], {})
    ledger.record_decision("dec-id-123", "strat-v1", "INFY", dec)

    # 2. votes
    votes_res = router.handle_command("hokage committee votes INFY")
    assert "=== Investment Committee Votes for INFY ===" in votes_res
    assert "Final Verdict:          REJECTED" in votes_res
    assert "Trend" in votes_res

    # 3. why
    why_res = router.handle_command("hokage committee why Trend INFY")
    assert "=== Committee 'Trend' Vote Audit: INFY ===" in why_res
    assert "Vote:        REJECT" in why_res
    assert "Confidence:  80.0%" in why_res

    # 4. stats
    stats_res = router.handle_command("hokage committee stats")
    assert "=== Investment Committee Performance Stats ===" in stats_res


def test_committee_natural_language_routing() -> None:
    """Test natural language committee query routing."""
    from hokage.router.nl_router import NaturalLanguageRouter
    nl = NaturalLanguageRouter()

    assert nl.parse_query("Which committee had veto authority?") == "hokage committee vetoes"
    assert nl.parse_query("Why did the Risk Committee reject the proposal?") == "hokage committee why Risk"
    assert nl.parse_query("Why did Capital Preservation block execution?") == "hokage committee why CapitalPreservation"
    assert nl.parse_query("Which committee has the highest historical accuracy?") == "hokage committee stats"
    assert nl.parse_query("Show committee votes.") == "hokage committee votes"


def test_command_hokage_strategy_evolution_commands(router: CommandRouter) -> None:
    """Test 'hokage strategy notifications' and 'hokage strategy pipeline' commands."""
    resolver = router.orchestrator.resolver
    brain_root = resolver.resolve_brain_root()
    portfolio_dir = resolver.resolve_portfolio_dir()
    journal_dir = brain_root / "journal"
    
    # 1. Test empty / initial states
    notif_res = router.handle_command("hokage strategy notifications")
    assert "No strategy notifications logged in the pipeline." in notif_res
    
    pipe_res = router.handle_command("hokage strategy pipeline")
    assert "=== Hokage Strategy Evolution Pipeline ===" in pipe_res

    # 2. Seed strategy notifications and portfolio
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)
    
    strategy_portfolio_data = {
        "strategies": {
            "strat_1": {
                "strategy_id": "strat_1",
                "name": "Moving Average Crossover",
                "status": "SHADOW_MODE",
                "supported_assets": ["BTC", "ETH"],
                "pnl_history": {"DEFAULT": [10.0, 20.0]}
            },
            "strat_2": {
                "strategy_id": "strat_2",
                "name": "Mean Reversion",
                "status": "PRODUCTION",
                "supported_assets": ["BTC", "ETH"],
                "pnl_history": {"DEFAULT": [15.0, 25.0]}
            }
        }
    }
    with (portfolio_dir / "strategy_portfolio.json").open("w", encoding="utf-8") as f:
        json.dump(strategy_portfolio_data, f)
        
    notifications_file = journal_dir / "strategy_notifications.jsonl"
    notification_data = {
        "timestamp": "2026-06-25T13:30:00Z",
        "strategy_id": "strat_1",
        "change_type": "PROMOTION",
        "validation_status": "PRODUCTION",
        "confidence": 95.0,
        "status": "PROMOTED",
        "reason": "Welch's t-test passed.",
        "supporting_evidence": {
            "t_statistic": 2.1,
            "confidence_interval_lower": 0.5
        }
    }
    with notifications_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(notification_data) + "\n")

    # 3. Test again with seeded data
    notif_res_2 = router.handle_command("hokage strategy notifications")
    assert "=== Hokage Strategy Evolution Notifications ===" in notif_res_2
    assert "Strategy ID:       strat_1" in notif_res_2
    assert "Reason:            Welch's t-test passed." in notif_res_2

    pipe_res_2 = router.handle_command("hokage strategy pipeline")
    assert "=== Hokage Strategy Evolution Pipeline ===" in pipe_res_2
    assert "Stage: SHADOW_MODE" in pipe_res_2
    assert "Stage: PRODUCTION" in pipe_res_2
    assert "Moving Average Crossover" in pipe_res_2


def test_cli_secrets_commands(tmp_path: Path) -> None:
    """Verify that the command router successfully handles all 'hokage secrets' subcommands."""
    orchestrator = HokageOrchestrator(brain_root=tmp_path)
    router = CommandRouter(orchestrator)

    # 1. Bootstrap a mock secrets.json file for status check
    secrets_file = orchestrator.secrets_manager.secrets_file_path
    secrets_file.parent.mkdir(parents=True, exist_ok=True)
    with secrets_file.open("w", encoding="utf-8") as fh:
        json.dump({"api_key": "YOUR_API_KEY", "access_token": "YOUR_ACCESS_TOKEN"}, fh)

    # 2. Check initial status
    status_res = router.handle_command("hokage secrets")
    assert "=== Hokage Secrets Status ===" in status_res
    assert "api_key      : NOT CONFIGURED" in status_res

    # 3. Set a secret
    set_res = router.handle_command("hokage secrets set api_key super_secret_123")
    assert "Secret 'api_key' for broker 'zerodha' set successfully in secure vault" in set_res

    # Verify via status that it is configured securely
    status_res_2 = router.handle_command("hokage secrets")
    assert "api_key      : CONFIGURED SECURELY" in status_res_2

    # 4. Rollback
    rollback_res = router.handle_command("hokage secrets rollback")
    assert "Secrets rollback completed. Plaintext credentials restored" in rollback_res

    # Verify secrets.json is restored
    with secrets_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["api_key"] == "super_secret_123"

    # 5. Migrate
    migrate_res = router.handle_command("hokage secrets migrate")
    assert "Secrets migration completed. All plaintext credentials migrated" in migrate_res

    # Verify secrets.json is masked
    with secrets_file.open("r", encoding="utf-8") as fh:
        data_masked = json.load(fh)
    assert data_masked["api_key"] == "MIGRATED_TO_KEYRING"


def test_command_hokage_shadow_diagnostics(router: CommandRouter) -> None:
    """Test 'hokage shadow diagnostics' command executes successfully."""
    res = router.handle_command("hokage shadow diagnostics")
    assert "=== Hokage Shadow Statistical Diagnostics ===" in res
    assert "Overall Health Status:" in res
    assert "1. Ljung-Box Q-Test" in res
    assert "2. Jarque-Bera Test" in res
    assert "3. Kupiec Proportion of Failures" in res









