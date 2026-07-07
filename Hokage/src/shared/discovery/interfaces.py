"""Interfaces for the future Global Opportunity Discovery Engine.

Defines the core abstractions required to extend Hokage from a local stock watchlist 
scanner into a unified, multi-broker, multi-exchange, global cross-asset query system.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.discovery.models import (
        Opportunity,
        CrossMarketPosition,
        CurrencyExposure,
        MacroIndicators,
    )


class BaseAssetScanner(ABC):
    """Abstract base class for asset-agnostic scanning engines.
    
    Implementations will scan specific domains (e.g. NSE equities, US ETFs, crypto, bonds)
    and output unified Opportunity structures.
    """

    @abstractmethod
    def scan(self) -> list[Opportunity]:
        """Scan the designated market domain for qualifying opportunities.
        
        Returns:
            List of detected Opportunity objects matching scanning heuristics.
        """
        pass


class BaseBrokerConnector(ABC):
    """Abstract base class for multi-broker integration layers.
    
    Provides read-only queries and order execution adapters (Zerodha, Interactive Brokers, Binance, etc.).
    """

    @property
    @abstractmethod
    def broker_id(self) -> str:
        """Unique identifier for the broker integration."""
        pass

    @abstractmethod
    def get_balances(self) -> dict[str, float]:
        """Fetch cash, margin, and equity balances from the broker."""
        pass

    @abstractmethod
    def get_positions(self) -> list[CrossMarketPosition]:
        """Fetch active positions held under this broker."""
        pass


class BaseExchangeConnector(ABC):
    """Abstract base class for multi-exchange connectivity (NSE, BSE, NASDAQ, NYSE, CME, etc.)."""

    @property
    @abstractmethod
    def exchange_id(self) -> str:
        """Unique exchange symbol name."""
        pass

    @abstractmethod
    def get_order_book(self, symbol: str) -> dict:
        """Fetch real-time order book quotes."""
        pass


class BaseCrossMarketRiskManager(ABC):
    """Abstract base class for cross-asset portfolio risk management.
    
    Calculates unified leverage, global drawdowns, currency exposures, and asset correlations.
    """

    @abstractmethod
    def evaluate_risk(
        self, 
        proposed_opportunity: Opportunity, 
        current_positions: list[CrossMarketPosition],
        macro_state: MacroIndicators
    ) -> bool:
        """Evaluate if executing a proposed opportunity complies with global risk limits.
        
        Args:
            proposed_opportunity: The candidate opportunity to check.
            current_positions: Existing cross-asset positions list.
            macro_state: Global macro economic indicator values.

        Returns:
            True if risk levels are acceptable, False otherwise.
        """
        pass


class BaseOpportunityRankingEngine(ABC):
    """Abstract base class for ranking cross-asset opportunities.
    
    Implements multi-criteria decision analysis to prioritize the highest risk-adjusted
    opportunities across equities, commodities, bonds, and crypto.
    """

    @abstractmethod
    def rank_opportunities(self, opportunities: list[Opportunity]) -> list[Opportunity]:
        """Rank a heterogeneous list of opportunities by conviction, expected return, and risk.
        
        Returns:
            Sorted list of opportunities, highest priority first.
        """
        pass
