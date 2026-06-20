from __future__ import annotations

from bots.research.interfaces import ResearchSource
from bots.research.models import ResearchFinding, ResearchQuery, SourceReference, utc_now


class DummyResearchSource:
    """A dummy source for testing the pipeline without external API calls."""

    @property
    def source_id(self) -> str:
        return "dummy-source-v1"

    @property
    def name(self) -> str:
        return "Dummy Data Source"

    def search(self, query: ResearchQuery) -> tuple[ResearchFinding, ...]:
        """Return fake findings based on the query text."""
        topic = query.topics[0] if query.topics else "market"
        
        reference = SourceReference(
            source_id=self.source_id,
            name=self.name,
            retrieved_at=utc_now(),
            url="http://dummy-source.local",
        )

        finding = ResearchFinding(
            title=f"Macro outlook for {query.text}",
            summary=f"Analysis indicates strong potential for {query.text}. Focus on {topic} factors.",
            details="Detailed dummy content regarding the requested macro research query.",
            relevance_score=0.95,
            sources=(reference,),
            tags=("macro", topic.lower()),
        )

        return (finding,)
