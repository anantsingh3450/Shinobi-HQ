"""Answer the commander from Hokage's real state, or say nothing was readable.

WHAT WAS WRONG
The chat was a 16-branch keyword cascade in conversation.py with a bare LLM as
the final fallthrough: `generate_response(query, system_instruction="")`. No
tools, no data. So it was canned when a keyword matched and an ungrounded model
guessing when it was not — the source of the phantom narratives in the logs.
The style prompt also hardcoded facts that have since gone stale ("four
competing strategies... 50,000-rupee budget... NIFTY, BANK NIFTY and SENSEX"),
so the model was being told wrong things before the question even arrived.

THE INVERSION
This is LLM-first with tools, which is how a capable assistant actually works.
The model is handed the read-only tools in `hokage_tools` and decides what to
call; the tools return real state; the model only phrases it.

THREE THINGS THAT MAKE IT HONEST
  1. A compact live-state digest is injected into EVERY prompt, so the common
     questions ("what's open", "how much have we got") are grounded before the
     model chooses whether to call anything at all.
  2. The system instruction forbids stating any figure that did not come from
     the digest or a tool result, and requires "I don't have that" instead.
  3. When the model is unreachable it DEGRADES TO FACTS — it returns the digest
     verbatim rather than an apology or, worse, an unaided guess. A trading
     assistant that goes quiet when the API is down is useless; one that
     invents an answer is dangerous.

READ-ONLY. Every tool exposed here only reads. The chat surface must not be
able to move money: the existing plain-English trade path already bypasses the
whole risk chain, which is exactly why it is pinned to paper.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from bots.autonomous import hokage_tools

logger = logging.getLogger("Hokage.GroundedChat")

GROUNDING_RULES = (
    "HARD RULES, these override any style guidance:\n"
    "1. NEVER state a number — a price, a P&L, a balance, a count, a date — "
    "that did not come from the live-state block below or from a tool result "
    "in this conversation. You have tools; call them. If a tool cannot answer, "
    "say plainly that you do not have that information.\n"
    "2. NEVER invent a position, a trade, a strategy name or an outcome. If "
    "asked about something you cannot verify, say so.\n"
    "3. Do not guess at causes. If asked why something happened and no tool "
    "explains it, say what you can see and that the rest is unknown.\n"
    "4. You are READ-ONLY here. You cannot place, modify or cancel a trade "
    "from this conversation, and you must not imply that you can. If asked to "
    "trade, say the commander should use the dashboard or an explicit command.\n"
    "5. Losses are reported as plainly as wins. Never soften a loss or imply a "
    "recovery you cannot see in the data.\n"
    "6. Paper money on live prices. Never imply real cash is at stake."
)

PERSONA = (
    "You are Hokage, an automated options-trading system, talking to your "
    "commander Anant. Speak like a sharp, straight-talking analyst who knows "
    "this book cold — not a status terminal and not a generic chatbot. Plain "
    "language. If you use a trading term, define it in a few words in the same "
    "sentence. Be concise; expand only when asked."
)


@dataclass
class GroundedAnswer:
    text: str
    tools_used: list[str] = field(default_factory=list)
    degraded: bool = False


def _default_model_factory(system_instruction: str, tools: list[Callable]) -> Any:
    """Build a Gemini model with the tools attached. Returns None when no key
    is configured, which the caller treats as 'degrade to facts'."""
    from integrations.llm.processor import get_ai_api_key_info

    _, api_key = get_ai_api_key_info()
    if not api_key:
        return None
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_instruction,
        tools=tools,
    )


class GroundedChat:
    """Ask a question, get an answer built from real state."""

    def __init__(
        self,
        model_factory: Callable[[str, list[Callable]], Any] | None = None,
        tools: list[Callable] | None = None,
    ) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._tools = tools if tools is not None else list(hokage_tools.READ_ONLY_TOOLS)

    def system_instruction(self, digest: str) -> str:
        return (
            f"{PERSONA}\n\n{GROUNDING_RULES}\n\n"
            f"--- LIVE STATE (already read for you, trust these) ---\n{digest}\n"
            f"--- END LIVE STATE ---\n\n"
            f"For anything not covered above, call a tool. Available tools cover "
            f"open positions, balances, recent trades, the strategy lineup, the "
            f"weekly measured-edge audit, what a given account size can afford, "
            f"system health, and recorded no-trade decisions."
        )

    def ask(self, question: str) -> GroundedAnswer:
        """Answer from state. Never raises; degrades to plain facts instead."""
        digest = ""
        try:
            digest = hokage_tools.current_state_digest()
        except Exception as exc:
            logger.error(f"Could not build the live-state digest: {exc}")

        if not (question or "").strip():
            return GroundedAnswer(text=digest or "Nothing to report.", degraded=True)

        try:
            model = self._model_factory(self.system_instruction(digest), self._tools)
        except Exception as exc:
            logger.error(f"Could not construct the chat model: {exc}")
            model = None

        if model is None:
            return self._degrade(digest, "the language model is not configured")

        try:
            chat = model.start_chat(enable_automatic_function_calling=True)
            reply = chat.send_message(question)
            text = (getattr(reply, "text", "") or "").strip()
            if not text:
                return self._degrade(digest, "the model returned nothing")
            return GroundedAnswer(text=text, tools_used=self._tools_called(chat))
        except Exception as exc:
            logger.error(f"Grounded chat failed, degrading to facts: {exc}")
            return self._degrade(digest, f"the model call failed ({type(exc).__name__})")

    @staticmethod
    def _tools_called(chat: Any) -> list[str]:
        """Which tools the model actually used, for transparency. Best-effort:
        never let bookkeeping break a good answer."""
        names: list[str] = []
        try:
            for message in getattr(chat, "history", []) or []:
                for part in getattr(message, "parts", []) or []:
                    call = getattr(part, "function_call", None)
                    if call is not None and getattr(call, "name", ""):
                        names.append(call.name)
        except Exception:
            return []
        seen: list[str] = []
        for n in names:
            if n not in seen:
                seen.append(n)
        return seen

    @staticmethod
    def _degrade(digest: str, why: str) -> GroundedAnswer:
        """Facts without prose. NEVER an apology alone, never a guess.

        The commander asking "what's open" at 11pm needs the answer more than
        he needs it phrased nicely, and a silent assistant is worse than a
        blunt one.
        """
        body = digest or "I could not read the ledger just now."
        return GroundedAnswer(
            text=f"{body}\n\n(Plain facts only — {why}.)",
            degraded=True,
        )
