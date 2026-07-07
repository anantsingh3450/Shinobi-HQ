"""Strategy Research Pipeline and Evolution Engine for Hokage.

Enforces:
- Expanded Lifecycle: RESEARCH -> BACKTEST -> PAPER_VALIDATION -> SHADOW_MODE -> PROBATION -> PRODUCTION.
- Statistical, evidence-based promotions.
- Immutable notification logs for the commander.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver
from shared.statistics import hac_t_test

logger = logging.getLogger("Hokage.StrategyEvolution")


class StrategyEvolutionEngine:
    """Manages strategy mutation, candidate lifecycle, promotions, and notifications."""

    def __init__(self, resolver: PathResolver | None = None) -> None:
        self._resolver = resolver or PathResolver()
        self._journal_dir = self._resolver.resolve_brain_root() / "journal"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._notifications_file = self._journal_dir / "strategy_notifications.jsonl"
        self._shadow_decisions_file = self._journal_dir / "shadow_decisions.jsonl"

    def discover_candidate(
        self,
        parent_id: str,
        name: str,
        version: str,
        intended_assets: list[str],
        intended_regimes: list[str],
        evidence: dict[str, Any]
    ) -> dict[str, Any]:
        """Discovers and logs a new strategy candidate in RESEARCH status."""
        strategy_id = f"strat-{name.lower().replace(' ', '-')}-{str(uuid.uuid4())[:8]}"
        now_str = datetime.now(timezone.utc).isoformat()

        candidate = {
            "strategy_id": strategy_id,
            "name": name,
            "version": version,
            "parent_strategy_id": parent_id,
            "created_at": now_str,
            "discovery_timestamp": now_str,
            "status": "RESEARCH",  # RESEARCH -> BACKTEST -> PAPER_VALIDATION -> SHADOW_MODE -> PROBATION -> PRODUCTION
            "supported_assets": [a.upper() for a in intended_assets],
            "supported_regimes": [r.upper() for r in intended_regimes],
            "domain_confidence": {"DEFAULT": 50.0},
            "expectancy": {"DEFAULT": 0.0},
            "win_rate": {"DEFAULT": 50.0},
            "drawdown": {"DEFAULT": 0.0},
            "sharpe_ratio": {"DEFAULT": 1.0},
            "trade_count": {"DEFAULT": 0},
            "supporting_evidence": evidence,
            "history": [
                {"timestamp": now_str, "event": f"Candidate strategy discovered in RESEARCH status. Parent: {parent_id}."}
            ]
        }

        # Log Notification
        self.notify_commander(
            strategy_id=strategy_id,
            change_type="DISCOVERY",
            reason=f"Genuinely new strategy candidate '{name}' created from parent '{parent_id}'.",
            evidence=evidence,
            validation_status="RESEARCH",
            confidence=50.0,
            is_experimental=True
        )

        return candidate

    def notify_commander(
        self,
        strategy_id: str,
        change_type: str,  # "DISCOVERY", "PROMOTION", "DEMOTION", "EVOLUTION"
        reason: str,
        evidence: dict[str, Any],
        validation_status: str,
        confidence: float,
        is_experimental: bool
    ) -> None:
        """Write notification record atomically (write-then-rename) to strategy_notifications.jsonl or SQL."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self._resolver):
            engine = SqliteStorageEngine(self._resolver)
            conn = engine.get_connection()
            try:
                now_str = datetime.now(timezone.utc).isoformat()
                status_str = "EXPERIMENTAL" if is_experimental else "PRODUCTION_READY"
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO strategy_notifications (
                            timestamp, strategy_id, change_type, reason, supporting_evidence,
                            validation_status, confidence, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        now_str, strategy_id, change_type, reason, json.dumps(evidence),
                        validation_status, confidence, status_str
                    ))
                logger.info(f"Commander notification dispatched for strategy {strategy_id} via SQLite: {change_type}")
                return
            except Exception as exc:
                logger.error(f"Failed to write strategy notification to SQLite: {exc}")
                raise exc

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_id": strategy_id,
            "change_type": change_type,
            "reason": reason,
            "supporting_evidence": evidence,
            "validation_status": validation_status,
            "confidence": confidence,
            "status": "EXPERIMENTAL" if is_experimental else "PRODUCTION_READY",
        }

        lines = []
        if self._notifications_file.exists():
            try:
                with self._notifications_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            lines.append(line)
            except Exception as exc:
                logger.error("Failed to read strategy notifications: %s", exc)

        lines.append(json.dumps(record, sort_keys=True) + "\n")

        tmp_file = self._notifications_file.with_suffix(".tmp")
        try:
            with tmp_file.open("w", encoding="utf-8") as fh:
                fh.writelines(lines)
                fh.flush()
                os.fsync(fh.fileno())
            tmp_file.replace(self._notifications_file)
            logger.info(f"Commander notification dispatched for strategy {strategy_id}: {change_type}")
        except Exception as exc:
            logger.error("Failed to write strategy notification atomically: %s", exc)

    def log_shadow_decision(
        self,
        strategy_id: str,
        symbol: str,
        decision_type: str,  # "ENTRY", "EXIT", "SIZING", "HOLD"
        decision_details: dict[str, Any]
    ) -> None:
        """Appends a simulated decision record in shadow mode (without real execution)."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self._resolver):
            engine = SqliteStorageEngine(self._resolver)
            conn = engine.get_connection()
            try:
                now_str = datetime.now(timezone.utc).isoformat()
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO shadow_decisions (
                            timestamp, strategy_id, symbol, decision_type, details
                        ) VALUES (?, ?, ?, ?, ?);
                    """, (
                        now_str, strategy_id, symbol.upper(), decision_type, json.dumps(decision_details)
                    ))
                logger.info(f"Logged shadow decision for {strategy_id} on {symbol} to SQLite.")
                return
            except Exception as exc:
                logger.error(f"Failed to write shadow decision to SQLite: {exc}")
                raise exc

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_id": strategy_id,
            "symbol": symbol.upper(),
            "decision_type": decision_type,
            "details": decision_details,
        }
        try:
            # We append directly to append-only shadow decisions file
            with self._shadow_decisions_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except Exception as exc:
            logger.error("Failed to write shadow decision: %s", exc)

    def evaluate_pipeline_transition(
        self,
        strategy: dict[str, Any],
        active_production_strategy: dict[str, Any] | None,
        asset: str = "DEFAULT"
    ) -> tuple[bool, str]:
        """Runs pipeline stage validations and performs evidence-based promotions."""
        status = strategy.get("status", "RESEARCH")
        strategy_id = strategy["strategy_id"]
        now_str = datetime.now(timezone.utc).isoformat()
        
        # 1. RESEARCH -> BACKTEST
        if status == "RESEARCH":
            evidence = strategy.get("supporting_evidence", {})
            if evidence.get("backtest_win_rate", 0.0) >= 55.0 and evidence.get("backtest_expectancy", 0.0) > 0:
                strategy["status"] = "BACKTEST"
                strategy["history"].append({"timestamp": now_str, "event": "Transitioned to BACKTEST: Backtest win rate >= 55%."})
                return True, "Transitioned from RESEARCH to BACKTEST."
            return False, "Insufficient backtest evidence to exit RESEARCH status."

        # 2. BACKTEST -> PAPER_VALIDATION
        if status == "BACKTEST":
            # Check backtest drawdown limits (e.g. max drawdown <= 15%)
            evidence = strategy.get("supporting_evidence", {})
            max_dd = evidence.get("max_drawdown", 100.0)
            if max_dd <= 15.0:
                strategy["status"] = "PAPER_VALIDATION"
                strategy["history"].append({"timestamp": now_str, "event": "Transitioned to PAPER_VALIDATION: Max backtest drawdown <= 15%."})
                return True, "Transitioned from BACKTEST to PAPER_VALIDATION."
            return False, f"Backtest drawdown ({max_dd}%) exceeds limit of 15%."

        # 3. PAPER_VALIDATION -> SHADOW_MODE
        if status == "PAPER_VALIDATION":
            # Paper trading simulation must have positive outcome records
            trade_count = strategy["trade_count"].get("DEFAULT", 0)
            win_rate = strategy["win_rate"].get("DEFAULT", 50.0)
            if trade_count >= 5 and win_rate >= 55.0:
                strategy["status"] = "SHADOW_MODE"
                strategy["history"].append({"timestamp": now_str, "event": "Transitioned to SHADOW_MODE: Passed initial paper trading (>= 5 trades, wr >= 55%)."})
                self.notify_commander(
                    strategy_id=strategy_id,
                    change_type="PROMOTION",
                    reason=f"Strategy '{strategy['name']}' promoted to SHADOW_MODE. Initiating shadow executions.",
                    evidence={"trade_count": trade_count, "win_rate": win_rate},
                    validation_status="SHADOW_MODE",
                    confidence=win_rate,
                    is_experimental=True
                )
                return True, "Transitioned from PAPER_VALIDATION to SHADOW_MODE."
            return False, f"Insufficient paper trades ({trade_count}/5 completed) or low win rate ({win_rate}%)."

        # 4. SHADOW_MODE -> PROBATION
        if status == "SHADOW_MODE":
            trade_count = strategy["trade_count"].get("DEFAULT", 0)
            win_rate = strategy["win_rate"].get("DEFAULT", 50.0)
            if trade_count >= 8 and win_rate >= 57.0:
                strategy["status"] = "PROBATION"
                strategy["history"].append({"timestamp": now_str, "event": "Transitioned to PROBATION: Passed shadow mode tracking."})
                return True, "Transitioned from SHADOW_MODE to PROBATION."
            return False, f"Insufficient shadow trades ({trade_count}/8) or low win rate ({win_rate}%)."

        # 5. PROBATION -> PRODUCTION (ACTIVE)
        # Evidence-Based Promotion: Compare against production strategy
        if status == "PROBATION":
            if not active_production_strategy:
                # No existing production strategy in this domain, promote directly!
                strategy["status"] = "PRODUCTION"
                strategy["history"].append({"timestamp": now_str, "event": "PROMOTION: Promoted to PRODUCTION (first strategy in domain)."})
                self.notify_commander(
                    strategy_id=strategy_id,
                    change_type="PROMOTION",
                    reason=f"Strategy '{strategy['name']}' promoted to PRODUCTION.",
                    evidence=strategy["domain_confidence"],
                    validation_status="PRODUCTION",
                    confidence=strategy["domain_confidence"].get("DEFAULT", 50.0),
                    is_experimental=False
                )
                return True, "Promoted from PROBATION to PRODUCTION."

            # Perform statistical comparison
            t_count = strategy.get("trade_count", {}).get(asset, strategy.get("trade_count", {}).get("DEFAULT", 0))
            t_win_rate = strategy.get("win_rate", {}).get(asset, strategy.get("win_rate", {}).get("DEFAULT", 50.0))
            t_expectancy = strategy.get("expectancy", {}).get(asset, strategy.get("expectancy", {}).get("DEFAULT", 0.0))
            t_sharpe = strategy.get("sharpe_ratio", {}).get(asset, strategy.get("sharpe_ratio", {}).get("DEFAULT", 1.0))
            t_drawdown = strategy.get("drawdown", {}).get(asset, strategy.get("drawdown", {}).get("DEFAULT", 0.0))

            prod_count = active_production_strategy.get("trade_count", {}).get(asset, active_production_strategy.get("trade_count", {}).get("DEFAULT", 0))
            prod_win_rate = active_production_strategy.get("win_rate", {}).get(asset, active_production_strategy.get("win_rate", {}).get("DEFAULT", 50.0))
            prod_expectancy = active_production_strategy.get("expectancy", {}).get(asset, active_production_strategy.get("expectancy", {}).get("DEFAULT", 0.0))
            prod_sharpe = active_production_strategy.get("sharpe_ratio", {}).get(asset, active_production_strategy.get("sharpe_ratio", {}).get("DEFAULT", 1.0))
            prod_drawdown = active_production_strategy.get("drawdown", {}).get(asset, active_production_strategy.get("drawdown", {}).get("DEFAULT", 0.0))

            # Retrieve actual histories to calculate standard deviations directly
            t_history = strategy.get("pnl_history", {}).get(asset, strategy.get("pnl_history", {}).get("DEFAULT", []))
            if len(t_history) > 1:
                t_mean = sum(t_history) / len(t_history)
                t_var = sum((x - t_mean) ** 2 for x in t_history) / (len(t_history) - 1)
                t_std = math.sqrt(t_var)
            else:
                t_std = abs(t_expectancy / t_sharpe) if t_sharpe != 0 else 1.0

            prod_history = active_production_strategy.get("pnl_history", {}).get(asset, active_production_strategy.get("pnl_history", {}).get("DEFAULT", []))
            if len(prod_history) > 1:
                prod_mean = sum(prod_history) / len(prod_history)
                prod_var = sum((x - prod_mean) ** 2 for x in prod_history) / (len(prod_history) - 1)
                prod_std = math.sqrt(prod_var)
            else:
                prod_std = abs(prod_expectancy / prod_sharpe) if prod_sharpe != 0 else 1.0

            # Perform statistical comparison using both classical and HAC-adjusted statistics
            res = hac_t_test(
                t_history,
                prod_history,
                fallback_mean_x=t_expectancy,
                fallback_mean_y=prod_expectancy,
                fallback_std_x=t_std,
                fallback_std_y=prod_std,
                fallback_n_x=t_count,
                fallback_n_y=prod_count,
                method="newey_west_1994"
            )
            
            classical_t_stat = res["classical_t_stat"]
            classical_se_diff = res["classical_se_diff"]
            classical_ci_lower = res["classical_ci_lower"]
            
            hac_t_stat = res["hac_t_stat"]
            hac_se_diff = res["hac_se_diff"]
            hac_ci_lower = res["hac_ci_lower"]
            
            lag_x = res["lag_x"]
            lag_y = res["lag_y"]
            bandwidth_method = res["bandwidth_method"]

            # Check robustness across different market regimes
            regime_stats = strategy.get("regime_stats", {})
            is_regime_robust = True
            for reg, stats in regime_stats.items():
                if stats.get("trade_count", 0) > 0 and stats.get("win_rate", 50.0) < 50.0:
                    is_regime_robust = False
                    break

            # Determine decisions
            # Classical decision
            classical_would_promote = (
                t_count >= 5 and 
                t_sharpe >= prod_sharpe and 
                t_drawdown <= prod_drawdown and 
                classical_t_stat >= 1.645 and 
                is_regime_robust
            )
            
            # HAC decision (actual authority)
            hac_promotes = (
                t_count >= 5 and 
                t_sharpe >= prod_sharpe and 
                t_drawdown <= prod_drawdown and 
                hac_t_stat >= 1.645 and 
                is_regime_robust
            )
            
            # Classification logic
            if classical_would_promote and not hac_promotes:
                event_classification = "FALSE_POSITIVE_PREVENTED"
                verdict = "REJECTED"
                explanation = (
                    f"Classical t-test approved promotion (t={classical_t_stat:.2f} >= 1.645), "
                    f"but HAC rejected it (t={hac_t_stat:.2f} < 1.645) due to serial correlation "
                    f"or heteroskedasticity (Lags: Probation={lag_x}, Production={lag_y})."
                )
            elif hac_promotes and not classical_would_promote:
                event_classification = "HAC_SIGNAL_DETECTED"
                verdict = "PROMOTED"
                explanation = (
                    f"HAC t-test approved promotion (t={hac_t_stat:.2f} >= 1.645), "
                    f"whereas classical Welch t-test rejected it (t={classical_t_stat:.2f} < 1.645)."
                )
            elif hac_promotes and classical_would_promote:
                event_classification = "STATISTICAL_CONSENSUS"
                verdict = "PROMOTED"
                explanation = (
                    f"Both classical (t={classical_t_stat:.2f}) and HAC-adjusted (t={hac_t_stat:.2f}) "
                    f"statistics agree on promotion."
                )
            else:
                event_classification = "STATISTICAL_CONSENSUS"
                verdict = "REJECTED"
                explanation = (
                    f"Both classical (t={classical_t_stat:.2f}) and HAC-adjusted (t={hac_t_stat:.2f}) "
                    f"statistics agree to reject promotion."
                )

            # Every promotion evaluation records the full side-by-side metrics
            evaluation_evidence = {
                "probation_sharpe": t_sharpe, "prod_sharpe": prod_sharpe,
                "probation_drawdown": t_drawdown, "prod_drawdown": prod_drawdown,
                "probation_expectancy": t_expectancy, "prod_expectancy": prod_expectancy,
                "t_statistic": round(classical_t_stat, 4),  # Preserve legacy output name for Welch
                "confidence_interval_lower": round(classical_ci_lower, 4),  # Preserve legacy output name
                "classical_t_statistic": round(classical_t_stat, 4),
                "hac_t_statistic": round(hac_t_stat, 4),
                "classical_se_diff": round(classical_se_diff, 4),
                "hac_se_diff": round(hac_se_diff, 4),
                "selected_lag_probation": lag_x,
                "selected_lag_production": lag_y,
                "bandwidth_selection_method": bandwidth_method,
                "classical_ci_lower": round(classical_ci_lower, 4),
                "hac_ci_lower": round(hac_ci_lower, 4),
                "promotion_verdict": verdict,
                "event_classification": event_classification,
                "explanation": explanation,
                "regime_robustness": is_regime_robust
            }
            
            # Record inside strategy evolution history
            strategy.setdefault("history", []).append({
                "timestamp": now_str,
                "event": f"EVALUATION [{event_classification}]: Verdict={verdict}. {explanation}"
            })

            if hac_promotes:
                strategy["status"] = "PRODUCTION"
                strategy["history"].append({
                    "timestamp": now_str,
                    "event": f"PROMOTION: Promoted to PRODUCTION. {explanation}"
                })
                
                # Update parent production strategy to archived/probation
                active_production_strategy["status"] = "PROBATION"
                active_production_strategy.setdefault("history", []).append({
                    "timestamp": now_str,
                    "event": f"DEMOTION: Replaced by superior strategy '{strategy['name']}'."
                })

                self.notify_commander(
                    strategy_id=strategy_id,
                    change_type="PROMOTION",
                    reason=f"Strategy '{strategy['name']}' promoted to PRODUCTION, replacing '{active_production_strategy['name']}'. {explanation}",
                    evidence=evaluation_evidence,
                    validation_status="PRODUCTION",
                    confidence=t_win_rate,
                    is_experimental=False
                )
                return True, f"Promoted from PROBATION to PRODUCTION. Verdict: {event_classification}."
            
            # If rejected, we still notify the commander of the false positive prevention or general rejection
            # to make sure the side-by-side comparison is logged and auditable.
            self.notify_commander(
                strategy_id=strategy_id,
                change_type="EVOLUTION",
                reason=f"Promotion evaluation evaluated. Verdict: {verdict}. {explanation}",
                evidence=evaluation_evidence,
                validation_status="PROBATION",
                confidence=t_win_rate,
                is_experimental=True
            )
            return False, f"Failed to outperform active production strategy with statistical confidence. Verdict: {event_classification}. {explanation}"

        return False, "Strategy already in PRODUCTION or ARCHIVED."

    def load_notifications(self) -> list[dict[str, Any]]:
        """Load all notifications from strategy_notifications.jsonl or SQLite."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self._resolver):
            engine = SqliteStorageEngine(self._resolver)
            conn = engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM strategy_notifications ORDER BY timestamp ASC;")
                entries = []
                for row in cursor.fetchall():
                    entries.append({
                        "timestamp": row["timestamp"],
                        "strategy_id": row["strategy_id"],
                        "change_type": row["change_type"],
                        "reason": row["reason"],
                        "supporting_evidence": json.loads(row["supporting_evidence"]),
                        "validation_status": row["validation_status"],
                        "confidence": row["confidence"],
                        "status": row["status"]
                    })
                return entries
            except Exception as exc:
                logger.error(f"Failed to read strategy notifications from SQLite: {exc}")
                return []

        entries = []
        if not self._notifications_file.exists():
            return entries
        try:
            with self._notifications_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s:
                        entries.append(json.loads(s))
        except Exception as exc:
            logger.error("Failed to read strategy notifications: %s", exc)
        return entries
