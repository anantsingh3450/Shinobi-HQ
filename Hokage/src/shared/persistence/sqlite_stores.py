"""SQLite-backed implementations for all Hokage stores and ledgers.

Provides production-grade, thread-safe, transactional ACID persistence
for Hokage Alpha, conforming to the existing store protocols.
"""
from __future__ import annotations

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bots.execution.models import TradeRecord, TradeDirection, TradeStatus
from bots.portfolio.models import Account, Position, EquitySnapshot
from integrations.tax.models import TaxEvent, TaxComponent, TaxComponentType, TaxJurisdiction
from hokage.ledger.prediction_ledger import PredictionRecord
from bots.autonomous.models import NoTradeDecision, TradeAuthorization
from hokage.memory.resolver import PathResolver
from shared.persistence.sqlite_engine import SqliteStorageEngine

logger = logging.getLogger("Hokage.SqliteStores")


class SqliteTradeStore:
    """SQLite-backed implementation of TradeStore."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with storage engine."""
        self.engine = engine

    @property
    def output_directory(self) -> Path:
        """Directory where the trade log is written (for backward compatibility)."""
        return self.engine.resolver.resolve_trades_dir()

    @property
    def trades_file(self) -> Path:
        """Absolute path to the trades.jsonl file (for backward compatibility)."""
        return self.output_directory / "trades.jsonl"

    def save(self, trade: TradeRecord) -> None:
        """Persist a trade record to the SQLite database."""
        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trades (
                        trade_id, proposal_id, market, direction, quantity, entry_price, 
                        simulated_value, mode, status, strategy_name, sources_cited, executed_at,
                        playbook_id, failure_reason, volatility_regime
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    trade.trade_id, trade.proposal_id, trade.market, trade.direction.value,
                    trade.quantity, trade.entry_price, trade.simulated_value, trade.mode.value,
                    trade.status.value, trade.strategy_name, ",".join(trade.sources_cited),
                    trade.executed_at.isoformat(), getattr(trade, "playbook_id", None),
                    getattr(trade, "failure_reason", None), getattr(trade, "volatility_regime", None)
                ))

            # Store friction metrics in trade_replays table if available
            if trade.friction_metrics:
                timeline = [
                    {
                        "timestamp": trade.executed_at.isoformat(),
                        "event": "EXECUTION_FRICTION",
                        "description": (
                            f"Friction model applied: price adjusted from mid {trade.friction_metrics['mid_price']} "
                            f"to {trade.friction_metrics['fill_price']} (Slippage: {trade.friction_metrics['slippage_pct']}%). "
                            f"Latency: {trade.friction_metrics['latency_ms']} ms."
                        ),
                        "metadata": trade.friction_metrics
                    }
                ]
                explainability_manifest = {
                    "why_taken": "Executed via PaperEngine with friction model.",
                    "why_position_size": (
                        f"Requested qty: {trade.friction_metrics['requested_quantity']}, "
                        f"Filled qty: {trade.friction_metrics['filled_quantity']} "
                        f"(Partial: {trade.friction_metrics['partial_fill']})."
                    ),
                    "why_stop_loss": "N/A",
                    "why_target": "N/A",
                    "why_now": "N/A",
                    "why_not_later": "N/A",
                    "why_this_strategy": trade.strategy_name,
                    "why_this_asset": trade.market,
                    "why_this_regime": f"Profile: {trade.friction_metrics.get('profile', 'ZERO')}",
                    "why_another_rejected": "N/A",
                }
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO trade_replays (
                            trade_id, symbol, explainability_manifest, lifecycle_timeline
                        ) VALUES (?, ?, ?, ?);
                    """, (
                        trade.trade_id,
                        trade.market,
                        json.dumps(explainability_manifest),
                        json.dumps(timeline)
                    ))

            logger.info(f"Persisted trade {trade.trade_id} to SQLite.")
        except Exception as exc:
            logger.error(f"Failed to save trade {trade.trade_id} to SQLite: {exc}")
            raise exc

    def load_all(self) -> tuple[TradeRecord, ...]:
        """Load all trade records from SQLite in insertion order."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM trades ORDER BY rowid ASC;")
            trades = []
            for row in cursor.fetchall():
                sources = tuple(row["sources_cited"].split(",")) if row["sources_cited"] else ()
                from integrations.brokers.models import ExecutionMode
                trades.append(TradeRecord(
                    trade_id=row["trade_id"],
                    proposal_id=row["proposal_id"],
                    market=row["market"],
                    direction=TradeDirection(row["direction"]),
                    quantity=row["quantity"],
                    entry_price=row["entry_price"],
                    simulated_value=row["simulated_value"],
                    mode=ExecutionMode(row["mode"]),
                    status=TradeStatus(row["status"]),
                    strategy_name=row["strategy_name"],
                    sources_cited=sources,
                    executed_at=datetime.fromisoformat(row["executed_at"]),
                    playbook_id=row["playbook_id"] if "playbook_id" in row.keys() else None,
                    failure_reason=row["failure_reason"] if "failure_reason" in row.keys() else None,
                    volatility_regime=row["volatility_regime"] if "volatility_regime" in row.keys() else None,
                ))
            return tuple(trades)
        except Exception as exc:
            logger.error(f"Failed to load trades from SQLite: {exc}")
            return ()


