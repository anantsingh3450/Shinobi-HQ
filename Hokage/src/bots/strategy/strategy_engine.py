from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Hokage.StrategyEngine")

class StrategyEngine:
    """Manages playbook execution limits, daily quotas, and unique asset rotation rules."""

    def __init__(self, max_unique_assets: int = 5) -> None:
        self.max_unique_assets = max_unique_assets
        # Keep track of daily utilized symbols per playbook: {date_str: {playbook_id: set(symbols)}}
        self._daily_utilized_symbols: dict[str, dict[str, set[str]]] = {}

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
        """Check if entry is allowed under batch limits and asset uniqueness rules."""
        self.reset_daily_stats_if_needed(date_str)
        
        utilized_symbols = self._daily_utilized_symbols[date_str].setdefault(playbook_id, set())
        symbol_upper = symbol.upper()

        # 1. Unique Asset Diversification guard: check if symbol has already been utilized
        if symbol_upper in utilized_symbols:
            return False, f"Playbook {playbook_id} has already utilized {symbol_upper} in today's daily batch."

        # 2. Check total unique symbols in the daily batch (max 5)
        if len(utilized_symbols) >= self.max_unique_assets:
            return False, f"Playbook {playbook_id} has exhausted its daily rotation quota of {self.max_unique_assets} unique assets."

        return True, "Allowed"

    def record_trade(self, playbook_id: str, symbol: str, date_str: str) -> None:
        """Record trade and add utilized symbol for the playbook's daily batch."""
        self.reset_daily_stats_if_needed(date_str)
        
        if playbook_id not in self._daily_utilized_symbols[date_str]:
            self._daily_utilized_symbols[date_str][playbook_id] = set()
        
        symbol_upper = symbol.upper()
        self._daily_utilized_symbols[date_str][playbook_id].add(symbol_upper)
        logger.info(
            f"Strategy Battle Arena: Recorded playbook {playbook_id} entry for {symbol_upper}. "
            f"Daily unique symbols count: {len(self._daily_utilized_symbols[date_str][playbook_id])}/{self.max_unique_assets}"
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
