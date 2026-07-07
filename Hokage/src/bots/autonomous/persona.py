from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.PersonaEngine")

WITTY_TRANSITIONS = [
    "As the autumn wind dances through the Hidden Leaf, the scrolls reveal...",
    "By the Will of Fire and a well-placed entry signal...",
    "Risk gates are guarded tighter than a forbidden jutsu library...",
    "Sharpening our trading kunai in the shadows...",
]

WITTY_SUFFIXES = [
    "\n\n*Hokage's Wisdom:* 'A trade without a stop-loss is like executing a chidori with your eyes closed!'",
    "\n\n*Shinobi Observation:* 'We sit on our hands when the market is cloudy. Even a Hokage doesn't throw shuriken in a storm!'",
    "\n\n*Jonin Note:* 'Capital preservation is the ultimate genjutsu we cast on ourselves to survive the winter!'",
]

class PersonaEngine:
    """Manages conversational personality, humor, and tone overrides inside HOKAGE."""

    def __init__(self, brain_root: Path | None = None) -> None:
        self.resolver = PathResolver(brain_root)
        self.brain_json_path = self.resolver.resolve_brain_root() / "brain.json"

    def get_persona(self) -> dict[str, str]:
        """Load persona state from brain.json."""
        if not self.brain_json_path.exists():
            return {"humor_level": "normal", "tone": "normal", "style": "normal"}
        try:
            with open(self.brain_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("persona", {"humor_level": "normal", "tone": "normal", "style": "normal"})
        except Exception as e:
            logger.error(f"Failed to load persona: {e}")
            return {"humor_level": "normal", "tone": "normal", "style": "normal"}

    def set_persona(self, tone: str) -> None:
        """Update persona state in brain.json."""
        tone = tone.lower().strip()
        if tone not in ("witty", "stoic", "serious", "normal"):
            tone = "normal"
        
        # Load existing data
        data = {}
        if self.brain_json_path.exists():
            try:
                with open(self.brain_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read brain.json: {e}")

        # Update persona fields
        data["persona"] = {
            "humor_level": "high" if tone == "witty" else "zero",
            "tone": tone,
            "style": tone
        }

        try:
            with open(self.brain_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Hokage persona updated to: {tone}")
        except Exception as e:
            logger.error(f"Failed to write persona to brain.json: {e}")

    def format_text(self, text: str) -> str:
        """Adjust tone and style of the text according to active persona."""
        persona = self.get_persona()
        tone = persona.get("tone", "normal").lower()

        if tone == "witty":
            # Add some flavor text
            prefix = random.choice(WITTY_TRANSITIONS)
            suffix = random.choice(WITTY_SUFFIXES)
            
            # Clean up default greets
            if text.startswith("Hokage:"):
                text = text[7:].strip()
            
            # Add ninja analogy checks
            return f"{prefix}\n\n{text}{suffix}"
            
        elif tone in ("stoic", "serious"):
            # Strip emojis, exclamation marks, and informal words
            import re
            cleaned = text
            # Replace exclamation marks with periods
            cleaned = cleaned.replace("!", ".")
            # Strip typical emojis
            cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", cleaned)
            # Remove ninja references or command headers
            cleaned = re.sub(r"\bCommander\b", "Client", cleaned)
            cleaned = re.sub(r"\bElder Anant\b", "Account Owner", cleaned)
            cleaned = re.sub(r"\bAnant\b", "Account Owner", cleaned)
            cleaned = re.sub(r"\bHokage\b", "Automated System", cleaned)
            cleaned = re.sub(r"\bWill of Fire\b", "System parameters", cleaned)
            cleaned = re.sub(r"\bGood morning\b", "Daily session check initialized", cleaned)
            return cleaned.strip()

        return text
