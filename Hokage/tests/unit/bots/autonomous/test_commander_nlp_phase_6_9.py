"""Unit tests for Phase 6.9: Natural Language & Voice Commander."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from bots.autonomous.cache import IntelligenceCache
from bots.autonomous.voice_commander import MockVoiceProvider, VoiceSessionManager
from bots.autonomous.explainability_aggregator import ExplainabilityAggregator
from bots.autonomous.conversation import CommanderConversationEngine
from hokage.router.nl_router import NaturalLanguageRouter
from bots.autonomous.briefings import BriefingGenerator


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock(spec=IntelligenceCache)
    cache.read_intelligence.return_value = {}
    return cache


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    orch = MagicMock()
    orch.resolver = MagicMock()
    orch.resolver.resolve_brain_root.return_value = MagicMock()
    return orch


def test_voice_commander_abstraction():
    # Test Mock Provider
    provider = MockVoiceProvider()
    trans = provider.speech_to_text(b"MOCK_AUDIO_PORTFOLIO")
    assert trans == "Explain today's portfolio"
    
    audio = provider.text_to_speech("Hello")
    assert audio == b"MOCK_SPEECH_FOR: Hello"
    
    # Test Session Manager
    vsm = VoiceSessionManager(provider)
    assert vsm.session_active is False
    assert vsm.session_state == "IDLE"
    
    # Process voice input
    res = vsm.process_audio_input(b"MOCK_AUDIO_WAKE_WORD")
    assert res["has_wake_word"] is True
    assert "risks" in res["cleaned_text"]
    assert vsm.session_active is True
    assert vsm.session_state == "LISTENING"
    
    # Generate voice output
    output_audio = vsm.generate_voice_output("Response text")
    assert output_audio == b"MOCK_SPEECH_FOR: Response text"
    assert vsm.session_state == "LISTENING"


def test_explainability_aggregator(mock_orchestrator, mock_cache):
    agg = ExplainabilityAggregator(mock_orchestrator, mock_cache)
    
    # Retrieve aggregated explanation
    report = agg.aggregate_explanation(symbol="TCS")
    assert "strategy" in report
    assert "conviction" in report
    assert "market_intel" in report
    assert "portfolio_intel" in report
    assert "risk" in report
    assert "execution" in report
    assert "shadow_analytics" in report
    assert "unified_narrative" in report
    assert "[STRATEGY]" in report["unified_narrative"]
    assert "[CONVICTION]" in report["unified_narrative"]


def test_questions_are_answered_from_real_state_not_canned_text(mock_orchestrator, mock_cache):
    """The 16-branch keyword cascade was deleted 2026-08-16.

    It was canned when a branch matched ("how's SessionShift's performance"
    contains "performance", so it returned a fixed portfolio blurb) and it fed
    the model NO data when every branch missed. Questions now go to
    GroundedChat, which answers from the ledger — and with no API key
    configured, as in this test environment, it degrades to real facts rather
    than to a canned paragraph or a guess.
    """
    engine = CommanderConversationEngine(mock_orchestrator, mock_cache)

    for question in ("Explain today's portfolio", "Explain today's risks",
                     "Explain today's P&L", "how are we doing?"):
        reply = engine.respond(question)
        assert "Live state read at" in reply, "answer is not grounded in real state"
        assert "Index Dojo" in reply and "MCX Arena" in reply


def test_the_stale_equity_branch_is_gone(mock_orchestrator, mock_cache):
    """One branch matched "why did" plus hardcoded EQUITY tickers — tcs, infy,
    reliance, ongc, hal, bel, sbin, lt — none of which Hokage has traded since
    the universe became index options and MCX commodities. It swallowed "why
    did you buy silver" too."""
    engine = CommanderConversationEngine(mock_orchestrator, mock_cache)
    reply = engine.respond("Why did we buy TCS?")
    # No canned per-symbol explainer any more; it is answered from state.
    assert "Live state read at" in reply


