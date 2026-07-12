"""Investment Committee & Institutional Decision Engine for Hokage.

Implements Phase 5B.5:
- Independent committee members evaluating distinct evidence.
- Weighted collective confidence based on uncertainty and calibrated weights.
- Atomic append-only ledger for institutional memory.
- Dynamic performance tracking and self-calibration.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.InvestmentCommittee")


class Vote:
    """Represents a single committee member's vote details."""

    def __init__(
        self,
        vote: str,  # "APPROVE", "REJECT", "ABSTAIN"
        confidence: float,  # 0.0 to 100.0
        reasoning: str,
        evidence: dict[str, Any],
        uncertainty: float,  # 0.0 (complete certainty) to 1.0 (complete uncertainty)
        veto_status: bool = False,
    ) -> None:
        self.vote = vote.upper()
        self.confidence = confidence
        self.reasoning = reasoning
        self.evidence = evidence
        self.uncertainty = uncertainty
        self.veto_status = veto_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "vote": self.vote,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "veto_status": self.veto_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vote:
        return cls(
            vote=data.get("vote", "ABSTAIN"),
            confidence=data.get("confidence", 50.0),
            reasoning=data.get("reasoning", ""),
            evidence=data.get("evidence", {}),
            uncertainty=data.get("uncertainty", 0.5),
            veto_status=data.get("veto_status", False),
        )


class CommitteeDecision:
    """Represents the final collective decision of the Investment Committee."""

    def __init__(
        self,
        final_verdict: str,  # "APPROVED", "REJECTED"
        votes: dict[str, Vote],
        approval_percentage: float,
        decision_confidence: float,
        veto_triggered: bool,
        rejecting_committees: list[str],
        veto_committees: list[str],
        evidence_references: dict[str, Any],
    ) -> None:
        self.final_verdict = final_verdict
        self.votes = votes
        self.approval_percentage = approval_percentage
        self.decision_confidence = decision_confidence
        self.veto_triggered = veto_triggered
        self.rejecting_committees = rejecting_committees
        self.veto_committees = veto_committees
        self.evidence_references = evidence_references

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_verdict": self.final_verdict,
            "votes": {name: vote.to_dict() for name, vote in self.votes.items()},
            "approval_percentage": self.approval_percentage,
            "decision_confidence": self.decision_confidence,
            "veto_triggered": self.veto_triggered,
            "rejecting_committees": self.rejecting_committees,
            "veto_committees": self.veto_committees,
            "evidence_references": self.evidence_references,
        }


