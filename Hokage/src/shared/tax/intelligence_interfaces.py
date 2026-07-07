"""Interfaces for the Tax Intelligence Engine.

Establishes the core tax evaluation abstractions supporting equities, commodities, 
forex, and crypto capital gains projections.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shared.tax.intelligence_models import PaperTaxLedger, LiveTaxLedger


class BaseTaxIntelligenceEngine(ABC):
    """Abstract base class for calculating and projecting after-tax performance.
    
    Implementations will compute short-term/long-term capital gains, manage loss harvests,
    and estimate advance tax obligations across diverse asset categories.
    """

    @abstractmethod
    def calculate_paper_tax(self, closed_trades: list) -> PaperTaxLedger:
        """Calculate simulated capital gains liability for paper trading trades.
        
        Args:
            closed_trades: List of simulated trade executions.

        Returns:
            PaperTaxLedger containing compiled simulated tax liabilities.
        """
        pass

    @abstractmethod
    def calculate_live_tax(self, live_trades: list, income_sources: dict) -> LiveTaxLedger:
        """Calculate realized capital gains and advance tax projections for live trading.
        
        Args:
            live_trades: List of live trade executions.
            income_sources: Outer income fields (dividend interest, carry forwards).

        Returns:
            LiveTaxLedger containing compiled live tax outcomes.
        """
        pass
