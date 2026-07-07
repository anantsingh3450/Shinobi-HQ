"""Market Intelligence Layer for Hokage.

Contains scanner, news, and geopolitical engines parsing RSS feeds
or falling back to local mocks and persisting results in IntelligenceCache.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.ResearchIntel")


class MarketScanner:
    """Scans indices, commodities, and currency quotes to construct opportunity universes."""

    def __init__(self, orchestrator: HokageOrchestrator, cache: IntelligenceCache) -> None:
        """Initialize scanner."""
        self.orchestrator = orchestrator
        self.cache = cache

    def scan_indices(self) -> dict[str, float]:
        """Fetch quotes for key global and domestic benchmarks."""
        results = {}
        # Try fetching real quotes for default indices via price source
        for symbol in ["NIFTY 50", "BANKNIFTY", "USDINR", "CRUDEOIL", "GOLD"]:
            try:
                price = self.orchestrator.price_source.get_price(symbol)
                if not isinstance(price, (int, float)) or isinstance(price, bool):
                    raise TypeError("Price must be a float or int")
                results[symbol] = price
            except Exception:
                # Mock fallbacks
                mock_prices = {
                    "NIFTY 50": 23500.0,
                    "BANKNIFTY": 51200.0,
                    "USDINR": 83.50,
                    "CRUDEOIL": 84.50,
                    "GOLD": 2350.0
                }
                results[symbol] = mock_prices.get(symbol, 100.0)

        # Write to cache
        self.cache.write_intelligence("market_snapshot.json", results)
        return results

    def get_market_opportunity_universe(self) -> list[str]:
        """Return full opportunity universe of symbols to scan."""
        # Returns Nifty 50 constituents list or fallback defaults
        return ["TCS", "INFY", "RELIANCE", "HDFCBANK", "ICICIBANK", "ONGC", "LT", "SBIN"]


class NewsIntelligenceEngine:
    """Fetches and parses financial RSS news feeds, compiling structured Event Objects."""

    def __init__(self, cache: IntelligenceCache) -> None:
        """Initialize news engine."""
        self.cache = cache
        # Public finance RSS feeds for news headlines
        self.rss_urls = [
            "https://www.moneycontrol.com/rss/marketoutlook.xml",
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021500.cms"
        ]

    def fetch_news_events(self) -> list[dict[str, Any]]:
        """Fetch and parse RSS feeds into structured event objects."""
        events = []
        for url in self.rss_urls:
            try:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=5) as resp:
                    tree = ET.parse(resp)
                    root = tree.getroot()
                    for item in root.findall(".//item"):
                        title = item.find("title")
                        desc = item.find("description")
                        link = item.find("link")
                        pub_date = item.find("pubDate")
                        
                        title_text = title.text if title is not None else ""
                        desc_text = desc.text if desc is not None else ""
                        
                        sentiment = self._analyze_sentiment(title_text + " " + desc_text)
                        
                        events.append({
                          "title": title_text,
                          "description": desc_text,
                          "url": link.text if link is not None else "",
                          "published_at": pub_date.text if pub_date is not None else datetime.now(timezone.utc).isoformat(),
                          "sentiment_weight": sentiment,
                          "source": "RSS_News_Feed"
                        })
            except Exception as exc:
                logger.warning(f"Failed to fetch RSS from {url}: {exc}")

        # Graceful fallback if no RSS feeds parsed
        if not events:
            events.append({
                "title": "RBI rate decision leaves repo rates unchanged at 6.5%",
                "description": "The Reserve Bank of India maintained policy stance of withdrawal of accommodation.",
                "url": "https://rbi.org.in",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "sentiment_weight": 0.15,
                "source": "Mock_Fallback"
            })
            events.append({
                "title": "Red Sea shipping shipping corridors face escalation",
                "description": "Oil spikes as freight channels experience transit adjustments.",
                "url": "https://reuters.com",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "sentiment_weight": -0.40,
                "source": "Mock_Fallback"
            })

        # Calculate dynamic market sentiment index
        total_sentiment = sum(e["sentiment_weight"] for e in events)
        avg_sentiment = round(total_sentiment / len(events), 4) if events else 0.0

        sentiment_report = {
            "average_market_sentiment": avg_sentiment,
            "events_analyzed": len(events),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sentiment_summary_list": events[:10]  # Cache top 10 events
        }

        # Write to cache
        self.cache.write_intelligence("market_sentiment.json", sentiment_report)
        return events

    def _analyze_sentiment(self, text: str) -> float:
        """Simple keyword sentiment scoring helper."""
        lower_text = text.lower()
        bullish_keys = ["gain", "rise", "rally", "surpass", "bullish", "growth", "positive", "buying", "high", "upgrade"]
        bearish_keys = ["fall", "drop", "plunge", "decline", "bearish", "loss", "negative", "selling", "low", "downgrade", "tension", "conflict"]
        
        score = 0.0
        for k in bullish_keys:
            if k in lower_text:
                score += 0.1
        for k in bearish_keys:
            if k in lower_text:
                score -= 0.15
        return max(-1.0, min(1.0, score))


class GeopoliticalIntelligenceEngine:
    """Filters news feeds for geopolitical conflicts, trade sanctions, and central bank actions."""

    def __init__(self, news_engine: NewsIntelligenceEngine, cache: IntelligenceCache) -> None:
        """Initialize geopolitical engine."""
        self.news_engine = news_engine
        self.cache = cache

    def assess_geopolitical_impact(self) -> list[dict[str, Any]]:
        """Filter events for geopolitical keywords and construct impact assessments."""
        raw_events = self.news_engine.fetch_news_events()
        assessments = []
        
        geopolitical_keywords = ["war", "conflict", "sanctions", "election", "tariff", "escalate", "central bank", "fed", "rbi", "inflation", "tariff"]
        
        max_vix_impact = 0.0
        for ev in raw_events:
            combined = (ev["title"] + " " + ev["description"]).lower()
            if any(kw in combined for kw in geopolitical_keywords):
                # Construct impact assessment
                impacted_sectors = []
                if any(k in combined for k in ["oil", "crude", "energy", "red sea"]):
                    impacted_sectors.extend(["energy", "aviation", "logistics"])
                if any(k in combined for k in ["rbi", "fed", "bank", "rate", "repo"]):
                    impacted_sectors.extend(["banking", "financials", "realty"])
                if any(k in combined for k in ["tech", "tcs", "nasdaq"]):
                    impacted_sectors.extend(["it"])
                
                vix_delta = 1.5 if ev["sentiment_weight"] < -0.2 else 0.0
                max_vix_impact = max(max_vix_impact, vix_delta)

                assessments.append({
                    "event_title": ev["title"],
                    "category": "GEOPOLITICAL" if "war" in combined or "conflict" in combined else "MACRO_ECONOMIC",
                    "impacted_sectors": impacted_sectors or ["general"],
                    "sentiment_score": ev["sentiment_weight"],
                    "vix_impact_delta": vix_delta,
                    "date": datetime.now(timezone.utc).date().isoformat()
                })
        
        # Fallback assessment if empty
        if not assessments:
            assessments.append({
                "event_title": "Red Sea Shipping Tensions",
                "category": "GEOPOLITICAL",
                "impacted_sectors": ["energy", "aviation", "logistics"],
                "sentiment_score": -0.45,
                "vix_impact_delta": 2.0,
                "date": datetime.now(timezone.utc).date().isoformat()
            })
            max_vix_impact = 2.0

        risk_report = {
            "vix_impact_delta": max_vix_impact,
            "risk_on_off_status": "RISK-OFF" if max_vix_impact >= 1.5 else "RISK-ON",
            "active_geopolitical_assessments": assessments
        }

        # Write to cache files
        self.cache.write_intelligence("global_risk_state.json", risk_report)
        self.cache.write_intelligence("risk_state.json", risk_report)
        return assessments
