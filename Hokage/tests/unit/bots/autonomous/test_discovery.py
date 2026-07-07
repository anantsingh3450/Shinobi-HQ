from __future__ import annotations
import pytest
from shared.discovery.models import AssetCategory, HorizonMode
from shared.discovery.scanners import (
    EquityAssetScanner,
    CommodityAssetScanner,
    CryptoAssetScanner,
    ForexAssetScanner,
    ETFAssetScanner,
)
from shared.discovery.rankers import (
    OpportunityRankingEngine,
)
from integrations.data.mock_provider import MockMarketDataProvider

def test_concrete_scanners() -> None:
    """Verify that concrete asset scanners instantiate and scan successfully."""
    provider = MockMarketDataProvider()
    
    # Equity
    eq_scanner = EquityAssetScanner(provider, ["RELIANCE", "TCS"])
    eq_opps = eq_scanner.scan()
    assert len(eq_opps) == 2
    assert eq_opps[0].asset_category == AssetCategory.EQUITY
    assert eq_opps[0].symbol in ("RELIANCE", "TCS")
    assert eq_opps[0].current_price > 0
    assert eq_opps[0].conviction_score > 0
    assert eq_opps[0].expected_rr > 0

    # Commodity
    cmd_scanner = CommodityAssetScanner(provider, ["GOLD", "CRUDE_OIL"])
    cmd_opps = cmd_scanner.scan()
    assert len(cmd_opps) == 2
    assert cmd_opps[0].asset_category == AssetCategory.COMMODITY

    # Crypto
    cry_scanner = CryptoAssetScanner(provider, ["BTC", "ETH"])
    cry_opps = cry_scanner.scan()
    assert len(cry_opps) == 2
    assert cry_opps[0].asset_category == AssetCategory.CRYPTO

    # Forex
    fx_scanner = ForexAssetScanner(provider, ["USD/INR"])
    fx_opps = fx_scanner.scan()
    assert len(fx_opps) == 1
    assert fx_opps[0].asset_category == AssetCategory.FOREX

    # ETF
    etf_scanner = ETFAssetScanner(provider, ["NASDAQ"])
    etf_opps = etf_scanner.scan()
    assert len(etf_opps) == 1
    assert etf_opps[0].asset_category == AssetCategory.ETF


def test_opportunity_ranking_engine() -> None:
    """Verify that the ranking engine ranks opportunities correctly."""
    provider = MockMarketDataProvider()
    eq_scanner = EquityAssetScanner(provider, ["RELIANCE", "TCS"])
    eq_opps = eq_scanner.scan()

    # Manually modify conviction scores
    eq_opps[0].conviction_score = 90.0
    eq_opps[0].expected_rr = 2.5
    eq_opps[1].conviction_score = 95.0
    eq_opps[1].expected_rr = 1.8

    ranker = OpportunityRankingEngine()
    ranked = ranker.rank_opportunities(eq_opps)
    
    # 95.0 conviction is ranked higher than 90.0
    assert ranked[0].conviction_score == 95.0
    assert ranked[1].conviction_score == 90.0