class InvestmentCommittee:
    """Orchestrates independent specialized committee evaluations."""

    def __init__(self, resolver: PathResolver | None = None) -> None:
        self._resolver = resolver or PathResolver()
        self._config_dir = self._resolver.resolve_config_dir()
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._weights_file = self._config_dir / "committee_weights.json"
        self._load_weights()

    def _load_weights(self) -> None:
        """Load calibrated committee weights from config, defaulting to 1.0."""
        self.weights = {
            "Research": 1.0,
            "Trend": 1.0,
            "MarketStructure": 1.0,
            "Macro": 1.0,
            "Volatility": 1.0,
            "Risk": 1.0,
            "CapitalPreservation": 1.0,
            "LiquidityExecution": 1.0,
            "Strategy": 1.0,
        }
        if self._weights_file.exists():
            try:
                with self._weights_file.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    for k, v in data.items():
                        if k in self.weights:
                            self.weights[k] = float(v)
            except Exception as exc:
                logger.error("Failed to load committee weights: %s", exc)

    def _save_weights(self) -> None:
        """Save calibrated committee weights atomically using write-then-rename."""
        tmp_path = self._weights_file.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(self.weights, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            tmp_path.replace(self._weights_file)
        except Exception as exc:
            logger.error("Failed to save calibrated weights: %s", exc)

    def evaluate_proposal(
        self,
        proposal: Any,
        backtest_result: Any,
        context: dict[str, Any]
    ) -> CommitteeDecision:
        """Runs independent evaluations across all 9 members to make a decision."""
        # 1. Research Committee
        res_score = proposal.confidence_score if hasattr(proposal, "confidence_score") else 50.0
        if res_score >= 60.0:
            v_res = Vote("APPROVE", res_score, f"Strong research conviction score of {res_score}.", {"proposal_score": res_score}, 1.0 - (res_score / 100.0))
        elif res_score >= 45.0:
            v_res = Vote("ABSTAIN", res_score, f"Moderate research conviction score of {res_score}.", {"proposal_score": res_score}, 0.5)
        else:
            v_res = Vote("REJECT", res_score, f"Insufficient research conviction score of {res_score}.", {"proposal_score": res_score}, res_score / 100.0)

        # 2. Trend Committee
        win_rate = backtest_result.win_rate if hasattr(backtest_result, "win_rate") else 50.0
        market_regime = context.get("market_regime", "NORMAL")
        if market_regime in ("NORMAL", "RISK-ON") and win_rate >= 50.0:
            v_trend = Vote("APPROVE", win_rate, f"Favorable regime {market_regime} and acceptable backtest win rate {win_rate}%.", {"regime": market_regime, "win_rate": win_rate}, 0.1)
        elif win_rate >= 40.0:
            v_trend = Vote("ABSTAIN", win_rate, f"Regime {market_regime} with moderate win rate {win_rate}%.", {"regime": market_regime, "win_rate": win_rate}, 0.4)
        else:
            v_trend = Vote("REJECT", win_rate, f"Unfavorable trend parameters (win rate {win_rate}%).", {"regime": market_regime, "win_rate": win_rate}, 0.6)

        # 3. Market Structure Committee
        profit_factor = backtest_result.profit_factor if hasattr(backtest_result, "profit_factor") else 1.0
        struct_conf = min(100.0, profit_factor * 40.0)
        if profit_factor >= 1.3:
            v_struct = Vote("APPROVE", struct_conf, f"Acceptable reward/risk structure with profit factor {profit_factor}.", {"profit_factor": profit_factor}, 0.15)
        elif profit_factor >= 1.0:
            v_struct = Vote("ABSTAIN", struct_conf, f"Marginal reward/risk profile (profit factor {profit_factor}).", {"profit_factor": profit_factor}, 0.4)
        else:
            v_struct = Vote("REJECT", struct_conf, f"Poor reward/risk structure (profit factor {profit_factor}).", {"profit_factor": profit_factor}, 0.7)

        # 4. Macro Committee
        flow_strength = context.get("sector_flow_strength", 0.0)
        macro_conf = min(100.0, max(0.0, (flow_strength + 0.1) * 500.0))
        if flow_strength > 0.05:
            v_macro = Vote("APPROVE", macro_conf, f"Positive sector rotation inflows of {flow_strength:.3f}.", {"flow_strength": flow_strength}, 0.2)
        elif flow_strength >= -0.02:
            v_macro = Vote("ABSTAIN", macro_conf, f"Neutral sector rotation flows of {flow_strength:.3f}.", {"flow_strength": flow_strength}, 0.5)
        else:
            v_macro = Vote("REJECT", macro_conf, f"Sector rotation outflows of {flow_strength:.3f}.", {"flow_strength": flow_strength}, 0.6)

        # 5. Volatility Committee — relaxed: REJECT only on extreme panic (VIX delta >=4.0)
        vix_impact = context.get("vix_impact_delta", 0.0)
        vol_conf = max(0.0, 100.0 - (vix_impact * 20.0))
        if vix_impact < 2.5:
            v_vol = Vote("APPROVE", vol_conf, f"Volatility levels within boundaries (VIX delta {vix_impact:.2f}).", {"vix_impact": vix_impact}, 0.1)
        elif vix_impact < 4.0:
            v_vol = Vote("ABSTAIN", vol_conf, f"Elevated volatility detected (VIX delta {vix_impact:.2f}). Proceeding with caution.", {"vix_impact": vix_impact}, 0.3)
        else:
            v_vol = Vote("REJECT", vol_conf, f"VIX delta {vix_impact:.2f} exceeds extreme panic thresholds. Vetoing.", {"vix_impact": vix_impact}, 0.8)

        # 6. Risk Committee (Veto)
        risk_approved = context.get("risk_approved", False)
        risk_reason = context.get("risk_reason", "Risk parameters verified.")
        if risk_approved:
            v_risk = Vote("APPROVE", 100.0, "All risk boundaries and exposures satisfied.", {"reason": risk_reason}, 0.0, veto_status=True)
        else:
            v_risk = Vote("REJECT", 100.0, f"Risk check failed: {risk_reason}", {"reason": risk_reason}, 0.0, veto_status=True)

        # 7. Capital Preservation Committee (Veto)
        preservation_mode = context.get("preservation_mode", "NORMAL")
        drawdown_pct = context.get("drawdown_pct", 0.0)
        if preservation_mode == "NORMAL":
            v_pres = Vote("APPROVE", 100.0, f"Capital drawdown {drawdown_pct:.2f}% inside normal limits.", {"mode": preservation_mode, "drawdown": drawdown_pct}, 0.0, veto_status=True)
        elif preservation_mode == "RECOVERY":
            v_pres = Vote("ABSTAIN", 50.0, f"System is in RECOVERY mode due to {drawdown_pct:.2f}% drawdown.", {"mode": preservation_mode, "drawdown": drawdown_pct}, 0.3, veto_status=True)
        else:
            v_pres = Vote("REJECT", 100.0, f"Capital Preservation mode is {preservation_mode}. Veto active.", {"mode": preservation_mode, "drawdown": drawdown_pct}, 0.0, veto_status=True)

        # 8. Liquidity & Execution Committee (Veto)
        has_cash = context.get("cash_available", True)
        valid_price = context.get("valid_price", True)
        if has_cash and valid_price:
            v_liq = Vote("APPROVE", 100.0, "Liquidity and feed validation passed.", {"cash": has_cash, "price": valid_price}, 0.0, veto_status=True)
        else:
            reasons = []
            if not has_cash:
                reasons.append("insufficient funds")
            if not valid_price:
                reasons.append("invalid price feeds")
            v_liq = Vote("REJECT", 100.0, f"Execution failed: {', '.join(reasons)}.", {"cash": has_cash, "price": valid_price}, 0.0, veto_status=True)

        # 9. Strategy Committee
        strategy_conf = context.get("strategy_confidence", 50.0)
        strategy_name = context.get("strategy_name", "strat-autotrend")
        if strategy_conf >= 70.0:
            v_strat = Vote("APPROVE", strategy_conf, f"Strategy {strategy_name} matches domain requirements.", {"strategy": strategy_name, "strat_confidence": strategy_conf}, 1.0 - (strategy_conf / 100.0))
        elif strategy_conf >= 50.0:
            v_strat = Vote("ABSTAIN", strategy_conf, f"Strategy {strategy_name} within acceptable bounds.", {"strategy": strategy_name, "strat_confidence": strategy_conf}, 0.5)
        else:
            v_strat = Vote("REJECT", strategy_conf, f"Strategy {strategy_name} exhibits low domain expectation.", {"strategy": strategy_name, "strat_confidence": strategy_conf}, 1.0 - (strategy_conf / 100.0))

        votes = {
            "Research": v_res,
            "Trend": v_trend,
            "MarketStructure": v_struct,
            "Macro": v_macro,
            "Volatility": v_vol,
            "Risk": v_risk,
            "CapitalPreservation": v_pres,
            "LiquidityExecution": v_liq,
            "Strategy": v_strat,
        }

        # Determine veto triggers
        veto_triggered = False
        veto_committees = []
        for name in ["Risk", "CapitalPreservation", "LiquidityExecution"]:
            if votes[name].vote == "REJECT":
                veto_triggered = True
                veto_committees.append(name)

        # Count votes
        approvals = sum(1 for v in votes.values() if v.vote == "APPROVE")
        rejections = sum(1 for v in votes.values() if v.vote == "REJECT")
        non_abstaining = approvals + rejections
        approval_pct = (approvals / non_abstaining * 100.0) if non_abstaining > 0 else 0.0

        # Calculate final verdict:
        # APPROVED if:
        #   - No hard veto (Risk, CapitalPreservation, LiquidityExecution)
        #   - AND approvals >= rejections (ABSTAIN votes are neutral — they do NOT count as rejections)
        # This ensures ABSTAIN from noisy committees (Macro, Research, Strategy) doesn't kill good trades.
        if not veto_triggered and approvals >= rejections:
            final_verdict = "APPROVED"
        else:
            final_verdict = "REJECTED"

        # Calculate Weighted Collective Decision Confidence
        total_weight = 0.0
        weighted_confidence_sum = 0.0
        for name, vote in votes.items():
            # Only weight votes that contributed to the winning direction
            is_winner = (final_verdict == "APPROVED" and vote.vote == "APPROVE") or (final_verdict == "REJECTED" and vote.vote == "REJECT")
            if is_winner:
                weight = self.weights.get(name, 1.0) * (1.0 - vote.uncertainty)
                weighted_confidence_sum += weight * vote.confidence
                total_weight += weight

        decision_confidence = (weighted_confidence_sum / total_weight) if total_weight > 0 else 50.0

        rejecting_committees = [name for name, v in votes.items() if v.vote == "REJECT"]

        evidence_references = {
            "proposal_score": res_score,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "vix_impact_delta": vix_impact,
            "drawdown_pct": drawdown_pct,
            "sector_flow_strength": flow_strength,
            "market_regime": market_regime,
        }

        return CommitteeDecision(
            final_verdict=final_verdict,
            votes=votes,
            approval_percentage=approval_pct,
            decision_confidence=decision_confidence,
            veto_triggered=veto_triggered,
            rejecting_committees=rejecting_committees,
            veto_committees=veto_committees,
            evidence_references=evidence_references,
        )


class CommitteeLedger:
    """Manages immutable committee ledger writes."""

    def __init__(self, resolver: PathResolver | None = None) -> None:
        self._resolver = resolver or PathResolver()
        self._journal_dir = self._resolver.resolve_brain_root() / "journal"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_file = self._journal_dir / "committee_ledger.jsonl"

    def record_decision(
        self,
        decision_id: str,
        strategy_id: str,
        symbol: str,
        decision: CommitteeDecision
    ) -> None:
        """Append the decision to the ledger file atomically (write-then-rename)."""
        record = {
            "opportunity_id": decision_id,
            "strategy_id": strategy_id,
            "symbol": symbol.upper(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "committee_votes": {name: vote.to_dict() for name, vote in decision.votes.items()},
            "veto_triggered": decision.veto_triggered,
            "final_verdict": decision.final_verdict,
            "approval_percentage": decision.approval_percentage,
            "decision_confidence": decision.decision_confidence,
            "evidence_references": decision.evidence_references,
            "rejecting_committees": decision.rejecting_committees,
            "veto_committees": decision.veto_committees,
        }

        # Safe append pattern:
        # Since this is an append-only jsonl log, we first read existing lines, append the new line,
        # write to a temp file, and rename it to overwrite.
        lines = []
        if self._ledger_file.exists():
            try:
                with self._ledger_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            lines.append(line)
            except Exception as exc:
                logger.error("Failed to read existing committee ledger: %s", exc)

        lines.append(json.dumps(record, sort_keys=True) + "\n")

        tmp_file = self._ledger_file.with_suffix(".tmp")
        try:
            with tmp_file.open("w", encoding="utf-8") as fh:
                fh.writelines(lines)
                fh.flush()
                os.fsync(fh.fileno())
            tmp_file.replace(self._ledger_file)
        except Exception as exc:
            logger.error("Failed to write atomically to committee ledger: %s", exc)

    def load_entries(self) -> list[dict[str, Any]]:
        """Load all ledger records from disk."""
        entries = []
        if not self._ledger_file.exists():
            return entries
        try:
            with self._ledger_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s:
                        entries.append(json.loads(s))
        except Exception as exc:
            logger.error("Failed to read committee ledger: %s", exc)
        return entries


class CommitteePerformanceTracker:
    """Analyzes committee performance and updates calibrated weights."""

    def __init__(self, resolver: PathResolver | None = None) -> None:
        self._resolver = resolver or PathResolver()
        self.ledger = CommitteeLedger(self._resolver)

    def compute_stats(self, outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Calculates stats for all committees based on actual outcomes."""
        entries = self.ledger.load_entries()
        
        # Maps opportunity_id -> outcome dict
        outcomes_map = {o["decision_id"]: o for o in outcomes}

        stats: dict[str, dict[str, Any]] = {
            "Research": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "Trend": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "MarketStructure": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "Macro": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "Volatility": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "Risk": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "CapitalPreservation": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "LiquidityExecution": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
            "Strategy": {"correct": 0, "incorrect": 0, "abstains": 0, "vetoes_prevented_loss": 0},
        }

        for ent in entries:
            opp_id = ent.get("opportunity_id")
            votes = ent.get("committee_votes", {})
            
            # If the trade was actually executed and we have its outcome
            if opp_id in outcomes_map:
                out = outcomes_map[opp_id]
                outcome = out.get("outcome")  # "WIN" or "LOSS" or "BREAKEVEN"
                if outcome not in ("WIN", "LOSS"):
                    continue
                
                is_win = (outcome == "WIN")

                for name, v_data in votes.items():
                    vote_val = v_data.get("vote")
                    if vote_val == "APPROVE":
                        if is_win:
                            stats[name]["correct"] += 1
                        else:
                            stats[name]["incorrect"] += 1
                    elif vote_val == "REJECT":
                        if not is_win:
                            stats[name]["correct"] += 1
                        else:
                            stats[name]["incorrect"] += 1
                    elif vote_val == "ABSTAIN":
                        stats[name]["abstains"] += 1

            # For rejected/vetoed entries (no execution), evaluate veto accuracy if we can
            elif ent.get("final_verdict") == "REJECTED":
                # A veto was accurate if VIX was high or backtest win_rate < 50
                ev = ent.get("evidence_references", {})
                is_justified = (ev.get("vix_impact_delta", 0) >= 2.0 or ev.get("win_rate", 100) < 50.0)
                
                for name, v_data in votes.items():
                    vote_val = v_data.get("vote")
                    if vote_val == "REJECT":
                        if is_justified:
                            stats[name]["vetoes_prevented_loss"] += 1

        # Format stats with percentages
        summary = {}
        for name, data in stats.items():
            correct = data["correct"]
            incorrect = data["incorrect"]
            total_voted = correct + incorrect
            accuracy = (correct / total_voted * 100.0) if total_voted > 0 else 100.0
            
            summary[name] = {
                "accuracy": round(accuracy, 2),
                "correct_votes": correct,
                "incorrect_votes": incorrect,
                "abstains": data["abstains"],
                "losses_prevented": data["vetoes_prevented_loss"],
            }

        return summary

    def calibrate_weights(self, outcomes: list[dict[str, Any]]) -> dict[str, float]:
        """Recalibrate committee weights based on accuracy, saving to file."""
        stats = self.compute_stats(outcomes)
        
        committee = InvestmentCommittee(self._resolver)
        
        for name, data in stats.items():
            acc = data["accuracy"]
            
            # Calibration logic: adjust weights gradually towards accuracy ratio
            # Baseline weight is 1.0. If accuracy is 75%, weight adjusts towards 1.5.
            # If accuracy is 40%, weight adjusts downwards.
            target_weight = max(0.1, min(2.0, acc / 60.0)) # 60% = 1.0 weight
            current_weight = committee.weights.get(name, 1.0)
            
            # Smooth weight evolution (learning rate of 0.2)
            new_weight = current_weight + 0.2 * (target_weight - current_weight)
            committee.weights[name] = round(new_weight, 3)

        committee._save_weights()
        return committee.weights
