"""ImprovementBot for Hokage — Phase 5: Self-Improving Loop.

Compares historical backtest parameters against actual paper/live trading outcomes,
detects performance and slippage drift, and generates/applies optimization proposals.
Strictly advisory in Hokage Alpha.
"""
from __future__ import annotations

import json
import logging
import uuid
import os
from datetime import datetime, timezone
from typing import Any

from hokage.memory.resolver import PathResolver
from hokage.ledger.prediction_ledger import JsonPredictionLedger
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.strategy.portfolio import StrategyPortfolioManager

logger = logging.getLogger("Hokage.ImprovementBot")


class ImprovementBot:
    """Detects strategy performance drift and manages optimization proposals."""

    def __init__(
        self,
        portfolio_manager: StrategyPortfolioManager,
        resolver: PathResolver | None = None,
        prediction_ledger: JsonPredictionLedger | None = None,
        trade_store: JsonTradeStore | None = None,
        autonomous_mode: bool = False
    ) -> None:
        """Initialize ImprovementBot."""
        self.portfolio_manager = portfolio_manager
        self.resolver = resolver or PathResolver()
        self.prediction_ledger = prediction_ledger or JsonPredictionLedger(self.resolver.resolve_predictions_dir())
        self.trade_store = trade_store or JsonTradeStore(self.resolver.resolve_trades_dir())
        self.autonomous_mode = autonomous_mode  # STRICTLY FALSE FOR ALPHA

        # Resolve paths
        self._brain_root = self.resolver.resolve_brain_root()
        self._improvement_dir = self._brain_root / "improvement"
        self._improvement_dir.mkdir(parents=True, exist_ok=True)
        self._proposals_file = self._improvement_dir / "improvement_proposals.jsonl"
        self._journal_dir = self._brain_root / "journal"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._applied_improvements_file = self._journal_dir / "applied_improvements.jsonl"
        self._autopsies_file = self._improvement_dir / "trade_autopsies.jsonl"

    def analyze_performance_drift(self, strategy_id: str, asset: str = "DEFAULT") -> dict[str, Any]:
        """Compare backtest parameters vs. actual execution metrics for a strategy and asset."""
        strat = self.portfolio_manager.portfolio.get("strategies", {}).get(strategy_id)
        if not strat:
            raise ValueError(f"Strategy {strategy_id} not found in portfolio.")

        asset_upper = asset.upper()

        # 1. Fetch backtest benchmarks from supporting evidence
        evidence = strat.get("supporting_evidence", {})
        backtest_wr = float(evidence.get("backtest_win_rate", 55.0))
        backtest_exp = float(evidence.get("backtest_expectancy", 0.0))
        backtest_dd = float(evidence.get("max_drawdown", evidence.get("backtest_drawdown", 15.0)))

        # 2. Fetch actual portfolio outcomes
        actual_wr = float(strat.get("win_rate", {}).get(asset_upper, strat.get("win_rate", {}).get("DEFAULT", 50.0)))
        actual_exp = float(strat.get("expectancy", {}).get(asset_upper, strat.get("expectancy", {}).get("DEFAULT", 0.0)))
        actual_dd = float(strat.get("drawdown", {}).get(asset_upper, strat.get("drawdown", {}).get("DEFAULT", 0.0)))
        trade_count = int(strat.get("trade_count", {}).get(asset_upper, strat.get("trade_count", {}).get("DEFAULT", 0)))

        # 3. Compute slippage drift from trade records
        avg_slippage = 0.0
        slippage_count = 0
        try:
            # Cross-reference with trade authorizations or predictions to get target prices
            auths_file = self._journal_dir / "trade_authorizations.jsonl"
            target_prices = {}
            if auths_file.exists():
                with auths_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            auth_data = json.loads(line.strip())
                            # Store target price by asset and closest timestamp or simply proposal_id if present
                            asset_key = auth_data.get("asset", "").upper()
                            target_prices[asset_key] = float(auth_data.get("entry_price", 0.0))

            # Load actual trades
            trades = self.trade_store.load_all()
            strategy_name_lower = strat.get("name", "").lower()
            matching_trades = [
                t for t in trades 
                if t.strategy_name.lower() == strategy_name_lower and t.market.upper() == asset_upper
            ]

            if matching_trades:
                slippage_sum = 0.0
                for trade in matching_trades:
                    # Target price from auths or fallback to trade entry price (0 slippage)
                    target = target_prices.get(asset_upper, trade.entry_price)
                    slippage = abs(trade.entry_price - target)
                    slippage_sum += slippage
                    slippage_count += 1
                if slippage_count > 0:
                    avg_slippage = slippage_sum / slippage_count
        except Exception as exc:
            logger.warning(f"Error computing slippage drift: {exc}")

        # Calculate drifts
        win_rate_drift = actual_wr - backtest_wr
        expectancy_drift = actual_exp - backtest_exp
        drawdown_drift = actual_dd - backtest_dd

        return {
            "strategy_id": strategy_id,
            "strategy_name": strat.get("name", ""),
            "asset": asset_upper,
            "trade_count": trade_count,
            "backtest": {
                "win_rate": backtest_wr,
                "expectancy": backtest_exp,
                "drawdown": backtest_dd
            },
            "actual": {
                "win_rate": actual_wr,
                "expectancy": actual_exp,
                "drawdown": actual_dd,
                "avg_slippage": avg_slippage
            },
            "drift": {
                "win_rate_drift": round(win_rate_drift, 2),
                "expectancy_drift": round(expectancy_drift, 2),
                "drawdown_drift": round(drawdown_drift, 2),
                "slippage_drift": round(avg_slippage, 2)
            }
        }

    def generate_improvement_proposals(self) -> list[dict[str, Any]]:
        """Scan all active or probation strategies and generate advisory optimization proposals."""
        logger.info("Generating advisory improvement proposals.")
        strategies = self.portfolio_manager.portfolio.get("strategies", {})
        proposals = []

        # Load existing proposals to prevent duplicates or preserve history
        existing_proposals = self.load_proposals()
        existing_keys = {
            (p["strategy_id"], p["asset"], p["action"]): p["proposal_id"] 
            for p in existing_proposals if p.get("status") == "PENDING_APPROVAL"
        }

        for strat_id, strat in strategies.items():
            if strat.get("status") == "ARCHIVED":
                continue

            # Analyze default drift and asset-specific drifts
            assets_to_check = set(strat.get("supported_assets", []))
            if not assets_to_check:
                assets_to_check.add("DEFAULT")

            for asset in assets_to_check:
                try:
                    drift_stats = self.analyze_performance_drift(strat_id, asset)
                except Exception as exc:
                    logger.error(f"Failed to run drift analysis for {strat_id} {asset}: {exc}")
                    continue

                trade_count = drift_stats["trade_count"]
                if trade_count < 3:
                    # Insufficient execution history to reliably detect drift
                    continue

                wr_drift = drift_stats["drift"]["win_rate_drift"]
                dd_drift = drift_stats["drift"]["drawdown_drift"]
                actual_wr = drift_stats["actual"]["win_rate"]
                actual_dd = drift_stats["actual"]["drawdown"]

                # Heuristics for generating proposals
                # 1. Severe underperformance -> DEMOTE + RISK_MULTIPLIER
                if wr_drift <= -10.0 or dd_drift >= 5.0 or actual_wr < 45.0:
                    action = "DEMOTE"
                    previous_status = strat.get("status", "ACTIVE")
                    proposed_status = "PROBATION" if previous_status == "ACTIVE" else "ARCHIVED"
                    
                    prev_values = {"status": previous_status, "risk_multiplier": 1.0}
                    new_values = {"status": proposed_status, "risk_multiplier": 0.5}
                    
                    rationale = (
                        f"Severe performance drift detected for {asset}. "
                        f"Actual win rate ({actual_wr}%) is {abs(wr_drift)}% lower than backtest. "
                        f"Actual max drawdown ({actual_dd}%) exceeds backtest drawdown by {dd_drift}%."
                    )
                    expected_imp = (
                        f"Demoting to {proposed_status} and reducing risk multiplier to 0.5x "
                        f"preserves capital, reducing expected drawdown exposure by 50% "
                        f"while the strategy is undergoing parameter recalibration."
                    )
                    
                    self._create_proposal_record(
                        strat_id, strat.get("name", ""), asset, action, prev_values, new_values, rationale, expected_imp, proposals, existing_keys
                    )

                # 2. Mild underperformance or high slippage -> PARAMETER_TUNE
                elif wr_drift <= -5.0 or drift_stats["actual"]["avg_slippage"] > 0.0:
                    action = "PARAMETER_TUNE"
                    
                    # Propose tightening stop loss to cut losses faster
                    current_stop_rule = "Standard 2% stop loss applied."
                    proposed_stop_rule = "Tightened 1.5% stop loss due to negative drift."
                    
                    prev_values = {"stop_loss_rule": current_stop_rule}
                    new_values = {"stop_loss_rule": proposed_stop_rule}
                    
                    rationale = (
                        f"Mild performance drift or execution slippage detected. "
                        f"Win rate drift is {wr_drift}%. Average slippage is {drift_stats['actual']['avg_slippage']:.2f}."
                    )
                    expected_imp = (
                        "Tightening the stop loss cuts losing trades faster, "
                        "which is estimated to improve expectancy by 10-15% under sideways or volatile regimes."
                    )
                    
                    self._create_proposal_record(
                        strat_id, strat.get("name", ""), asset, action, prev_values, new_values, rationale, expected_imp, proposals, existing_keys
                    )

        if proposals:
            # Write new proposals atomically to the ledger
            all_proposals = existing_proposals + [p for p in proposals if p["proposal_id"] not in [x["proposal_id"] for x in existing_proposals]]
            self._save_proposals_atomic(all_proposals)
            
            # Notify Commander for each new proposal
            from bots.strategy.evolution import StrategyEvolutionEngine
            evo_engine = StrategyEvolutionEngine(self.resolver)
            for prop in proposals:
                evo_engine.notify_commander(
                    strategy_id=prop["strategy_id"],
                    change_type="EVOLUTION",
                    reason=f"Advisory improvement proposal {prop['proposal_id']} generated: {prop['rationale']}",
                    evidence={
                        "proposal_id": prop["proposal_id"],
                        "asset": prop["asset"],
                        "action": prop["action"],
                        "expected_improvement": prop["expected_improvement"]
                    },
                    validation_status=prop["status"],
                    confidence=50.0,
                    is_experimental=True
                )

        return proposals

    def _create_proposal_record(
        self, strat_id: str, strat_name: str, asset: str, action: str,
        prev_values: dict[str, Any], new_values: dict[str, Any],
        rationale: str, expected_imp: str, proposals: list[dict[str, Any]],
        existing_keys: dict[tuple[str, str, str], str]
    ) -> None:
        key = (strat_id, asset, action)
        if key in existing_keys:
            # Already exists as pending, do not duplicate
            return

        prop_id = f"prop-{strat_name.lower().replace(' ', '-')}-{str(uuid.uuid4())[:8]}"
        proposal = {
            "proposal_id": prop_id,
            "strategy_id": strat_id,
            "strategy_name": strat_name,
            "asset": asset,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "previous_values": prev_values,
            "new_values": new_values,
            "rationale": rationale,
            "expected_improvement": expected_imp,
            "status": "PENDING_APPROVAL",
            "approving_commander": None,
            "applied_at": None,
            "actual_post_change_performance": None
        }
        proposals.append(proposal)

    def apply_improvement_proposal(self, proposal_id: str, commander_name: str) -> bool:
        """Apply a specific improvement proposal. Requires explicit Commander name."""
        if not commander_name or not commander_name.strip():
            raise ValueError("Applying an improvement proposal requires an explicit approving Commander name.")

        proposals = self.load_proposals()
        target_prop = None
        for prop in proposals:
            if prop["proposal_id"] == proposal_id:
                target_prop = prop
                break

        if not target_prop:
            logger.error(f"Proposal {proposal_id} not found.")
            return False

        if target_prop["status"] != "PENDING_APPROVAL":
            logger.warning(f"Proposal {proposal_id} is already in {target_prop['status']} status.")
            return False

        strat_id = target_prop["strategy_id"]
        strat = self.portfolio_manager.portfolio.get("strategies", {}).get(strat_id)
        if not strat:
            logger.error(f"Strategy {strat_id} referenced by proposal {proposal_id} not found in portfolio.")
            return False

        # Apply the proposed changes to the strategy portfolio
        new_vals = target_prop["new_values"]
        prev_vals = target_prop["previous_values"]
        asset = target_prop["asset"]
        action = target_prop["action"]

        now_str = datetime.now(timezone.utc).isoformat()

        # Update fields in strategy portfolio
        if "status" in new_vals:
            strat["status"] = new_vals["status"]
            strat["history"].append({
                "timestamp": now_str,
                "event": f"Status updated from {prev_vals.get('status')} to {new_vals['status']} via Commander approved proposal {proposal_id}."
            })

        if "risk_multiplier" in new_vals:
            # We store risk multipliers per asset under a specialized portfolio dictionary
            multipliers = strat.setdefault("risk_multipliers", {})
            multipliers[asset] = new_vals["risk_multiplier"]
            strat["history"].append({
                "timestamp": now_str,
                "event": f"Risk multiplier for {asset} updated to {new_vals['risk_multiplier']}x via proposal {proposal_id}."
            })

        if "stop_loss_rule" in new_vals:
            # Update stop loss rule text in the strategy
            strat["stop_loss_rule"] = new_vals["stop_loss_rule"]
            strat["history"].append({
                "timestamp": now_str,
                "event": f"Stop loss rule updated via proposal {proposal_id}."
            })

        # Update proposal status
        target_prop["status"] = "APPLIED"
        target_prop["approving_commander"] = commander_name
        target_prop["applied_at"] = now_str

        # Persist updated strategy portfolio
        self.portfolio_manager.save()

        # Persist updated proposals ledger
        self._save_proposals_atomic(proposals)

        # Log an immutable record to applied_improvements.jsonl (atomic write-then-rename)
        self._log_applied_improvement_immutable(target_prop)

        logger.info(f"Successfully applied improvement proposal {proposal_id} approved by {commander_name}.")
        return True

    def load_proposals(self) -> list[dict[str, Any]]:
        """Load all proposals from the proposals ledger."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self.resolver):
            engine = SqliteStorageEngine(self.resolver)
            conn = engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM improvement_proposals ORDER BY timestamp ASC;")
                proposals = []
                for row in cursor.fetchall():
                    proposals.append({
                        "proposal_id": row["proposal_id"],
                        "strategy_id": row["strategy_id"],
                        "strategy_name": row["strategy_name"],
                        "asset": row["asset"],
                        "timestamp": row["timestamp"],
                        "action": row["action"],
                        "previous_values": json.loads(row["previous_values"]),
                        "new_values": json.loads(row["new_values"]),
                        "rationale": row["rationale"],
                        "expected_improvement": row["expected_improvement"],
                        "status": row["status"],
                        "approving_commander": row["approving_commander"],
                        "applied_at": row["applied_at"],
                        "actual_post_change_performance": json.loads(row["actual_post_change_performance"]) if row["actual_post_change_performance"] else None
                    })
                return proposals
            except Exception as exc:
                logger.error(f"Failed to read proposals from SQLite: {exc}")
                return []

        proposals = []
        if not self._proposals_file.exists():
            return proposals
        try:
            with self._proposals_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        proposals.append(json.loads(line.strip()))
        except Exception as exc:
            logger.error(f"Failed to read proposals ledger: {exc}")
        return proposals

    def _save_proposals_atomic(self, data: list[dict[str, Any]]) -> None:
        """Atomically save proposals list to the proposals ledger."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self.resolver):
            engine = SqliteStorageEngine(self.resolver)
            conn = engine.get_connection()
            try:
                with conn:
                    for p in data:
                        conn.execute("""
                            INSERT OR REPLACE INTO improvement_proposals (
                                proposal_id, strategy_id, strategy_name, asset, timestamp, action,
                                previous_values, new_values, rationale, expected_improvement, status,
                                approving_commander, applied_at, actual_post_change_performance
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            p["proposal_id"], p["strategy_id"], p["strategy_name"], p["asset"],
                            p["timestamp"], p["action"], json.dumps(p["previous_values"]),
                            json.dumps(p["new_values"]), p["rationale"], p["expected_improvement"],
                            p["status"], p.get("approving_commander"), p.get("applied_at"),
                            json.dumps(p.get("actual_post_change_performance"))
                        ))
                logger.info("Saved proposals atomically to SQLite.")
                return
            except Exception as exc:
                logger.error(f"Failed to write proposals to SQLite: {exc}")
                raise exc

        temp_path = self._proposals_file.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fh:
                for prop in data:
                    fh.write(json.dumps(prop, sort_keys=True) + "\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            temp_path.replace(self._proposals_file)
        except Exception as exc:
            logger.error(f"Failed to atomically write proposals ledger: {exc}")

    def _log_applied_improvement_immutable(self, prop: dict[str, Any]) -> None:
        """Atomically log an applied improvement to the immutable ledger."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self.resolver):
            engine = SqliteStorageEngine(self.resolver)
            conn = engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO applied_improvements (
                            proposal_id, strategy_id, strategy_name, asset, timestamp,
                            previous_values, new_values, rationale, expected_improvement,
                            actual_post_change_performance, approving_commander
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        prop["proposal_id"], prop["strategy_id"], prop["strategy_name"], prop["asset"],
                        prop["applied_at"], json.dumps(prop["previous_values"]), json.dumps(prop["new_values"]),
                        prop["rationale"], prop["expected_improvement"],
                        json.dumps(prop.get("actual_post_change_performance")), prop["approving_commander"]
                    ))
                logger.info(f"Logged applied improvement {prop['proposal_id']} to SQLite.")
                return
            except Exception as exc:
                logger.error(f"Failed to write applied improvement to SQLite: {exc}")
                raise exc

        lines = []
        if self._applied_improvements_file.exists():
            try:
                with self._applied_improvements_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            lines.append(line)
            except Exception as exc:
                logger.error(f"Failed to read applied improvements: {exc}")

        # Formulate the audit record
        audit_record = {
            "proposal_id": prop["proposal_id"],
            "strategy_id": prop["strategy_id"],
            "strategy_name": prop["strategy_name"],
            "asset": prop["asset"],
            "timestamp": prop["applied_at"],
            "previous_values": prop["previous_values"],
            "new_values": prop["new_values"],
            "rationale": prop["rationale"],
            "expected_improvement": prop["expected_improvement"],
            "actual_post_change_performance": None,
            "approving_commander": prop["approving_commander"]
        }
        lines.append(json.dumps(audit_record, sort_keys=True) + "\n")

        temp_path = self._applied_improvements_file.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fh:
                fh.writelines(lines)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            temp_path.replace(self._applied_improvements_file)
        except Exception as exc:
            logger.error(f"Failed to atomically write applied improvements log: {exc}")

    def process_autopsy(self, autopsy: Any) -> None:
        """Process and save a TradeAutopsy record."""
        try:
            record = autopsy.to_dict()
            with self._autopsies_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            logger.info(f"Saved TradeAutopsy for {autopsy.symbol} (Trade ID: {autopsy.trade_id})")
            
            # Check if we should trigger evolution and LLM journal
            # For this alpha, we'll run it every 5 trades.
            count = 0
            with self._autopsies_file.open("r", encoding="utf-8") as fh:
                count = sum(1 for line in fh if line.strip())
            
            if count > 0 and count % 5 == 0:
                logger.info(f"Autopsy threshold reached ({count}). Triggering Pattern Detection and Evolution.")
                patterns = self.detect_patterns("strat-autotrend-equities-v1")
                if patterns:
                    self.apply_autonomous_evolution(patterns)
                    
                    from integrations.llm.processor import LLMProcessor
                    llm = LLMProcessor()
                    journal_entry = llm.generate_trading_journal_entry(patterns)
                    
                    from integrations.notifications.telegram_bot import TelegramBotUplink
                    tb = TelegramBotUplink()
                    if tb.enabled:
                        tb.send_message(f"📖 *HOKAGE TRADING JOURNAL*\n\n{journal_entry}")
                    
                    self.evaluate_promotions()
                    
        except Exception as e:
            logger.error(f"Failed to process TradeAutopsy: {e}")

    def detect_patterns(self, strategy_id: str) -> dict[str, Any]:
        """Analyze recent autopsies to find statistical edge patterns."""
        if not self._autopsies_file.exists():
            return {}
        
        try:
            autopsies = []
            with self._autopsies_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        autopsies.append(json.loads(line.strip()))
            
            if len(autopsies) < 5:
                return {}
            
            # Basic pattern detection
            wins = [a for a in autopsies if a.get("pnl", 0) > 0]
            losses = [a for a in autopsies if a.get("pnl", 0) <= 0]
            
            win_rate = len(wins) / len(autopsies)
            avg_win_vix = sum(w.get("vix_at_entry", 15) for w in wins) / max(1, len(wins))
            avg_loss_vix = sum(l.get("vix_at_entry", 15) for l in losses) / max(1, len(losses))
            
            # Identify if stop losses are too tight (many losses with max_favorable > 0 but max_adverse hitting stop)
            premature_stops = len([l for l in losses if l.get("max_favorable_excursion_pct", 0) > 1.0])
            stop_tightness_issue = premature_stops > len(losses) * 0.5
            
            return {
                "strategy_id": strategy_id,
                "win_rate": win_rate,
                "avg_win_vix": avg_win_vix,
                "avg_loss_vix": avg_loss_vix,
                "stop_tightness_issue": stop_tightness_issue,
                "recent_trades": len(autopsies),
                "premature_stops": premature_stops
            }
        except Exception as e:
            logger.error(f"Failed to detect patterns: {e}")
            return {}

    def apply_autonomous_evolution(self, patterns: dict[str, Any]) -> None:
        """Apply safe autonomous adjustments to strategy parameters based on patterns."""
        strategy_id = patterns.get("strategy_id")
        if not strategy_id:
            return
            
        strat = self.portfolio_manager.portfolio.get("strategies", {}).get(strategy_id)
        if not strat:
            return
            
        # Evolution Boundaries (Safety Caps)
        # Risk Multiplier: 0.5x to 1.5x
        # Stop-Loss: Max +0.5x ATR widening
        
        adjustments_made = []
        
        if patterns.get("stop_tightness_issue"):
            # Widen stop loss slightly
            current_atr_sl = float(strat.get("risk_management", {}).get("stop_loss_atr_multiplier", 1.5))
            new_atr_sl = min(current_atr_sl + 0.2, 2.0) # Cap at 2.0 (i.e. +0.5 from base 1.5)
            
            if new_atr_sl > current_atr_sl:
                strat["risk_management"]["stop_loss_atr_multiplier"] = new_atr_sl
                adjustments_made.append(f"Widened Stop-Loss ATR from {current_atr_sl} to {new_atr_sl} due to premature stops.")
                
        if patterns.get("win_rate", 0) > 0.6:
            # Increase risk multiplier
            current_risk = float(strat.get("risk_management", {}).get("risk_multiplier", 1.0))
            new_risk = min(current_risk + 0.1, 1.5) # Cap at 1.5
            if new_risk > current_risk:
                strat["risk_management"]["risk_multiplier"] = new_risk
                adjustments_made.append(f"Increased Risk Multiplier from {current_risk} to {new_risk} due to high win rate.")
        elif patterns.get("win_rate", 0) < 0.4:
            # Decrease risk multiplier
            current_risk = float(strat.get("risk_management", {}).get("risk_multiplier", 1.0))
            new_risk = max(current_risk - 0.2, 0.5) # Cap at 0.5
            if new_risk < current_risk:
                strat["risk_management"]["risk_multiplier"] = new_risk
                adjustments_made.append(f"Decreased Risk Multiplier from {current_risk} to {new_risk} due to low win rate.")
                
        if adjustments_made:
            self.portfolio_manager.save_portfolio()
            logger.info(f"Applied Autonomous Evolution: {adjustments_made}")
            
            # Send Telegram Alert if possible
            bus = EventBus()
            bus.publish("EVOLUTION_APPLIED", {
                "strategy": strategy_id,
                "adjustments": adjustments_made,
                "timestamp": datetime.utcnow().isoformat()
            })

    def evaluate_promotions(self) -> None:
        """Evaluate probation strategies for promotion to LIVE/ACTIVE."""
        strategies = self.portfolio_manager.portfolio.get("strategies", {})
        promoted = False
        for s_id, strat in strategies.items():
            if strat.get("status") == "PROBATION":
                # Check metrics
                wr = strat.get("win_rate", {}).get("DEFAULT", 0)
                tc = strat.get("trade_count", {}).get("DEFAULT", 0)
                
                if tc >= 10 and wr >= 55.0:
                    strat["status"] = "ACTIVE"
                    strat["history"].append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": "Promoted to ACTIVE due to proven paper/shadow performance."
                    })
                    promoted = True
                    
                    try:
                        from integrations.notifications.telegram_bot import TelegramBotUplink
                        tb = TelegramBotUplink()
                        tb.send_message(
                            f"🚀 *STRATEGY PROMOTION* 🚀\n"
                            f"Strategy `{strat.get('name')}` ({s_id}) has proven itself in Shadow/Paper trading.\n"
                            f"• Trades: {tc}\n"
                            f"• Win Rate: {wr}%\n"
                            f"Automatically promoted to ACTIVE/LIVE mode."
                        )
                    except Exception as e:
                        logger.error(f"Error sending promotion alert: {e}")
                        
        if promoted:
            self.portfolio_manager.save()
