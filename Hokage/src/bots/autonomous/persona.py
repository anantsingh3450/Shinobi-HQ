from __future__ import annotations

import json
import logging
from pathlib import Path

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.PersonaEngine")

#: Humor runs on a 0-10 dial. The commander turns it up or down in plain
#: language ("be funnier", "tone it down", "be serious"); the level is
#: persisted and fed into the LLM system prompt so the model adjusts its own
#: tone natively — no post-hoc string decoration that mangles a good reply.
DEFAULT_HUMOR_LEVEL = 3
MIN_HUMOR_LEVEL = 0
MAX_HUMOR_LEVEL = 10

#: Legacy tone words map onto the dial so older "hokage persona set <tone>"
#: commands keep working.
_TONE_TO_LEVEL = {
    "serious": 0,
    "stoic": 1,
    "normal": DEFAULT_HUMOR_LEVEL,
    "witty": 7,
    "funny": 8,
    "comedian": 10,
}


def _humor_directive(level: int) -> str:
    """A plain-language tone instruction for the LLM, by humor level."""
    if level <= 1:
        return (
            "Tone: completely serious and businesslike. No jokes, no wordplay, "
            "no emojis. Just clear, direct answers."
        )
    if level <= 3:
        return (
            "Tone: professional and warm, with only occasional light humor. "
            "Stay grounded; a rare, subtle bit of levity is fine, nothing more."
        )
    if level <= 5:
        return (
            "Tone: friendly and personable, with natural, easygoing humor where "
            "it fits. Like a sharp friend who happens to know markets."
        )
    if level <= 7:
        return (
            "Tone: playful and witty. Jokes, light banter, and clever analogies "
            "are welcome — but never let a joke blur a real number or a real risk."
        )
    return (
        "Tone: very funny and playful — lean into jokes, vivid analogies, and "
        "banter. Keep it genuinely entertaining, but every fact, number, and "
        "risk warning must stay 100% accurate underneath the comedy."
    )


class PersonaEngine:
    """Manages Hokage's conversational humor level and tone."""

    def __init__(self, brain_root: Path | None = None) -> None:
        self.resolver = PathResolver(brain_root)
        self.brain_json_path = self.resolver.resolve_brain_root() / "brain.json"

    # ---- raw brain.json persona I/O -------------------------------------

    def _load_brain(self) -> dict:
        if not self.brain_json_path.exists():
            return {}
        try:
            with open(self.brain_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read brain.json: {e}")
            return {}

    def _save_brain(self, data: dict) -> None:
        try:
            with open(self.brain_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write brain.json: {e}")

    # ---- humor level ----------------------------------------------------

    def get_humor_level(self) -> int:
        """Current humor level (0-10), clamped, default 3."""
        persona = self._load_brain().get("persona", {})
        raw = persona.get("humor_level", DEFAULT_HUMOR_LEVEL)
        # Tolerate legacy string values ("high"/"zero"/"normal"/tone words).
        if isinstance(raw, str):
            token = raw.strip().lower()
            if token in _TONE_TO_LEVEL:
                raw = _TONE_TO_LEVEL[token]
            elif token in ("high", "max"):
                raw = 8
            elif token in ("zero", "none", "off"):
                raw = 0
            else:
                raw = DEFAULT_HUMOR_LEVEL
        try:
            level = int(round(float(raw)))
        except (TypeError, ValueError):
            level = DEFAULT_HUMOR_LEVEL
        return max(MIN_HUMOR_LEVEL, min(MAX_HUMOR_LEVEL, level))

    def set_humor_level(self, level: int) -> int:
        """Persist a humor level (clamped 0-10). Returns the stored value."""
        level = max(MIN_HUMOR_LEVEL, min(MAX_HUMOR_LEVEL, int(level)))
        data = self._load_brain()
        persona = data.get("persona", {}) if isinstance(data.get("persona"), dict) else {}
        persona["humor_level"] = level
        data["persona"] = persona
        self._save_brain(data)
        logger.info(f"Hokage humor level set to {level}/10.")
        return level

    def adjust_humor(self, delta: int) -> int:
        """Nudge humor up or down. Returns the new level."""
        return self.set_humor_level(self.get_humor_level() + delta)

    def humor_instruction(self) -> str:
        """The tone directive for the current level, for the LLM system prompt."""
        return _humor_directive(self.get_humor_level())

    def describe_humor(self) -> str:
        """A short human-readable name for the current level."""
        level = self.get_humor_level()
        if level <= 1:
            band = "serious"
        elif level <= 3:
            band = "lightly professional"
        elif level <= 5:
            band = "friendly"
        elif level <= 7:
            band = "playful"
        else:
            band = "very funny"
        return f"{level}/10 ({band})"

    # ---- backward-compatible tone API -----------------------------------

    def get_persona(self) -> dict[str, str]:
        """Legacy persona dict (kept so older callers keep working)."""
        level = self.get_humor_level()
        return {"humor_level": str(level), "tone": "witty" if level >= 6 else ("serious" if level <= 1 else "normal")}

    def set_persona(self, tone: str) -> None:
        """Legacy tone setter: map a tone word onto the humor dial."""
        self.set_humor_level(_TONE_TO_LEVEL.get(tone.lower().strip(), DEFAULT_HUMOR_LEVEL))

    def format_text(self, text: str) -> str:
        """Light post-processing only.

        Tone now lives in the LLM system prompt (see LLMProcessor), so this no
        longer slaps ninja prefixes/suffixes onto a good reply. At humor 0-1 it
        strips emojis for a strictly businesslike surface; otherwise it passes
        the text through untouched.
        """
        if self.get_humor_level() <= 1:
            import re
            return re.sub(r"[\U00010000-\U0010ffff]", "", text).strip()
        return text
