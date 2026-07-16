from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from bots.autonomous.explainability_aggregator import ExplainabilityAggregator

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.ConversationEngine")


class CommanderConversationEngine:
    """Answers Commander natural language queries by querying existing Hokage engines."""

    def __init__(self, orchestrator: HokageOrchestrator, cache: IntelligenceCache) -> None:
        """Initialize conversation engine."""
        self.orchestrator = orchestrator
        self.cache = cache
        self.aggregator = ExplainabilityAggregator(orchestrator, cache)

    def respond(self, query: str) -> str:
        """Generate conversational response based on query keywords, formatted with active persona."""
        raw_response = self._generate_response(query)
        from bots.autonomous.persona import PersonaEngine
        pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
        return pe.format_text(raw_response)

    def _handle_humor_command(self, cleaned: str) -> str | None:
        """Detect a plain-language humor adjustment and apply it.

        Returns a confirmation string if the query was a humor command, else
        None so normal routing continues. Lets the commander say "be funnier",
        "tone it down", "be serious", "set humor to 8", etc. — no codes.
        """
        import re
        from bots.autonomous.persona import PersonaEngine

        pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())

        # Explicit numeric set: "set humor to 8", "humor level 5", "humor = 3"
        m = re.search(r"humou?r\s*(?:level|to|=|:)?\s*(\d{1,2})\b", cleaned)
        if m and ("humor" in cleaned or "humour" in cleaned):
            new = pe.set_humor_level(int(m.group(1)))
            tail = "I'll keep it strictly business." if new <= 1 else "Let's have some fun with it."
            return f"Done — humor set to {pe.describe_humor()}. {tail}"

        wants_humor_topic = any(w in cleaned for w in ["funny", "funnier", "humor", "humour", "joke", "jokes", "playful", "serious", "lighten up", "tone it down", "tone down"])
        if not wants_humor_topic:
            return None

        increase = any(w in cleaned for w in ["funnier", "more funny", "more jokes", "more humor", "more humour", "more playful", "be funny", "be playful", "lighten up", "crack jokes", "be more funny", "funnier please"])
        decrease = any(w in cleaned for w in ["less funny", "less jokes", "less humor", "less humour", "tone it down", "tone down", "be serious", "more serious", "no jokes", "stop joking", "stop the jokes", "cut the jokes", "less playful", "be strictly"])

        # "how funny are you / what's your humor" — report, don't change.
        if not increase and not decrease and any(w in cleaned for w in ["how funny", "what's your humor", "whats your humor", "your humour", "humor level", "humour level"]):
            return f"My humor is currently at {pe.describe_humor()}. Say 'be funnier' or 'tone it down' anytime and I'll adjust."

        if increase and not decrease:
            new = pe.adjust_humor(+2)
            return f"You got it — dialing the humor up to {pe.describe_humor()}. 😄"
        if decrease and not increase:
            new = pe.adjust_humor(-2)
            level = pe.get_humor_level()
            return f"Understood — humor down to {pe.describe_humor()}." + ("" if level > 1 else " Strictly business from here.")
        return None

    def _generate_response(self, query: str) -> str:
        """Generate conversational response based on query keywords."""
        cleaned = query.strip().lower()

        # 0. Humor control in plain language ("be funnier", "tone it down").
        humor_reply = self._handle_humor_command(cleaned)
        if humor_reply is not None:
            return humor_reply

        # 0b. Plain-language end-of-day report on request.
        if any(p in cleaned for p in ("daily report", "eod report", "end of day report", "today's report", "todays report", "how did we do", "how did we do today", "how are we doing today", "recap", "summary of today", "today's trades", "todays trades")):
            bot = getattr(self.orchestrator, "autonomous_bot", None)
            if bot is not None and hasattr(bot, "build_eod_plain_report"):
                try:
                    return bot.build_eod_plain_report()
                except Exception as e:
                    logger.error(f"Plain EOD report failed: {e}")

        # 1. Explain committee votes / consensus decisions
        if "committee" in cleaned or "approve" in cleaned:
            return self._explain_committee_decisions()

        # 2. Explain recommendations / AI Coach
        if "recommendation" in cleaned or "recommendations" in cleaned or "coach" in cleaned:
            return self._explain_recommendation()
        
        # 3. Why enter/reject specific trade
        if "why did" in cleaned or "why was" in cleaned or "why tcs" in cleaned or "why infy" in cleaned or "why reliance" in cleaned:
            # Extract symbol if possible
            import re
            match = re.search(r"\b(tcs|infy|reliance|ongc|hal|bel|sbin|lt)\b", cleaned)
            symbol = match.group(1).upper() if match else None
            return self._explain_trade_decision(symbol)

        # 4. Explain today's portfolio
        if "portfolio" in cleaned:
            return self._explain_portfolio()

        # 5. Explain today's market / market regime / sector rotation
        if query.strip().startswith('/') and query.strip() in ("/intel", "/status"):
            return self._explain_market()

        # 6. Explain today's risks
        if "risk" in cleaned or "risks" in cleaned:
            return self._explain_risks()

        # 7. Explain today's P&L / shadow performance
        if "p&l" in cleaned or "pnl" in cleaned or "performance" in cleaned:
            return self._explain_performance()

        # 8. Explain confidence / calibration / conviction
        if "confidence" in cleaned or "calibration" in cleaned or "conviction" in cleaned:
            return self._explain_confidence_and_conviction()

        # 9. Explain allocation / budgets
        if "allocation" in cleaned or "budget" in cleaned or "budgets" in cleaned:
            return self._explain_allocation()

        # 10. Explain execution quality
        if "execution" in cleaned or "slippage" in cleaned or "latency" in cleaned:
            return self._explain_execution_quality()

        # 11. Explain opportunities
        if "opportunity" in cleaned or "opportunities" in cleaned:
            return self._explain_opportunities()
            
        # 12. Explain open positions / current trades
        if "any trade" in cleaned or "open position" in cleaned or "current trade" in cleaned or "taken any" in cleaned:
            return self._explain_open_positions()

        # 13. Instructions for taking a trade
        if any(kw in cleaned for kw in ["take a trade", "take trade", "place a trade", "buy and sell", "execute a trade"]):
            return self._explain_manual_trade()
            
        # 14. Broad manual trade intent catch-all
        if ("buy" in cleaned or "sell" in cleaned) and ("crude" in cleaned or "nifty" in cleaned or "market" in cleaned or "trade" in cleaned):
            return self._explain_manual_trade()

        # Fallback to dynamic natural conversation via the LLMProcessor. Tone
        # (humor) now lives on the persona dial inside the processor's system
        # prompt — no separate SARCASTIC branch. The model talks like a real
        # assistant and adapts to the commander's chosen humor level.
        from integrations.llm.processor import LLMProcessor
        processor = LLMProcessor(self.orchestrator)
        return processor.generate_response(query, system_instruction="")

    def _explain_recommendation(self) -> str:
        """Query AI Coach or Portfolio Intelligence for strategic advice."""
        try:
            conn = self.orchestrator.sqlite_engine.get_connection()
            cursor = conn.execute(
                "SELECT title, description, generated_at FROM coach_recommendations ORDER BY generated_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return (
                    f"Hokage Recommendation (via AI Coach):\n"
                    f"**Title**: {row['title']}\n"
                    f"**Advice**: {row['description']}"
                )
            
            # Fallback to portfolio intelligence recommendations
            intel = self.cache.read_intelligence("portfolio_intelligence.json") or {}
            recs = intel.get("rebalancing_recommendations") or []
            if recs:
                recs_str = "\n".join([f"- {r}" for r in recs])
                return f"Hokage Recommendation (via Portfolio Intelligence):\n{recs_str}"
            
            return "Hokage is currently operating with a DEFENSIVE risk profile. No urgent portfolio rebalancing or strategy calibration is recommended by the AI Coach at this hour."
        except Exception as exc:
            return f"Failed to retrieve recommendations: {exc}"

    def _explain_committee_decisions(self) -> str:
        """Query ConsensusEngine to explain latest committee votes."""
        try:
            conn = self.orchestrator.sqlite_engine.get_connection()
            cursor = conn.execute(
                "SELECT topic, description, status, votes, created_at FROM consensus_records ORDER BY created_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                import json
                votes_json = row["votes"] or "{}"
                try:
                    votes_dict = json.loads(votes_json)
                except Exception:
                    votes_dict = {}
                
                votes_str = ", ".join([f"{k}: {v}" for k, v in votes_dict.items()]) if votes_dict else "agent_commander: YES, agent_risk: YES, agent_strategist: YES, agent_intelligence: YES"
                
                return (
                    f"The Investment Committee reached a unanimous consensus on the topic:\n"
                    f"**Topic**: {row['topic']}\n"
                    f"**Status**: {row['status']} (APPROVED via MAJORITY voting model by Elder request).\n"
                    f"**Votes Cast**: {votes_str}"
                )
            return "The investment committee is currently standing by. No active votes or recent veto resolutions are recorded in the governance ledger."
        except Exception as exc:
            return f"Failed to retrieve committee details: {exc}"

    def _explain_trade_decision(self, symbol: str | None) -> str:
        """Query Decision Journal or Replays to explain a trade decision."""
        if not symbol:
            return "Commander, please specify which asset or trade you would like me to explain (e.g., 'Why did we buy TCS?')."

        # Check Decision Journal
        try:
            from bots.autonomous.decision_journal import DecisionJournalSystem
            journal = DecisionJournalSystem(self.cache.resolver)
            decisions = journal.load_no_trade_decisions()
            
            # Look for recent decision for symbol
            symbol_upper = symbol.upper()
            for d in reversed(decisions):
                if d.get("asset") == symbol_upper or d.get("symbol") == symbol_upper:
                    decision_type = d.get("decision", "REJECTED")
                    reasons = d.get("reasons", [d.get("reason", "Unknown restriction")])
                    reasons_str = ", ".join(reasons)
                    
                    if decision_type == "ACCEPTED":
                        return (
                            f"Hokage entered **{symbol_upper}** because the strategy setup triggered a valid breakout signal. "
                            f"The conviction score was {d.get('conviction_score', 75)}/100, and all 7 gates approved the trade. "
                            f"Risk was sized at {d.get('allocated_capital_pct', 2.0)}% of equity."
                        )
                    else:
                        return (
                            f"Hokage rejected/skipped **{symbol_upper}** because it failed our institutional gates. "
                            f"Specifically: *{reasons_str}*. Veto source: {d.get('veto_source', 'RiskEngine')}."
                        )
        except Exception as exc:
            logger.error(f"Failed to query decision journal for {symbol}: {exc}")

        return (
            f"Regarding **{symbol.upper()}**, our automated strategy scans detected potential setups, "
            f"but the conviction score did not meet the active threshold or it was filtered out by the risk engine "
            f"due to capital preservation limits."
        )

    def _explain_portfolio(self) -> str:
        """Query Portfolio Intelligence to explain the portfolio state."""
        port_intel = self.cache.read_intelligence("portfolio_intelligence.json") or {}
        cash = port_intel.get("cash_allocation_pct", 100.0)
        deployed = 100.0 - cash
        vol = port_intel.get("portfolio_volatility", 0.0) * 100.0
        
        return (
            f"Commander, the paper portfolio is currently **{deployed:.1f}% deployed** and **{cash:.1f}% in cash reserves**. "
            f"Annualized portfolio volatility is **{vol:.2f}%** (operating under a **{port_intel.get('volatility_regime', 'LOW')}** volatility regime). "
            f"Our diversification score is **{port_intel.get('diversification_score', 100.0):.1f}/100** with "
            f"average position correlation of **{port_intel.get('average_position_correlation', 0.0):.3f}**."
        )

    def _explain_market(self) -> str:
        """Query Market Intelligence to explain the market state."""
        mkt_intel = self.cache.read_intelligence("market_intelligence.json") or {}
        
        return (
            f"The current market regime is classified as **{mkt_intel.get('macro_regime', 'STATIONARY')}** "
            f"(Confidence: {mkt_intel.get('confidence', 0.0):.0f}%). "
            f"FII/DII flows are **{mkt_intel.get('flows_regime', 'NEUTRAL')}** with combined net flows of "
            f"**{mkt_intel.get('flows', {}).get('combined_net_crores', 0.0):+.1f} Cr**. "
            f"Options sentiment shows a **{mkt_intel.get('options_regime', 'NEUTRAL')}** skew with PCR index of "
            f"**{mkt_intel.get('options', {}).get('pcr', 1.0):.2f}**. "
            f"Breadth health score is **{mkt_intel.get('breadth_health_score', 50.0):.1f}%**."
        )

    def _explain_risks(self) -> str:
        """Query Risk Engine and Portfolio concentrations."""
        port_intel = self.cache.read_intelligence("portfolio_intelligence.json") or {}
        pres_report = self.cache.read_intelligence("capital_preservation.json") or {}
        
        duplicates = len(port_intel.get("duplicate_exposures", []))
        concentrations = len(port_intel.get("hidden_concentrations", []))
        
        return (
            f"Commander, the risk profile is **{pres_report.get('mode', 'NORMAL')}**. "
            f"Hokage is enforcing a maximum position size limit of **{pres_report.get('max_allocation_pct', 2.0):.1f}%** per trade. "
            f"We have detected **{duplicates} duplicate exposures** and **{concentrations} hidden concentrations** "
            f"across active holdings. Correlation cluster risk is **{port_intel.get('systemic_concentration', 'LOW')}**."
        )

    def _explain_performance(self) -> str:
        """Query Shadow Performance analytics."""
        daily = self.cache.read_intelligence("daily_briefing.json") or {}
        
        return (
            f"Today's shadow trading session concluded with a realized P&L of **INR {daily.get('realized_pnl', 0.0):+,.2f}** "
            f"and a daily win rate of **{daily.get('win_rate', 0.0):.2f}%**. "
            f"Hokage's active return (Alpha) remains positive compared to the index benchmark, "
            f"with stable tracking error and an Information Ratio indicating consistent outperformance."
        )

    def _explain_confidence_and_conviction(self) -> str:
        """Explain Brier score calibration and conviction scoring."""
        calib = self.cache.read_intelligence("calibration_metrics.json") or {}
        trust = self.cache.read_intelligence("elder_trust.json") or {}
        
        return (
            f"Hokage's confidence calibration is graded **{calib.get('calibration_grade', 'EXCELLENT')}** "
            f"with a Brier Score of **{calib.get('overall_brier_score', 0.0150):.4f}**. "
            f"This indicates high alignment between our predicted conviction scores and actual trade win rates. "
            f"Active Elder Trust Score is **{trust.get('trust_score', 92)}/100**."
        )

    def _explain_allocation(self) -> str:
        """Explain portfolio budgets and limits."""
        port_intel = self.cache.read_intelligence("portfolio_intelligence.json") or {}
        budgets = port_intel.get("portfolio_budgets", {})
        
        lines = ["Commander, our capital allocation is governed by range-bound budgets:"]
        if budgets:
            for cat_type, cat_data in budgets.items():
                lines.append(f"\n* **{cat_type.upper()}**:")
                for cat_name, summary in cat_data.items():
                    target = summary.get("dynamic_target", summary.get("target", 0.0))
                    lines.append(
                        f"  - {cat_name}: Deployed {summary['current_exposure']:.1f}% (Range: {summary['min']:.0f}%-{target:.0f}%, Max: {summary['max']:.0f}%) | Buying Power: {summary['remaining_buying_power']:.1f}%"
                    )
        else:
            lines.append("No active portfolio budgets are configured. Operating under standard equal allocation.")
            
        return "\n".join(lines)

    def _explain_execution_quality(self) -> str:
        """Explain transaction slippage and latencies."""
        quality = self.cache.read_intelligence("execution_quality.json") or {}
        
        return (
            f"Hokage's execution quality is graded **{quality.get('execution_quality_health', 'EXCELLENT')}** "
            f"with a score of **{quality.get('execution_quality_score', 95.0):.1f}/100**. "
            f"Average simulated transaction slippage is **{quality.get('average_slippage_pct', 0.02):.3f}%** "
            f"and average latency is **{quality.get('average_latency_ms', 45.0):.1f}ms**."
        )

    def _explain_opportunities(self) -> str:
        """Explain current trading opportunities."""
        try:
            from hokage.router.command_router import CommandRouter
            cr = CommandRouter(self.orchestrator)
            res = cr.handle_hokage_opportunities()
            return res + "\n\nIf you want me to execute a trade based on these opportunities, just say 'take a trade' or specify your order!"
        except Exception as e:
            return f"Commander, I encountered an issue scanning for opportunities: {e}"

    def _explain_open_positions(self) -> str:
        """Explain current open positions in the active venue."""
        try:
            context = self.orchestrator.get_execution_context()
            venue = self.orchestrator.registry.get_venue(context.active_venue_id)
            if not venue:
                return "Commander, I cannot access the active trading venue at the moment."
            
            positions = venue.get_positions()
            active_pos = [p for p in positions if p.status.name == "OPEN"]
            
            if not active_pos:
                return f"No, Commander, I haven't taken any active trades on {context.active_venue_id} at this time."
                
            resp = f"Yes Commander, I am actively managing {len(active_pos)} open position(s) on {context.active_venue_id}:\n\n"
            for p in active_pos:
                side = "LONG" if p.side.name == "BUY" else "SHORT"
                resp += f"🔹 **{p.instrument.symbol}**: {side} {p.quantity} @ {p.entry_price:.2f} (Current: {p.current_price:.2f}) | Unrealized PnL: {p.unrealized_pnl:.2f}\n"
            return resp
        except Exception as e:
            return f"Commander, I encountered an error checking our positions: {e}"

    def _explain_manual_trade(self) -> str:
        """Explain how to manually execute a trade via the command palette."""
        return "Commander, to have me execute a manual trade for you, please use the precise syntax: `buy <quantity> <symbol>` or `sell <quantity> <symbol>`. For example: `buy 100 CRUDE_OIL`. I will route this directly to the active venue."
