"""Protocols for pluggable strategy components.

Keeping these as Protocols (not base classes) means a module is anything with
the right shape — no inheritance tax, trivially testable in isolation, and a
bred strategy can mix modules from unrelated parents.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bots.strategy.components.models import EntrySignal, MarketContext


@runtime_checkable
class EntryModule(Protocol):
    """Decides WHETHER and WHICH WAY to enter. Owns no exit or sizing opinion."""

    #: Stable identifier recorded on every trade so entry quality (MFE) can be
    #: attributed back to the exact module that fired it.
    module_id: str

    def evaluate(self, ctx: MarketContext) -> EntrySignal:
        """Return a verdict for this tape. Must never raise on missing data —
        stand aside instead."""
        ...
