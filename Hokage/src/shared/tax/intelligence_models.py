"""Tax Intelligence models and schemas.

Defines the data structures representing the Paper and Live Tax Ledgers across all
supported asset classes (Equities, Commodities, Forex, and Crypto).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class EquityTaxDetails:
    """Detailed tax components for Equities trading."""
    stcg_estimated: float = 0.0
    ltcg_estimated: float = 0.0
    stt_paid: float = 0.0
    stamp_duty: float = 0.0
    brokerage_gst: float = 0.0


@dataclass
class CommodityTaxDetails:
    """Detailed tax components for Commodities trading."""
    gains_tax_estimated: float = 0.0
    ctt_paid: float = 0.0  # Commodity Transaction Tax
    brokerage_gst: float = 0.0


@dataclass
class ForexTaxDetails:
    """Detailed tax components for Forex trading."""
    income_tax_estimated: float = 0.0
    gst_on_currency_conversion: float = 0.0


@dataclass
class CryptoTaxDetails:
    """Detailed tax components for Crypto assets (e.g. flat 30% tax + 1% TDS in India)."""
    flat_gains_tax_30pct: float = 0.0
    tds_1pct_withheld: float = 0.0
    non_offsetable_losses: float = 0.0  # Crypto losses cannot be offset against gains under standard regulations


@dataclass
class AssetTaxBreakdown:
    """Represents tax calculations grouped by asset category, extensible for detailed calculations."""
    equity_tax: float = 0.0
    commodity_tax: float = 0.0
    forex_tax: float = 0.0
    crypto_tax: float = 0.0
    
    # Detailed sub-breakdown models
    equity_details: EquityTaxDetails = field(default_factory=EquityTaxDetails)
    commodity_details: CommodityTaxDetails = field(default_factory=CommodityTaxDetails)
    forex_details: ForexTaxDetails = field(default_factory=ForexTaxDetails)
    crypto_details: CryptoTaxDetails = field(default_factory=CryptoTaxDetails)


@dataclass
class PaperTaxLedger:
    """Simulated capital gains and liability ledger for paper accounts.
    
    Conforms to the core doctrine: 'Hokage optimizes after-tax risk-adjusted returns'.
    """
    simulated_stcg: float = 0.0       # Short Term Capital Gains tax estimated
    simulated_ltcg: float = 0.0       # Long Term Capital Gains tax estimated
    simulated_dividend_tax: float = 0.0
    breakdown: AssetTaxBreakdown = field(default_factory=AssetTaxBreakdown)
    estimated_tax_liability: float = 0.0
    post_tax_return_pct: float = 0.0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class LiveTaxLedger:
    """Realized capital gains, dividend yields, and advance tax projections for live trading."""
    realized_stcg: float = 0.0
    realized_ltcg: float = 0.0
    dividend_income: float = 0.0
    interest_income: float = 0.0
    carry_forward_losses: float = 0.0
    breakdown: AssetTaxBreakdown = field(default_factory=AssetTaxBreakdown)
    advance_tax_estimates: float = 0.0
    post_tax_performance_pct: float = 0.0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
