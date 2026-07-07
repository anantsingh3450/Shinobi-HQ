from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4
from shared.utils import utc_now


@dataclass(frozen=True, slots=True)
class StrategyProposal:
    """
    Output produced by Strategy Bot from a ResearchReport.
    """

    name: str
    description: str
    market: str

    entry_rule: str
    exit_rule: str

    stop_loss_rule: str
    take_profit_rule: str

    timeframe: str

    confidence_score: float

    sources_cited: tuple[str, ...] = field(default_factory=tuple)

    generated_at: datetime = field(default_factory=utc_now)
    proposal_id: str = field(default_factory=lambda: str(uuid4()))

    playbook_id: str | None = None
    volatility_regime: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Strategy name cannot be empty.")

        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError(
                "confidence_score must be between 0.0 and 1.0."
            )