def test_the_humor_dial_deliberately_survives(mock_orchestrator, mock_cache, tmp_path):
    """"be funnier" is not a question about state — it WRITES a setting, so it
    must be handled before anything tries to answer it, and must never be
    routed to a model that would merely TALK about being funnier."""
    mock_orchestrator.resolver.resolve_brain_root.return_value = tmp_path
    engine = CommanderConversationEngine(mock_orchestrator, mock_cache)

    from bots.autonomous.persona import PersonaEngine

    before = PersonaEngine(tmp_path).get_humor_level()
    reply = engine.respond("be funnier")
    assert "humor" in reply.lower()
    assert PersonaEngine(tmp_path).get_humor_level() > before

    reply = engine.respond("tone it down")
    assert "humor" in reply.lower()

    engine.respond("set humor to 3")
    assert PersonaEngine(tmp_path).get_humor_level() == 3

    # Asking ABOUT the level must report it, not change it.
    engine.respond("how funny are you?")
    assert PersonaEngine(tmp_path).get_humor_level() == 3


def test_a_normal_question_does_not_touch_the_humor_dial(mock_orchestrator, mock_cache, tmp_path):
    mock_orchestrator.resolver.resolve_brain_root.return_value = tmp_path
    engine = CommanderConversationEngine(mock_orchestrator, mock_cache)

    from bots.autonomous.persona import PersonaEngine

    engine.respond("set humor to 5")
    engine.respond("what is open right now?")
    assert PersonaEngine(tmp_path).get_humor_level() == 5


def test_nl_command_router_extensions():
    router = NaturalLanguageRouter()
    
    # Test conversational queries map to 'hokage chat'
    assert router.parse_query("Explain today's portfolio") == 'hokage chat "Explain today\'s portfolio"'
    assert router.parse_query("Why did Hokage enter this trade?") == 'hokage chat "Why did Hokage enter this trade?"'
    assert router.parse_query("how did we perform today?") == 'hokage chat "how did we perform today?"'
    
    # Verify unmapped fallback still functions
    assert router.parse_query("some random words") == "unmapped"


def test_briefing_narrator(mock_orchestrator, mock_cache):
    # Instantiate BriefingGenerator with mocks
    generator = BriefingGenerator(
        scanner=MagicMock(),
        news_engine=MagicMock(),
        geo_engine=MagicMock(),
        analog_engine=MagicMock(),
        discovery_engine=MagicMock(),
        cache=mock_cache
    )
    
    markdown_text = (
        "# Commander Daily Briefing — 2026-06-28\n\n"
        "## Executive Summary\n"
        "Hokage completed today's trading session.\n\n"
        "## 1. Actionable Intelligence Narrative\n"
        "- **BUY 10 TCS** @ average price of ₹4,000.00\n"
        "- **BUY 20 INFY** @ average price of ₹1,500.00"
    )
    
    narration = generator.narrate_briefing(markdown_text)
    
    # Narrated text should not contain markdown tags
    assert "#" not in narration
    assert "**" not in narration
    assert "Good day, Commander" in narration
    assert "First, regarding" in narration
    assert "Indeed," in narration  # from bullet point conversion


def test_cli_command_router(mock_orchestrator, mock_cache):
    from hokage.router.command_router import CommandRouter
    
    router = CommandRouter(mock_orchestrator)
    mock_orchestrator.resolver.resolve_brain_root.return_value = MagicMock()
    
    # Test hokage chat command
    with patch("bots.autonomous.conversation.CommanderConversationEngine.respond", return_value="Test Chat Response"):
        out_chat = router.handle_command("hokage chat \"Explain today's portfolio\"")
        assert "Hokage: Test Chat Response" in out_chat
        
    # Test hokage voice-status command
    out_voice = router.handle_command("hokage voice-status")
    assert "Voice Commander Session" in out_voice


def test_dynamic_conversation_llm_processor(mock_orchestrator, mock_cache):
    from integrations.llm.processor import LLMProcessor
    processor = LLMProcessor(mock_orchestrator)
    
    # Test normal response
    res = processor.generate_response("what is the portfolio status?", system_instruction="")
    assert "portfolio" in res.lower()
    
    # Test sarcastic response
    res_sarcastic = processor.generate_response("what is the portfolio status?", system_instruction="sarcastic retail-critique")
    assert "portfolio" in res_sarcastic.lower()
    assert "fomo" in res_sarcastic.lower() or "will of fire" in res_sarcastic.lower() or "youtube" in res_sarcastic.lower()
