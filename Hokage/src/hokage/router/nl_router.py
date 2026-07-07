"""Natural Language Router for Hokage.

Heuristically parses natural language input from the commander and maps it to the 
standard read-only CLI commands of CommandRouter.
"""
from __future__ import annotations
import re


class NaturalLanguageRouter:
    """Parses user sentences and maps them to standard command router queries."""

    def __init__(self) -> None:
        """Initialize regex patterns for natural language mapping."""
        # Why queries (captures ticker symbol, e.g. "Why TCS?", "why did we reject INFY?")
        self.why_pattern = re.compile(
            r"\bwhy\b(?:.*?(?:reject|accept|buy|is|about))?\s+([a-zA-Z0-9_.-]+)",
            re.IGNORECASE
        )
        
        # Knowledge queries (captures topic, e.g. "what is the rule on risk?", "knowledge psychology")
        self.knowledge_pattern = re.compile(
            r"\b(?:knowledge|rule|rules|doctrine|doctrines|say|says|book|books)\b(?:.*?(?:on|about|for))?\s+([a-zA-Z0-9\s_.-]+)",
            re.IGNORECASE
        )

        # Standard keyword triggers mapped to subcommands
        self.status_keywords = ("status", "system state", "are we trading", "system status", "loop state")
        self.portfolio_keywords = ("portfolio", "cash", "balance", "equity", "money", "capital")
        self.positions_keywords = ("position", "positions", "holding", "holdings", "open trades")
        self.decisions_keywords = ("decisions today", "today's decisions", "decision today", "decisions")
        self.performance_keywords = ("performance", "performing", "perform", "win rate", "expectancy", "sharpe", "drawdown", "returns")
        self.lessons_keywords = ("lessons", "lesson", "what did we learn", "lessons learned", "reviews")
        self.dna_keywords = ("dna", "fingerprint", "regime stats", "sector stats", "trade dna")
        self.briefing_keywords = ("briefing", "morning briefing", "pre-market", "morning summary")
        self.review_keywords = ("review template", "daily review", "eod template", "eod review", "review")
        self.opportunities_keywords = ("opportunity", "opportunities", "best opportunity", "approved universe", "radar")
        self.profile_keywords = ("profile", "who am i", "commander name", "configured as")
        self.horizon_keywords = ("horizon", "universe am i monitoring", "universe monitoring", "what is my horizon")
        
        # Phase 5B.3A.1 Interrogations
        self.wait_reason_keywords = (
            "why are we waiting", 
            "what confirmation is missing", 
            "what would trigger execution",
            "why we wait",
            "waiting reason"
        )
        self.what_changed_keywords = (
            "what changed",
            "what has changed",
            "show changes"
        )
        self.show_authorization_keywords = (
            "why was this trade authorised",
            "show trade authorisation",
            "why was this trade authorized",
            "show trade authorization",
            "show authorization",
            "show authorisation"
        )
        self.show_rejection_keywords = (
            "why was this trade rejected",
            "show latest no-trade review",
            "why rejected",
            "show rejection"
        )
        self.strategy_notifications_keywords = (
            "strategy notifications",
            "pipeline notifications",
            "strategy changes",
            "evolution log"
        )
        self.strategy_pipeline_keywords = (
            "strategy pipeline",
            "strategy stage",
            "candidate strategies",
            "strategy lifecycle"
        )

    def parse_query(self, raw_query: str) -> str:
        """Parse natural language query and return equivalent hokage command.

        Args:
            raw_query: Raw user query sentence.

        Returns:
            Mapped CLI command string (e.g. 'hokage portfolio') or help string if unmapped.
        """
        cleaned = raw_query.strip().lower()
        if not cleaned:
            return ""

        # Remove trailing period, question mark, or exclamation
        if cleaned[-1] in (".", "?", "!"):
            cleaned = cleaned[:-1].strip()

        # Strip leading "hokage, ", "hokage: ", or "hokage " prefix if present
        if cleaned.startswith("hokage,"):
            cleaned = cleaned[7:].strip()
        elif cleaned.startswith("hokage:"):
            cleaned = cleaned[7:].strip()
        elif cleaned.startswith("hokage "):
            cleaned = cleaned[7:].strip()
        elif cleaned == "hokage":
            cleaned = ""

        # Direct natural language matching for live/paper dynamic mode toggles
        if "switch to live" in cleaned or "enable live trading" in cleaned or "mode set live" in cleaned or "mode live" in cleaned:
            return "hokage mode set live"
        if "switch to paper" in cleaned or "enable paper trading" in cleaned or "mode set paper" in cleaned or "mode paper" in cleaned:
            return "hokage mode set paper"

        # Direct natural language matching for persona/humor adjustments
        if "adjust humor to witty" in cleaned or "humor to witty" in cleaned or "be witty" in cleaned or "adjust tone to witty" in cleaned:
            return "hokage persona set witty"
        if "be completely stoic" in cleaned or "be stoic" in cleaned or "be serious" in cleaned or "adjust tone to stoic" in cleaned or "adjust humor to stoic" in cleaned:
            return "hokage persona set stoic"
        if "be normal" in cleaned or "reset tone" in cleaned or "adjust humor to normal" in cleaned or "adjust tone to normal" in cleaned:
            return "hokage persona set normal"

        # Direct risk parameter overrides matching
        if "keep stop loss at" in cleaned or "set stop loss to" in cleaned:
            # Extract number
            match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
            val = match.group(1) if match else "5"
            return f"hokage override stop-loss {val}"
        if "keep take profit at" in cleaned or "set take profit to" in cleaned:
            match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
            val = match.group(1) if match else "10"
            return f"hokage override take-profit {val}"
        if "revoke the override" in cleaned or "cancel the override" in cleaned or "revoke override" in cleaned:
            return "hokage override revoke"

        # Greetings mapping
        if cleaned in ("", "good morning", "hello", "hi", "goodmorning"):
            return "hokage greet"

        # Active missions mapping
        if cleaned in ("what missions are active", "active missions", "missions", "show active missions"):
            return "hokage missions"

        # 0. Check committee-related queries (Specific)
        if "veto authority" in cleaned:
            return "hokage committee vetoes"
        
        if "highest historical accuracy" in cleaned or "committee has the highest" in cleaned or "committee is underperforming" in cleaned or "underperforming committee" in cleaned:
            return "hokage committee stats"

        if "risk committee reject" in cleaned or "why did the risk committee reject" in cleaned:
            match = re.search(r"reject\s+([a-zA-Z0-9_-]+)", cleaned)
            sym = match.group(1).upper() if match else ""
            if sym in ("THIS", "TRADE", "EXECUTION", "THE", "WE", "YOU", "ME", "NOW", "PROPOSAL"):
                sym = ""
            return f"hokage committee why Risk {sym}".strip()
            
        if "capital preservation block" in cleaned or "capital preservation reject" in cleaned or "preservation block" in cleaned:
            match = re.search(r"(?:block|reject)\s+([a-zA-Z0-9_-]+)", cleaned)
            sym = match.group(1).upper() if match else ""
            if sym in ("THIS", "TRADE", "EXECUTION", "THE", "WE", "YOU", "ME", "NOW", "PROPOSAL"):
                sym = ""
            return f"hokage committee why CapitalPreservation {sym}".strip()

        if "committee approve" in cleaned or "why did the committee approve" in cleaned or "committee approved" in cleaned:
            return f'hokage chat "{raw_query}"'

        if "committee votes" in cleaned or "voted against execution" in cleaned or "committee reject this trade" in cleaned or "why did the committee reject" in cleaned:
            match = re.search(r"(?:votes|execution|reject)\s+(?:for\s+|on\s+)?([a-zA-Z0-9_-]+)", cleaned)
            sym = match.group(1).upper() if match else ""
            if sym in ("THIS", "TRADE", "EXECUTION", "THE", "WE", "YOU", "ME", "NOW"):
                sym = ""
            return f"hokage committee votes {sym}".strip()

        # 1. Check for specific symbol-extraction matches first
        
        # Why <symbol>
        why_match = self.why_pattern.search(cleaned)
        if why_match:
            symbol = why_match.group(1).upper()
            # If the extracted symbol is a keyword, skip (e.g. "why did we trade today")
            if symbol not in ("TODAY", "NOW", "THIS", "THE", "WE", "YOU", "TRADE", "ENTER", "POSITION", "DECISION", "ASSET"):
                return f"hokage why {symbol}"

        # Knowledge <topic>
        know_match = self.knowledge_pattern.search(cleaned)
        if know_match:
            topic = know_match.group(1).strip()
            # If the extracted topic is a keyword, skip
            if topic not in ("today", "now", "this", "the", "we", "you", "me"):
                return f"hokage knowledge {topic}"

        # 2. Conversational explanations (Phase 6.9)
        if "explain" in cleaned or any(cleaned.startswith(prefix) for prefix in (
            "why did", "why was", "how did", "why does", "why we", "how we", "why did we", "why was this"
        )):
            return f'hokage chat "{raw_query}"'

        # 3. Check keyword triggers
        if any(kw in cleaned for kw in self.wait_reason_keywords):
            return "hokage wait-reason"
        if any(kw in cleaned for kw in self.what_changed_keywords):
            return "hokage what-changed"
        if any(kw in cleaned for kw in self.show_authorization_keywords):
            return "hokage show-authorization"
        if any(kw in cleaned for kw in self.show_rejection_keywords):
            return "hokage show-rejection"
            
        if any(kw in cleaned for kw in self.strategy_notifications_keywords):
            return "hokage strategy notifications"
        if any(kw in cleaned for kw in self.strategy_pipeline_keywords):
            return "hokage strategy pipeline"
            
        if any(kw in cleaned for kw in self.status_keywords):
            return "hokage status"
        if any(kw in cleaned for kw in self.portfolio_keywords):
            return "hokage portfolio"
        if any(kw in cleaned for kw in self.positions_keywords):
            return "hokage positions"
        if any(kw in cleaned for kw in self.decisions_keywords):
            return "hokage decisions today"
        if any(kw in cleaned for kw in self.performance_keywords):
            return "hokage performance"
        if any(kw in cleaned for kw in self.lessons_keywords):
            return "hokage lessons"
        if any(kw in cleaned for kw in self.dna_keywords):
            return "hokage dna"
        if any(kw in cleaned for kw in self.briefing_keywords):
            return "hokage briefing"
        if any(kw in cleaned for kw in self.review_keywords):
            return "hokage review"
        if any(kw in cleaned for kw in self.opportunities_keywords):
            return "hokage opportunities"
        if any(kw in cleaned for kw in self.profile_keywords):
            return "hokage profile"
        if any(kw in cleaned for kw in self.horizon_keywords):
            return "hokage horizon"

        # Fallback to direct substring search as a last resort
        words = cleaned.split()
        if "why" in words:
            # Fallback if regex failed but "why" is present
            idx = words.index("why")
            if idx + 1 < len(words):
                symbol = words[idx + 1].upper()
                if symbol not in ("DID", "DO", "DOES", "IS", "ARE", "WAS", "WERE", "CAN", "COULD", "SHOULD", "WOULD", "HAS", "HAVE", "HAD"):
                    return f"hokage why {symbol}"

        # Conversational fallback for queries containing question words
        if any(w in cleaned for w in ("why", "how", "what", "explain", "describe", "status", "portfolio", "risk", "pnl", "p&l")):
            return f'hokage chat "{raw_query}"'

        # Return a instruction guide if no query matches
        return "unmapped"
