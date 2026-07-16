"""Pluggable strategy components (entry / exit / risk).

Split apart so the Dojo can attribute performance to a specific part of a
strategy and later breed new strategies from the best parts of existing ones.
"""
from __future__ import annotations

from bots.strategy.components.entries import ENTRY_MODULES
from bots.strategy.components.interfaces import EntryModule
from bots.strategy.components.models import EntrySignal, MarketContext

__all__ = ["ENTRY_MODULES", "EntryModule", "EntrySignal", "MarketContext"]
