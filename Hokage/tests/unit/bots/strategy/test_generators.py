"""Unit tests for HeuristicStrategyGenerator."""
from __future__ import annotations

from bots.research.models import ResearchQuery, ResearchReport
from bots.strategy.generators import HeuristicStrategyGenerator
from tests.conftest import make_finding


class TestHeuristicStrategyGenerator:
    def test_market_identification_from_topics(self, sample_query: ResearchQuery) -> None:
        # Arrange
        generator = HeuristicStrategyGenerator()
        finding = make_finding("EUR/USD macro", source_id="src-1")
        report = ResearchReport(
            query=ResearchQuery(text="ECB policy", topics=("GBP/USD", "forex")),
            findings=(finding,),
            executive_summary="Executive summary",
        )

        # Act
        proposal = generator.generate(report)

        # Assert
        assert proposal.market == "GBP/USD"
        assert proposal.name == "Heuristic GBP/USD Strategy"

    def test_market_identification_from_finding_tags(self) -> None:
        # Arrange
        generator = HeuristicStrategyGenerator()
        # Finding with a specific tag and 'macro' tag
        ref = make_finding("Gold outlook", source_id="src-1")
        # Overwrite tags
        ref = ref.__class__(
            title=ref.title,
            summary=ref.summary,
            details=ref.details,
            relevance_score=ref.relevance_score,
            sources=ref.sources,
            tags=("macro", "GOLD"),
        )
        report = ResearchReport(
            query=ResearchQuery(text="macro commodity"),  # No topics
            findings=(ref,),
            executive_summary="Gold summary",
        )

        # Act
        proposal = generator.generate(report)

        # Assert
        assert proposal.market == "GOLD"

    def test_volatility_keywords_wider_stop_loss(self, sample_query: ResearchQuery) -> None:
        # Arrange
        generator = HeuristicStrategyGenerator()
        finding = make_finding("Extreme volatility in markets", source_id="src-1")
        report = ResearchReport(
            query=sample_query,
            findings=(finding,),
            executive_summary="Markets are experiencing high volatility.",
        )

        # Act
        proposal = generator.generate(report)

        # Assert
        assert "Wider 3% stop loss" in proposal.stop_loss_rule
        assert "Aggressive take profit" in proposal.take_profit_rule

    def test_scalp_keywords_lower_timeframe(self, sample_query: ResearchQuery) -> None:
        # Arrange
        generator = HeuristicStrategyGenerator()
        finding = make_finding("Scalp opportunities", source_id="src-1")
        report = ResearchReport(
            query=sample_query,
            findings=(finding,),
            executive_summary="We focus on intraday scalp opportunities.",
        )

        # Act
        proposal = generator.generate(report)

        # Assert
        assert proposal.timeframe == "1H"
        assert "1H breakouts" in proposal.entry_rule
        assert "end of session" in proposal.exit_rule

    def test_bullish_and_bearish_keywords(self, sample_query: ResearchQuery) -> None:
        generator = HeuristicStrategyGenerator()

        # Bullish
        r_bull = ResearchReport(
            query=sample_query,
            findings=(make_finding("Bullish crossover", source_id="src-1"),),
            executive_summary="An uptrend is starting.",
        )
        proposal_bull = generator.generate(r_bull)
        assert "long" in proposal_bull.entry_rule

        # Bearish
        r_bear = ResearchReport(
            query=sample_query,
            findings=(make_finding("Bearish breakdown", source_id="src-2"),),
            executive_summary="Market is entering a downtrend.",
        )
        proposal_bear = generator.generate(r_bear)
        assert "short" in proposal_bear.entry_rule

    def test_confidence_scoring_and_sources_cited(self, sample_query: ResearchQuery) -> None:
        # Arrange
        generator = HeuristicStrategyGenerator()
        f1 = make_finding("Finding 1", relevance_score=0.9, source_id="src-2")
        f2 = make_finding("Finding 2", relevance_score=0.7, source_id="src-1")
        report = ResearchReport(
            query=sample_query,
            findings=(f1, f2),
            executive_summary="Summary text.",
        )

        # Act
        proposal = generator.generate(report)

        # Assert
        assert proposal.confidence_score == 0.80  # Average of 0.9 and 0.7
        assert proposal.sources_cited == ("src-1", "src-2")  # Sorted & unique
