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


def test_commander_conversation_engine(mock_orchestrator, mock_cache):
    engine = CommanderConversationEngine(mock_orchestrator, mock_cache)
    
    # Test portfolio query
    res_port = engine.respond("Explain today's portfolio")
    assert "portfolio" in res_port.lower()
    
    # Test market query
    res_mkt = engine.respond("/intel")
    assert "regime" in res_mkt.lower()
    
    # Test risk query
    res_risk = engine.respond("Explain today's risks")
    assert "risk" in res_risk.lower()
    
    # Test performance query
    res_perf = engine.respond("Explain today's P&L")
    assert "p&l" in res_perf.lower() or "win rate" in res_perf.lower()
    
    # Test symbol decision query
    res_sym = engine.respond("Why did we buy TCS?")
    assert "tcs" in res_sym.lower()


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
