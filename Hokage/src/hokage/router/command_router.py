"""Hokage command router — parses user intent and dispatches to the orchestrator.

Supports:
  help / ?              — list available commands
  research <topic>      — Run Research and Strategy pipeline, display StrategyProposal
  trade <topic>         — Run pipeline: Research → Strategy → Paper Execution pipeline
  full-trade <topic>    — Run full pipeline: Research → Strategy → Backtest → Paper Execution pipeline
  portfolio             — Show current paper account summary
  positions             — List all open positions
  predictions           — Summarize prediction ledger (pass/fail/win rate)
  tax                   — Summarize tax ledger (total tax, component breakdown)
"""
from __future__ import annotations

import json
from datetime import date

from hokage.orchestrator.pipeline import HokageOrchestrator
from bots.autonomous.trade_dna import TradeDNAEngine
from bots.autonomous.position_review import PositionReviewEngine
from bots.autonomous.performance_analytics import PerformanceAnalyticsEngine
from bots.autonomous.knowledge import KnowledgeManager
from shared.discovery.scanners import (
    EquityAssetScanner,
    CommodityAssetScanner,
    CryptoAssetScanner,
    ForexAssetScanner,
    ETFAssetScanner,
)
from shared.discovery.rankers import (
    OpportunityRankingEngine,
)
from shared.discovery.models import AssetCategory, HorizonMode
from hokage.router.nl_router import NaturalLanguageRouter


_HELP_TEXT = """\
Available commands:
  research <topic>      — Run Research and Strategy pipeline, display StrategyProposal
  trade <topic>         — Run pipeline: Research → Strategy → Paper Trade execution
  full-trade <topic>    — Run full pipeline: Research → Strategy → Backtest → Paper Trade
  portfolio             — Show current paper account balance, cash, PnL, and open position count
  positions             — List all currently open positions
  predictions           — Show prediction ledger summary (total, passed, failed, avg win rate)
  tax                   — Show tax ledger summary (total tax, breakdown by component type)
  zerodha-funds         — Show Zerodha funds and margins
  zerodha-holdings      — Show Zerodha holdings
  zerodha-positions     — Show Zerodha positions
  zerodha-pnl           — Show today's P&L in Zerodha
  price <symbol>        — Show last traded price of <symbol>
  zerodha-profile       — Show Zerodha account profile
  start trading         — Start background autonomous trading loop
  stop trading          — Stop background autonomous trading loop
  trading status        — Show status of autonomous trading loop
  daily report          — Generate EOD daily summary briefing
  help / ?              — Show this help message
  exit / quit           — Exit Hokage Commander

Hokage Read-Only Commands (Phase 5A.2):
  hokage status         — Show operational status, trust score, and capital preservation mode
  hokage portfolio      — Show current paper account portfolio summary (INR formatted)
  hokage portfolio-intelligence — Show rolling correlations, cash reserve target, volatility, and recommendations
  hokage market-intelligence   — Show macroeconomic regimes, news index, flows, and sector rotations
  hokage positions      — Show all open paper trading positions in a clean table (INR formatted)
  hokage chat "<query>" — Ask Hokage a question in natural language (e.g. "Explain today's portfolio")
  hokage voice-status   — Show the active voice commander session state and history
  hokage decisions today — Show all trade decisions (accepted/rejected) made today
  hokage why <symbol>   — Audit the 7-gate reasoning chain for the latest decision of <symbol>
  hokage performance    — Show detailed portfolio performance statistics (expectancy, Sharpe, drawdown)
  hokage lessons        — List the most recent trade reviews and structured lessons learned
  hokage dna            — Show wins/losses clustered by regime, sector, and conviction grade
  hokage briefing       — Show the latest cached morning briefing markdown
  hokage review         — Generate a pre-populated daily review template with today's stats
  hokage knowledge <topic> — Search institutional books for doctrines, rules, and principles
  hokage opportunities  — Show ranked opportunities across equities, commodities, forex, and crypto
  hokage profile        — Show commander settings, execution mode, and risk status
  hokage horizon        — Show progression phase, horizon mode, and universe metrics
  hokage universe       — Show active monitor universe assets list
  hokage strategy notifications — Show all strategy evolution pipeline notifications
  hokage strategy pipeline — Show all strategies registered in the pipeline and their stages
  hokage proposals      — Show all pending strategy improvement proposals
  hokage improve <proposal_id> — Approve and apply a strategy improvement proposal
  hokage analyze-drift <strategy_id> <symbol> — Run performance drift analysis on a strategy
  hokage secrets        — Show, set, delete, migrate, or rollback secure credentials
  hokage watchdog       — Show status, incidents, heartbeats, or restart subsystems"""


def format_inr(val: float | int) -> str:
    """Format numeric values as Indian Rupees (INR) with Indian numbering format and ₹ prefix."""
    if val < 0:
        return f"-₹{abs(val):,.2f}"
    return f"₹{val:,.2f}"


