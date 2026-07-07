"""Prediction ledger for strategy/backtest decisions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared.utils import utc_now
from bots.backtest.models import BacktestResult
from bots.strategy.models import StrategyProposal


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """Record of a strategy prediction and validation result."""

    proposal_id: str
    strategy_name: str
    market: str
    timeframe: str
    confidence_score: float
    backtest_passed: bool
    win_rate: float
    net_profit: float
    after_tax_net_profit: float | None
    provider: str
    recorded_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_pipeline(
        cls,
        proposal: StrategyProposal,
        backtest_result: BacktestResult,
    ) -> PredictionRecord:
        """Build a prediction record from pipeline artifacts."""
        return cls(
            proposal_id=proposal.proposal_id,
            strategy_name=proposal.name,
            market=proposal.market,
            timeframe=proposal.timeframe,
            confidence_score=proposal.confidence_score,
            backtest_passed=backtest_result.passed,
            win_rate=backtest_result.win_rate,
            net_profit=backtest_result.net_profit,
            after_tax_net_profit=backtest_result.after_tax_net_profit,
            provider=backtest_result.provider,
        )

    def to_dict(self) -> dict:
        """Serialize the prediction record."""
        return {
            "proposal_id": self.proposal_id,
            "strategy_name": self.strategy_name,
            "market": self.market,
            "timeframe": self.timeframe,
            "confidence_score": self.confidence_score,
            "backtest_passed": self.backtest_passed,
            "win_rate": self.win_rate,
            "net_profit": self.net_profit,
            "after_tax_net_profit": self.after_tax_net_profit,
            "provider": self.provider,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> PredictionRecord:
        """Deserialize a prediction record."""
        return cls(
            proposal_id=data["proposal_id"],
            strategy_name=data["strategy_name"],
            market=data["market"],
            timeframe=data["timeframe"],
            confidence_score=data["confidence_score"],
            backtest_passed=data["backtest_passed"],
            win_rate=data["win_rate"],
            net_profit=data["net_profit"],
            after_tax_net_profit=data.get("after_tax_net_profit"),
            provider=data["provider"],
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
        )


class JsonPredictionLedger:
    """Persist prediction records separately from trades and taxes."""

    _FILENAME = "predictions.jsonl"

    def __init__(self, output_directory: Path) -> None:
        self._output_directory = output_directory
        
        # Determine if SQLite is active
        from hokage.memory.resolver import PathResolver
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        from shared.persistence.sqlite_stores import SqlitePredictionLedger
        
        resolver = PathResolver(output_directory.parent)
        if SqliteStorageEngine.is_active(resolver):
            engine = SqliteStorageEngine(resolver)
            self._delegate = SqlitePredictionLedger(engine)
        else:
            self._delegate = None

    @property
    def predictions_file(self) -> Path:
        """Path to the prediction ledger file."""
        return self._output_directory / self._FILENAME

    def record(self, record: PredictionRecord) -> None:
        """Append a prediction record."""
        if self._delegate is not None:
            self._delegate.record(record)
            return

        self._output_directory.mkdir(parents=True, exist_ok=True)
        with self.predictions_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def load_all(self) -> tuple[PredictionRecord, ...]:
        """Load all prediction records."""
        if self._delegate is not None:
            return self._delegate.load_all()

        if not self.predictions_file.exists():
            return ()
        records: list[PredictionRecord] = []
        with self.predictions_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(PredictionRecord.from_dict(json.loads(line)))
        return tuple(records)
