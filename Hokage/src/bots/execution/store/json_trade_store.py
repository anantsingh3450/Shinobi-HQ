"""JSON Lines trade store — implements TradeStore for paper trade persistence.

Trades are appended to a .jsonl file (one JSON object per line). This format
is append-only, requires no file locking on single-machine deployments, and
is trivially stream-readable for future analytics and dashboard queries.

Output location: data/paper_trades/trades.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

from bots.execution.models import TradeRecord


class JsonTradeStore:
    """Persists TradeRecord objects as JSON Lines under a configured directory.

    Each call to ``save()`` appends one line to ``trades.jsonl``.
    ``load_all()`` reads and deserializes all lines in insertion order.

    Example:
        >>> store = JsonTradeStore(Path("data/paper_trades"))
        >>> store.save(trade)
        >>> all_trades = store.load_all()
    """

    _FILENAME = "trades.jsonl"

    def __init__(self, output_directory: Path) -> None:
        """Initialize the store.

        Args:
            output_directory: Target folder (typically ``data/paper_trades/``).
                              Created automatically on first write.
        """
        self._output_directory = output_directory

    @property
    def output_directory(self) -> Path:
        """Directory where the trade log is written."""
        return self._output_directory

    @property
    def trades_file(self) -> Path:
        """Absolute path to the trades.jsonl file."""
        return self._output_directory / self._FILENAME

    def save(self, trade: TradeRecord) -> None:
        """Append a trade record as a single JSON line.

        Args:
            trade: The TradeRecord to persist.
        """
        self._output_directory.mkdir(parents=True, exist_ok=True)
        with self.trades_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trade.to_dict(), sort_keys=True) + "\n")

    def load_all(self) -> tuple[TradeRecord, ...]:
        """Load all persisted trade records in insertion order.

        Returns:
            Tuple of TradeRecord objects. Empty tuple if file does not exist.
        """
        if not self.trades_file.exists():
            return ()

        trades: list[TradeRecord] = []
        with self.trades_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    trades.append(TradeRecord.from_dict(json.loads(line)))
        return tuple(trades)
