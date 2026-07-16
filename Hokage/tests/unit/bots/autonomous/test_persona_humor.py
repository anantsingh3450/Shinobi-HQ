"""Humor dial: a 0-10 level the commander controls in plain language."""
from __future__ import annotations

import json

from bots.autonomous.persona import PersonaEngine, DEFAULT_HUMOR_LEVEL


def _engine(tmp_path):
    (tmp_path / "brain.json").write_text(json.dumps({"brain_id": "x"}), encoding="utf-8")
    return PersonaEngine(tmp_path)


def test_default_and_set_get(tmp_path):
    pe = _engine(tmp_path)
    assert pe.get_humor_level() == DEFAULT_HUMOR_LEVEL
    assert pe.set_humor_level(8) == 8
    assert pe.get_humor_level() == 8


def test_clamped_to_range(tmp_path):
    pe = _engine(tmp_path)
    assert pe.set_humor_level(99) == 10
    assert pe.set_humor_level(-5) == 0


def test_adjust_up_and_down(tmp_path):
    pe = _engine(tmp_path)
    pe.set_humor_level(4)
    assert pe.adjust_humor(+2) == 6
    assert pe.adjust_humor(-3) == 3


def test_legacy_string_values_tolerated(tmp_path):
    pe = _engine(tmp_path)
    # Older brains stored words, not integers.
    data = json.loads((tmp_path / "brain.json").read_text(encoding="utf-8"))
    data["persona"] = {"humor_level": "high"}
    (tmp_path / "brain.json").write_text(json.dumps(data), encoding="utf-8")
    assert pe.get_humor_level() == 8  # "high" -> 8


def test_humor_instruction_changes_with_level(tmp_path):
    pe = _engine(tmp_path)
    pe.set_humor_level(0)
    assert "serious" in pe.humor_instruction().lower()
    pe.set_humor_level(10)
    assert "funny" in pe.humor_instruction().lower()


def test_legacy_set_persona_maps_to_dial(tmp_path):
    pe = _engine(tmp_path)
    pe.set_persona("witty")
    assert pe.get_humor_level() == 7
    pe.set_persona("serious")
    assert pe.get_humor_level() == 0


def test_format_text_strips_emoji_only_when_serious(tmp_path):
    pe = _engine(tmp_path)
    pe.set_humor_level(6)
    assert pe.format_text("All good 🚀") == "All good 🚀"
    pe.set_humor_level(0)
    assert "🚀" not in pe.format_text("All good 🚀")
