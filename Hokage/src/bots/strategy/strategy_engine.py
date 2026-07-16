from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Hokage.StrategyEngine")

class StrategyEngine:
    """Manages playbook execution limits, daily quotas, and unique asset rotation rules."""

    def __init__(self, max_unique_assets: int = 5, max_entries_per_symbol: int = 3) -> None:
        self.max_unique_assets = max_unique_assets
        # Same-day re-entry cap per symbol. The old rule was ONE entry per
        # symbol per playbook per day — with a 3-index universe that ended the
        # trading day by mid-morning (each asset spent after its first trade),
        # which starved the league of the very repetition evolution needs.
        # Re-entries are allowed up to this cap; concurrent duplicates and
        # revenge re-entries are prevented elsewhere (open-underlying dedup
        # and the post-exit cooldown in the scan loop).
        self.max_entries_per_symbol = max_entries_per_symbol
        # Daily entry counts per playbook: {date_str: {playbook_id: {symbol: count}}}
        self._daily_utilized_symbols: dict[str, dict[str, dict[str, int]]] = {}

    def get_playbook_id(self, strategy_name: str) -> str:
        """Resolve playbook ID from strategy name."""
        name_lower = strategy_name.lower()
        if "macro" in name_lower or "scarecrow" in name_lower:
            return "SCARECROW_EMA"
        elif "trend" in name_lower or "konoha" in name_lower:
            return "KONOHA_ORB"
        else:
            return strategy_name.upper().replace(" ", "_")

    def reset_daily_stats_if_needed(self, date_str: str) -> None:
        """Reset statistics if it is a new day."""
        if date_str not in self._daily_utilized_symbols:
            self._daily_utilized_symbols[date_str] = {}

    def is_entry_allowed(self, playbook_id: str, symbol: str, date_str: str) -> tuple[bool, str]:
        """Check if entry is allowed under batch limits and re-entry caps."""
        self.reset_daily_stats_if_needed(date_str)

        entry_counts = self._daily_utilized_symbols[date_str].setdefault(playbook_id, {})
        symbol_upper = symbol.upper()

        # 1. Same-day re-entry cap: an asset may be traded again after an exit
        # (evolution needs repetition), but never more than the cap — churn on
        # one symbol is revenge trading, not data collection.
        if entry_counts.get(symbol_upper, 0) >= self.max_entries_per_symbol:
            return False, (
                f"Playbook {playbook_id} reached the daily re-entry cap of "
                f"{self.max_entries_per_symbol} entries on {symbol_upper}."
            )

        # 2. Check total unique symbols in the daily batch (max 5)
        if symbol_upper not in entry_counts and len(entry_counts) >= self.max_unique_assets:
            return False, f"Playbook {playbook_id} has exhausted its daily rotation quota of {self.max_unique_assets} unique assets."

        return True, "Allowed"

    def record_trade(self, playbook_id: str, symbol: str, date_str: str) -> None:
        """Record trade and count the entry against the playbook's daily caps."""
        self.reset_daily_stats_if_needed(date_str)

        entry_counts = self._daily_utilized_symbols[date_str].setdefault(playbook_id, {})
        symbol_upper = symbol.upper()
        entry_counts[symbol_upper] = entry_counts.get(symbol_upper, 0) + 1
        logger.info(
            f"Strategy Battle Arena: Recorded playbook {playbook_id} entry #{entry_counts[symbol_upper]} "
            f"for {symbol_upper}. Daily unique symbols count: {len(entry_counts)}/{self.max_unique_assets}"
        )

    def load_daily_trades_from_db(self, db_engine: Any, date_str: str) -> None:
        """Recover daily utilized symbols from SQLite db on startup."""
        conn = db_engine.get_connection()
        try:
            # Query all trades executed today
            cursor = conn.execute("SELECT market, strategy_name, executed_at, playbook_id FROM trades;")
            for row in cursor.fetchall():
                executed_at_str = row["executed_at"]
                if executed_at_str.startswith(date_str):
                    playbook_id = row["playbook_id"]
                    if not playbook_id:
                        playbook_id = self.get_playbook_id(row["strategy_name"])
                    market = row["market"]
                    self.record_trade(playbook_id, market, date_str)
            logger.info("Successfully recovered daily Strategy Battle Arena stats from database.")
        except Exception as e:
            logger.error(f"Failed to load daily trades from database: {e}")
