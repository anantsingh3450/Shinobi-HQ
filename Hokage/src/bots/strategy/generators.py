from __future__ import annotations

from bots.research.models import ResearchReport
from bots.strategy.interfaces import StrategyGenerator
from bots.strategy.models import StrategyProposal


class HeuristicStrategyGenerator(StrategyGenerator):
    """
    A temporary heuristic generator that extracts parameters from a ResearchReport
    using basic keyword and sentiment matching. This should eventually be replaced
    by an LLMStrategyGenerator.
    """

    #: Topics too generic to be a tradable symbol — fall through to text parsing.
    _GENERIC_TOPICS = {"market", "macro", "general", "trade", "trading", "forex", "equity", "crypto"}

    #: Known tradable symbols recognised inside free-form query text.
    _KNOWN_SYMBOLS = (
        "EUR/USD", "GBP/USD", "USD/JPY", "USD/INR", "BTC/USD", "ETH/USD",
        "BTCUSDT", "ETHUSDT", "BANKNIFTY", "NIFTY", "SENSEX",
        "CRUDE_OIL", "CRUDEOIL", "CRUDE OIL", "NATURALGAS", "GOLD", "SILVER",
        "TCS", "INFY", "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN",
    )

    def _resolve_market(self, report: ResearchReport) -> str:
        """Resolve a concrete tradable symbol; placeholder names are a last resort.

        Order: specific query topic → known symbol inside the query text →
        specific finding tag → generic topic verbatim → UNKNOWN. Placeholder
        results ("MARKET"/"UNKNOWN") are blocked from execution downstream.
        """
        topic = report.query.topics[0].upper() if report.query.topics else ""
        if topic and topic.lower() not in self._GENERIC_TOPICS:
            return topic

        text = (report.query.text or "").upper()
        for sym in self._KNOWN_SYMBOLS:
            if sym in text:
                return "CRUDE_OIL" if sym == "CRUDE OIL" else sym

        for finding in report.findings:
            if finding.tags:
                specific_tags = [t for t in finding.tags if t.lower() not in self._GENERIC_TOPICS]
                if specific_tags:
                    return specific_tags[0].upper()

        return topic or "UNKNOWN"

    def generate(self, report: ResearchReport) -> StrategyProposal:
        """Convert a ResearchReport into a StrategyProposal dynamically."""

        # 1. Market Identification
        market = self._resolve_market(report)
        
        # 2. Heuristic Analysis of Content
        combined_text = report.executive_summary.lower()
        for finding in report.findings:
            combined_text += f" {finding.title.lower()} {finding.summary.lower()}"

        # Dynamic rule formulation based on simple heuristics
        entry_rule = "Enter position when standard momentum indicators align."
        exit_rule = "Exit position upon trend reversal confirmation."
        stop_loss_rule = "Standard 2% stop loss applied."
        take_profit_rule = "Take profit at 3:1 risk-reward ratio."
        timeframe = "1D" # Default

        if "volatility" in combined_text or "volatile" in combined_text:
            stop_loss_rule = "Wider 3% stop loss due to elevated volatility."
            take_profit_rule = "Aggressive take profit at key resistance due to volatility."
        
        if "scalp" in combined_text or "intraday" in combined_text:
            timeframe = "1H"
            entry_rule = "Enter on confirmed pullbacks to the VWAP or EMA(21) within an established trend (1H breakouts)."
            exit_rule = "Exit at end of session."

        if "bullish" in combined_text or "uptrend" in combined_text:
            entry_rule = "Enter long on confirmed pullback to the moving average."
        elif "bearish" in combined_text or "downtrend" in combined_text:
            entry_rule = "Enter short on confirmed pullback to the moving average."

        # 3. Confidence Scoring
        confidence = 0.5 # Default neutral
        if report.findings:
            avg_relevance = sum(f.relevance_score for f in report.findings) / len(report.findings)
            confidence = round(avg_relevance, 2)

        # 4. Provenance Tracking
        sources = []
        for finding in report.findings:
            for source in finding.sources:
                sources.append(source.source_id)
        unique_sources = tuple(sorted(set(sources)))

        return StrategyProposal(
            name=f"Heuristic {market} Strategy",
            description=report.executive_summary,
            market=market,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            stop_loss_rule=stop_loss_rule,
            take_profit_rule=take_profit_rule,
            timeframe=timeframe,
            confidence_score=confidence,
            sources_cited=unique_sources,
        )
