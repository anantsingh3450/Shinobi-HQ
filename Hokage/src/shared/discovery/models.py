"""Domain models and schemas for the future Global Opportunity Discovery Engine.

Provides unified models representing multi-broker, multi-exchange, global cross-asset 
opportunities, exposures, positions, and macro indicators, promoting Crypto, Forex, 
Commodities, and Equities as first-class citizens.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum


class AssetCategory(str, Enum):
    """Core asset classes supported under the Global Opportunity Discovery Engine.
    
    Equities, Commodities, Forex, and Crypto are treated as first-class citizens.
    """
    EQUITY = "EQUITY"
    COMMODITY = "COMMODITY"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    ETF = "ETF"
    REIT = "REIT"
    MUTUAL_FUND = "MUTUAL_FUND"
    BOND = "BOND"
    MACRO = "MACRO"


class HorizonMode(str, Enum):
    """Discovery horizons mapping authorized asset scans to active modes.
    
    Supports unified asset abstraction across Equities, Commodities, Forex, and Crypto.
    """
    FOCUSED = "FOCUSED"
    TACTICAL = "TACTICAL"
    EXPANDED = "EXPANDED"
    MARKET = "MARKET"
    GLOBAL = "GLOBAL"

    @classmethod
    def get_assets_for_mode(cls, mode: HorizonMode) -> list[str]:
        """Retrieve authorized assets for the selected Horizon Mode.
        
        Designed from day one to support Equities, Commodities, Forex, and Crypto.
        """
        if mode == cls.FOCUSED:
            return ["Crude Oil", "Gold", "BTC", "ETH", "Bank Nifty"]
        elif mode == cls.TACTICAL:
            return ["Gold", "Silver", "Crude", "BTC", "ETH", "USDINR", "Bank Nifty"]
        else: # GLOBAL mode and intermediate expanded/market horizons
            return [
                "Equities", "Commodities", "Forex", "Crypto", 
                "ETFs", "Bonds", "REITs", "Global Indices"
            ]


# Progression Phases under the Horizon Expansion Doctrine
class ProgressionPhase(str, Enum):
    """Progression path of Hokage's opportunity discovery universe to preserve decision quality."""
    ALPHA = "ALPHA"  # 1 Asset (e.g. CRUDE_OIL)
    BETA = "BETA"    # 3-7 Assets (e.g. Gold, Crude, BTC, ETH, Bank Nifty)
    GAMMA = "GAMMA"  # 25-100 Assets (e.g. Sector leaders, top cryptos)
    DELTA = "DELTA"  # Entire Market (e.g. full national markets)
    OMEGA = "OMEGA"  # Global Multi-Asset Opportunity Discovery (Equities, Commodities, Forex, Crypto, ETFs, etc.)


class RiskMode(str, Enum):
    """Modes under which portfolio risk limits are scaled."""
    DEFENSIVE = "DEFENSIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    RECOVERY = "RECOVERY"
    ADAPTIVE = "ADAPTIVE"



@dataclass
class HorizonContext:
    """Represents the currently authorized discovery scope and execution constraints.
    
    Aligns with the Horizon Expansion Doctrine (Alpha -> Beta -> Gamma -> Delta -> Omega)
    to ensure controlled progression of universe scanning.
    """
    current_mode: HorizonMode
    active_universe_size: int
    target_assets: list[str]
    authorized_categories: list[AssetCategory]
    progression_phase: ProgressionPhase
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Opportunity:
    """Unified schema representing a discovery prospect across any asset class.
    
    Supports asset-agnostic listings including BTC, ETH, Gold, Crude Oil, or stocks.
    """
    opportunity_id: str
    symbol: str
    asset_category: AssetCategory
    exchange: str
    broker: str
    conviction_score: float  # 0 to 100
    expected_rr: float       # Expected Risk-to-Reward ratio
    volatility_atr: float    # ATR volatility measurement
    current_price: float
    base_currency: str       # E.g. USD, INR
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)


@dataclass
class CrossMarketPosition:
    """Unified representation of a holding held under any broker or exchange."""
    position_id: str
    symbol: str
    asset_category: AssetCategory
    broker_id: str
    exchange_id: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    currency: str            # Local denomination currency
    opened_at: datetime


@dataclass
class CurrencyExposure:
    """Tracks currency translation risk and hedging requirements across assets."""
    currency: str
    spot_rate_to_inr: float
    net_exposure_value: float
    hedged_ratio: float      # Hedged proportion (0.0 to 1.0)


@dataclass
class MacroIndicators:
    """Captures global macroeconomic indicators used for strategy regime mapping."""
    vix_index: float
    us_10y_yield: float
    india_10y_yield: float
    dollar_index_dxy: float
    oil_brent: float
    gold_spot: float
    sp500_momentum: str      # E.g. BULL, BEAR, CONSOLIDATION
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