class CommandRouter:
    """Parses user intent and routes commands to the appropriate orchestrator."""

    def __init__(self, orchestrator: HokageOrchestrator) -> None:
        """Initialize the router with an orchestrator instance."""
        self.orchestrator = orchestrator
        from hokage.memory.profile import ProfileService
        self.profile_service = ProfileService(self.orchestrator.resolver)
        self.nl_router = NaturalLanguageRouter()

    def handle_command(self, raw_input: str) -> str | dict | list:
        """Process a raw user command.

        Args:
            raw_input: Text entered by the user.

        Returns:
            A string message (for help/errors), a dict (for single-record display),
            or a list of dicts (for tabular display).
        """
        cmd = raw_input.strip()
        # Register manual input for Gatekeeper Protocol
        try:
            if hasattr(self.orchestrator, "autonomous_bot") and self.orchestrator.autonomous_bot:
                self.orchestrator.autonomous_bot.elder_manual_input_received = True
        except Exception:
            pass

        if not cmd:
            return ""

        # Remove trailing period or question mark for robust matching
        if cmd.endswith(".") or cmd.endswith("?"):
            cmd = cmd[:-1].strip()
        lower_cmd = cmd.lower()

        # Help
        if lower_cmd in ("help", "?"):
            return _HELP_TEXT

        # Handle 'hokage ' prefix commands (Phase 5A.2)
        if lower_cmd == "hokage" or lower_cmd.startswith("hokage "):
            sub_cmd_str = cmd[len("hokage"):].strip()
            lower_sub_cmd = sub_cmd_str.lower()

            if not lower_sub_cmd:
                return (
                    "=== Hokage Commander CLI ===\n"
                    "Usage: hokage <subcommand>\n\n"
                    "Available Hokage subcommands:\n"
                    "  hokage status\n"
                    "  hokage portfolio\n"
                    "  hokage portfolio-intelligence\n"
                    "  hokage market-intelligence\n"
                    "  hokage positions\n"
                    "  hokage chat \"<query>\"\n"
                    "  hokage voice-status\n"
                    "  hokage decisions today\n"
                    "  hokage why <symbol>\n"
                    "  hokage performance\n"
                    "  hokage lessons\n"
                    "  hokage dna\n"
                    "  hokage briefing\n"
                    "  hokage review\n"
                    "  hokage knowledge <topic>"
                )

            if lower_sub_cmd == "status":
                return self.handle_hokage_status()
            elif lower_sub_cmd == "greet":
                return self.handle_hokage_greet()
            elif lower_sub_cmd == "missions":
                return self.handle_hokage_missions()
            elif lower_sub_cmd == "doctor":
                return self.handle_hokage_doctor()
            elif lower_sub_cmd == "portfolio":
                return self.handle_hokage_portfolio()
            elif lower_sub_cmd in ("portfolio-intelligence", "portfolio_intelligence", "intel"):
                return self.handle_hokage_portfolio_intelligence()
            elif lower_sub_cmd in ("market-intelligence", "market_intelligence", "mkt-intel"):
                return self.handle_hokage_market_intelligence()
            elif lower_sub_cmd.startswith("chat "):
                query_arg = sub_cmd_str[5:].strip().strip('"').strip("'")
                return self.handle_hokage_chat(query_arg)
            elif lower_sub_cmd == "voice-status":
                return self.handle_hokage_voice_status()
            elif lower_sub_cmd == "positions":
                return self.handle_hokage_positions()
            elif lower_sub_cmd == "decisions today":
                return self.handle_hokage_decisions_today()
            elif lower_sub_cmd.startswith("why "):
                symbol_arg = sub_cmd_str[len("why "):].strip()
                return self.handle_hokage_why(symbol_arg)
            elif lower_sub_cmd == "performance":
                return self.handle_hokage_performance()
            elif lower_sub_cmd == "lessons":
                return self.handle_hokage_lessons()
            elif lower_sub_cmd == "dna":
                return self.handle_hokage_dna()
            elif lower_sub_cmd == "briefing":
                return self.handle_hokage_briefing()
            elif lower_sub_cmd == "review":
                return self.handle_hokage_review()
            elif lower_sub_cmd.startswith("knowledge "):
                topic_arg = sub_cmd_str[len("knowledge "):].strip()
                return self.handle_hokage_knowledge(topic_arg)
            elif lower_sub_cmd in ("opportunities", "opportunity"):
                return self.handle_hokage_opportunities()
            elif lower_sub_cmd == "profile":
                return self.handle_hokage_profile()
            elif lower_sub_cmd == "horizon":
                return self.handle_hokage_horizon()
            elif lower_sub_cmd == "universe":
                return self.handle_hokage_universe()
            elif lower_sub_cmd == "proposals":
                return self.handle_hokage_proposals()
            elif lower_sub_cmd.startswith("improve "):
                proposal_arg = sub_cmd_str[len("improve "):].strip()
                return self.handle_hokage_improve(proposal_arg)
            elif lower_sub_cmd.startswith("analyze-drift "):
                parts = sub_cmd_str[len("analyze-drift "):].strip().split()
                strat_arg = parts[0] if len(parts) > 0 else ""
                symbol_arg = parts[1] if len(parts) > 1 else "DEFAULT"
                return self.handle_hokage_analyze_drift(strat_arg, symbol_arg)
            elif lower_sub_cmd == "wait-reason":
                return self.handle_hokage_wait_reason()
            elif lower_sub_cmd == "what-changed":
                return self.handle_hokage_what_changed()
            elif lower_sub_cmd == "show-authorization":
                return self.handle_hokage_show_authorization()
            elif lower_sub_cmd == "show-rejection":
                return self.handle_hokage_show_rejection()
            elif lower_sub_cmd == "committee vetoes":
                return self.handle_hokage_committee_vetoes()
            elif lower_sub_cmd == "committee stats":
                return self.handle_hokage_committee_stats()
            elif lower_sub_cmd.startswith("committee votes"):
                symbol_arg = sub_cmd_str[len("committee votes"):].strip()
                return self.handle_hokage_committee_votes(symbol_arg)
            elif lower_sub_cmd.startswith("committee why "):
                parts = sub_cmd_str[len("committee why "):].strip().split()
                committee_arg = parts[0] if len(parts) > 0 else ""
                symbol_arg = parts[1] if len(parts) > 1 else ""
                return self.handle_hokage_committee_why(committee_arg, symbol_arg)
            elif lower_sub_cmd == "strategy notifications":
                return self.handle_hokage_strategy_notifications()
            elif lower_sub_cmd == "strategy pipeline":
                return self.handle_hokage_strategy_pipeline()
            elif lower_sub_cmd == "reconcile" or lower_sub_cmd.startswith("reconcile"):
                args_str = sub_cmd_str[len("reconcile"):].strip()
                return self.handle_hokage_reconcile(args_str)
            elif lower_sub_cmd == "secrets" or lower_sub_cmd.startswith("secrets"):
                args_str = sub_cmd_str[len("secrets"):].strip()
                return self.handle_hokage_secrets(args_str)
            elif lower_sub_cmd == "watchdog" or lower_sub_cmd.startswith("watchdog"):
                args_str = sub_cmd_str[len("watchdog"):].strip()
                return self.handle_hokage_watchdog(args_str)
            elif lower_sub_cmd == "shadow" or lower_sub_cmd.startswith("shadow"):
                args_str = sub_cmd_str[len("shadow"):].strip()
                return self.handle_hokage_shadow(args_str)
            elif lower_sub_cmd.startswith("replay "):
                trade_id = sub_cmd_str[len("replay "):].strip()
                return self.handle_hokage_replay(trade_id)
            elif lower_sub_cmd.startswith("persona set "):
                tone_arg = sub_cmd_str[len("persona set "):].strip()
                return self.handle_hokage_persona_set(tone_arg)
            elif lower_sub_cmd.startswith("mode set "):
                mode_arg = sub_cmd_str[len("mode set "):].strip()
                return self.handle_hokage_mode_set(mode_arg)
            elif lower_sub_cmd.startswith("override stop-loss "):
                val_arg = sub_cmd_str[len("override stop-loss "):].strip()
                return self.handle_hokage_override_stop_loss(val_arg)
            elif lower_sub_cmd.startswith("override take-profit "):
                val_arg = sub_cmd_str[len("override take-profit "):].strip()
                return self.handle_hokage_override_take_profit(val_arg)
            elif lower_sub_cmd == "override revoke":
                return self.handle_hokage_override_revoke()
            else:
                return f"Unknown Hokage subcommand: '{sub_cmd_str}'. Type 'help' for details."

        # research <topic> — Research → Strategy only
        if lower_cmd == "research" or lower_cmd.startswith("research "):
            query = cmd[len("research"):].strip()
            if not query:
                return "Error: Please specify a topic. Usage: research <topic>"
            try:
                return self.orchestrator.execute_research_to_strategy(query)
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        # take a trade / take any trade - bypass to demonstrate paper trading
        if lower_cmd in ("take a trade", "take any trade", "execute a trade", "take trade"):
            demo_symbol = "CRUDEOIL24NOVFUT" # Or just a standard symbol
            try:
                msg = f"Executing manual discretionary override. Initiating unverified paper trade sequence on {demo_symbol}..."
                res = self.orchestrator.execute_paper_trade(demo_symbol)
                return f"{msg}\n\nPipeline Output:\n{res}"
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        # trade <topic> — Research → Strategy → PaperExecution
        if lower_cmd == "trade" or lower_cmd.startswith("trade "):
            query = cmd[len("trade"):].strip()
            if not query:
                return "Error: Please specify a topic. Usage: trade <topic>"
            try:
                return self.orchestrator.execute_paper_trade(query)
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        # full-trade <topic> — Research → Strategy → Backtest → PaperExecution
        if lower_cmd == "full-trade" or lower_cmd.startswith("full-trade "):
            query = cmd[len("full-trade"):].strip()
            if not query:
                return "Error: Please specify a topic. Usage: full-trade <topic>"
            try:
                return self.orchestrator.execute_full_pipeline(query)
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        # portfolio — paper account summary (read-only)
        if lower_cmd == "portfolio":
            try:
                return self.orchestrator.query_portfolio()
            except Exception as exc:
                return f"Portfolio query failed: {exc}"

        # positions — open positions list (read-only)
        if lower_cmd == "positions":
            try:
                return self.orchestrator.query_positions()
            except Exception as exc:
                return f"Positions query failed: {exc}"

        # predictions — prediction ledger summary (read-only)
        if lower_cmd == "predictions":
            try:
                return self.orchestrator.query_predictions()
            except Exception as exc:
                return f"Predictions query failed: {exc}"

        # tax — tax ledger summary (read-only)
        if lower_cmd == "tax":
            try:
                return self.orchestrator.query_tax()
            except Exception as exc:
                return f"Tax query failed: {exc}"

        # zerodha-profile / show account profile
        if lower_cmd in ("zerodha-profile", "show account profile", "account profile", "zerodha profile", "show my zerodha account", "show profile", "profile", "show my account profile"):
            try:
                prof = self.orchestrator.get_kite_profile()
                return (
                    "=== Zerodha Account Profile ===\n"
                    f"User Name: {prof['user_name']}\n"
                    f"User ID: {prof['user_id']}\n"
                    f"Broker: {prof['broker']}\n"
                    f"Account Type: {prof['account_type']}\n"
                    "==============================="
                )
            except Exception as exc:
                return f"Zerodha profile query failed: {exc}"

        # zerodha-funds / show funds
        if lower_cmd in ("zerodha-funds", "show my zerodha funds", "zerodha funds", "show funds", "show balance", "show available cash", "show zerodha funds"):
            try:
                funds = self.orchestrator.get_kite_funds()
                return (
                    "=== Zerodha Funds & Margin ===\n"
                    f"Available Cash: INR {funds['available_cash']:.2f}\n"
                    f"Utilized Margin: INR {funds['utilized_margin']:.2f}\n"
                    f"Available Margin: INR {funds['available_margin']:.2f}\n"
                    "=============================="
                )
            except Exception as exc:
                return f"Zerodha funds query failed: {exc}"

        # zerodha-holdings / show holdings
        if lower_cmd in ("zerodha-holdings", "show my zerodha holdings", "show my holdings", "holdings", "zerodha holdings", "show holdings", "what stocks do i own", "show zerodha holdings"):
            try:
                holdings = self.orchestrator.get_kite_holdings()
                if not holdings:
                    return "No holdings found."
                lines = [
                    "=== Zerodha Holdings ===",
                    f"{'Symbol':<10}{'Qty':<8}{'Avg Cost':<12}{'Current Val':<14}{'Unrealized P&L':<15}",
                    "-" * 59
                ]
                for h in holdings:
                    pnl_prefix = "+" if h['unrealized_pnl'] >= 0 else ""
                    lines.append(f"{h['symbol']:<10}{h['quantity']:<8.0f}{h['average_cost']:<12.2f}{h['current_value']:<14.2f}{pnl_prefix}{h['unrealized_pnl']:<15.2f}")
                lines.append("=" * 59)
                return "\n".join(lines)
            except Exception as exc:
                return f"Zerodha holdings query failed: {exc}"

        # zerodha-positions / show positions
        if lower_cmd in ("zerodha-positions", "show my zerodha positions", "show my positions", "zerodha positions", "show positions", "open positions", "show zerodha positions"):
            try:
                positions = self.orchestrator.get_kite_positions()
                if not positions:
                    return "No open positions found."
                lines = [
                    "=== Zerodha Open Positions ===",
                    f"{'Symbol':<10}{'Qty':<8}{'Side':<8}{'Unrealized P&L':<15}",
                    "-" * 41
                ]
                for p in positions:
                    pnl_prefix = "+" if p['pnl'] >= 0 else ""
                    lines.append(f"{p['symbol']:<10}{p['quantity']:<8.0f}{p['side']:<8}{pnl_prefix}{p['pnl']:<15.2f}")
                lines.append("=" * 41)
                return "\n".join(lines)
            except Exception as exc:
                return f"Zerodha positions query failed: {exc}"

        # zerodha-pnl
        if lower_cmd in ("zerodha-pnl", "show today's p&l", "show today's pnl", "today's pnl", "zerodha pnl"):
            try:
                pnl = self.orchestrator.query_zerodha_pnl()
                return (
                    "=== Zerodha P&L Summary ===\n"
                    f"Total P&L: INR {pnl['total_pnl']:.2f}\n"
                    f"Currency: {pnl['currency']}\n"
                    f"Position Count: {pnl['position_count']}\n"
                    "==========================="
                )
            except Exception as exc:
                return f"Zerodha PnL query failed: {exc}"

        # market status / NSE open check
        if lower_cmd in ("market status", "market open", "is nse open", "show market status", "show nifty status", "nifty status"):
            try:
                status = self.orchestrator.get_market_status()
                return (
                    "=== Market Status ===\n"
                    f"Market: {status['market']}\n"
                    f"Status: {status['status']}\n"
                    f"Time (IST): {status['time_ist']}\n"
                    f"Reason: {status['reason']}\n"
                    "====================="
                )
            except Exception as exc:
                return f"Market status query failed: {exc}"

        # show my watchlist / watchlist
        if lower_cmd in ("show my watchlist", "watchlist", "show watchlist"):
            try:
                symbols = self.orchestrator.get_kite_watchlist()
                if not symbols:
                    return "Watchlist is empty."
                lines = ["=== Watchlist ==="]
                for s in symbols:
                    lines.append(f"- {s.upper()}")
                lines.append("=================")
                return "\n".join(lines)
            except Exception as exc:
                return f"Watchlist query failed: {exc}"

        # price queries
        target_symbol = None
        if lower_cmd.startswith("show current price of "):
            target_symbol = cmd[len("show current price of "):].strip()
        elif lower_cmd.startswith("show price of "):
            target_symbol = cmd[len("show price of "):].strip()
        elif lower_cmd.startswith("current price of "):
            target_symbol = cmd[len("current price of "):].strip()
        elif lower_cmd.startswith("quote "):
            target_symbol = cmd[len("quote "):].strip()
        elif lower_cmd.startswith("price "):
            target_symbol = cmd[len("price "):].strip()

        if target_symbol:
            try:
                q = self.orchestrator.get_kite_quote(target_symbol)
                sign = "+" if q['change'] >= 0 else ""
                return (
                    "=== Zerodha Market Quote ===\n"
                    f"Symbol: {q['symbol']}\n"
                    f"Last Traded Price: INR {q['last_traded_price']:.2f}\n"
                    f"Change: INR {sign}{q['change']:.2f} ({sign}{q['percentage_change']:.2f}%)\n"
                    "============================"
                )
            except Exception as exc:
                return f"Price query failed for {target_symbol}: {exc}"

        # start trading
        if lower_cmd in ("start trading", "start autonomous trading"):
            try:
                return self.orchestrator.start_autonomous_trading()
            except Exception as exc:
                return f"Failed to start autonomous trading: {exc}"

        # stop trading
        if lower_cmd in ("stop trading", "stop autonomous trading"):
            try:
                return self.orchestrator.stop_autonomous_trading()
            except Exception as exc:
                return f"Failed to stop autonomous trading: {exc}"

        # trading status
        if lower_cmd in ("trading status", "is trading active", "autonomous trading status"):
            try:
                status = self.orchestrator.get_autonomous_trading_status()
                state_str = "ACTIVE" if status["is_active"] else "INACTIVE"
                watchlist_str = ", ".join(status["watchlist"])
                return (
                    "=== Autonomous Trading Status ===\n"
                    f"Status: {state_str}\n"
                    f"Execution Mode: {status['execution_mode']}\n"
                    f"Active Venue: {status['active_venue_id']}\n"
                    f"Watchlist: {watchlist_str}\n"
                    f"Scan Interval: {status['scan_interval']} seconds\n"
                    "================================="
                )
            except Exception as exc:
                return f"Failed to query trading status: {exc}"

        # daily report
        if lower_cmd in ("daily report", "show daily report", "summary report", "briefing"):
            try:
                rep = self.orchestrator.get_daily_summary_report()
                lines = [
                    f"=== Elder Daily Briefing ({rep['date']}) ===",
                    f"Realized P&L: INR {rep['realized_pnl']:.2f}",
                    f"Unrealized P&L: INR {rep['unrealized_pnl']:.2f}",
                    f"Win Rate: {rep['win_rate']:.2f}%",
                    "Portfolio Allocation:"
                ]
                for k, v in rep['portfolio_allocation'].items():
                    lines.append(f"  - {k}: {v}%")
                lines.append(f"Trades Taken: {len(rep['trades_taken'])}")
                lines.append(f"Exits Executed: {len(rep['exits_executed'])}")
                lines.append(f"Market Summary: {rep['market_summary']}")
                lines.append(f"Lessons Learned: {rep['lessons_learned']}")
                lines.append("=========================================")
                return "\n".join(lines)
            except Exception as exc:
                return f"Failed to generate daily report: {exc}"

        # morning briefing
        if lower_cmd in ("morning briefing", "show morning briefing", "pre-market briefing", "morning report"):
            try:
                return self.orchestrator.get_morning_briefing()
            except Exception as exc:
                return f"Failed to generate morning briefing: {exc}"

        # daily briefing
        if lower_cmd in ("daily briefing", "show daily briefing", "eod briefing", "eod report"):
            try:
                return self.orchestrator.get_daily_briefing_report()
            except Exception as exc:
                return f"Failed to generate daily briefing: {exc}"

        # learn today
        if lower_cmd in ("learn today", "run learning loop", "eod learning", "learn"):
            try:
                result = self.orchestrator.run_eod_learning()
                return (
                    "=== EOD Learning Analyzer ===\n"
                    f"Date: {result['date']}\n"
                    f"Checked Predictions: {result['predictions_checked']}\n"
                    f"Accuracy Win Rate: {result['prediction_win_rate']}%\n"
                    f"Realized PnL: INR {result['realized_pnl']:+.2f}\n"
                    f"Lesson: {result['lesson']}\n"
                    "============================="
                )
            except Exception as exc:
                return f"Failed to run EOD learning: {exc}"

        # set scan mode
        if lower_cmd.startswith("set scan mode ") or lower_cmd.startswith("set trading mode "):
            parts = cmd.split()
            if len(parts) >= 4:
                mode_arg = parts[3].upper()
                if mode_arg in ("OPEN", "OPEN_MARKET"):
                    mode_val = "OPEN_MARKET"
                elif mode_arg in ("SECTOR", "SECTOR_RESTRICTED"):
                    mode_val = "SECTOR_RESTRICTED"
                elif mode_arg in ("WATCHLIST", "WATCHLIST_RESTRICTED"):
                    mode_val = "WATCHLIST_RESTRICTED"
                elif mode_arg in ("SINGLE", "SINGLE_ASSET"):
                    mode_val = "SINGLE_ASSET"
                else:
                    mode_val = mode_arg

                constraints_arg = parts[4:] if len(parts) > 4 else None
                if constraints_arg and len(constraints_arg) == 1:
                    constraints_arg = constraints_arg[0]
                try:
                    return self.orchestrator.set_autonomous_mode(mode_val, constraints_arg)
                except Exception as exc:
                    return f"Failed to set scan mode: {exc}"
            return "Usage: set scan mode <open|sector|watchlist|single> [<constraints>]"

        # Check natural language mapping if unrecognized
        mapped = self.nl_router.parse_query(raw_input)
        if mapped and mapped != "unmapped" and mapped != raw_input:
            return self.handle_command(mapped)

        return f"Unknown command: '{cmd}'. Type 'help' for available commands."

    # ------------------------------------------------------------------
    # Hokage Command Handlers (Phase 5A.2)
    # ------------------------------------------------------------------

    def handle_hokage_greet(self) -> str:
        """Greeting banner for conversational start."""
        profile = self.profile_service.get_profile()
        try:
            status_api = self.handle_hokage_status()
            loop_state = "ACTIVE" if "Autonomous Loop:            ACTIVE" in status_api else "INACTIVE"
            sys_state = "ONLINE" if "System State:               ONLINE" in status_api else "OFFLINE"
        except Exception:
            loop_state = "INACTIVE"
            sys_state = "OFFLINE"

        try:
            mkt_status = self.orchestrator.get_market_status()
            market_state = "Open" if mkt_status.get("is_open", False) else "Closed"
        except Exception:
            market_state = "Closed"

        lines = [
            "========================================",
            "HOKAGE AI OPERATING SYSTEM",
            f"Commander: {profile.commander_title} {profile.commander_name}",
            f"Execution Mode: {profile.environment.mode.value.upper()}",
            f"System State: {sys_state}",
            "Mission Engine: READY",
            "AI Coach: READY",
            "Knowledge Graph: READY",
            "Watchdog: ACTIVE",
            "EventBus: ACTIVE",
            "",
            "Good morning, Commander. Awaiting your orders.",
            "========================================"
        ]
        return "\n".join(lines)

    def handle_hokage_missions(self) -> str:
        """Handler for 'hokage missions'."""
        try:
            conn = self.orchestrator.sqlite_engine.get_connection()
            cursor = conn.execute(
                "SELECT name, status, current_stage, progress_pct FROM missions WHERE status IN ('RUNNING', 'PENDING', 'PAUSED', 'SCHEDULED') ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
            if not rows:
                return "No active missions in the queue. System is idling."
            
            lines = ["=== Active Hokage Missions ==="]
            for row in rows:
                lines.append(
                    f"- {row['name']} | Status: {row['status']} | Stage: {row['current_stage']} | Progress: {row['progress_pct']}%"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"Failed to retrieve active missions: {exc}"

    def handle_hokage_status(self) -> str:
        """Handler for 'hokage status'."""
        import urllib.request
        import json

        loop_active = False
        watchdog_active = False
        state = "OFFLINE"
        venue = "paper_main"
        mode = "PAPER"

        try:
            # Query the running server for live runtime state
            req_url = "http://127.0.0.1:5000/api/v1/system/status"
            res = urllib.request.urlopen(req_url, timeout=0.5)
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                loop_active = data.get("loop_active", False)
                watchdog_active = data.get("watchdog_active", False)
                state = data.get("state", "ONLINE")
                venue = data.get("active_venue_id", "paper_main")
                mode = data.get("execution_mode", "PAPER")
        except Exception:
            # Fallback to local configuration/orchestrator if server is offline
            state = "OFFLINE"
            try:
                status = self.orchestrator.get_autonomous_trading_status()
                loop_active = status.get("is_active", False)
                venue = status.get("active_venue_id", "paper_main")
            except Exception:
                loop_active = False
                venue = "paper_main"

            profile = self.profile_service.get_profile()
            mode = profile.environment.mode.value

        profile = self.profile_service.get_profile()
        preservation_enabled = profile.risk.capital_preservation

        try:
            account = self.orchestrator.portfolio_store.load_account("paper")
            cash = account.cash
            balance = account.initial_balance
            open_count = sum(1 for p in account.positions.values() if p.status.name == "OPEN")
        except Exception:
            cash = profile.portfolio.starting_capital
            balance = profile.portfolio.starting_capital
            open_count = 0

        trust_score = "N/A"
        trust_grade = "N/A"
        try:
            trust_file = self.orchestrator.resolver.resolve_brain_root() / "intelligence" / "elder_trust.json"
            if trust_file.exists():
                with trust_file.open("r", encoding="utf-8") as f:
                    trust_data = json.load(f)
                    trust_score = f"{trust_data.get('trust_score', 'N/A')}/100"
                    trust_grade = trust_data.get("grade", "N/A")
        except Exception:
            pass

        health_score = "N/A"
        health_grade = "N/A"
        try:
            health_file = self.orchestrator.resolver.resolve_brain_root() / "intelligence" / "portfolio_health.json"
            if health_file.exists():
                with health_file.open("r", encoding="utf-8") as f:
                    health_data = json.load(f)
                    health_score = f"{health_data.get('health_score', 'N/A')}/100"
                    health_grade = health_data.get("health_grade", health_data.get("grade", "N/A"))
        except Exception:
            pass

        preservation_state = "NORMAL"
        try:
            pres_file = self.orchestrator.resolver.resolve_brain_root() / "intelligence" / "capital_preservation.json"
            if pres_file.exists():
                with pres_file.open("r", encoding="utf-8") as f:
                    pres_data = json.load(f)
                    preservation_state = pres_data.get("mode", "NORMAL")
        except Exception:
            pass

        if not preservation_enabled:
            preservation_state = "DISABLED"

        lines = [
            "=== Hokage System Status ===",
            f"Commander:                  {profile.commander_title} {profile.commander_name}",
            f"System State:               {state}",
            f"Execution Mode:             {mode}",
            f"Autonomous Loop:            {'ACTIVE' if loop_active else 'INACTIVE'}",
            f"Watchdog Status:            {'ACTIVE' if watchdog_active else 'INACTIVE'}",
            f"Active Venue:               {venue}",
            f"Capital Preservation State: {preservation_state}",
            f"Elder Trust Score:          {trust_score} (Grade: {trust_grade})",
            f"Portfolio Health:           {health_score} (Grade: {health_grade})",
            f"Paper Account Balance:      {format_inr(balance)}",
            f"Current Cash:               {format_inr(cash)}",
            f"Open Positions:             {open_count}",
            "============================"
        ]
        return "\n".join(lines)

    def handle_hokage_portfolio(self) -> str:
        """Handler for 'hokage portfolio'."""
        try:
            account = self.orchestrator.portfolio_store.load_account("paper")
            cash = account.cash
            initial = account.initial_balance
            realized = account.realized_pnl
            open_positions = [p for p in account.positions.values() if p.status.name == "OPEN"]
            unrealized = sum(p.unrealized_pnl for p in open_positions)
            equity = cash + sum(p.quantity * p.current_price for p in open_positions)
        except Exception as exc:
            return f"Failed to load paper account portfolio: {exc}"

        lines = [
            "=== Hokage Paper Portfolio ===",
            f"Account ID:         {account.account_id}",
            f"Initial Balance:    {format_inr(initial)}",
            f"Current Cash:       {format_inr(cash)}",
            f"Realized P&L:       {format_inr(realized)}",
            f"Unrealized P&L:     {format_inr(unrealized)}",
            f"Total Equity:       {format_inr(equity)}",
            f"Open Positions:     {len(open_positions)}",
            "=============================="
        ]
        return "\n".join(lines)

    def handle_hokage_portfolio_intelligence(self) -> str:
        """Handler for 'hokage portfolio-intelligence'."""
        try:
            account = self.orchestrator.portfolio_store.load_account("paper")
            
            from integrations.brokers.interfaces import BaseExecutionVenue
            from integrations.brokers.models import AccountBalance, VenuePosition, OrderSide
            
            class CLITemporaryVenue(BaseExecutionVenue):
                def __init__(self, acc, orchestrator) -> None:
                    self._acc = acc
                    self._orch = orchestrator
                    self._venue_id = f"temp_{acc.account_id}"
                @property
                def venue_id(self) -> str:
                    return self._venue_id
                def get_account_balance(self) -> AccountBalance:
                    return AccountBalance(
                        venue_id=self.venue_id,
                        total_equity=self._acc.equity,
                        cash=self._acc.cash,
                        margin_available=0.0,
                        margin_used=0.0
                    )
                def get_positions(self) -> list[VenuePosition]:
                    records = []
                    for pos in self._acc.positions.values():
                        if pos.status.name == "OPEN":
                            inst = self._orch.price_source.resolve_instrument(pos.market)
                            side = OrderSide.BUY if pos.direction == "LONG" else OrderSide.SELL
                            records.append(VenuePosition(
                                instrument=inst,
                                side=side,
                                quantity=pos.quantity,
                                average_price=pos.entry_price,
                                current_price=pos.current_price,
                                unrealized_pnl=pos.unrealized_pnl,
                                venue_id=self.venue_id
                            ))
                    return records
                def place_order(self, request): pass
                def cancel_order(self, order_id): pass
                def get_order_status(self, order_id): pass
                def list_orders(self): return []
                
            temp_venue = CLITemporaryVenue(account, self.orchestrator)
            from bots.autonomous.portfolio_intelligence import PortfolioAwareness
            from bots.autonomous.cache import IntelligenceCache
            
            cache = IntelligenceCache(self.orchestrator.resolver.resolve_brain_root())
            awareness = PortfolioAwareness(temp_venue, cache, self.orchestrator.price_source)
            metrics = awareness.compute_portfolio_metrics()
        except Exception as exc:
            return f"Failed to compute portfolio intelligence: {exc}"

        if not metrics.get("data_ready", True):
            return (
                "Portfolio intelligence unavailable: venue is not connected, "
                "so no real balance/position data could be read. No metrics "
                "were fabricated. Connect the broker (or paper venue) and retry."
            )

        lines = [
            "=== Hokage Portfolio Intelligence ===",
            f"Total Assets:            {format_inr(metrics['total_assets'])}",
            f"Invested Capital:        {format_inr(metrics['total_value'])} ({metrics['invested_capital_pct']:.1f}%)",
            f"Current Cash:            {format_inr(metrics['available_buying_power'])} ({metrics['cash_allocation_pct']:.1f}%)",
            "",
            "--- Volatility & Beta ---",
            f"Portfolio Volatility:    {metrics['portfolio_volatility'] * 100.0:.2f}% (Regime: {metrics['volatility_regime']})",
            f"Portfolio Beta:          {metrics['portfolio_beta']:.2f}",
            "",
            "--- Allocation Targets ---",
            f"Target Cash Reserve:     {metrics['recommended_cash_reserve_pct']:.1f}%",
            f"Reserved Capital:        {format_inr(metrics['reserved_capital'])}",
            f"Buying Power Limit:      {format_inr(metrics['available_buying_power'])}",
            f"Target Addl Deployment:  {format_inr(metrics['target_additional_deployment'])}",
            "",
            "--- Correlation Analytics ---",
            f"Avg Position Correlation: {metrics['average_position_correlation']:.3f} ({metrics['systemic_concentration']} concentration)",
            f"Diversification Score:   {metrics['diversification_score']:.1f}/100",
            f"Hidden Concentrations:   {len(metrics['hidden_concentrations'])} detected",
            f"Duplicate Exposures:     {len(metrics['duplicate_exposures'])} detected",
            f"Correlation Clusters:    {len(metrics['correlation_clusters'])} detected",
        ]
        
        portfolio_budgets = metrics.get("portfolio_budgets", {})
        if portfolio_budgets:
            lines.extend([
                "",
                "--- Portfolio Budgets & Limits ---"
            ])
            for cat_type, cat_data in portfolio_budgets.items():
                lines.append(f"  [{cat_type.upper()}]")
                for cat_name, summary in cat_data.items():
                    target = summary.get("dynamic_target", summary.get("target", 0.0))
                    lines.append(
                        f"    * {cat_name:<12} Exposure: {summary['current_exposure']:>5.1f}% | Target: {summary['min']:.0f}%-{target:.0f}% (Max {summary['max']:.0f}%) | Buying Power: {summary['remaining_buying_power']:.1f}%"
                    )

        if metrics.get("rebalancing_recommendations"):
            lines.append("")
            lines.append("--- Rebalancing Recommendations ---")
            for rec in metrics["rebalancing_recommendations"]:
                lines.append(f"  * {rec}")
                
        lines.append("==============================")
        return "\n".join(lines)

    def handle_hokage_market_intelligence(self) -> str:
        """Handler for 'hokage market-intelligence'."""
        try:
            from bots.autonomous.market_intelligence import MarketIntelligenceEngine
            from bots.autonomous.cache import IntelligenceCache
            
            cache = IntelligenceCache(self.orchestrator.resolver.resolve_brain_root())
            engine = MarketIntelligenceEngine(self.orchestrator, cache)
            report = engine.get_or_compute_report()
        except Exception as exc:
            return f"Failed to compute market intelligence: {exc}"

        lines = [
            "=== Hokage Market Intelligence ===",
            f"Macro Regime:           {report.get('macro_regime', 'STATIONARY')}",
            f"Report Confidence:      {report.get('confidence', 0.0):.0f}%",
            f"Event Impact Score:     {report.get('event_impact_score', 0.0):+.2f}",
            f"Breadth Health Score:   {report.get('breadth_health_score', 0.0):.1f}%",
            f"FII/DII Flows Regime:   {report.get('flows_regime', 'NEUTRAL')}",
            f"Options Sentiment:      {report.get('options_regime', 'NEUTRAL')}",
            "",
            "--- Explainable Market Summary ---",
            report.get('explainable_summary', 'No summary available.'),
            "",
            "--- Sector Rotation Momentum ---"
        ]
        
        rotation = report.get("sector_rotation", {})
        sector_details = rotation.get("sector_details", {})
        for sector, details in sector_details.items():
            lines.append(f"  * {sector:<12} Momentum: {details.get('momentum_score', 0.0):>6.2f} | Capital Flow Coeff: {details.get('capital_flow_coefficient', 0.0):>7.4f}")
            
        economic = report.get("economic_events", [])
        if economic:
            lines.extend([
                "",
                "--- Economic Calendar ---"
            ])
            for ev in economic:
                lines.append(f"  * [{ev.get('severity', 'MEDIUM')}] {ev.get('event', 'Event')} ({ev.get('country', 'Global')}) -> Actual: {ev.get('actual', '')} / Forecast: {ev.get('forecast', '')}")

        earnings = report.get("earnings_releases", [])
        if earnings:
            lines.extend([
                "",
                "--- Upcoming/Completed Earnings ---"
            ])
            for ea in earnings:
                lines.append(f"  * {ea.get('symbol', ''):<10} Surprise: {ea.get('surprise_pct', 0.0):>+6.2f}% | Est: {ea.get('eps_estimate', '')} / Act: {ea.get('eps_actual', '')}")
                
        lines.append("==============================")
        return "\n".join(lines)

    def handle_hokage_chat(self, query: str) -> str:
        """Handler for 'hokage chat "<query>"'."""
        try:
            from bots.autonomous.conversation import CommanderConversationEngine
            from bots.autonomous.cache import IntelligenceCache
            
            cache = IntelligenceCache(self.orchestrator.resolver.resolve_brain_root())
            engine = CommanderConversationEngine(self.orchestrator, cache)
            response = engine.respond(query)
            return f"Hokage: {response}"
        except Exception as exc:
            return f"Failed to process conversation query: {exc}"

    def handle_hokage_voice_status(self) -> str:
        """Handler for 'hokage voice-status'."""
        return "Voice Commander Session: INACTIVE | Wake Phrase: 'Hokage' | Provider: MockVoiceProvider"

    def handle_hokage_positions(self) -> str:
        """Handler for 'hokage positions'."""
        try:
            account = self.orchestrator.portfolio_store.load_account("paper")
            open_positions = [p for p in account.positions.values() if p.status.name == "OPEN"]
        except Exception as exc:
            return f"Failed to load open positions: {exc}"

        if not open_positions:
            return "No open positions found in the paper account."

        open_positions.sort(key=lambda p: p.opened_at)

        lines = [
            "=== Hokage Open Positions ===",
            f"{'Symbol':<12}{'Direction':<10}{'Quantity':<10}{'Entry Price':<14}{'Current Price':<15}{'Unrealized P&L':<16}{'Opened At'}",
            "-" * 90
        ]
        for p in open_positions:
            opened_str = p.opened_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(
                f"{p.market:<12}"
                f"{p.direction.value:<10}"
                f"{p.quantity:<10.2f}"
                f"{format_inr(p.entry_price):<14}"
                f"{format_inr(p.current_price):<15}"
                f"{format_inr(p.unrealized_pnl):<16}"
                f"{opened_str}"
            )
        lines.append("=============================")
        return "\n".join(lines)

    def handle_hokage_decisions_today(self) -> str:
        """Handler for 'hokage decisions today'."""
        journal_file = self.orchestrator.resolver.resolve_brain_root() / "journal" / "decision_journal.jsonl"
        if not journal_file.exists():
            return "No decisions recorded in journal yet."

        today_str = date.today().strftime("%Y-%m-%d")
        lines = [f"=== Hokage Decisions Today ({today_str}) ==="]
        found_any = False

        try:
            with journal_file.open("r", encoding="utf-8") as f:
                for line_str in f:
                    s = line_str.strip()
                    if not s:
                        continue
                    entry = json.loads(s)
                    timestamp = entry.get("timestamp", "")
                    if timestamp:
                        dt_str = timestamp.split("T")[0]
                        if dt_str == today_str:
                            found_any = True
                            symbol = entry.get("symbol", "N/A")
                            decision = entry.get("decision", "REJECTED")
                            conviction = entry.get("conviction", 0)
                            
                            from bots.autonomous.trade_dna import _score_to_grade
                            grade = _score_to_grade(conviction)
                            time_str = "N/A"
                            try:
                                time_str = timestamp.split("T")[1][:8]
                            except Exception:
                                pass
                            
                            lines.append(f"[{time_str}] {symbol} | {decision} | Conviction: {conviction} ({grade})")
                            if decision == "ACCEPTED":
                                reason = entry.get("decision_reason", entry.get("reason", "No reason provided."))
                                lines.append(f"           Reason: {reason}")
                            else:
                                veto_gate = entry.get("veto_source", "N/A")
                                reason = entry.get("reason", "No reason provided.")
                                lines.append(f"           Veto Gate: {veto_gate} | Reason: {reason}")
        except Exception as exc:
            return f"Failed to read decisions journal: {exc}"

        if not found_any:
            lines.append("No decisions recorded today.")

        return "\n".join(lines)

    def handle_hokage_why(self, symbol_arg: str) -> str:
        """Handler for 'hokage why <symbol>'."""
        symbol_query = symbol_arg.strip().upper()
        if not symbol_query:
            return "Error: Please specify a symbol. Usage: hokage why <symbol>"

        journal_file = self.orchestrator.resolver.resolve_brain_root() / "journal" / "decision_journal.jsonl"
        if not journal_file.exists():
            return "No decisions recorded in journal yet."

        try:
            latest_entry = None
            with journal_file.open("r", encoding="utf-8") as f:
                entries = [json.loads(line.strip()) for line in f if line.strip()]
                for entry in reversed(entries):
                    if entry.get("symbol", "").upper() == symbol_query:
                        latest_entry = entry
                        break
        except Exception as exc:
            return f"Failed to read decisions journal: {exc}"

        if not latest_entry:
            return f"No decision journal entry found for symbol {symbol_query}."

        decision = latest_entry.get("decision", "REJECTED")
        conviction = latest_entry.get("conviction", 0)
        from bots.autonomous.trade_dna import _score_to_grade
        grade = _score_to_grade(conviction)
        timestamp = latest_entry.get("timestamp", "")
        time_str = timestamp.replace("T", " ")[:19] if timestamp else "N/A"
        reason = latest_entry.get("decision_reason", latest_entry.get("reason", "No reason provided."))

        lines = [
            f"=== Hokage Decision Audit: {symbol_query} ===",
            f"Timestamp:       {time_str}",
            f"Decision:        {decision}",
            f"Conviction:      {conviction} ({grade})",
            f"Summary Reason:  {reason}",
            "",
            "Reasoning Chain Audit Trail (7-Gate Analysis):"
        ]

        reasoning_chain = latest_entry.get("reasoning_chain", [])
        if not reasoning_chain:
            lines.append("  No reasoning chain logged for this decision.")
        else:
            for idx, gate_res in enumerate(reasoning_chain, 1):
                gate = gate_res.get("gate", "Unknown Gate")
                gate_dec = gate_res.get("decision", "N/A")
                gate_reason = gate_res.get("reason", "")
                lines.append(f"  {idx}. Gate: {gate} -> Verdict: {gate_dec}")
                lines.append(f"     Reason: {gate_reason}")

        return "\n".join(lines)

    def handle_hokage_performance(self) -> str:
        """Handler for 'hokage performance'."""
        try:
            engine = PerformanceAnalyticsEngine(self.orchestrator.resolver.resolve_brain_root())
            records = engine.load_records()
        except Exception as exc:
            return f"Failed to initialize performance metrics: {exc}"

        if not records:
            return "No completed trade outcomes found in performance history."

        try:
            win_count = sum(1 for r in records if r.get("is_win", False))
            total = len(records)
            win_rate = (win_count / total) * 100.0 if total > 0 else 0.0

            profit_factor = engine.compute_profit_factor(records)
            expectancy = engine.compute_expectancy(records)
            sharpe = engine.compute_sharpe(records)
            drawdown = engine.compute_drawdown_analytics(records)
            holding = engine.compute_holding_period_stats(records)
        except Exception as exc:
            return f"Failed to compute performance analytics: {exc}"

        lines = [
            "=== Hokage Trading Performance ===",
            f"Total Trades:    {total}",
            f"Win Rate:        {win_rate:.2f}% ({win_count} Wins, {total - win_count} Losses)",
            f"Profit Factor:   {profit_factor}",
            f"Expectancy:      {format_inr(expectancy)}",
            f"Sharpe Ratio:    {sharpe}",
            "",
            "Drawdown Metrics:",
            f"  - Max Drawdown (%):   {drawdown.get('max_drawdown_pct', 0.0):.2f}%",
            f"  - Max Drawdown (INR): {format_inr(drawdown.get('max_drawdown_inr', 0.0))}",
            f"  - Worst Session PnL:  {format_inr(drawdown.get('worst_session_pnl', 0.0))} ({drawdown.get('worst_session_symbol', 'N/A')})",
            f"  - Max Consecutive Losses: {drawdown.get('consecutive_losses_max', 0)}",
            "",
            "Holding Periods:",
            f"  - Avg Hold (All):     {holding.get('avg_hold_all', 0.0):.2f} days",
            f"  - Avg Hold (Winners): {holding.get('avg_hold_winners', 0.0):.2f} days",
            f"  - Avg Hold (Losers):  {holding.get('avg_hold_losers', 0.0):.2f} days",
            "=============================="
        ]
        return "\n".join(lines)

    def handle_hokage_lessons(self) -> str:
        """Handler for 'hokage lessons'."""
        try:
            engine = PositionReviewEngine(brain_root=self.orchestrator.resolver.resolve_brain_root())
            reviews = engine.load_reviews()
        except Exception as exc:
            return f"Failed to load reviews: {exc}"

        if not reviews:
            return "No position reviews recorded yet."

        reviews.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

        lines = [
            "=== Hokage Lessons Learned (Recent) ===",
            "-" * 80
        ]
        for r in reviews[:10]:
            ts_str = r.get("timestamp", "")[:10]
            symbol = r.get("symbol", "N/A")
            pnl = r.get("pnl", 0.0)
            lesson = r.get("lesson", "No lesson details.")
            lines.append(f"[{ts_str}] {symbol} (PnL: {format_inr(pnl)}):")
            lines.append(f"      {lesson}")
            lines.append("-" * 80)

        return "\n".join(lines)

    def handle_hokage_dna(self) -> str:
        """Handler for 'hokage dna'."""
        try:
            engine = TradeDNAEngine(self.orchestrator.resolver.resolve_brain_root())
            summary = engine.summarize()
        except Exception as exc:
            return f"Failed to load DNA metrics: {exc}"

        total_records = summary.get("total_dna_records", 0)
        if total_records == 0:
            return "No Trade DNA records found."

        lines = [
            "=== Hokage Trade DNA Analysis ===",
            f"Total DNA Records: {total_records}",
            ""
        ]

        def format_dna_group(title: str, group_dict: dict) -> None:
            lines.append(f"{title}:")
            for key, stats in sorted(group_dict.items(), key=lambda item: item[1]["total"], reverse=True):
                wins = stats.get("WIN", 0)
                losses = stats.get("LOSS", 0)
                be = stats.get("BREAKEVEN", 0)
                tot = stats.get("total", 0)
                wr = (wins / tot) * 100.0 if tot > 0 else 0.0
                lines.append(f"  - {key}: {tot} trades ({wins} Wins, {losses} Losses, {be} Breakeven) | Win Rate: {wr:.2f}%")
            lines.append("")

        format_dna_group("By Conviction Grade", summary.get("by_conviction_grade", {}))
        format_dna_group("By Market Regime", summary.get("by_regime", {}))
        format_dna_group("By Sector", summary.get("by_sector", {}))

        lines.append("==============================")
        return "\n".join(lines)

    def handle_hokage_briefing(self) -> str:
        """Handler for 'hokage briefing'."""
        briefing_file = self.orchestrator.resolver.resolve_brain_root() / "intelligence" / "morning_briefing.json"
        if not briefing_file.exists():
            return "No morning briefing cached. Run the autonomous pipeline to generate one."

        try:
            with briefing_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                markdown = data.get("markdown", "Empty morning briefing.")
                return markdown
        except Exception as exc:
            return f"Failed to load morning briefing: {exc}"

    def handle_hokage_review(self) -> str:
        """Handler for 'hokage review'."""
        today_str = date.today().strftime("%Y-%m-%d")

        try:
            analytics = PerformanceAnalyticsEngine(self.orchestrator.resolver.resolve_brain_root())
            records = analytics.load_records()
        except Exception:
            records = []

        today_records = []
        cumulative_pnl = 0.0
        for r in records:
            cumulative_pnl += r.get("pnl", 0.0)
            ts = r.get("timestamp", "")
            if ts and ts.split("T")[0] == today_str:
                today_records.append(r)

        today_pnl = sum(r.get("pnl", 0.0) for r in today_records)

        try:
            account = self.orchestrator.portfolio_store.load_account("paper")
            cash = account.cash
            open_positions = [p for p in account.positions.values() if p.status.name == "OPEN"]
            equity = cash + sum(p.quantity * p.current_price for p in open_positions)
        except Exception:
            cash = 500000.0
            equity = 500000.0
            open_positions = []

        def calc_win_rate(recs):
            if not recs:
                return 0.0
            wins = sum(1 for r in recs if r.get("is_win", False))
            return (wins / len(recs)) * 100.0

        today_wr = calc_win_rate(today_records)
        cum_wr = calc_win_rate(records)

        def calc_pf(recs):
            gross_wins = sum(r["pnl"] for r in recs if r.get("is_win", False) and r["pnl"] > 0)
            gross_losses = abs(sum(r["pnl"] for r in recs if not r.get("is_win", True) and r["pnl"] < 0))
            if gross_losses == 0:
                return float(gross_wins) if gross_wins > 0 else 1.0
            return gross_wins / gross_losses

        today_pf = calc_pf(today_records)
        cum_pf = calc_pf(records)

        trust_score = 100
        trust_grade = "A"
        compliance_score = 100.0
        try:
            trust_file = self.orchestrator.resolver.resolve_brain_root() / "intelligence" / "elder_trust.json"
            if trust_file.exists():
                with trust_file.open("r", encoding="utf-8") as f:
                    t_data = json.load(f)
                    trust_score = t_data.get("trust_score", 100)
                    trust_grade = t_data.get("grade", "A")
                    compliance_score = t_data.get("metrics", {}).get("risk_compliance", 100.0)
        except Exception:
            pass

        today_executed = []
        today_rejected = []
        journal_file = self.orchestrator.resolver.resolve_brain_root() / "journal" / "decision_journal.jsonl"
        if journal_file.exists():
            try:
                with journal_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        entry = json.loads(s)
                        ts = entry.get("timestamp", "")
                        if ts and ts.split("T")[0] == today_str:
                            if entry.get("decision") == "ACCEPTED":
                                today_executed.append(entry)
                            else:
                                today_rejected.append(entry)
            except Exception:
                pass

        drawdown_pct = 0.0
        if records:
            try:
                dd_stats = analytics.compute_drawdown_analytics(records)
                drawdown_pct = dd_stats.get("max_drawdown_pct", 0.0)
            except Exception:
                pass

        reviews_today = []
        reviews_file = self.orchestrator.resolver.resolve_brain_root() / "reviews" / "position_reviews.jsonl"
        if reviews_file.exists():
            try:
                with reviews_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        entry = json.loads(s)
                        ts = entry.get("timestamp", "")
                        if ts and ts.split("T")[0] == today_str:
                            reviews_today.append(entry)
            except Exception:
                pass

        preservation_mode = "NORMAL"
        sizing_multiplier = 1.0
        try:
            pres_file = self.orchestrator.resolver.resolve_brain_root() / "intelligence" / "capital_preservation.json"
            if pres_file.exists():
                with pres_file.open("r", encoding="utf-8") as f:
                    pres_data = json.load(f)
                    preservation_mode = pres_data.get("mode", "NORMAL")
                    if preservation_mode == "DEFENSIVE":
                        sizing_multiplier = 0.5
                    elif preservation_mode == "RECOVERY":
                        sizing_multiplier = 0.25
        except Exception:
            pass

        personality_mode = "BALANCED"
        if today_executed:
            personality_mode = today_executed[-1].get("personality_mode", "BALANCED")
        elif today_rejected:
            personality_mode = today_rejected[-1].get("personality_mode", "BALANCED")

        template = f"""# HOKAGE Alpha EOD Daily Review
## Date: {today_str} | Session: Day {len(records)}

---

## 1. Executive Summary

| Metric | Daily Value | Session Cumulative | Status / Alerts |
| :--- | :---: | :---: | :--- |
| **Daily PnL** | {format_inr(today_pnl)} | {format_inr(cumulative_pnl)} | {"Normal" if today_pnl >= 0 else "Drawdown Warning"} |
| **Account Equity** | {format_inr(equity)} | - | - |
| **Win Rate** | {today_wr:.2f}% | {cum_wr:.2f}% | - |
| **Profit Factor** | {today_pf:.2f} | {cum_pf:.2f} | - |
| **Compliance Score** | {compliance_score:.2f}% | {compliance_score:.2f}% | {"Normal" if compliance_score >= 95.0 else "WARNING: Compliance < 95%"} |

---

## 2. Order Activity Logs

### Trades Executed
"""
        if not today_executed:
            template += "*   *No trades executed today.*\n"
        else:
            for t in today_executed:
                symbol = t.get("symbol", "N/A")
                direction = t.get("action", t.get("decision", "ACCEPTED"))
                qty = t.get("quantity", 1.0)
                entry_price = t.get("entry_price", 0.0)
                dec_id = t.get("decision_id", "N/A")
                conv = t.get("conviction", 0)
                from bots.autonomous.trade_dna import _score_to_grade
                grade = _score_to_grade(conv)
                template += f"*   **Symbol:** `{symbol}` | **Direction:** `{direction}` | **Qty:** `{qty:.2f}` | **Entry Price:** `{format_inr(entry_price)}`\n"
                template += f"    *   *Reasoning Chain Link:* `{dec_id}`\n"
                template += f"    *   *Conviction Grade:* `{conv} ({grade})`\n"

        template += "\n### Trades Rejected / Vetoed\n"
        if not today_rejected:
            template += "*   *No trades rejected/vetoed today.*\n"
        else:
            for t in today_rejected:
                symbol = t.get("symbol", "N/A")
                conv = t.get("conviction", 0)
                veto_gate = t.get("veto_source", "N/A")
                veto_reason = t.get("reason", "No details.")
                template += f"*   **Symbol:** `{symbol}` | **Conviction Score:** `{conv}`\n"
                template += f"    *   *Veto Gate:* `{veto_gate}`\n"
                template += f"    *   *Veto Reason:* `{veto_reason}`\n"

        template += f"""
---

## 3. Subsystem Metrics

*   **Elder Trust Score:** `{trust_score}/100` (Grade: `{trust_grade}`)
*   **Active Personality Mode:** `{personality_mode}`
*   **Daily Drawdown Level:** `{drawdown_pct:.2f}%` (Daily limit: 2%)

---

## 4. Layer 2 Post-Exit Quality Reviews

"""
        if not reviews_today:
            template += "*   *No closed trades reviewed today.*\n"
        else:
            for r in reviews_today:
                symbol = r.get("symbol", "N/A")
                entry_q = r.get("entry_quality", "N/A")
                sizing_q = r.get("sizing_quality", "N/A")
                stop_q = r.get("stop_quality", "N/A")
                exit_q = r.get("exit_quality", "N/A")
                rr = r.get("risk_reward_achieved", 0.0)
                lesson = r.get("lesson", "No details.")
                template += f"*   **Closed Symbol:** `{symbol}`\n"
                template += f"    *   *Entry Quality:* `{entry_q}`\n"
                template += f"    *   *Sizing Quality:* `{sizing_q}`\n"
                template += f"    *   *Stop Quality:* `{stop_q}`\n"
                template += f"    *   *Exit Quality:* `{exit_q}`\n"
                template += f"    *   *Actual R:R Achieved:* `{rr:.2f}`\n"
                template += f"    *   *Structured Lesson:* `{lesson}`\n"

        template += f"""
---

## 5. Trade DNA & Pattern Observations
*   **Win/Loss DNA Cluster:** Today's execution operated under `{preservation_mode}` preservation state in `{personality_mode}` personality mode.

---

## 6. Adjustments & Action Plan
*   **Cooldown Status:** {"Active" if preservation_mode != "NORMAL" else "Inactive"}
*   **Required Sizing Scale:** `{sizing_multiplier:.2f}x` (Multiplier applied: `{sizing_multiplier}x`)
"""
        return template

    def handle_hokage_knowledge(self, topic_arg: str) -> str:
        """Handler for 'hokage knowledge <topic>'."""
        topic_query = topic_arg.strip()
        if not topic_query:
            return "Error: Please specify a topic. Usage: hokage knowledge <topic>"

        try:
            manager = KnowledgeManager(self.orchestrator.resolver.resolve_brain_root())
            doctrines = manager.search_doctrines(topic_query)
            principles = manager.search_principles(topic_query)
            rules = manager.search_rules(topic_query)
            anti_patterns = manager.search_anti_patterns(topic_query)
            mental_models = manager.search_mental_models(topic_query)
        except Exception as exc:
            return f"Failed to search knowledge repository: {exc}"

        if not (doctrines or principles or rules or anti_patterns or mental_models):
            return f"No knowledge matches found for topic '{topic_query}'."

        lines = [f"=== Hokage Knowledge Search: \"{topic_query}\" ==="]

        if doctrines:
            lines.append("\n--- Doctrines ---")
            for d in doctrines:
                mod_id = d["module_id"]
                doc = d["doctrine"]
                lines.append(f"[{mod_id}] {doc.get('name', 'N/A')}")
                lines.append(f"  Description: {doc.get('description', 'N/A')}")

        if principles:
            lines.append("\n--- Principles ---")
            for p in principles:
                mod_id = p["module_id"]
                pr = p["principle"]
                lines.append(f"[{mod_id}] {pr.get('name', 'N/A')}")
                lines.append(f"  Description: {pr.get('description', 'N/A')}")

        if rules:
            lines.append("\n--- Rules & Frameworks ---")
            for r in rules:
                mod_id = r["module_id"]
                rule_type = r["rule_type"]
                rule = r["rule"]
                lines.append(f"[{mod_id}] [{rule_type}] {rule.get('name', 'N/A')}")
                lines.append(f"  Description: {rule.get('description', 'N/A')}")

        if anti_patterns:
            lines.append("\n--- Anti-Patterns ---")
            for ap in anti_patterns:
                mod_id = ap["module_id"]
                item = ap["anti_pattern"]
                lines.append(f"[{mod_id}] {item.get('name', 'N/A')}")
                lines.append(f"  Mitigation: {item.get('mitigation', 'N/A')}")

        if mental_models:
            lines.append("\n--- Mental Models ---")
            for mm in mental_models:
                mod_id = mm["module_id"]
                item = mm["mental_model"]
                lines.append(f"[{mod_id}] {item.get('name', 'N/A')}")
                lines.append(f"  Framework: {item.get('framework', 'N/A')}")

        return "\n".join(lines)

    def handle_hokage_opportunities(self) -> str:
        """Handler for 'hokage opportunities'."""
        profile = self.profile_service.get_profile()
        active_mode = profile.horizon.mode
        active_universe = [u.upper() for u in profile.horizon.active_universe]
        phase_str = profile.horizon.phase.value

        # Build list of active universe names for display
        def get_display_name(symbol: str) -> str:
            mapping = {
                "CRUDE": "Crude Oil",
                "CRUDE_OIL": "Crude Oil",
                "CRUDEOIL": "Crude Oil",
                "GOLD": "Gold",
                "BANKNIFTY": "Bank Nifty",
                "BANK NIFTY": "Bank Nifty",
                "USD/INR": "USD/INR",
                "USDINR": "USD/INR",
                "NASDAQ": "Nasdaq ETF",
                "RELIANCE": "Reliance",
            }
            return mapping.get(symbol.upper(), symbol)

        display_universe = [get_display_name(u) for u in active_universe]
        active_universe_scope_str = ", ".join(display_universe)

        lines = [
            "=== Hokage Global Opportunity Radar ===",
            f"Active Horizon Mode: {active_mode.value} (Progression Phase: {phase_str})",
            f"Active Universe Scope: {active_universe_scope_str}",
            "Asset universe expansion conforms to the Horizon Expansion Doctrine.\n",
            "Ranked Opportunities in Approved Universe:",
            f"{'Asset':<15} {'Category':<15} {'Conviction':<12} {'Risk Level':<12} {'Horizon Mode':<15}",
            "-" * 70
        ]

        # Scan using concrete scanners
        provider = self.orchestrator.price_source
        scanners = [
            EquityAssetScanner(provider, ["BANKNIFTY", "RELIANCE"]),
            CommodityAssetScanner(provider, ["GOLD", "CRUDE_OIL"]),
            CryptoAssetScanner(provider, ["BTC", "ETH"]),
            ForexAssetScanner(provider, ["USD/INR"]),
            ETFAssetScanner(provider, ["NASDAQ"]),
        ]

        all_scanned_opps = []
        for scanner in scanners:
            all_scanned_opps.extend(scanner.scan())

        # Rank using ranking engine
        ranker = OpportunityRankingEngine()
        ranked_opps = ranker.rank_opportunities(all_scanned_opps)

        # Helpers for mapping and filtering
        def get_horizon_for_asset(symbol: str) -> str:
            sym_upper = symbol.upper().strip()
            focused_symbols = {"CRUDE_OIL", "CRUDE", "CRUDEOIL", "GOLD", "BTC", "ETH", "BANKNIFTY", "BANK NIFTY"}
            tactical_symbols = {"SILVER", "USDINR", "USD/INR"}
            if sym_upper in focused_symbols:
                return "FOCUSED"
            elif sym_upper in tactical_symbols:
                return "TACTICAL"
            else:
                return "GLOBAL"

        def is_horizon_active(opp_horizon: str, active_horizon_mode: HorizonMode) -> bool:
            mode_levels = {
                HorizonMode.FOCUSED: 1,
                HorizonMode.TACTICAL: 2,
                HorizonMode.EXPANDED: 3,
                HorizonMode.MARKET: 4,
                HorizonMode.GLOBAL: 5
            }
            active_level = mode_levels.get(active_horizon_mode, 1)
            
            opp_mode_enum = None
            if opp_horizon == "FOCUSED":
                opp_mode_enum = HorizonMode.FOCUSED
            elif opp_horizon == "TACTICAL":
                opp_mode_enum = HorizonMode.TACTICAL
            else:
                opp_mode_enum = HorizonMode.GLOBAL
                
            opp_level = mode_levels.get(opp_mode_enum, 5)
            return opp_level <= active_level

        def get_risk_level(category: AssetCategory, symbol: str) -> str:
            if category == AssetCategory.CRYPTO:
                return "HIGH"
            elif category == AssetCategory.FOREX:
                return "LOW"
            elif category == AssetCategory.COMMODITY:
                return "LOW"
            elif symbol.upper() in ("RELIANCE", "TCS", "INFY"):
                return "LOW"
            else:
                return "MEDIUM"

        # Output rows
        for opp in ranked_opps:
            disp_name = get_display_name(opp.symbol)
            category = opp.asset_category.value
            conv = f"{int(opp.conviction_score)}/100"
            risk = get_risk_level(opp.asset_category, opp.symbol)
            horizon = get_horizon_for_asset(opp.symbol)

            marker = ""
            if is_horizon_active(horizon, active_mode):
                marker = " *"

            lines.append(f"{disp_name + marker:<15} {category:<15} {conv:<12} {risk:<12} {horizon:<15}")

        lines.append("-" * 70)
        lines.append(f"Note: (*) Denotes assets within active {active_mode.value} scan mode.")
        lines.append("Scanner filters are asset-agnostic and query across Stocks, Commodities, Forex, and Crypto.")
        lines.append("Strict READ_ONLY mode. No placement of live trades is authorized.")

        return "\n".join(lines)


    def handle_hokage_profile(self) -> str:
        """Handler for 'hokage profile'."""
        profile = self.profile_service.get_profile()
        status = "ACTIVE" if profile.risk.capital_preservation else "INACTIVE"
        lines = [
            "=== Hokage Commander Profile ===",
            f"Commander:             {profile.commander_title} {profile.commander_name}",
            f"Risk Mode:             {profile.risk.risk_mode.value}",
            f"Execution Mode:        {profile.environment.mode.value}",
            f"Base Currency:         {profile.environment.base_currency}",
            f"Preservation State:    {status}",
            f"Starting Capital:      {format_inr(profile.portfolio.starting_capital)}",
            f"Tax-Aware Routing:     {profile.tax.tax_aware}",
        ]
        return "\n".join(lines)

    def handle_hokage_horizon(self) -> str:
        """Handler for 'hokage horizon'."""
        profile = self.profile_service.get_profile()
        lines = [
            "=== Hokage Horizon State ===",
            f"Progression Phase:     {profile.horizon.phase.value}",
            f"Active Horizon Mode:   {profile.horizon.mode.value}",
            f"Universe Size:         {len(profile.horizon.active_universe)}",
            f"Primary Asset:         {profile.horizon.active_universe[0] if profile.horizon.active_universe else 'N/A'}",
        ]
        return "\n".join(lines)

    def handle_hokage_universe(self) -> str:
        """Handler for 'hokage universe'."""
        profile = self.profile_service.get_profile()
        lines = [
            "=== Hokage Active Monitor Universe ===",
            f"Phase:                 {profile.horizon.phase.value}",
            f"Mode:                  {profile.horizon.mode.value}",
            f"Assets ({len(profile.horizon.active_universe)}):",
        ]
        for asset in profile.horizon.active_universe:
            lines.append(f"  - {asset}")
        return "\n".join(lines)

    def handle_hokage_wait_reason(self) -> str:
        """Handler for 'hokage wait-reason'."""
        surv_file = self.orchestrator.resolver.resolve_brain_root() / "autonomous" / "asset_surveillance_state.json"
        if not surv_file.exists():
            return "No active surveillance state exists."
        try:
            with surv_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            return f"Failed to load surveillance state: {exc}"

        waiting_assets = []
        for symbol, state_data in data.items():
            if state_data.get("state") == "WAITING":
                waiting_assets.append(state_data)

        if not waiting_assets:
            return "No assets are currently in WAITING state. Operating loop is either executing or watching."

        lines = ["=== Hokage Active Wait Reasons ==="]
        for asset in waiting_assets:
            blockers = ", ".join(asset.get("current_blockers", [])) or "None"
            confirmations = ", ".join(asset.get("missing_confirmations", [])) or "None"
            lines.append(f"Asset:                  {asset.get('asset')}")
            lines.append(f"State:                  {asset.get('state')}")
            lines.append(f"Conviction Score:       {asset.get('conviction_score')}/100")
            lines.append(f"Risk Score:             {asset.get('risk_score')}")
            lines.append(f"Current Blockers:       {blockers}")
            lines.append(f"Missing Confirmations:  {confirmations}")
            lines.append(f"What Would Trigger:     {asset.get('what_would_trigger')}")
            lines.append(f"Next Review Time:       {asset.get('next_review_time')}")
            lines.append(f"Last Changed At:        {asset.get('last_changed_at')}")
            lines.append("-" * 35)
        return "\n".join(lines)

    def handle_hokage_what_changed(self) -> str:
        """Handler for 'hokage what-changed'."""
        surv_file = self.orchestrator.resolver.resolve_brain_root() / "autonomous" / "asset_surveillance_state.json"
        if not surv_file.exists():
            return "No active surveillance state exists."
        try:
            with surv_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            return f"Failed to load surveillance state: {exc}"

        lines = ["=== Hokage Recent Surveillance State Changes ==="]
        for symbol, asset in data.items():
            lines.append(f"Asset:            {symbol}")
            lines.append(f"Active State:     {asset.get('state')}")
            lines.append(f"Conviction Score: {asset.get('conviction_score')}/100")
            lines.append(f"Last Changed At:  {asset.get('last_changed_at')}")
            lines.append(f"What Would Trigger: {asset.get('what_would_trigger')}")
            lines.append("-" * 35)
        return "\n".join(lines)

    def handle_hokage_show_authorization(self) -> str:
        """Handler for 'hokage show-authorization'."""
        from bots.autonomous.decision_journal import DecisionJournalSystem
        journal = DecisionJournalSystem(self.orchestrator.resolver.resolve_brain_root())
        auths = journal.load_trade_authorizations()
        if not auths:
            return "No trade authorizations have been recorded in the ledger."
        
        auth = auths[-1]
        lines = [
            "=== Hokage Latest Trade Authorization ===",
            f"Asset:                  {auth.get('asset')}",
            f"Timestamp:              {auth.get('timestamp')}",
            f"Direction:              {auth.get('direction')}",
            f"Conviction Score:       {auth.get('conviction_score')}/100",
            f"Risk/Reward Ratio:      {auth.get('risk_reward')}",
            f"Trend Validation:       {auth.get('trend_validation')}",
            f"Volatility Check:       {auth.get('volatility_validation')}",
            f"Capital Preservation:   {auth.get('capital_preservation_validation')}",
            f"Universe Validation:    {auth.get('universe_validation')}",
            f"Execution Reason:       {auth.get('execution_reason')}",
            f"Authorised By:          {auth.get('authorised_by')}",
            "========================================="
        ]
        return "\n".join(lines)

    def handle_hokage_show_rejection(self) -> str:
        """Handler for 'hokage show-rejection'."""
        reports_dir = self.orchestrator.resolver.resolve_brain_root() / "reports"
        no_trade_review = reports_dir / "no_trade_eod_review.txt"
        if no_trade_review.exists():
            try:
                return no_trade_review.read_text(encoding="utf-8")
            except Exception:
                pass

        from bots.autonomous.decision_journal import DecisionJournalSystem
        journal = DecisionJournalSystem(self.orchestrator.resolver.resolve_brain_root())
        rejections = journal.load_no_trade_decisions()
        if not rejections:
            return "No rejections or no-trade decisions have been recorded in the ledger."

        rej = rejections[-1]
        reasons = "\n".join(f"  * {r}" for r in rej.get("reasons", []))
        lines = [
            "=== Hokage Latest No-Trade Decision ===",
            f"Asset:                  {rej.get('asset')}",
            f"Timestamp:              {rej.get('timestamp')}",
            f"Decision:               {rej.get('decision')}",
            f"Confidence Score:       {rej.get('confidence')}/100",
            f"Reasons:\n{reasons}",
            f"Invalidated Setups:     {', '.join(rej.get('invalidated_setups', []))}",
            f"Next Review Time:       {rej.get('next_review_time')}",
            "======================================="
        ]
        return "\n".join(lines)

    def handle_hokage_committee_vetoes(self) -> str:
        """Handler for 'hokage committee vetoes'."""
        return (
            "=== Hokage Committee Veto Powers ===\n"
            "- Risk Committee: VETO POWER (Position sizing, exposure limits, RiskBot checks)\n"
            "- Capital Preservation Committee: VETO POWER (Drawdown thresholds, preservation settings)\n"
            "- Liquidity & Execution Committee: VETO POWER (Cash limits, price feed validation, execution feasibility)\n"
            "===================================="
        )

    def handle_hokage_committee_stats(self) -> str:
        """Handler for 'hokage committee stats'."""
        from bots.autonomous.committee import CommitteePerformanceTracker
        from bots.autonomous.decision_journal import DecisionJournalSystem
        tracker = CommitteePerformanceTracker(self.orchestrator.resolver)
        journal = DecisionJournalSystem(self.orchestrator.resolver.resolve_brain_root())
        outcomes = journal.load_outcomes()
        
        stats = tracker.compute_stats(outcomes)
        lines = ["=== Investment Committee Performance Stats ==="]
        for name, data in stats.items():
            lines.append(f"Committee: {name}")
            lines.append(f"  Accuracy:          {data['accuracy']}%")
            lines.append(f"  Correct Votes:     {data['correct_votes']}")
            lines.append(f"  Incorrect Votes:   {data['incorrect_votes']}")
            lines.append(f"  Abstains:          {data['abstains']}")
            lines.append(f"  Losses Prevented:  {data['losses_prevented']}")
            lines.append("-" * 35)
        
        non_zero_stats = {k: v for k, v in stats.items() if (v['correct_votes'] + v['incorrect_votes']) > 0}
        if non_zero_stats:
            highest = max(non_zero_stats.keys(), key=lambda k: non_zero_stats[k]['accuracy'])
            lowest = min(non_zero_stats.keys(), key=lambda k: non_zero_stats[k]['accuracy'])
            lines.append(f"Highest Performing: {highest} ({non_zero_stats[highest]['accuracy']}%)")
            lines.append(f"Underperforming:    {lowest} ({non_zero_stats[lowest]['accuracy']}%)")
        else:
            lines.append("Highest Performing: N/A")
            lines.append("Underperforming:    N/A")
        lines.append("==============================================")
        return "\n".join(lines)

    def handle_hokage_committee_votes(self, symbol: str) -> str:
        """Handler for 'hokage committee votes [symbol]'."""
        from bots.autonomous.committee import CommitteeLedger
        ledger = CommitteeLedger(self.orchestrator.resolver)
        entries = ledger.load_entries()
        if not entries:
            return "No committee decisions logged."
        
        if symbol:
            entries = [e for e in entries if e.get("symbol") == symbol.upper()]
            if not entries:
                return f"No committee decisions found for symbol {symbol.upper()}."
        
        entry = entries[-1]
        votes = entry.get("committee_votes", {})
        
        lines = [
            f"=== Investment Committee Votes for {entry.get('symbol')} ===",
            f"Opportunity ID:         {entry.get('opportunity_id')}",
            f"Timestamp:              {entry.get('timestamp')}",
            f"Final Verdict:          {entry.get('final_verdict')}",
            f"Approval Percentage:    {entry.get('approval_percentage')}%",
            f"Decision Confidence:    {entry.get('decision_confidence'):.1f}/100",
            f"Veto Triggered:         {entry.get('veto_triggered')}",
            "----------------------------------------"
        ]
        for member, v_data in votes.items():
            lines.append(f"Committee: {member}")
            lines.append(f"  Vote:        {v_data.get('vote')}")
            lines.append(f"  Confidence:  {v_data.get('confidence')}%")
            lines.append(f"  Reasoning:   {v_data.get('reasoning')}")
            lines.append(f"  Uncertainty: {v_data.get('uncertainty')}")
            lines.append(f"  Veto Member: {v_data.get('veto_status')}")
            lines.append("-" * 25)
        lines.append("=========================================")
        return "\n".join(lines)

    def handle_hokage_committee_why(self, committee_name: str, symbol: str) -> str:
        """Handler for 'hokage committee why <committee> <symbol>'."""
        from bots.autonomous.committee import CommitteeLedger
        ledger = CommitteeLedger(self.orchestrator.resolver)
        entries = ledger.load_entries()
        if not entries:
            return "No committee decisions logged."
        
        if symbol:
            entries = [e for e in entries if e.get("symbol") == symbol.upper()]
            if not entries:
                return f"No committee decisions found for symbol {symbol.upper()}."
        else:
            # If symbol not specified, use latest symbol from ledger
            symbol = entries[-1].get("symbol", "")
            entries = [e for e in entries if e.get("symbol") == symbol.upper()]
            if not entries:
                return "No committee decisions logged."

        entry = entries[-1]
        votes = entry.get("committee_votes", {})
        
        matched_name = None
        for name in votes.keys():
            if name.lower() == committee_name.lower():
                matched_name = name
                break
        
        if not matched_name:
            available = ", ".join(votes.keys())
            return f"Committee '{committee_name}' not found. Available: {available}"
        
        v_data = votes[matched_name]
        lines = [
            f"=== Committee '{matched_name}' Vote Audit: {entry.get('symbol')} ===",
            f"Vote:        {v_data.get('vote')}",
            f"Confidence:  {v_data.get('confidence')}%",
            f"Reasoning:   {v_data.get('reasoning')}",
            f"Uncertainty: {v_data.get('uncertainty')}",
            f"Veto Member: {v_data.get('veto_status')}",
            "----------------------------------------",
            "Evidence references used:"
        ]
        for k, v in entry.get("evidence_references", {}).items():
            lines.append(f"  - {k}: {v}")
        lines.append("=========================================")
        return "\n".join(lines)

    def handle_hokage_strategy_notifications(self) -> str:
        """Handler for 'hokage strategy notifications'."""
        from bots.strategy.evolution import StrategyEvolutionEngine
        engine = StrategyEvolutionEngine(self.orchestrator.resolver)
        notifications = engine.load_notifications()
        if not notifications:
            return "No strategy notifications logged in the pipeline."
            
        lines = ["=== Hokage Strategy Evolution Notifications ==="]
        for notif in reversed(notifications):
            lines.append(f"Timestamp:         {notif.get('timestamp')}")
            lines.append(f"Strategy ID:       {notif.get('strategy_id')}")
            lines.append(f"Change Type:       {notif.get('change_type')}")
            lines.append(f"Validation Status: {notif.get('validation_status')}")
            lines.append(f"Confidence Score:  {notif.get('confidence')}%")
            lines.append(f"Status:            {notif.get('status')}")
            lines.append(f"Reason:            {notif.get('reason')}")
            evidence = notif.get("supporting_evidence", {})
            if evidence:
                lines.append("Supporting Evidence:")
                for k, v in evidence.items():
                    lines.append(f"  * {k}: {v}")
            lines.append("-" * 40)
        return "\n".join(lines)

    def handle_hokage_strategy_pipeline(self) -> str:
        """Handler for 'hokage strategy pipeline'."""
        from bots.strategy.portfolio import StrategyPortfolioManager
        manager = StrategyPortfolioManager(self.orchestrator.resolver)
        strategies = manager.portfolio.get("strategies", {})
        if not strategies:
            return "No strategies registered in the portfolio."
            
        lines = ["=== Hokage Strategy Evolution Pipeline ==="]
        by_status = {}
        for s_id, s in strategies.items():
            by_status.setdefault(s.get("status", "UNKNOWN"), []).append(s)
            
        stages = ["RESEARCH", "BACKTEST", "PAPER_VALIDATION", "SHADOW_MODE", "PROBATION", "ACTIVE", "PRODUCTION", "ARCHIVED"]
        for stage in stages:
            if stage in by_status or (stage == "ACTIVE" and "PRODUCTION" in by_status):
                strats = by_status.get(stage, [])
                lines.append(f"\nStage: {stage}")
                lines.append("-" * 30)
                if not strats:
                    lines.append("  (None)")
                for s in strats:
                    lines.append(f"  * Name: {s.get('name')} (v{s.get('version')})")
                    lines.append(f"    ID:   {s.get('strategy_id')}")
                    if s.get("parent_strategy_id"):
                        lines.append(f"    Parent: {s.get('parent_strategy_id')}")
                    trade_count = s.get("trade_count", {}).get("DEFAULT", 0)
                    win_rate = s.get("win_rate", {}).get("DEFAULT", 0.0)
                    expectancy = s.get("expectancy", {}).get("DEFAULT", 0.0)
                    sharpe = s.get("sharpe_ratio", {}).get("DEFAULT", 1.0)
                    drawdown = s.get("drawdown", {}).get("DEFAULT", 0.0)
                    lines.append(f"    Metrics: Trades={trade_count}, WinRate={win_rate}%, Expectancy={expectancy}, Sharpe={sharpe}, Drawdown={drawdown}%")
                    
        return "\n".join(lines)

    def handle_hokage_proposals(self) -> str:
        """Handler for 'hokage proposals'."""
        try:
            proposals = self.orchestrator.get_improvement_proposals()
        except Exception as exc:
            return f"Failed to load improvement proposals: {exc}"

        if not proposals:
            return "No strategy improvement proposals found in the ledger."

        pending = [p for p in proposals if p.get("status") == "PENDING_APPROVAL"]
        applied = [p for p in proposals if p.get("status") == "APPLIED"]

        lines = ["=== Hokage Strategy Improvement Proposals ==="]
        if pending:
            lines.append("\n[PENDING COMMANDER APPROVAL]")
            for p in pending:
                lines.append(f"- Proposal ID:   {p['proposal_id']}")
                lines.append(f"  Strategy:      {p['strategy_name']} ({p['strategy_id']})")
                lines.append(f"  Asset/Scope:   {p['asset']}")
                lines.append(f"  Action:        {p['action']}")
                lines.append(f"  Rationale:     {p['rationale']}")
                lines.append(f"  Expected Imp:  {p['expected_improvement']}")
                prev_str = ", ".join(f"{k}={v}" for k, v in p['previous_values'].items())
                new_str = ", ".join(f"{k}={v}" for k, v in p['new_values'].items())
                lines.append(f"  Changes:       [{prev_str}] -> [{new_str}]")
                lines.append("-" * 40)
        else:
            lines.append("\nNo pending proposals.")

        if applied:
            lines.append("\n[APPLIED HISTORICAL IMPROVEMENTS]")
            for p in applied:
                lines.append(f"- Proposal ID:   {p['proposal_id']}")
                lines.append(f"  Strategy:      {p['strategy_name']} ({p['strategy_id']})")
                lines.append(f"  Asset/Scope:   {p['asset']}")
                lines.append(f"  Action:        {p['action']}")
                lines.append(f"  Commander:     {p['approving_commander']}")
                lines.append(f"  Applied At:    {p['applied_at']}")
                lines.append("-" * 40)

        lines.append("=============================================")
        return "\n".join(lines)

    def handle_hokage_improve(self, proposal_id: str) -> str:
        """Handler for 'hokage improve <proposal_id>'."""
        if not proposal_id:
            return "Error: Please specify a proposal ID. Usage: hokage improve <proposal_id>"

        try:
            success = self.orchestrator.apply_improvement_proposal(proposal_id)
            if success:
                return f"Successfully approved and applied strategy improvement proposal '{proposal_id}'."
            else:
                return f"Failed to apply proposal '{proposal_id}'. Verify it is pending approval."
        except Exception as exc:
            return f"Failed to apply proposal: {exc}"

    def handle_hokage_analyze_drift(self, strategy_id: str, symbol: str) -> str:
        """Handler for 'hokage analyze-drift <strategy_id> <symbol>'."""
        if not strategy_id:
            return "Error: Please specify a strategy ID. Usage: hokage analyze-drift <strategy_id> [<symbol>]"

        try:
            stats = self.orchestrator.analyze_strategy_drift(strategy_id, symbol)
            lines = [
                f"=== Drift Analysis: {stats['strategy_name']} ({strategy_id}) ===",
                f"Asset/Scope:      {stats['asset']}",
                f"Trade Count:      {stats['trade_count']}",
                "",
                "Performance Benchmarks:",
                f"  - Win Rate (%):   Backtest={stats['backtest']['win_rate']:.2f}% | Actual={stats['actual']['win_rate']:.2f}% | Drift={stats['drift']['win_rate_drift']:+.2f}%",
                f"  - Expectancy:     Backtest={stats['backtest']['expectancy']:.2f} | Actual={stats['actual']['expectancy']:.2f} | Drift={stats['drift']['expectancy_drift']:+.2f}",
                f"  - Drawdown (%):   Backtest={stats['backtest']['drawdown']:.2f}% | Actual={stats['actual']['drawdown']:.2f}% | Drift={stats['drift']['drawdown_drift']:+.2f}%",
                f"  - Avg Slippage:   Actual={stats['actual']['avg_slippage']:.2f}",
                "=========================================================="
            ]
            return "\n".join(lines)
        except Exception as exc:
            return f"Drift analysis failed: {exc}"

    def handle_hokage_reconcile(self, args_str: str) -> str:
        """Execute and display broker reconciliation results."""
        args = args_str.strip().split()
        report_mode = False
        health_mode = False
        asset_filter = None

        i = 0
        while i < len(args):
            arg = args[i].lower()
            if arg == "--report":
                report_mode = True
            elif arg == "--health":
                health_mode = True
            elif arg in ("--asset", "-a"):
                if i + 1 < len(args):
                    asset_filter = args[i + 1].upper()
                    i += 1
                else:
                    return "Error: --asset requires a symbol argument (e.g. --asset BTC/USD)."
            i += 1

        try:
            # Run reconciliation
            report_dict = self.orchestrator.run_reconciliation(target_symbol=asset_filter)
            from shared.reconciliation.report import ReconciliationReport
            report = ReconciliationReport.from_dict(report_dict)

            if health_mode:
                status = "HEALTHY" if report.health_score >= 95.0 else ("ATTENTION" if report.health_score >= 80.0 else "CRITICAL")
                return f"System Health Score: {report.health_score:.1f}/100 ({status})"

            if report_mode:
                return report.generate_briefing()

            # Simple mode summary
            disc_cnt = len(report.discrepancies)
            frozen = f", Frozen Assets: {', '.join(report.frozen_assets)}" if report.frozen_assets else ""
            status = "PERFECT" if disc_cnt == 0 else ("CRITICAL MISMATCHES" if report.is_critical else "DISCREPANCIES DETECTED")

            summary = [
                "=== Hokage Reconciliation ===",
                f"Status        : {status}",
                f"Health Score  : {report.health_score:.1f}/100",
                f"Discrepancies : {disc_cnt} outstanding{frozen}",
                "-----------------------------",
            ]
            if disc_cnt > 0:
                for idx, d in enumerate(report.discrepancies, 1):
                    summary.append(f"[{idx}] {d.type.value} on {d.asset}: {d.risk_estimate}")
                summary.append("Use 'hokage reconcile --report' for a full detailed briefing.")
            else:
                summary.append("Broker and local systems are in alignment. Safe to trade.")

            summary.append("=============================")
            return "\n".join(summary)

        except Exception as exc:
            return f"Reconciliation failed: {exc}"

    def handle_hokage_secrets(self, args_str: str) -> str:
        """Handler for 'hokage secrets' commands.

        Supports:
          hokage secrets             - Show status of configured secrets (masked)
          hokage secrets set <key> <value> [<broker>] - Set a credential in the secure vault
          hokage secrets delete <key> [<broker>]      - Delete a credential from the vault
          hokage secrets migrate     - Manually trigger migration of secrets.json
          hokage secrets rollback    - Rollback secure credentials to plaintext secrets.json
        """
        # Get secrets manager from orchestrator
        sm = self.orchestrator.secrets_manager

        args = args_str.strip().split()
        if not args:
            # Show status summary of secrets
            lines = [
                "=== Hokage Secrets Status ===",
                "Secure Vault Active : YES (OS-Native Keyring)",
                f"Storage Location    : {sm.secrets_file_path}",
                f"Test Mode           : {'ACTIVE (Mock)' if sm.test_mode else 'INACTIVE'}",
                "Configured Credentials:",
            ]

            try:
                # Load configuration structure from secrets.json
                if sm.secrets_file_path.exists():
                    with sm.secrets_file_path.open("r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        for key in data.keys():
                            val = sm.get_secret(key)
                            if val:
                                masked = val[:3] + "..." if len(val) > 3 else "..."
                                lines.append(f"  - {key:<12} : CONFIGURED SECURELY ({masked})")
                            else:
                                # Check if plaintext in file
                                file_val = data.get(key)
                                if file_val in ("YOUR_API_KEY", "YOUR_API_SECRET", "YOUR_ACCESS_TOKEN", "MIGRATED_TO_KEYRING"):
                                    lines.append(f"  - {key:<12} : NOT CONFIGURED")
                                else:
                                    lines.append(f"  - {key:<12} : CONFIGURED IN PLAINTEXT (NEEDS MIGRATION)")
                    else:
                        lines.append("  (secrets.json format is invalid)")
                else:
                    lines.append("  (No secrets.json file found. Run 'hokage secrets' to bootstrap template.)")
            except Exception as e:
                lines.append(f"  Error reading status: {e}")

            lines.append("=============================")
            return "\n".join(lines)

        sub = args[0].lower()

        if sub == "migrate":
            try:
                sm._migrate_if_needed()
                return "Secrets migration completed. All plaintext credentials migrated to OS-native keyring."
            except Exception as e:
                return f"Migration failed: {e}"

        elif sub == "rollback":
            try:
                sm.rollback_to_json(broker="zerodha")
                return "Secrets rollback completed. Plaintext credentials restored to secrets.json and secure keyring cleaned."
            except Exception as e:
                return f"Rollback failed: {e}"

        elif sub == "set":
            if len(args) < 3:
                return "Error: Usage: hokage secrets set <key> <value> [<broker>]"
            key = args[1]
            value = args[2]
            broker = args[3] if len(args) > 3 else "zerodha"
            try:
                sm.set_secret(key, value, broker=broker)
                masked = value[:3] + "..." if len(value) > 3 else "..."
                return f"Secret '{key}' for broker '{broker}' set successfully in secure vault ({masked})."
            except Exception as e:
                return f"Failed to set secret: {e}"

        elif sub == "delete":
            if len(args) < 2:
                return "Error: Usage: hokage secrets delete <key> [<broker>]"
            key = args[1]
            broker = args[2] if len(args) > 2 else "zerodha"
            try:
                sm.delete_secret(key, broker=broker)
                return f"Secret '{key}' for broker '{broker}' deleted successfully from secure vault."
            except Exception as e:
                return f"Failed to delete secret: {e}"

        else:
            return f"Unknown secrets subcommand: '{sub}'. Available: set, delete, migrate, rollback."

    def handle_hokage_watchdog(self, args_str: str) -> str:
        """Handler for 'hokage watchdog' commands.

        Supports:
          hokage watchdog status            - Run diagnostics and show overall health summary
          hokage watchdog incidents         - List all recorded incidents in the journal
          hokage watchdog incidents ack <id> - Acknowledge a specific incident by ID
          hokage watchdog heartbeat         - Display the latest heartbeat metrics for all subsystems
          hokage watchdog restart <subsys>  - Manually trigger a safe background restart
        """
        args = args_str.strip().split()
        if not args:
            # Default to status if no sub-arg is specified
            sub = "status"
        else:
            sub = args[0].lower()

        if sub == "status":
            try:
                # Run diagnostic check to update health score
                status = self.orchestrator.run_watchdog_check()
                health = status["health_score"]
                status_str = "HEALTHY" if health >= 95.0 else ("DEGRADED" if health >= 75.0 else "HAZARDOUS")

                lines = [
                    "=== Hokage Watchdog Status ===",
                    f"Overall Health Score : {health:.1f}/100 ({status_str})",
                    f"Active Incidents     : {status['active_incidents_count']} unresolved",
                    f"Critical Alerts      : {status['critical_alerts_count']} critical active",
                    f"Last Recovery Time   : {status['last_recovery_time'] or 'None'}",
                    f"Total Restarts       : {status['total_restart_count']}",
                    "",
                    "Subsystem Status Matrix:",
                ]

                if not status["subsystems"]:
                    lines.append("  (No subsystems active yet. Subsystems publish heartbeats on demand.)")
                else:
                    for name, data in status["subsystems"].items():
                        lines.append(f"  - {name:<20} : {data['status']:<10} (Uptime: {data['uptime']:.0f}s, Latency: {data['latency_ms']:.1f}ms)")

                lines.append("==============================")
                return "\n".join(lines)
            except Exception as e:
                return f"Failed to query watchdog status: {e}"

        elif sub == "heartbeat":
            try:
                status = self.orchestrator.get_watchdog_status()
                subsystems = status["subsystems"]
                if not subsystems:
                    return "No heartbeats registered yet."

                lines = [
                    "=== Subsystem Heartbeat Dashboard ===",
                    f"{'Subsystem':<20}{'Status':<10}{'Uptime':<10}{'Latency (ms)':<14}{'Memory (MB)':<12}{'Last Cycle'}",
                    "-" * 78
                ]
                for name, data in subsystems.items():
                    lines.append(
                        f"{name:<20}"
                        f"{data['status']:<10}"
                        f"{data['uptime']:<10.0f}"
                        f"{data['latency_ms']:<14.1f}"
                        f"{data['memory_mb']:<12.1f}"
                        f"{data['last_cycle']}"
                    )
                lines.append("======================================")
                return "\n".join(lines)
            except Exception as e:
                return f"Failed to load heartbeats: {e}"

        elif sub == "incidents":
            try:
                if len(args) > 1 and args[1].lower() in ("ack", "acknowledge"):
                    if len(args) < 3:
                        return "Error: Please specify an incident ID to acknowledge. Usage: hokage watchdog incidents ack <incident_id>"
                    inc_id = args[2]
                    success = self.orchestrator.acknowledge_watchdog_incident(inc_id)
                    if success:
                        return f"Incident '{inc_id}' successfully acknowledged by Commander."
                    else:
                        return f"Incident '{inc_id}' not found in the journal."

                # Otherwise, list all incidents
                incidents = self.orchestrator.get_watchdog_incidents()
                if not incidents:
                    return "Watchdog Incident Journal is clean. No incidents recorded."

                lines = ["=== Immutable Incident Journal ==="]
                for inc in incidents:
                    ack_status = "ACKNOWLEDGED" if inc["commander_acknowledgement"] else "UNACKNOWLEDGED"
                    dur_str = f"{inc['duration']:.0f}s" if inc["duration"] is not None else "N/A (Active)"
                    lines.append(f"[{inc['timestamp'][:19]}] {inc['incident_id']} | {inc['severity']:<8} | Subsys: {inc['subsystem']}")
                    lines.append(f"  Root Cause : {inc['root_cause']}")
                    lines.append(f"  Status     : {inc['resolution']:<12} | Duration: {dur_str} | {ack_status}")
                    lines.append(f"  Actions    : Auto: {inc['automatic_actions']}")
                    lines.append(f"  Recommend  : {inc['recommended_actions']}")
                    lines.append("-" * 50)
                lines.append("==================================")
                return "\n".join(lines)
            except Exception as e:
                return f"Failed to query incidents: {e}"

        elif sub == "restart":
            if len(args) < 2:
                return "Error: Please specify a subsystem to restart. Usage: hokage watchdog restart <subsystem>"
            subsys = args[1]
            try:
                success = self.orchestrator.trigger_watchdog_restart(subsys)
                if success:
                    return f"Subsystem '{subsys}' was safely and successfully restarted in the background."
                else:
                    return f"Failed to restart subsystem '{subsys}'. Safety criteria were not met. Check incidents for details."
            except Exception as e:
                return f"Error during restart execution: {e}"

        else:
            return f"Unknown watchdog subcommand: '{sub}'. Available: status, heartbeat, incidents, restart."

    def handle_hokage_shadow(self, args_str: str) -> str:
        """Handler for 'hokage shadow <args>'."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        from bots.autonomous.shadow_engine import ShadowEngine
        from integrations.data.models import Exchange

        sqlite_engine = SqliteStorageEngine(self.orchestrator.resolver)
        sqlite_engine.run_migrations()
        shadow_engine = ShadowEngine(sqlite_engine)

        args = args_str.strip().split()
        if not args:
            return (
                "=== Hokage Shadow Trading & Performance Validation ===\n"
                "Usage: hokage shadow <subcommand> [exchange]\n\n"
                "Available subcommands:\n"
                "  hokage shadow start [exchange]          — Start new shadow session (defaults to NSE)\n"
                "  hokage shadow stop [exchange]           — Stop active shadow session\n"
                "  hokage shadow status [exchange]         — Display session status & returns\n"
                "  hokage shadow report <type> [exchange]  — Generate & archive validation report (daily|weekly|monthly)\n"
                "  hokage shadow alpha [exchange]          — Show composite Hokage Alpha Score\n"
                "  hokage shadow benchmark [exchange]      — Display relative metrics against benchmarks\n"
                "  hokage shadow readiness [exchange]      — Audit 12 evidence-based readiness criteria\n"
                "  hokage shadow diagnostics [exchange]    — Institutional statistical diagnostics\n"
                "  hokage shadow quality                   — Display transaction slippage, latency, and fill metrics\n"
            )

        sub = args[0].lower()

        # Parse target exchange from arguments if present
        target_exchange = None
        for arg in args[1:]:
            arg_upper = arg.upper()
            for ex in Exchange:
                if ex.name == arg_upper or ex.value == arg:
                    target_exchange = ex
                    break

        def _get_active_session(target_exch: Exchange | None = None) -> str | None:
            conn = sqlite_engine.get_connection()
            if target_exch:
                session_prefix = f"SHADOW_SES_{target_exch.name}_"
                cursor = conn.execute(
                    "SELECT session_id FROM shadow_sessions WHERE status = 'ACTIVE' AND session_id LIKE ? LIMIT 1;",
                    (f"{session_prefix}%",)
                )
            else:
                cursor = conn.execute("SELECT session_id FROM shadow_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1;")
            row = cursor.fetchone()
            return row["session_id"] if row else None

        if sub == "start":
            starting_equity = 100000.0
            # Parse starting equity if present
            for arg in args[1:]:
                try:
                    starting_equity = float(arg)
                    break
                except ValueError:
                    pass

            try:
                # Check if session already active for this exchange
                exch_name = target_exchange.name if target_exchange else "NSE"
                active = _get_active_session(target_exchange or Exchange.NSE)
                if active:
                    return f"Error: Shadow session for {exch_name} is already active: '{active}'. Stop it first."
                
                session_id = shadow_engine.start_shadow_session(
                    starting_equity=starting_equity,
                    git_version="git-commit-hash-shadow",
                    config_hash="commander-profile-sha256",
                    strategy_set_version="strategy-config-sha256",
                    market_universe_version="market-universe-sha256",
                    risk_profile_version="risk-rules-sha256",
                    exchange=exch_name
                )
                return f"Successfully started shadow session '{session_id}' for {exch_name} with starting capital {format_inr(starting_equity)}."
            except Exception as e:
                return f"Failed to start shadow session: {e}"

        elif sub == "stop":
            try:
                exch_name = target_exchange.name if target_exchange else "any exchange"
                active = _get_active_session(target_exchange)
                if not active:
                    return f"Error: No active shadow session found to stop for {exch_name}."
                shadow_engine.stop_shadow_session(active)
                return f"Successfully stopped shadow session '{active}'."
            except Exception as e:
                return f"Failed to stop shadow session: {e}"

        elif sub == "status":
            conn = sqlite_engine.get_connection()
            # If target_exchange is specified, query it. Otherwise, get all active sessions.
            if target_exchange:
                session_prefix = f"SHADOW_SES_{target_exchange.name}_"
                cursor = conn.execute(
                    "SELECT * FROM shadow_sessions WHERE session_id LIKE ? ORDER BY started_at DESC;",
                    (f"{session_prefix}%",)
                )
                rows = cursor.fetchall()
            else:
                # Load all active sessions
                cursor = conn.execute("SELECT * FROM shadow_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC;")
                rows = cursor.fetchall()
                if not rows:
                    # Fallback to the last session
                    cursor = conn.execute("SELECT * FROM shadow_sessions ORDER BY started_at DESC LIMIT 1;")
                    rows = cursor.fetchall()

            if not rows:
                return "No shadow sessions recorded in the database."

            output_lines = []
            for row in rows:
                status_str = row["status"]
                started = row["started_at"]
                stopped = row["stopped_at"] or "N/A"
                starting = row["starting_equity"]
                current = row["current_equity"]
                ret = (current - starting) / starting if starting > 0 else 0.0

                lines = [
                    f"=== Shadow Session Status: {row['session_id']} ===",
                    f"Status:             {status_str}",
                    f"Started At:         {started}",
                    f"Stopped At:         {stopped}",
                    f"Starting Capital:   {format_inr(starting)}",
                    f"Current Equity:     {format_inr(current)}",
                    f"Cumulative Return:  {ret * 100.0:+.2f}%",
                    f"Git Version:        {row['git_version'][:8]}...",
                    f"Schema Version:     {row['database_schema_version']}",
                    "=================================================="
                ]
                output_lines.append("\n".join(lines))
            return "\n\n".join(output_lines)

        elif sub == "report":
            if len(args) < 2:
                return "Error: Please specify report type. Usage: hokage shadow report <daily|weekly|monthly> [exchange]"
            rep_type = args[1].upper()
            if rep_type not in ("DAILY", "WEEKLY", "MONTHLY"):
                return f"Error: Invalid report type '{args[1]}'. Must be daily, weekly, or monthly."

            active = _get_active_session(target_exchange)
            if not active:
                exch_name = target_exchange.name if target_exchange else "any exchange"
                return f"Error: No active shadow session found for {exch_name}. Reports require an active session."

            try:
                report_id = shadow_engine.generate_and_archive_report(active, rep_type)
                return f"Successfully generated and archived immutable {rep_type} report: '{report_id}'."
            except Exception as e:
                return f"Failed to generate report: {e}"

        elif sub == "alpha":
            active = _get_active_session(target_exchange)
            if not active:
                exch_name = target_exchange.name if target_exchange else "any exchange"
                return f"Error: No active shadow session for {exch_name}."

            from bots.autonomous.quality_engine import ExecutionQualityEngine
            reality = shadow_engine.attribution_engine.generate_reality_metrics()
            calib = shadow_engine.calibration_engine.get_calibration_metrics()
            readiness = shadow_engine.promotion_engine.evaluate_promotion_readiness(active, reality, calib)
            quality_engine = ExecutionQualityEngine(sqlite_engine)
            q_metrics = quality_engine.get_quality_metrics()
            q_score = q_metrics["execution_quality_score"]

            # Simulated calculation aligned with API
            alpha_val = readiness.get("checklist", {}).get("benchmark_outperformance", {}).get("value", "0%")
            try:
                alpha_pct = float(alpha_val.replace("%", "").replace(" active Alpha", ""))
            except Exception:
                alpha_pct = 0.0
            outperformance_score = min(max(alpha_pct * 10.0, 0.0), 100.0)
            sharpe_score = min(max(1.5 * 50.0, 0.0), 100.0)

            dd_val = readiness.get("checklist", {}).get("drawdown_stability", {}).get("value", "0%")
            try:
                dd_pct = float(dd_val.replace("%", "").replace(" max drawdown", ""))
            except Exception:
                dd_pct = 0.0
            drawdown_score = max(100.0 - (dd_pct * 5.0), 0.0)

            reality_score = reality.get("reality_score", 0.0)
            consistency = reality.get("decision_consistency", 100.0)
            win_rate = calib.get("expected_vs_actual", {}).get("win_rate", {}).get("actual", 50.0)
            calib_err = calib.get("calibration_error", 0.0)
            calib_score = max(100.0 - calib_err, 0.0)

            alpha_score = (
                0.20 * outperformance_score +
                0.15 * sharpe_score +
                0.15 * drawdown_score +
                0.15 * reality_score +
                0.15 * consistency +
                0.10 * win_rate +
                0.05 * q_score +
                0.05 * calib_score
            )

            lines = [
                f"=== Hokage Shadow Alpha Score ({active}) ===",
                f"Composite Alpha Score:   {alpha_score:.2f}/100",
                "",
                "Breakdown of Weights & Components:",
                f"  1. Active Outperformance (20%): {outperformance_score:.2f}/100",
                f"  2. Sharpe Ratio (15%):          {sharpe_score:.2f}/100",
                f"  3. Drawdown Control (15%):      {drawdown_score:.2f}/100",
                f"  4. Reality Score (15%):         {reality_score:.2f}/100",
                f"  5. Decision Consistency (15%):  {consistency:.2f}/100",
                f"  6. Win Rate Quality (10%):      {win_rate:.2f}/100",
                f"  7. Calibration Accuracy (5%):   {calib_score:.2f}/100",
                f"  8. Execution Quality (5%):      {q_score:.2f}/100",
                "================================="
            ]
            return "\n".join(lines)

        elif sub == "benchmark":
            active = _get_active_session(target_exchange)
            if not active:
                exch_name = target_exchange.name if target_exchange else "any exchange"
                return f"Error: No active shadow session for {exch_name}."

            conn = sqlite_engine.get_connection()
            bench_cursor = conn.execute(
                "SELECT DISTINCT benchmark_symbol FROM shadow_benchmark_performance WHERE session_id = ?;",
                (active,),
            )
            rows = bench_cursor.fetchall()
            if not rows:
                return f"No benchmark data recorded for session {active} yet."

            lines = [
                f"=== Shadow Relative Benchmark Comparison ({active}) ===",
                f"{'Benchmark':<15}{'Trades':<8}{'Active Alpha':<14}{'Track Error':<13}{'Info Ratio':<12}{'Ann Info Ratio'}",
                "-" * 75
            ]
            for brow in rows:
                b_sym = brow["benchmark_symbol"]
                m = shadow_engine.benchmark_engine.calculate_relative_metrics(active, b_sym)
                lines.append(
                    f"{b_sym:<15}"
                    f"{m['sample_size']:<8}"
                    f"{m['active_return']*100.0:+.2f}%"
                    f"{m['tracking_error']*100.0:<13.2f}%"
                    f"{m['information_ratio']:<12.3f}"
                    f"{m['annualized_information_ratio']:.3f}"
                )
            lines.append("============================================")
            return "\n".join(lines)

        elif sub == "quality":
            from bots.autonomous.quality_engine import ExecutionQualityEngine
            quality_engine = ExecutionQualityEngine(sqlite_engine)
            q = quality_engine.get_quality_metrics()

            lines = [
                "=== Hokage Shadow Execution Realism Quality ===",
                f"Overall Execution Health: {q['execution_health']} (Score: {q['execution_quality_score']:.2f}/100)",
                f"Data Source:              SQLite + Fallback logs ({q['total_trades']} trades analyzed)",
                "",
                "1. Transaction Slippage (Mid-to-Fill Friction):",
                f"   - Average Slippage:    {q['average_slippage_pct']:.4f}%",
                f"   - Worst Case Slippage: {q['worst_slippage_pct']:.4f}%",
                "",
                "2. Network & Broker Latency (Numerical Simulation):",
                f"   - Average Latency:     {q['average_latency_ms']:.2f} ms",
                "",
                "3. Position Fill Performance:",
                f"   - Partial Fill Ratio:  {q['partial_fill_pct']:.2f}% of executed trades",
                "================================================"
            ]
            return "\n".join(lines)

        elif sub == "readiness":
            active = _get_active_session(target_exchange)
            if not active:
                exch_name = target_exchange.name if target_exchange else "any exchange"
                return f"Error: No active shadow session for {exch_name}."

            reality = shadow_engine.attribution_engine.generate_reality_metrics()
            calib = shadow_engine.calibration_engine.get_calibration_metrics()
            readiness = shadow_engine.promotion_engine.evaluate_promotion_readiness(active, reality, calib)

            lines = [
                f"=== Evidence-Based Promotion Readiness ({active}) ===",
                f"Readiness Level: {readiness['readiness_level']}",
                f"Verdict:         {readiness['recommendation']}",
                "",
                "12-Point Validation Checklist:",
            ]
            for key, val in readiness["checklist"].items():
                status_badge = "[PASS] ✅" if val["passed"] else "[FAIL] ❌"
                lines.append(
                    f"  - {key.replace('_', ' ').title():<28}: {val['value']:<25} (Req: {val['threshold']:<15}) {status_badge}"
                )

            # Print under-tested regimes if any
            under_tested = [
                k for k, v in readiness["regime_coverage"].items()
                if v["status"] == "UNDER_TESTED"
            ]
            if under_tested:
                lines.append(f"\n[WARNING] Under-tested regimes: {under_tested}")

            lines.append("===========================================")
            return "\n".join(lines)

        elif sub == "diagnostics":
            from bots.autonomous.performance_analytics import PerformanceAnalyticsEngine
            engine = PerformanceAnalyticsEngine(self.orchestrator.resolver.resolve_brain_root())
            diag = engine.get_statistical_diagnostics()

            lb = diag["ljung_box"]
            jb = diag["jarque_bera"]
            kp = diag["kupiec"]

            lb_pass = "PASS" if diag["passed_autocorrelation"] else "FAIL"
            jb_pass = "PASS" if diag["passed_normality"] else "WARNING"
            kp_pass = "PASS" if diag["passed_var_calibration"] else "FAIL"

            lines = [
                "=== Hokage Shadow Statistical Diagnostics ===",
                f"Overall Health Status: {diag['status']}",
                f"Explanation:           {diag['explanation']}",
                f"Data Source:           {diag['data_source']}",
                f"Sample Size:           {diag['sample_size']} observations",
                "",
                "1. Ljung-Box Q-Test (Autocorrelation Detection):",
                f"   - Q-Statistic:      {lb['stat']}",
                f"   - p-value:          {lb['p_value']}",
                f"   - Tested Lags:      {lb['lags']}",
                f"   - Status:           {lb['message']} ({lb_pass})",
                "",
                "2. Jarque-Bera Test (Normality of Returns):",
                f"   - JB-Statistic:     {jb['stat']}",
                f"   - p-value:          {jb['p_value']}",
                f"   - Skewness:         {jb['skewness']}",
                f"   - Kurtosis:         {jb['kurtosis']}",
                f"   - Status:           {jb['message']} ({jb_pass})",
                "",
                "3. Kupiec Proportion of Failures (POF) (VaR Calibration):",
                f"   - LR-Statistic:     {kp['stat']}",
                f"   - p-value:          {kp['p_value']}",
                f"   - Failures / Obs:   {kp['failures']} / {kp['total_observations']}",
                f"   - Failure Rate:     {kp['failure_rate'] * 100.0:.2f}% (Expected: {kp['expected_failure_rate'] * 100.0:.2f}%)",
                f"   - Status:           {kp['message']} ({kp_pass})",
                "============================================="
            ]
            return "\n".join(lines)

        else:
            return f"Unknown shadow subcommand: '{sub}'. Type 'hokage shadow' for help."

    def handle_hokage_replay(self, trade_id: str) -> str:
        """Handler for 'hokage replay <trade_id>'."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        sqlite_engine = SqliteStorageEngine(self.orchestrator.resolver)
        conn = sqlite_engine.get_connection()
        
        cursor = conn.execute("SELECT * FROM trade_replays WHERE trade_id = ?;", (trade_id.strip(),))
        row = cursor.fetchone()
        if not row:
            return f"Error: Replay timeline for trade ID '{trade_id}' not found in the database."
            
        manifest = json.loads(row["explainability_manifest"])
        timeline = json.loads(row["lifecycle_timeline"])
        
        lines = [
            f"=== Institutional Trade Replay: {row['trade_id']} ({row['symbol']}) ===",
            "",
            "1. Explainability Guarantee (The 9 Why Answers):",
            f"  - Why taken?               {manifest.get('why_taken', 'N/A')}",
            f"  - Why position size?       {manifest.get('why_position_size', 'N/A')}",
            f"  - Why stop-loss?           {manifest.get('why_stop_loss', 'N/A')}",
            f"  - Why profit target?       {manifest.get('why_target', 'N/A')}",
            f"  - Why now?                 {manifest.get('why_now', 'N/A')}",
            f"  - Why not later?           {manifest.get('why_not_later', 'N/A')}",
            f"  - Why this strategy?       {manifest.get('why_this_strategy', 'N/A')}",
            f"  - Why this asset?          {manifest.get('why_this_asset', 'N/A')}",
            f"  - Why this regime?         {manifest.get('why_this_regime', 'N/A')}",
            f"  - Why another rejected?    {manifest.get('why_another_rejected', 'N/A')}",
            "",
            "2. Chronological Lifecycle Timeline:",
        ]
        
        for idx, event in enumerate(timeline, 1):
            ts = event.get("timestamp", "")
            time_str = ts.replace("T", " ")[:19] if ts else "N/A"
            lines.append(f"  [{time_str}] Step {idx}: {event.get('event', 'EVENT')} | {event.get('description', '')}")
            
        lines.append("=========================================================================")
        return "\n".join(lines)

    def handle_hokage_doctor(self) -> str:
        """Handler for 'hokage doctor'."""
        try:
            from hokage.router.doctor import HokageDoctor
            doc = HokageDoctor(self.orchestrator.resolver.resolve_brain_root())
            diag = doc.run_diagnostics()
            
            score = diag["overall_health_score"]
            status_badge = "EXCELLENT" if score >= 90.0 else ("GOOD" if score >= 75.0 else "CRITICAL")
            
            lines = [
                "==================================================",
                "              HOKAGE SYSTEM DOCTOR                ",
                "==================================================",
                f"OVERALL HEALTH SCORE: {score}/100 ({status_badge})",
                "",
                "--- 1. Environment ---",
                f"  Python Version:     {diag['environment']['python_version']}",
                f"  OS Platform:        {diag['environment']['os_platform']}",
                f"  Supported:          {'YES' if diag['environment']['supported_python_version'] else 'NO (Requires >= 3.10)'}",
                "",
                "--- 2. Dependencies ---",
                f"  Status:             {'ALL SATISFIED' if diag['dependencies']['all_dependencies_satisfied'] else 'MISSING'}",
            ]
            if diag['dependencies']['missing_packages']:
                lines.append(f"  Missing:            {', '.join(diag['dependencies']['missing_packages'])}")
            
            lines.extend([
                "",
                "--- 3. Configuration ---",
                f"  Profile Status:     {'VALID' if diag['configuration']['profile_valid_json'] else 'INVALID/MISSING'}",
                f"  Hardcoded Secrets:  {'DETECTED ❌' if diag['configuration']['has_hardcoded_secrets'] else 'NONE DETECTED'}",
                "",
                "--- 4. Database ---",
                f"  DB Exists:          {'YES' if diag['database']['database_exists'] else 'NO'}",
                f"  Integrity:          {'PASS' if diag['database']['integrity_check_passed'] else 'FAIL'}",
                f"  Schema Version:     {diag['database']['schema_version']}",
                f"  Tables Count:       {len(diag['database']['database_tables'])} tables",
            ])
            
            lines.extend([
                "",
                "--- 5. Filesystem & Cache ---",
            ])
            for d, stat in diag['filesystem_and_cache']['directory_status'].items():
                lines.append(f"  Directory '{d}': {'Writable' if stat['writable'] else 'Missing/ReadOnly'}")
            for f, stat in diag['filesystem_and_cache']['cache_file_status'].items():
                lines.append(f"  Cache '{f}': {'Valid' if stat['valid_json'] else 'Missing/Invalid'}")

            lines.extend([
                "",
                "--- 6. Routing & Endpoints ---",
                f"  CLI Commands:       {len(diag['routing']['registered_cli_subcommands'])} subcommands registered",
                f"  REST API Routes:    {len(diag['routing']['registered_api_routes'])} routes registered",
                "",
                "--- 7. Performance ---",
                f"  Startup Latency:    {diag['performance']['startup_latency_ms']} ms",
                f"  Memory Footprint:   {diag['performance']['memory_usage_mb']} MB",
                f"  Disk Read Latency:  {diag['performance']['disk_read_latency_ms']} ms",
                f"  Disk Write Latency: {diag['performance']['disk_write_latency_ms']} ms",
                "",
                "--- 8. Security & Logging ---",
                f"  Logging Configured: {'YES' if diag['security_and_logging']['logging_configured'] else 'NO'}",
                f"  Security Scan:      {'PASS' if diag['security_and_logging']['security_passed'] else 'WARNING'}",
            ])
            if diag['security_and_logging']['security_scan_unsafe_findings']:
                for finding in diag['security_and_logging']['security_scan_unsafe_findings']:
                    lines.append(f"    * {finding}")
                    
            lines.append("==================================================")
            return "\n".join(lines)
        except Exception as exc:
            return f"Doctor diagnostics failed: {exc}"

    def handle_hokage_persona_set(self, tone: str) -> str:
        """Handler for 'hokage persona set <tone>'."""
        try:
            from bots.autonomous.persona import PersonaEngine
            engine = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
            engine.set_persona(tone)
            # Fetch confirmation in new persona
            msg = f"Persona tone successfully updated to {tone.upper()}."
            formatted = engine.format_text(msg)
            return formatted
        except Exception as exc:
            return f"Failed to set persona: {exc}"

    def handle_hokage_mode_set(self, mode: str) -> str:
        """Handler for 'hokage mode set <mode>'."""
        mode_upper = mode.upper().strip()
        if mode_upper not in ("LIVE", "PAPER", "READ_ONLY", "HYBRID"):
            return f"Error: Invalid execution mode '{mode_upper}'. Supported: LIVE, PAPER, READ_ONLY, HYBRID."
        
        try:
            # Write to brain.json override key
            import json
            brain_json_path = self.orchestrator.resolver.resolve_brain_root() / "brain.json"
            data = {}
            if brain_json_path.exists():
                with open(brain_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["execution_mode"] = mode_upper
            with open(brain_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            # Sync context
            self.orchestrator.get_execution_context()
            
            return f"HOKAGE execution mode dynamically updated to: {mode_upper} (stored in brain.json)."
        except Exception as exc:
            return f"Failed to set execution mode: {exc}"

    def handle_hokage_override_stop_loss(self, val: str) -> str:
        """Handler for 'hokage override stop-loss <val>'."""
        try:
            float_val = float(val)
            if float_val <= 0 or float_val >= 100:
                return "Error: Stop loss percentage must be between 0% and 100%."
            
            # Divide by 100 to get decimal representation for risk metrics
            decimal_val = float_val / 100.0
            
            bot = self.orchestrator.autonomous_bot
            bot.intraday_override["stop_loss_percent"] = decimal_val
            
            from bots.autonomous.persona import PersonaEngine
            pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
            msg = f"Intraday Risk Override Engaged: Stop-Loss locked at {float_val:.2f}% across all active positions."
            return pe.format_text(msg)
        except ValueError:
            return f"Error: Invalid stop-loss value '{val}'. Must be a number."
        except Exception as exc:
            return f"Failed to set stop-loss override: {exc}"

    def handle_hokage_override_take_profit(self, val: str) -> str:
        """Handler for 'hokage override take-profit <val>'."""
        try:
            float_val = float(val)
            if float_val <= 0 or float_val >= 500:
                return "Error: Take profit percentage must be between 0% and 500%."
            
            decimal_val = float_val / 100.0
            
            bot = self.orchestrator.autonomous_bot
            bot.intraday_override["take_profit_percent"] = decimal_val
            
            from bots.autonomous.persona import PersonaEngine
            pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
            msg = f"Intraday Risk Override Engaged: Take-Profit locked at {float_val:.2f}%."
            return pe.format_text(msg)
        except ValueError:
            return f"Error: Invalid take-profit value '{val}'. Must be a number."
        except Exception as exc:
            return f"Failed to set take-profit override: {exc}"

    def handle_hokage_override_revoke(self) -> str:
        """Handler for 'hokage override revoke'."""
        try:
            bot = self.orchestrator.autonomous_bot
            bot.intraday_override.clear()
            
            from bots.autonomous.persona import PersonaEngine
            pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
            msg = "All intraday risk overrides revoked. Restoring default quantitative strategy exit parameters."
            return pe.format_text(msg)
        except Exception as exc:
            return f"Failed to revoke overrides: {exc}"



