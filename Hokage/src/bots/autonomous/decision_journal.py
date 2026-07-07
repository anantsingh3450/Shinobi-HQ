"""Decision Journal System for Hokage — Phase 4C.5D.

Logs ALL accepted and rejected trade candidates with complete macro,
portfolio, and committee context to enable historical decision auditability.

Phase 4C.5D additions:
- reasoning_chain: Full 7-gate audit trail per decision
- update_decision_outcome: Writes to immutable decision_outcomes.jsonl
- get_summary_stats: Acceptance rate, most common veto, avg conviction

Architectural principle:
    Decision Journal  → records what Hokage BELIEVED.
    Decision Outcomes → records what ACTUALLY HAPPENED.
Both files are immutable append-only logs linked by decision_id.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver
from bots.autonomous.models import NoTradeDecision, TradeAuthorization

logger = logging.getLogger("Hokage.DecisionJournal")


class DecisionJournalSystem:
    """Logs accepted and rejected trade candidates to permanent memory journals.

    Storage:
        hokage_brain/journal/decision_journal.jsonl  — decision records
        hokage_brain/journal/decision_outcomes.jsonl — outcome updates (linked by decision_id)
        hokage_brain/journal/no_trade_decisions.jsonl — no-trade decision logs
        hokage_brain/journal/trade_authorizations.jsonl — trade authorization records
    Format: One JSON object per line (JSON Lines).
    """

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize DecisionJournalSystem."""
        self._resolver = PathResolver(brain_root)
        self._journal_dir = self._resolver.resolve_brain_root() / "journal"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._journal_file  = self._journal_dir / "decision_journal.jsonl"
        self._outcomes_file = self._journal_dir / "decision_outcomes.jsonl"
        self._no_trade_file = self._journal_dir / "no_trade_decisions.jsonl"
        self._authorizations_file = self._journal_dir / "trade_authorizations.jsonl"

        # Determine if SQLite is active
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        from shared.persistence.sqlite_stores import SqliteDecisionJournalSystem
        
        if SqliteStorageEngine.is_active(self._resolver):
            engine = SqliteStorageEngine(self._resolver)
            self._delegate = SqliteDecisionJournalSystem(engine)
        else:
            self._delegate = None

    def record_no_trade_decision(self, no_trade: NoTradeDecision) -> dict[str, Any]:
        """Record a NoTradeDecision entry."""
        if self._delegate is not None:
            return self._delegate.record_no_trade_decision(no_trade)

        entry = no_trade.to_dict()
        try:
            with self._no_trade_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
            logger.info("Recorded no-trade decision for %s", no_trade.asset)
        except Exception as exc:
            logger.error("Failed to write to no-trade decisions log: %s", exc)
        return entry

    def load_no_trade_decisions(self) -> list[dict[str, Any]]:
        """Load all no-trade decision entries from disk."""
        if self._delegate is not None:
            return self._delegate.load_no_trade_decisions()

        entries: list[dict[str, Any]] = []
        if not self._no_trade_file.exists():
            return entries
        try:
            with self._no_trade_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s:
                        entries.append(json.loads(s))
        except Exception as exc:
            logger.error("Failed to read no-trade decisions: %s", exc)
        return entries

    def record_trade_authorization(self, auth: TradeAuthorization) -> dict[str, Any]:
        """Record a TradeAuthorization entry."""
        if self._delegate is not None:
            return self._delegate.record_trade_authorization(auth)

        entry = auth.to_dict()
        try:
            with self._authorizations_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
            logger.info("Recorded trade authorization for %s %s", auth.direction, auth.asset)
        except Exception as exc:
            logger.error("Failed to write to trade authorizations log: %s", exc)
        return entry

    def load_trade_authorizations(self) -> list[dict[str, Any]]:
        """Load all trade authorization entries from disk."""
        if self._delegate is not None:
            return self._delegate.load_trade_authorizations()

        entries: list[dict[str, Any]] = []
        if not self._authorizations_file.exists():
            return entries
        try:
            with self._authorizations_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s:
                        entries.append(json.loads(s))
        except Exception as exc:
            logger.error("Failed to read trade authorizations: %s", exc)
        return entries

    # ------------------------------------------------------------------
    # Primary write method
    # ------------------------------------------------------------------

    def record_decision(
        self,
        symbol: str,
        # Core Phase 4C.5C fields
        decision: str = "REJECTED",
        conviction: int = 0,
        conviction_breakdown: dict[str, Any] | None = None,
        reason: str = "",
        veto_source: str | None = None,
        market_regime: str = "UNKNOWN",
        sector_flow: str = "N/A",
        expected_holding_days: int = 3,
        expected_return_pct: float = 0.0,
        expected_risk_pct: float = 0.0,
        decision_id: str | None = None,
        # Phase 4C.5D: full reasoning chain
        reasoning_chain: list[dict[str, Any]] | None = None,
        # Legacy / extended fields (backward compatibility)
        action: str | None = None,
        conviction_score: int | None = None,
        portfolio_health: int = 0,
        trust_score: int = 0,
        personality_mode: str = "BALANCED",
        sector: str = "other",
        news_drivers: list[str] | None = None,
        analog_match: str = "N/A",
        sector_rotation_state: str = "N/A",
        expected_holding_period: str = "2-5 Days",
        expected_outcome: str = "Profit target",
        pnl: float = 0.0,
        actual_outcome: str = "PENDING",
    ) -> dict[str, Any]:
        """Record a trade decision entry."""
        if self._delegate is not None:
            entry = self._delegate.record_decision(
                symbol=symbol, decision=decision, conviction=conviction,
                conviction_breakdown=conviction_breakdown, reason=reason, veto_source=veto_source,
                market_regime=market_regime, sector_flow=sector_flow, expected_holding_days=expected_holding_days,
                expected_return_pct=expected_return_pct, expected_risk_pct=expected_risk_pct,
                decision_id=decision_id, reasoning_chain=reasoning_chain, action=action,
                conviction_score=conviction_score, portfolio_health=portfolio_health, trust_score=trust_score,
                personality_mode=personality_mode, sector=sector, news_drivers=news_drivers,
                analog_match=analog_match, sector_rotation_state=sector_rotation_state,
                expected_holding_period=expected_holding_period, expected_outcome=expected_outcome,
                pnl=pnl, actual_outcome=actual_outcome
            )
        else:
            final_decision = (action or decision).upper()
            if final_decision == "ACCEPT":
                final_decision = "ACCEPTED"
            elif final_decision == "REJECT":
                final_decision = "REJECTED"

            final_conviction = conviction_score if conviction_score is not None else conviction

            entry = {
                # Phase 4C.5C canonical fields
                "timestamp":              datetime.now(timezone.utc).isoformat(),
                "decision_id":            decision_id or "",
                "symbol":                 symbol.upper(),
                "decision":               final_decision,
                "conviction":             final_conviction,
                "conviction_breakdown":   conviction_breakdown or {},
                "reason":                 reason,
                "veto_source":            veto_source,
                "market_regime":          market_regime,
                "sector_flow":            sector_flow,
                "expected_holding_days":  expected_holding_days,
                "expected_return_pct":    round(expected_return_pct, 2),
                "expected_risk_pct":      round(expected_risk_pct, 2),
                # Phase 4C.5D: 7-gate reasoning chain
                "reasoning_chain":        reasoning_chain or [],
                # Legacy / extended fields
                "action":                 final_decision,
                "conviction_score":       final_conviction,
                "sector":                 sector.lower(),
                "portfolio_health":       portfolio_health,
                "trust_score":            trust_score,
                "personality_mode":       personality_mode,
                "news_drivers":           news_drivers or [],
                "analog_match":           analog_match,
                "sector_rotation_state":  sector_rotation_state,
                "expected_holding_period": expected_holding_period,
                "expected_outcome":       expected_outcome,
                "actual_outcome":         actual_outcome,
                "pnl":                    round(pnl, 2),
                "decision_reason":        reason,
            }

            try:
                with self._journal_file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, sort_keys=True) + "\n")
                logger.info(
                    "Decision journal: %s %s (conviction=%d, veto=%s)",
                    final_decision, symbol.upper(), final_conviction, veto_source or "none"
                )
            except Exception as exc:
                logger.error("Failed to write to decision journal: %s", exc)

        # Publish to EventBus for real-time streaming and audit trail
        try:
            from hokage.dashboard.event_bus import EventBus
            EventBus().publish("JOURNAL_ENTRY", entry)
        except Exception:
            pass

        return entry

    # ------------------------------------------------------------------
    # Phase 4C.5D: Outcome update (immutable, separate file)
    # ------------------------------------------------------------------

    def update_decision_outcome(
        self,
        decision_id: str,
        outcome: str,            # "WIN" | "LOSS" | "BREAKEVEN" | "OPEN"
        pnl: float,
        exit_reason: str = "",
        holding_days: int = 0,
        return_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Append an outcome record."""
        if self._delegate is not None:
            return self._delegate.update_decision_outcome(
                decision_id=decision_id, outcome=outcome, pnl=pnl,
                exit_reason=exit_reason, holding_days=holding_days, return_pct=return_pct
            )

        record: dict[str, Any] = {
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "decision_id":  decision_id,
            "outcome":      outcome.upper(),
            "pnl":          round(pnl, 2),
            "return_pct":   round(return_pct, 4),
            "exit_reason":  exit_reason,
            "holding_days": holding_days,
        }
        try:
            with self._outcomes_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            logger.info(
                "Decision outcome recorded: decision_id=%s outcome=%s pnl=%+.2f",
                decision_id, outcome.upper(), pnl
            )
        except Exception as exc:
            logger.error("Failed to write decision outcome: %s", exc)
        return record

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def load_journal_entries(self) -> list[dict[str, Any]]:
        """Load all decision journal entries from disk."""
        if self._delegate is not None:
            return self._delegate.load_journal_entries()

        entries: list[dict[str, Any]] = []
        if not self._journal_file.exists():
            return entries
        try:
            with self._journal_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_str = line.strip()
                    if line_str:
                        entries.append(json.loads(line_str))
        except Exception as exc:
            logger.error("Failed to read decision journal: %s", exc)
        return entries

    def load_outcomes(self) -> list[dict[str, Any]]:
        """Load all decision outcome records from disk."""
        if self._delegate is not None:
            return self._delegate.load_outcomes()

        outcomes: list[dict[str, Any]] = []
        if not self._outcomes_file.exists():
            return outcomes
        try:
            with self._outcomes_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_str = line.strip()
                    if line_str:
                        outcomes.append(json.loads(line_str))
        except Exception as exc:
            logger.error("Failed to read decision outcomes: %s", exc)
        return outcomes

    def load_accepted_entries(self) -> list[dict[str, Any]]:
        """Return only accepted (executed) entries."""
        if self._delegate is not None:
            return self._delegate.load_accepted_entries()
        return [e for e in self.load_journal_entries() if e.get("decision") == "ACCEPTED"]

    def load_rejected_entries(self) -> list[dict[str, Any]]:
        """Return only rejected entries."""
        if self._delegate is not None:
            return self._delegate.load_rejected_entries()
        return [e for e in self.load_journal_entries() if e.get("decision") == "REJECTED"]

    # ------------------------------------------------------------------
    # Phase 4C.5D: Summary statistics
    # ------------------------------------------------------------------

    def get_summary_stats(self) -> dict[str, Any]:
        """Compute journal summary statistics."""
        if self._delegate is not None:
            return self._delegate.get_summary_stats()

        entries = self.load_journal_entries()
        if not entries:
            return {
                "total_decisions": 0,
                "accepted": 0,
                "rejected": 0,
                "acceptance_rate": 0.0,
                "most_common_veto": "N/A",
                "avg_conviction_accept": 0.0,
                "avg_conviction_reject": 0.0,
            }

        accepted = [e for e in entries if e.get("decision") == "ACCEPTED"]
        rejected = [e for e in entries if e.get("decision") == "REJECTED"]

        acceptance_rate = round((len(accepted) / len(entries)) * 100.0, 2)

        veto_sources = [
            e["veto_source"] for e in rejected
            if e.get("veto_source") and e["veto_source"] is not None
        ]
        most_common_veto = Counter(veto_sources).most_common(1)
        most_common_veto_str = most_common_veto[0][0] if most_common_veto else "N/A"

        avg_accept = (
            round(sum(e.get("conviction", 0) for e in accepted) / len(accepted), 2)
            if accepted else 0.0
        )
        avg_reject = (
            round(sum(e.get("conviction", 0) for e in rejected) / len(rejected), 2)
            if rejected else 0.0
        )

        return {
            "total_decisions":      len(entries),
            "accepted":             len(accepted),
            "rejected":             len(rejected),
            "acceptance_rate":      acceptance_rate,
            "most_common_veto":     most_common_veto_str,
            "avg_conviction_accept": avg_accept,
            "avg_conviction_reject": avg_reject,
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_journal_path(self) -> Path:
        """Return the absolute path to the journal file (for testing)."""
        return self._journal_file

    def get_outcomes_path(self) -> Path:
        """Return the absolute path to the outcomes file (for testing)."""
        return self._outcomes_file
