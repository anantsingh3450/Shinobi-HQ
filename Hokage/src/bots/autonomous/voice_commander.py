from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger("Hokage.VoiceCommander")


class BaseVoiceProvider(abc.ABC):
    """Abstract base class for voice recognition and synthesis."""

    @abc.abstractmethod
    def speech_to_text(self, audio_bytes: bytes) -> str:
        """Convert speech audio bytes into transcribed text."""
        pass

    @abc.abstractmethod
    def text_to_speech(self, text: str) -> bytes:
        """Convert text string into synthesized speech audio bytes."""
        pass


class MockVoiceProvider(BaseVoiceProvider):
    """Mock implementation of speech-to-text and text-to-speech for local testing."""

    def speech_to_text(self, audio_bytes: bytes) -> str:
        """Convert mock audio bytes to text."""
        # Simple mock behavior: if the audio bytes matches a known test signature, return specific text
        if audio_bytes == b"MOCK_AUDIO_PORTFOLIO":
            return "Explain today's portfolio"
        elif audio_bytes == b"MOCK_AUDIO_MARKET":
            return "Explain today's market"
        elif audio_bytes == b"MOCK_AUDIO_WAKE_WORD":
            return "Hokage, explain today's risks"
        return "Show my portfolio"

    def text_to_speech(self, text: str) -> bytes:
        """Convert text to mock audio bytes."""
        # Returns a mock audio payload
        return f"MOCK_SPEECH_FOR: {text}".encode("utf-8")


class VoiceSessionManager:
    """Manages active voice sessions, wake-word detection, and conversation history."""

    def __init__(self, provider: BaseVoiceProvider | None = None) -> None:
        """Initialize VoiceSessionManager."""
        self.provider = provider or MockVoiceProvider()
        self.session_active = False
        self.session_state = "IDLE"  # IDLE, LISTENING, SPEAKING
        self.wake_phrase = "hokage"
        self.history: list[dict[str, Any]] = []

    def start_session(self) -> None:
        """Activate the voice session."""
        self.session_active = True
        self.session_state = "LISTENING"
        logger.info("Voice session started.")

    def stop_session(self) -> None:
        """Deactivate the voice session."""
        self.session_active = False
        self.session_state = "IDLE"
        logger.info("Voice session stopped.")

    def process_audio_input(self, audio_bytes: bytes) -> dict[str, Any]:
        """Convert audio input to text and check for wake phrase."""
        if not self.session_active:
            self.start_session()

        transcription = self.provider.speech_to_text(audio_bytes)
        has_wake_word = self.wake_phrase in transcription.lower()
        
        # Clean wake phrase from transcription if present
        clean_text = transcription
        if has_wake_word:
            # Case insensitive replacement of the wake word
            import re
            clean_text = re.sub(rf"\b{self.wake_phrase}\b[,!?]?", "", transcription, flags=re.IGNORECASE).strip()

        result = {
            "transcription": transcription,
            "cleaned_text": clean_text,
            "has_wake_word": has_wake_word,
            "session_state": self.session_state
        }
        
        self.history.append({
            "direction": "input",
            "type": "voice",
            "text": transcription,
            "cleaned": clean_text
        })
        
        return result

    def generate_voice_output(self, text: str) -> bytes:
        """Generate audio bytes for a text response."""
        self.session_state = "SPEAKING"
        audio_bytes = self.provider.text_to_speech(text)
        self.session_state = "LISTENING"
        
        self.history.append({
            "direction": "output",
            "type": "voice",
            "text": text
        })
        
        return audio_bytes
