"""Research Bot — market and domain intelligence gathering."""

from bots.research.interfaces import ReportWriter, ResearchSource, ResearchSynthesizer
from bots.research.models import (
    ResearchFinding,
    ResearchQuery,
    ResearchReport,
    SourceReference,
)
from bots.research.research_bot import DefaultResearchSynthesizer, JsonReportWriter, ResearchBot

__all__ = [
    "DefaultResearchSynthesizer",
    "JsonReportWriter",
    "ReportWriter",
    "ResearchBot",
    "ResearchFinding",
    "ResearchQuery",
    "ResearchReport",
    "ResearchSource",
    "ResearchSynthesizer",
    "SourceReference",
]
