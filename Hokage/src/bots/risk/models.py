"""Risk Bot domain models.

These classes define the structures representing risk decisions, valuations,
and gating verdicts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskVerdict:
    """The result of a risk rule evaluation.

    Attributes:
        is_approved:           True if the trade is permitted under risk limits.
        max_approved_quantity: The maximum volume allowed for this trade.
                               Could be 0.0 (rejected) or less than the
                               requested quantity.
        reason:                A human-readable explanation of the verdict.
    """

    is_approved: bool
    max_approved_quantity: float
    reason: str
