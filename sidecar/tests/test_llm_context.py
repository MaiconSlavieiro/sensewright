"""Tests for ContextAssembler prompt variables."""
from __future__ import annotations

from sensewright_sidecar.config import DEFAULT_CONFIG, Config
from sensewright_sidecar.llm.context import ContextAssembler


def _assembler():
    return ContextAssembler(Config(DEFAULT_CONFIG))


def test_impulse_prompt_lists_mood_and_bias_options():
    messages = _assembler().assemble("sim.impulse", {"sim_id": 1, "sim_name": "Test"}, "pt-BR")
    system = messages[0]["content"]
    assert "{mood_options}" not in system
    assert "{bias_options}" not in system
    assert "focused" in system  # canonical mood token
    assert "creative" in system  # bias archetype
    assert "social" in system


def test_bias_options_come_from_locale_anchors():
    engine_anchors = _assembler()._render_ctx({}, "pt-BR")["bias_options"]
    assert "creative" in engine_anchors
    assert "active" in engine_anchors