class SqlitePortfolioStore:
    """SQLite-backed implementation of PortfolioStore."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with storage engine."""
        self.engine = engine

    @property
    def output_directory(self) -> Path:
        """Target folder path (for backward compatibility)."""
        return self.engine.resolver.resolve_portfolio_dir()

    def account_file(self, account_id: str) -> Path:
        """Get the filepath for a specific account identifier (for backward compatibility)."""
        clean_id = "".join(c for c in account_id if c.isalnum() or c in ("-", "_"))
        return self.output_directory / f"account_{clean_id}.json"

    def save_account(self, account: Account) -> None:
        """Persist Account and Positions atomically inside a transaction."""
        conn = self.engine.get_connection()
        try:
            # We run the entire save inside an ACID transaction block
            with conn:
                # 1. Save Portfolio Account
                conn.execute("""
                    INSERT OR REPLACE INTO portfolio (
                        account_id, initial_balance, cash, currency, realized_pnl, unrealized_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?);
                """, (
                    account.account_id, account.initial_balance, account.cash,
                    account.currency, account.realized_pnl, str(sum(p.unrealized_pnl for p in account.positions.values() if p.status == TradeStatus.OPEN))
                ))

                # 2. Clear old positions for this account
                conn.execute("DELETE FROM positions WHERE account_id = ?;", (account.account_id,))

                # 3. Save current positions
                for pid, pos in account.positions.items():
                    playbook_id = getattr(pos, "playbook_id", None)
                    failure_reason = getattr(pos, "failure_reason", None)
                    volatility_regime = getattr(pos, "volatility_regime", None)
                    conn.execute("""
                        INSERT INTO positions (
                            position_id, account_id, market, direction, quantity, entry_price, current_price,
                            unrealized_pnl, realized_pnl, status, opened_at, closed_at,
                            playbook_id, failure_reason, volatility_regime
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        pid, account.account_id, pos.market, pos.direction.value, pos.quantity,
                        pos.entry_price, pos.current_price, pos.unrealized_pnl, pos.realized_pnl,
                        pos.status.value, pos.opened_at.isoformat(),
                        pos.closed_at.isoformat() if pos.closed_at else None,
                        playbook_id, failure_reason, volatility_regime
                    ))
            logger.info(f"Persisted account {account.account_id} and {len(account.positions)} positions to SQLite.")
        except Exception as exc:
            logger.error(f"Failed to save account {account.account_id} to SQLite: {exc}")
            raise exc

    def load_account(self, account_id: str, default_balance: float = 10000.0) -> Account:
        """Load Account and Positions from SQLite."""
        conn = self.engine.get_connection()
        try:
            # 1. Load Account details
            cursor = conn.execute("SELECT * FROM portfolio WHERE account_id = ?;", (account_id,))
            row = cursor.fetchone()
            if not row:
                logger.info(f"Account {account_id} not found in SQLite, creating new default account.")
                return Account(
                    account_id=account_id,
                    initial_balance=default_balance,
                    cash=default_balance
                )

            # 2. Load positions for this account
            pos_cursor = conn.execute("SELECT * FROM positions WHERE account_id = ?;", (account_id,))
            positions = {}
            for prow in pos_cursor.fetchall():
                pid = prow["position_id"]
                closed_at_str = prow["closed_at"]
                positions[pid] = Position(
                    position_id=pid,
                    market=prow["market"],
                    direction=TradeDirection(prow["direction"]),
                    quantity=prow["quantity"],
                    entry_price=prow["entry_price"],
                    current_price=prow["current_price"],
                    unrealized_pnl=prow["unrealized_pnl"],
                    realized_pnl=prow["realized_pnl"],
                    status=TradeStatus(prow["status"]),
                    opened_at=datetime.fromisoformat(prow["opened_at"]),
                    closed_at=datetime.fromisoformat(closed_at_str) if closed_at_str else None,
                    playbook_id=prow["playbook_id"] if "playbook_id" in prow.keys() else None,
                    failure_reason=prow["failure_reason"] if "failure_reason" in prow.keys() else None,
                    volatility_regime=prow["volatility_regime"] if "volatility_regime" in prow.keys() else None,
                )

            return Account(
                account_id=account_id,
                initial_balance=row["initial_balance"],
                cash=row["cash"],
                currency=row["currency"],
                positions=positions,
                realized_pnl=row["realized_pnl"]
            )
        except Exception as exc:
            logger.error(f"Failed to load account {account_id} from SQLite: {exc}")
            return Account(
                account_id=account_id,
                initial_balance=default_balance,
                cash=default_balance
            )


class SqliteTaxLedger:
    """SQLite-backed implementation of TaxLedger."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with storage engine."""
        self.engine = engine

    @property
    def events_file(self) -> Path:
        """Path to the tax ledger file (for backward compatibility)."""
        return self.engine.resolver.resolve_tax_dir() / "tax_events.jsonl"

    def record_event(self, event: TaxEvent) -> None:
        """Persist tax event to SQLite."""
        conn = self.engine.get_connection()
        try:
            # Serialize components to JSON string
            components_data = [
                {
                    "component_type": component.component_type.value,
                    "amount": component.amount,
                    "currency": component.currency,
                    "description": component.description,
                }
                for component in event.components
            ]
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO tax_events (
                        trade_id, market, direction, quantity, entry_price, 
                        simulated_value, executed_at, jurisdiction, currency, components
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    event.trade_id, event.market, event.direction, event.quantity,
                    event.entry_price, event.simulated_value, event.executed_at.isoformat(),
                    event.jurisdiction.value, event.currency, json.dumps(components_data)
                ))
            logger.info(f"Persisted tax event for trade {event.trade_id} to SQLite.")
        except Exception as exc:
            logger.error(f"Failed to record tax event for trade {event.trade_id} to SQLite: {exc}")
            raise exc

    def load_events(self) -> tuple[TaxEvent, ...]:
        """Load all tax events from SQLite."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM tax_events ORDER BY rowid ASC;")
            events = []
            for row in cursor.fetchall():
                components_list = json.loads(row["components"])
                components = tuple(
                    TaxComponent(
                        component_type=TaxComponentType(c["component_type"]),
                        amount=c["amount"],
                        currency=c["currency"],
                        description=c.get("description", "")
                    )
                    for c in components_list
                )
                events.append(TaxEvent(
                    trade_id=row["trade_id"],
                    market=row["market"],
                    direction=row["direction"],
                    quantity=row["quantity"],
                    entry_price=row["entry_price"],
                    simulated_value=row["simulated_value"],
                    executed_at=datetime.fromisoformat(row["executed_at"]),
                    jurisdiction=TaxJurisdiction(row["jurisdiction"]),
                    currency=row["currency"],
                    components=components
                ))
            return tuple(events)
        except Exception as exc:
            logger.error(f"Failed to load tax events from SQLite: {exc}")
            return ()


class SqlitePredictionLedger:
    """SQLite-backed implementation of PredictionLedger."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with storage engine."""
        self.engine = engine

    @property
    def predictions_file(self) -> Path:
        """Path to the prediction ledger file (for backward compatibility)."""
        return self.engine.resolver.resolve_predictions_dir() / "predictions.jsonl"

    def record(self, record: PredictionRecord) -> None:
        """Persist prediction record to SQLite."""
        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO predictions (
                        proposal_id, strategy_name, market, timeframe, confidence_score, 
                        backtest_passed, win_rate, net_profit, after_tax_net_profit, provider, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    record.proposal_id, record.strategy_name, record.market, record.timeframe,
                    record.confidence_score, 1 if record.backtest_passed else 0, record.win_rate,
                    record.net_profit, record.after_tax_net_profit, record.provider,
                    record.recorded_at.isoformat()
                ))
            logger.info(f"Persisted prediction record {record.proposal_id} to SQLite.")
        except Exception as exc:
            logger.error(f"Failed to record prediction {record.proposal_id} to SQLite: {exc}")
            raise exc

    def load_all(self) -> tuple[PredictionRecord, ...]:
        """Load all prediction records from SQLite."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM predictions ORDER BY rowid ASC;")
            records = []
            for row in cursor.fetchall():
                records.append(PredictionRecord(
                    proposal_id=row["proposal_id"],
                    strategy_name=row["strategy_name"],
                    market=row["market"],
                    timeframe=row["timeframe"],
                    confidence_score=row["confidence_score"],
                    backtest_passed=bool(row["backtest_passed"]),
                    win_rate=row["win_rate"],
                    net_profit=row["net_profit"],
                    after_tax_net_profit=row["after_tax_net_profit"],
                    provider=row["provider"],
                    recorded_at=datetime.fromisoformat(row["recorded_at"])
                ))
            return tuple(records)
        except Exception as exc:
            logger.error(f"Failed to load predictions from SQLite: {exc}")
            return ()


class SqliteDecisionJournalSystem:
    """SQLite-backed implementation of DecisionJournalSystem."""

    def __init__(self, engine: SqliteStorageEngine) -> None:
        """Initialize with storage engine."""
        self.engine = engine
        self._journal_dir = self.engine.resolver.resolve_brain_root() / "journal"

    def get_journal_path(self) -> Path:
        """Return the path to the journal file (for backward compatibility)."""
        return self._journal_dir / "decision_journal.jsonl"

    def get_outcomes_path(self) -> Path:
        """Return the path to the outcomes file (for backward compatibility)."""
        return self._journal_dir / "decision_outcomes.jsonl"

    def record_no_trade_decision(self, no_trade: NoTradeDecision) -> dict[str, Any]:
        """Record a NoTradeDecision entry in SQLite."""
        entry = no_trade.to_dict()
        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO no_trade_decisions (
                        asset, timestamp, decision, confidence, reasons, invalidated_setups, next_review_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
                    no_trade.asset, no_trade.timestamp, no_trade.decision, no_trade.confidence,
                    json.dumps(no_trade.reasons), json.dumps(no_trade.invalidated_setups), no_trade.next_review_time
                ))
            logger.info(f"Recorded no-trade decision for {no_trade.asset} in SQLite.")
        except Exception as exc:
            logger.error(f"Failed to save no-trade decision to SQLite: {exc}")
        return entry

    def load_no_trade_decisions(self) -> list[dict[str, Any]]:
        """Load all no-trade decision entries from SQLite."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM no_trade_decisions ORDER BY timestamp ASC;")
            entries = []
            for row in cursor.fetchall():
                entries.append({
                    "asset": row["asset"],
                    "timestamp": row["timestamp"],
                    "decision": row["decision"],
                    "confidence": row["confidence"],
                    "reasons": json.loads(row["reasons"]),
                    "invalidated_setups": json.loads(row["invalidated_setups"]),
                    "next_review_time": row["next_review_time"]
                })
            return entries
        except Exception as exc:
            logger.error(f"Failed to load no-trade decisions from SQLite: {exc}")
            return []

    def record_trade_authorization(self, auth: TradeAuthorization) -> dict[str, Any]:
        """Record a TradeAuthorization entry in SQLite."""
        entry = auth.to_dict()
        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trade_authorizations (
                        asset, timestamp, direction, conviction_score, risk_reward, trend_validation,
                        volatility_validation, capital_preservation_validation, universe_validation,
                        execution_reason, authorised_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    auth.asset, auth.timestamp, auth.direction, auth.conviction_score,
                    auth.risk_reward, str(auth.trend_validation), auth.volatility_validation,
                    auth.capital_preservation_validation, auth.universe_validation,
                    auth.execution_reason, auth.authorised_by
                ))
            logger.info(f"Recorded trade authorization for {auth.asset} in SQLite.")
        except Exception as exc:
            logger.error(f"Failed to save trade authorization to SQLite: {exc}")
        return entry

    def load_trade_authorizations(self) -> list[dict[str, Any]]:
        """Load all trade authorization entries from SQLite."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM trade_authorizations ORDER BY timestamp ASC;")
            entries = []
            for row in cursor.fetchall():
                entries.append({
                    "asset": row["asset"],
                    "timestamp": row["timestamp"],
                    "direction": row["direction"],
                    "conviction_score": row["conviction_score"],
                    "risk_reward": row["risk_reward"],
                    "trend_validation": json.loads(row["trend_validation"]) if row["trend_validation"].startswith("{") or row["trend_validation"].startswith("[") else row["trend_validation"],
                    "volatility_validation": row["volatility_validation"],
                    "capital_preservation_validation": row["capital_preservation_validation"],
                    "universe_validation": row["universe_validation"],
                    "execution_reason": row["execution_reason"],
                    "authorised_by": row["authorised_by"]
                })
            return entries
        except Exception as exc:
            logger.error(f"Failed to load trade authorizations from SQLite: {exc}")
            return []

    def record_decision(
        self,
        symbol: str,
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
        reasoning_chain: list[dict[str, Any]] | None = None,
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
        """Record a trade decision entry in SQLite."""
        final_decision = (action or decision).upper()
        if final_decision == "ACCEPT":
            final_decision = "ACCEPTED"
        elif final_decision == "REJECT":
            final_decision = "REJECTED"

        final_conviction = conviction_score if conviction_score is not None else conviction
        dec_id = decision_id or ""

        entry: dict[str, Any] = {
            "timestamp":              datetime.now(timezone.utc).isoformat(),
            "decision_id":            dec_id,
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
            "reasoning_chain":        reasoning_chain or [],
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

        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO decision_journal (
                        decision_id, timestamp, symbol, decision, conviction, conviction_breakdown,
                        reason, veto_source, market_regime, sector_flow, expected_holding_days,
                        expected_return_pct, expected_risk_pct, reasoning_chain, action,
                        conviction_score, sector, portfolio_health, trust_score, personality_mode,
                        news_drivers, analog_match, sector_rotation_state, expected_holding_period,
                        expected_outcome, actual_outcome, pnl, decision_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    dec_id, entry["timestamp"], entry["symbol"], entry["decision"],
                    entry["conviction"], json.dumps(entry["conviction_breakdown"]), entry["reason"],
                    entry["veto_source"], entry["market_regime"], entry["sector_flow"],
                    entry["expected_holding_days"], entry["expected_return_pct"], entry["expected_risk_pct"],
                    json.dumps(entry["reasoning_chain"]), entry["action"], entry["conviction_score"],
                    entry["sector"], entry["portfolio_health"], entry["trust_score"], entry["personality_mode"],
                    json.dumps(entry["news_drivers"]), entry["analog_match"], entry["sector_rotation_state"],
                    entry["expected_holding_period"], entry["expected_outcome"], entry["actual_outcome"],
                    entry["pnl"], entry["decision_reason"]
                ))
            logger.info(f"Recorded decision {dec_id} for {symbol} in SQLite.")
        except Exception as exc:
            logger.error(f"Failed to save decision to SQLite: {exc}")
        return entry

    def update_decision_outcome(
        self,
        decision_id: str,
        outcome: str,
        pnl: float,
        exit_reason: str = "",
        holding_days: int = 0,
        return_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Append an outcome record to SQLite decision_outcomes table."""
        record: dict[str, Any] = {
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "decision_id":  decision_id,
            "outcome":      outcome.upper(),
            "pnl":          round(pnl, 2),
            "return_pct":   round(return_pct, 4),
            "exit_reason":  exit_reason,
            "holding_days": holding_days,
        }
        conn = self.engine.get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO decision_outcomes (
                        decision_id, timestamp, outcome, pnl, return_pct, exit_reason, holding_days
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
                    decision_id, record["timestamp"], record["outcome"], record["pnl"],
                    record["return_pct"], record["exit_reason"], record["holding_days"]
                ))
            logger.info(f"Recorded decision outcome for {decision_id} in SQLite.")
        except Exception as exc:
            logger.error(f"Failed to save decision outcome to SQLite: {exc}")
        return record

    def load_journal_entries(self) -> list[dict[str, Any]]:
        """Load all decision journal entries from SQLite."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM decision_journal ORDER BY timestamp ASC;")
            entries = []
            for row in cursor.fetchall():
                entries.append({
                    "timestamp":              row["timestamp"],
                    "decision_id":            row["decision_id"],
                    "symbol":                 row["symbol"],
                    "decision":               row["decision"],
                    "conviction":             row["conviction"],
                    "conviction_breakdown":   json.loads(row["conviction_breakdown"]),
                    "reason":                 row["reason"],
                    "veto_source":            row["veto_source"],
                    "market_regime":          row["market_regime"],
                    "sector_flow":            row["sector_flow"],
                    "expected_holding_days":  row["expected_holding_days"],
                    "expected_return_pct":    row["expected_return_pct"],
                    "expected_risk_pct":      row["expected_risk_pct"],
                    "reasoning_chain":        json.loads(row["reasoning_chain"]),
                    "action":                 row["action"],
                    "conviction_score":       row["conviction_score"],
                    "sector":                 row["sector"],
                    "portfolio_health":       row["portfolio_health"],
                    "trust_score":            row["trust_score"],
                    "personality_mode":       row["personality_mode"],
                    "news_drivers":           json.loads(row["news_drivers"]),
                    "analog_match":           row["analog_match"],
                    "sector_rotation_state":  row["sector_rotation_state"],
                    "expected_holding_period": row["expected_holding_period"],
                    "expected_outcome":       row["expected_outcome"],
                    "actual_outcome":         row["actual_outcome"],
                    "pnl":                    row["pnl"],
                    "decision_reason":        row["decision_reason"]
                })
            return entries
        except Exception as exc:
            logger.error(f"Failed to load journal entries from SQLite: {exc}")
            return []

    def load_outcomes(self) -> list[dict[str, Any]]:
        """Load all decision outcome records from SQLite."""
        conn = self.engine.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM decision_outcomes ORDER BY timestamp ASC;")
            outcomes = []
            for row in cursor.fetchall():
                outcomes.append({
                    "timestamp":    row["timestamp"],
                    "decision_id":  row["decision_id"],
                    "outcome":      row["outcome"],
                    "pnl":          row["pnl"],
                    "return_pct":   row["return_pct"],
                    "exit_reason":  row["exit_reason"],
                    "holding_days": row["holding_days"]
                })
            return outcomes
        except Exception as exc:
            logger.error(f"Failed to load outcomes from SQLite: {exc}")
            return []

    def load_accepted_entries(self) -> list[dict[str, Any]]:
        """Return only accepted entries."""
        return [e for e in self.load_journal_entries() if e.get("decision") == "ACCEPTED"]

    def load_rejected_entries(self) -> list[dict[str, Any]]:
        """Return only rejected entries."""
        return [e for e in self.load_journal_entries() if e.get("decision") == "REJECTED"]

    def get_summary_stats(self) -> dict[str, Any]:
        """Compute journal summary statistics from SQLite."""
        from collections import Counter
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
