"""Route commander text: settings commands here, everything else to real data.

WHAT THIS USED TO BE, AND WHY IT IS GONE
A 16-branch keyword cascade — `if "risk" in query`, `if "portfolio" in query` —
each branch returning a canned paragraph, with a bare
`generate_response(query, system_instruction="")` underneath when every branch
missed. That arrangement had three separate faults:

  * CANNED WHEN IT MATCHED. "how's SessionShift's performance" contains
    "performance", so it got a fixed portfolio blurb instead of an answer about
    SessionShift.
  * GUESSING WHEN IT DIDN'T. The fallthrough handed the model no data at all,
    which is where the phantom narratives in the logs came from.
  * SILENTLY STALE. One branch matched "why did" plus a hardcoded list of
    EQUITY tickers — tcs, infy, reliance, ongc, hal, bel, sbin, lt — none of
    which Hokage has traded since the universe became index options and MCX
    commodities. "why did you buy silver" hit that branch and fell through it.

Deleted 2026-08-16 on commander instruction. Questions now go to
`GroundedChat`, which hands the model read-only tools over the real ledger and
degrades to plain facts when the model is unreachable.

WHAT DELIBERATELY SURVIVES
The humor dial. "be funnier" / "tone it down" / "set humor to 8" is not a
question about state — it WRITES a setting — so it must be handled before
anything tries to answer it, and it must not be routed to a model that would
merely talk about being funnier without changing anything.

The end-of-day report is not lost either: it stays on `/report`, `/eod`,
`/summary`, `/daily` and the dashboard, and "how did we do today" now reaches
`get_trades`, which returns the real book for the model to narrate.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hokage.orchestrator.pipeline import HokageOrchestrator
    from bots.autonomous.cache import IntelligenceCache

logger = logging.getLogger("Hokage.ConversationEngine")


class CommanderConversationEngine:
    """Answers the commander from Hokage's real state."""

    def __init__(self, orchestrator: HokageOrchestrator, cache: IntelligenceCache) -> None:
        self.orchestrator = orchestrator
        self.cache = cache

    def respond(self, query: str) -> str:
        """Handle a setting command, or answer the question from real data."""
        from bots.autonomous.persona import PersonaEngine

        cleaned = (query or "").strip().lower()

        humor_reply = self._handle_humor_command(cleaned)
        if humor_reply is not None:
            return humor_reply

        text = ""
        try:
            from bots.autonomous.grounded_chat import GroundedChat

            text = GroundedChat().ask(query).text
        except Exception as exc:
            logger.error(f"Grounded chat failed: {exc}")

        if not text.strip():
            # Last resort only. No tools and no state, so it is capable of
            # inventing things — which is precisely why it sits behind
            # GroundedChat rather than in front of it.
            from integrations.llm.processor import LLMProcessor

            text = LLMProcessor(self.orchestrator).generate_response(query, system_instruction="")

        try:
            pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())
            return pe.format_text(text)
        except Exception:
            return text

    def _handle_humor_command(self, cleaned: str) -> str | None:
        """Detect a plain-language humor adjustment and apply it.

        Returns a confirmation when the query WAS a humor command, else None so
        normal routing continues. Lets the commander say "be funnier", "tone it
        down", "be serious", "set humor to 8" — no codes.
        """
        from bots.autonomous.persona import PersonaEngine

        pe = PersonaEngine(self.orchestrator.resolver.resolve_brain_root())

        m = re.search(r"humou?r\s*(?:level|to|=|:)?\s*(\d{1,2})\b", cleaned)
        if m and ("humor" in cleaned or "humour" in cleaned):
            pe.set_humor_level(int(m.group(1)))
            tail = "I'll keep it strictly business." if pe.get_humor_level() <= 1 else "Let's have some fun with it."
            return f"Done — humor set to {pe.describe_humor()}. {tail}"

        wants_humor_topic = any(w in cleaned for w in [
            "funny", "funnier", "humor", "humour", "joke", "jokes", "playful",
            "serious", "lighten up", "tone it down", "tone down",
        ])
        if not wants_humor_topic:
            return None

        increase = any(w in cleaned for w in [
            "funnier", "more funny", "more jokes", "more humor", "more humour",
            "more playful", "be funny", "be playful", "lighten up", "crack jokes",
        ])
        decrease = any(w in cleaned for w in [
            "less funny", "less jokes", "less humor", "less humour", "tone it down",
            "tone down", "be serious", "more serious", "no jokes", "stop joking",
            "stop the jokes", "cut the jokes", "less playful", "be strictly",
        ])

        # "how funny are you" — report, do not change.
        if not increase and not decrease and any(w in cleaned for w in [
            "how funny", "what's your humor", "whats your humor", "your humour",
            "humor level", "humour level",
        ]):
            return (f"My humor is currently at {pe.describe_humor()}. Say 'be funnier' "
                    f"or 'tone it down' anytime and I'll adjust.")

        if increase and not decrease:
            pe.adjust_humor(+2)
            return f"You got it — dialing the humor up to {pe.describe_humor()}. 😄"
        if decrease and not increase:
            pe.adjust_humor(-2)
            tail = "" if pe.get_humor_level() > 1 else " Strictly business from here."
            return f"Understood — humor down to {pe.describe_humor()}.{tail}"
        return None
