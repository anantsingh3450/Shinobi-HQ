"""Domain models for the Autonomous Trading Bot.

Defines the structure for exit conditions, market scanning results, 
and daily briefing/summary metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ExitConditionType(StrEnum):
    """Reason or trigger type for closing a position."""

    TRAILING_STOP = "TRAILING_STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_LIMIT = "TIME_LIMIT"
    MANUAL = "MANUAL"


@dataclass(frozen=True, slots=True)
class ExitCondition:
    """Trigger parameters for monitoring and exiting active positions."""

    condition_type: ExitConditionType
    threshold_value: float  # e.g. 0.05 for 5% trailing stop or timestamp as float
    activation_price: float  # The execution price at entry or peak price
    current_stop_price: float  # Absolute price at which exit is triggered


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Summary record of a watchlist scan cycle."""

    timestamp: datetime
    scanned_symbols: tuple[str, ...]
    candidates: tuple[dict[str, Any], ...]  # List of StrategyProposal fields
    selected_trades: tuple[str, ...]  # List of symbol names that passed risk checks


@dataclass(frozen=True, slots=True)
class DailyReport:
    """Execution summary for a specific trading day."""

    date: str  # YYYY-MM-DD
    trades_taken: tuple[dict[str, Any], ...]
    exits_executed: tuple[dict[str, Any], ...]
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    portfolio_allocation: dict[str, float]
    market_summary: str = ""
    news_summary: str = ""
    geopolitical_summary: str = ""
    lessons_learned: str = ""


@dataclass(frozen=True, slots=True)
class PositionReview:
    """Quality review for a single closed trade — Phase 4C.5D."""

    decision_id:          str   # Links to DecisionJournal entry
    symbol:               str
    entry_quality:        str   # EXCELLENT / GOOD / FAIR / POOR
    exit_quality:         str   # ON_TARGET / STOP_HIT / PREMATURE / TRAILING
    sizing_quality:       str   # OVERSIZED / CORRECT / UNDERSIZED
    stop_quality:         str   # TIGHT / CORRECT / WIDE
    risk_reward_achieved: float
    pnl:                  float
    return_pct:           float
    holding_days:         int
    lesson:               str
    timestamp:            str


class AssetDecisionState(StrEnum):
    """Execution state of a monitored asset under surveillance."""

    WATCHING = "WATCHING"
    WAITING = "WAITING"
    LONG_READY = "LONG_READY"
    SHORT_READY = "SHORT_READY"
    EXECUTED = "EXECUTED"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class TradeAuthorization:
    """Pre-execution validation check authorization record."""

    asset: str
    timestamp: str
    direction: str
    conviction_score: int
    risk_reward: float
    trend_validation: bool
    volatility_validation: bool
    capital_preservation_validation: bool
    universe_validation: bool
    execution_reason: str
    authorised_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timestamp": self.timestamp,
            "direction": self.direction,
            "conviction_score": self.conviction_score,
            "risk_reward": self.risk_reward,
            "trend_validation": self.trend_validation,
            "volatility_validation": self.volatility_validation,
            "capital_preservation_validation": self.capital_preservation_validation,
            "universe_validation": self.universe_validation,
            "execution_reason": self.execution_reason,
            "authorised_by": self.authorised_by,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TradeAuthorization:
        return cls(
            asset=d.get("asset", ""),
            timestamp=d.get("timestamp", ""),
            direction=d.get("direction", ""),
            conviction_score=d.get("conviction_score", 0),
            risk_reward=d.get("risk_reward", 0.0),
            trend_validation=bool(d.get("trend_validation", False)),
            volatility_validation=bool(d.get("volatility_validation", False)),
            capital_preservation_validation=bool(d.get("capital_preservation_validation", False)),
            universe_validation=bool(d.get("universe_validation", False)),
            execution_reason=d.get("execution_reason", ""),
            authorised_by=d.get("authorised_by", ""),
        )


@dataclass(frozen=True, slots=True)
class NoTradeDecision:
    """Formal decision to bypass trading an asset today."""

    asset: str
    timestamp: str
    decision: str = "NO_TRADE"
    confidence: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)
    supporting_evidence: dict[str, Any] = field(default_factory=dict)
    invalidated_setups: tuple[str, ...] = field(default_factory=tuple)
    next_review_time: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timestamp": self.timestamp,
            "decision": self.decision,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "supporting_evidence": self.supporting_evidence,
            "invalidated_setups": list(self.invalidated_setups),
            "next_review_time": self.next_review_time,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NoTradeDecision:
        return cls(
            asset=d.get("asset", ""),
            timestamp=d.get("timestamp", ""),
            decision=d.get("decision", "NO_TRADE"),
            confidence=d.get("confidence", 0),
            reasons=tuple(d.get("reasons", [])),
            supporting_evidence=d.get("supporting_evidence", {}),
            invalidated_setups=tuple(d.get("invalidated_setups", [])),
            next_review_time=d.get("next_review_time", ""),
        )


@dataclass(frozen=True, slots=True)
class AssetSurveillanceState:
    """Active surveillance state details for a monitored asset."""

    asset: str
    state: AssetDecisionState
    conviction_score: int
    risk_score: float
    current_blockers: tuple[str, ...] = field(default_factory=tuple)
    missing_confirmations: tuple[str, ...] = field(default_factory=tuple)
    next_review_time: str = ""
    what_would_trigger: str = ""
    last_changed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "state": self.state.value,
            "conviction_score": self.conviction_score,
            "risk_score": self.risk_score,
            "current_blockers": list(self.current_blockers),
            "missing_confirmations": list(self.missing_confirmations),
            "next_review_time": self.next_review_time,
            "what_would_trigger": self.what_would_trigger,
            "last_changed_at": self.last_changed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssetSurveillanceState:
        state_val = d.get("state", "WATCHING")
        try:
            state_enum = AssetDecisionState(state_val)
        except ValueError:
            state_enum = AssetDecisionState.WATCHING
        return cls(
            asset=d.get("asset", ""),
            state=state_enum,
            conviction_score=d.get("conviction_score", 0),
            risk_score=d.get("risk_score", 0.0),
            current_blockers=tuple(d.get("current_blockers", [])),
            missing_confirmations=tuple(d.get("missing_confirmations", [])),
            next_review_time=d.get("next_review_time", ""),
            what_would_trigger=d.get("what_would_trigger", ""),
            last_changed_at=d.get("last_changed_at", ""),
        )


